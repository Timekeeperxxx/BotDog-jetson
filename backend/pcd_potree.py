"""Disk-backed, additive Potree 2 export. Every finite source point appears once.

Hierarchy pages contain one node and at most eight proxies, never a scene-wide
JSON node list. Source partitions are streamed even when all points coincide.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import struct
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable
from urllib.parse import quote

import numpy as np

from .config import settings
from .pcd_errors import PcdMapError
from .pcd_intensity_stats import intensity_percentiles
from .pcd_reader import iter_pcd_xyz_intensity_float32, parse_pcd_header
from .services_pcd_maps import find_scene_pcd_files, resolve_scene_path

VERSION = 1
CHUNK_POINTS = 131072
LEAF_POINTS = 16384
BRANCH_POINTS = 2048
ROLES = ("ground", "wall", "footprint_fill")
RECORD = struct.Struct("<BBIqq")
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="potree-import")
_lock = threading.Lock()
_jobs: dict[str, dict] = {}


def scene_cache(scene_id: str):
    files = find_scene_pcd_files(resolve_scene_path(scene_id))
    sources = [(role, str(path.resolve()), path.stat().st_size, path.stat().st_mtime_ns)
               for role, path in files.items() if path]
    key = hashlib.sha256(json.dumps([VERSION, scene_id, sources]).encode()).hexdigest()
    return Path(settings.PCD_SCENE_TILE_CACHE_DIR).resolve() / "potree" / key, files


def _chunks(path: Path):
    with path.open("rb") as stream:
        while True:
            values = np.fromfile(stream, dtype="<f4", count=CHUNK_POINTS * 4)
            if not len(values):
                return
            yield values.reshape(-1, 4)


def _bounds(lo, hi):
    # Files use Three.js axes; the navigation API uses ROS map axes.
    return dict(min_x=float(lo[0]), max_x=float(hi[0]), min_y=float(-hi[2]),
                max_y=float(-lo[2]), min_z=float(lo[1]), max_z=float(hi[1]))


def build_layer(source: Path, output: Path, progress: Callable[[str], None] = lambda _: None):
    output.mkdir(parents=True)
    spool = output / "r.part"
    header, offset = parse_pcd_header(source)
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
    count = 0
    intensity_min, intensity_max = np.inf, -np.inf
    with spool.open("wb") as stream:
        for xyz, intensity in iter_pcd_xyz_intensity_float32(source, header, offset, chunk_points=CHUNK_POINTS):
            if not len(xyz):
                continue
            records = np.empty((len(xyz), 4), dtype="<f4")
            records[:, :3] = xyz[:, [0, 2, 1]]
            records[:, 2] *= -1
            records[:, 3] = np.nan_to_num(intensity, nan=0, posinf=0, neginf=0) if intensity is not None else 0
            lo = np.minimum(lo, records[:, :3].min(axis=0))
            hi = np.maximum(hi, records[:, :3].max(axis=0))
            intensity_min = min(intensity_min, float(records[:, 3].min()))
            intensity_max = max(intensity_max, float(records[:, 3].max()))
            records.tofile(stream)
            count += len(records)
            progress(f"读取 {source.name}：{count:,} 点")
    if not count:
        spool.unlink()
        return None

    color_range = intensity_percentiles(spool)
    color_quantiles = intensity_percentiles(spool, percentiles=range(0, 101, 5))
    bounds = _bounds(lo, hi)
    extent = max(float((hi - lo).max()), 0.001)
    cube_hi = lo + extent
    # Potree 2 stores int32 positions. At ordinary robot-map extents this is
    # micrometre quantization; the PCD itself is untouched, duplicates retained.
    scale = max(1e-6, extent / 2_000_000_000)
    db = sqlite3.connect(output / "build.sqlite")
    db.execute("CREATE TABLE nodes(name TEXT PRIMARY KEY, n INT, off INT, size INT, mask INT, h_off INT, h_size INT)")
    depth = 0
    written = 0
    packed = np.dtype([("xyz", "<i4", (3,)), ("intensity", "<f4")])
    with (output / "octree.bin").open("wb") as octree:
        def write_points(records):
            nonlocal written
            values = np.empty(len(records), dtype=packed)
            values["xyz"] = np.rint((records[:, :3].astype(np.float64) - lo) / scale).astype("<i4")
            values["intensity"] = records[:, 3]
            values.tofile(octree)
            written += len(records)

        def visit(name, low, high):
            nonlocal depth
            depth = max(depth, len(name) - 1)
            path = output / f"{name}.part"
            n = path.stat().st_size // 16
            start = octree.tell()
            # A depth guard also handles repeated identical coordinates without
            # recursion or whole-partition RAM growth. Such leaves still stream.
            leaf = n <= LEAF_POINTS or len(name) >= 25
            selected = np.linspace(0, n - 1, min(n, BRANCH_POINTS), dtype=np.int64) if not leaf else None
            middle = (low + high) / 2
            child_files = {}
            cursor = 0
            root_preview = []
            for records in _chunks(path):
                if leaf:
                    write_points(records)
                    if name == "r":
                        root_preview.append(records[:, :3].copy())
                else:
                    local = selected[(selected >= cursor) & (selected < cursor + len(records))] - cursor
                    write_points(records[local])
                    if name == "r":
                        root_preview.append(records[local, :3].copy())
                    keep = np.ones(len(records), dtype=bool)
                    keep[local] = False
                    rest = records[keep]
                    indices = ((rest[:, :3] >= middle) * [4, 2, 1]).sum(axis=1)
                    for index in np.unique(indices):
                        index = int(index)
                        if index not in child_files:
                            child_files[index] = (output / f"{name}{index}.part").open("wb")
                        rest[indices == index].tofile(child_files[index])
                cursor += len(records)
            for stream in child_files.values():
                stream.close()
            path.unlink()
            if name == "r":
                np.concatenate(root_preview).astype("<f4").tofile(output / "overview.bin")
            size = octree.tell() - start
            mask = sum(1 << i for i in child_files)
            db.execute("INSERT INTO nodes VALUES(?,?,?,?,?,0,0)", (name, size // 16, start, size, mask))
            progress(f"整理 {source.name}：{written:,} / {count:,} 点")
            for index in sorted(child_files):
                bits = np.array([index & 4, index & 2, index & 1], dtype=bool)
                visit(name + str(index), np.where(bits, middle, low), np.where(bits, high, middle))
        visit("r", lo, cube_hi)
    assert written == count
    db.commit()
    h_offset = 0
    for name, mask in db.execute("SELECT name,mask FROM nodes ORDER BY name"):
        size = RECORD.size * (1 + int(mask).bit_count())
        db.execute("UPDATE nodes SET h_off=?,h_size=? WHERE name=?", (h_offset, size, name))
        h_offset += size
    db.commit()
    with (output / "hierarchy.bin").open("wb") as hierarchy:
        for name, n, off, size, mask, _, _ in db.execute("SELECT * FROM nodes ORDER BY name"):
            hierarchy.write(RECORD.pack(0 if mask else 1, mask, n, off, size))
            for index in range(8):
                if mask & (1 << index):
                    cn, cmask, hoff, hsize = db.execute("SELECT n,mask,h_off,h_size FROM nodes WHERE name=?", (name + str(index),)).fetchone()
                    hierarchy.write(RECORD.pack(2, cmask, cn, hoff, hsize))
    root_size = db.execute("SELECT h_size FROM nodes WHERE name='r'").fetchone()[0]
    node_count = db.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    db.close()
    (output / "build.sqlite").unlink()
    metadata = dict(version="2.0", name=source.name, description="Original valid PCD points; additive octree",
                    points=count, projection="", hierarchy=dict(firstChunkSize=root_size, stepSize=1, depth=depth),
                    offset=lo.tolist(), scale=[scale] * 3, spacing=extent / 128,
                    boundingBox=dict(min=lo.tolist(), max=cube_hi.tolist()), encoding="DEFAULT",
                    attributes=[dict(name="position", description="", size=12, numElements=3, type="int32", min=lo.tolist(), max=hi.tolist()),
                                dict(name="intensity", description="", size=4, numElements=1, type="float", min=[intensity_min], max=[intensity_max])])
    (output / "metadata.json").write_text(json.dumps(metadata))
    return dict(bounds=bounds, points=count, nodes=node_count, intensity=color_range, intensity_quantiles=color_quantiles,
                overview_points=(output / "overview.bin").stat().st_size // 12, coordinate_scale=scale)


def build_scene(scene_id: str, cache: Path, files: dict, progress=lambda _: None):
    temporary = cache.with_name(f".{cache.name}.{os.getpid()}.tmp")
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True)
    layers, roots, layer_bounds, stats = [], [], {}, {}
    try:
        for role in ROLES:
            source = files.get(role)
            info = build_layer(source, temporary / role, progress) if source else None
            layer_bounds[role] = info["bounds"] if info else None
            stats[role] = None
            if not info:
                continue
            url = f"/api/v1/nav/pcd-scenes/{quote(scene_id, safe='')}/potree/{cache.name}/{role}/metadata.json"
            layers.append(dict(role=role, url=url, point_count=info["points"], coordinate_scale=info["coordinate_scale"]))
            roots.append(dict(id=role + "-root", role=role, file=role + ".root.bin", bounds=info["bounds"],
                              point_count=info["overview_points"], byte_length=info["overview_points"] * 12, has_intensity=False,
                              url=url.replace("metadata.json", "overview.bin")))
            stats[role] = dict(source_points=info["points"], retained_points=info["points"], original_points=info["points"],
                               balanced_points=info["points"], performance_points=info["points"], tile_count=info["nodes"],
                               intensity_percentile_2_98=info["intensity"], intensity_quantiles=info["intensity_quantiles"])
        valid = [b for b in layer_bounds.values() if b]
        if not valid:
            raise PcdMapError("场景没有有效点云")
        bounds = {key: (min if key.startswith("min") else max)(b[key] for b in valid) for key in valid[0]}
        manifest = dict(intensity_statistics_version=3, version=VERSION, cache_key=cache.name, scene_id=scene_id, frame_id=settings.PCD_FRAME_ID,
                        bounds=bounds, layer_bounds=layer_bounds, root_tiles=roots, nodes=[], stats=stats,
                        settings=dict(tile_size_m=0, max_points_per_tile=LEAF_POINTS), potree=dict(layers=layers))
        (temporary / "manifest.json").write_text(json.dumps(manifest))
        os.replace(temporary, cache)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def request_scene(scene_id: str):
    cache, files = scene_cache(scene_id)
    if (cache / "manifest.json").is_file():
        manifest = json.loads((cache / "manifest.json").read_text())
        if manifest.get("intensity_statistics_version") == 3:
            return manifest
    with _lock:
        if cache.name not in _jobs:
            state = dict(status="preparing", message="正在准备原始点云")
            _jobs[cache.name] = state
            def run():
                try:
                    if (cache / "manifest.json").is_file():
                        manifest = json.loads((cache / "manifest.json").read_text())
                        for layer in manifest["potree"]["layers"]:
                            role = layer["role"]
                            state.update(message=f"正在更新 {role} 强度颜色范围")
                            manifest["stats"][role]["intensity_percentile_2_98"] = intensity_percentiles(cache / role / "octree.bin")
                            manifest["stats"][role]["intensity_quantiles"] = intensity_percentiles(cache / role / "octree.bin", percentiles=range(0, 101, 5))
                        manifest["intensity_statistics_version"] = 3
                        temporary = cache / "manifest.intensity.tmp"
                        temporary.write_text(json.dumps(manifest))
                        temporary.replace(cache / "manifest.json")
                    else:
                        build_scene(scene_id, cache, files, lambda message: state.update(message=message))
                    state.update(status="ready")
                except Exception as exc:
                    state.update(status="error", message=str(exc))
            _executor.submit(run)
        return dict(_jobs[cache.name])


def resolve_asset(scene_id: str, cache_key: str, role: str, filename: str):
    resolve_scene_path(scene_id)
    if not re.fullmatch(r"[a-f0-9]{64}", cache_key) or role not in ROLES or filename not in {"metadata.json", "hierarchy.bin", "octree.bin", "overview.bin"}:
        raise FileNotFoundError("无效的点云资源")
    root = Path(settings.PCD_SCENE_TILE_CACHE_DIR).resolve() / "potree" / cache_key
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file() or json.loads(manifest_path.read_text())["scene_id"] != scene_id:
        raise FileNotFoundError("点云资源不存在")
    asset = root / role / filename
    if not asset.is_file():
        raise FileNotFoundError("点云资源不存在")
    return asset
