from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import threading
from pathlib import Path
from typing import Any, Iterator

import numpy as np

from .config import settings
from .logging_config import get_logger
from .pcd_errors import PcdMapError
from .pcd_reader import (
    iter_pcd_xyz_intensity_float32,
    normalize_pcd_header,
    parse_pcd_header,
    spatial_downsample_indices,
)
from .services_pcd_maps import find_scene_pcd_files, resolve_scene_path


tile_logger = get_logger("分层点云服务")

PCD_TILE_CACHE_VERSION = 2
PCD_TILE_FILE_PATTERN = re.compile(r"^[a-z0-9_.-]+\.bin$")
PCD_TILE_ROLE_ORDER = ("ground", "wall", "footprint_fill")
PCD_TILE_ROOT_CANDIDATES_PER_LEAF = 512
_tile_cache_lock = threading.Lock()


def _bounds_from_points(points: np.ndarray) -> dict[str, float]:
    return {
        "min_x": float(np.min(points[:, 0])),
        "max_x": float(np.max(points[:, 0])),
        "min_y": float(np.min(points[:, 1])),
        "max_y": float(np.max(points[:, 1])),
        "min_z": float(np.min(points[:, 2])),
        "max_z": float(np.max(points[:, 2])),
    }


def _merge_bounds(items: list[dict[str, float] | None]) -> dict[str, float]:
    valid = [item for item in items if item is not None]
    if not valid:
        return {
            "min_x": 0.0,
            "max_x": 0.0,
            "min_y": 0.0,
            "max_y": 0.0,
            "min_z": 0.0,
            "max_z": 0.0,
        }
    return {
        "min_x": min(item["min_x"] for item in valid),
        "max_x": max(item["max_x"] for item in valid),
        "min_y": min(item["min_y"] for item in valid),
        "max_y": max(item["max_y"] for item in valid),
        "min_z": min(item["min_z"] for item in valid),
        "max_z": max(item["max_z"] for item in valid),
    }


def _cache_key(scene_id: str) -> tuple[Path, dict[str, Path | None]]:
    scene_path = resolve_scene_path(scene_id)
    files = find_scene_pcd_files(scene_path)
    sources: dict[str, dict[str, Any] | None] = {}
    for role, path in files.items():
        if path is None:
            sources[role] = None
            continue
        stat = path.stat()
        sources[role] = {
            "path": str(path.resolve()),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }
    payload = {
        "version": PCD_TILE_CACHE_VERSION,
        "scene_id": scene_id,
        "frame_id": settings.PCD_FRAME_ID,
        "tile_size_m": float(settings.PCD_SCENE_TILE_SIZE_M),
        "balanced_voxel_size_m": float(settings.PCD_SCENE_TILE_BALANCED_VOXEL_SIZE_M),
        "balanced_points_per_voxel": int(settings.PCD_SCENE_TILE_BALANCED_POINTS_PER_VOXEL),
        "performance_voxel_size_m": float(settings.PCD_SCENE_TILE_PERFORMANCE_VOXEL_SIZE_M),
        "performance_points_per_voxel": int(settings.PCD_SCENE_TILE_PERFORMANCE_POINTS_PER_VOXEL),
        "max_points": int(settings.PCD_SCENE_TILE_MAX_POINTS),
        "root_points": int(settings.PCD_SCENE_TILE_ROOT_POINTS),
        "sources": sources,
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"),
    ).hexdigest()
    scene_digest = hashlib.sha1(scene_id.encode("utf-8")).hexdigest()[:12]
    cache_root = Path(settings.PCD_SCENE_TILE_CACHE_DIR).resolve()
    cache_root.mkdir(parents=True, exist_ok=True)
    return cache_root / f"{scene_digest}-{digest}", files


def _sample_indices(point_count: int, target_count: int) -> np.ndarray:
    target = min(max(0, int(target_count)), point_count)
    if target >= point_count:
        return np.arange(point_count, dtype=np.int64)
    if target <= 0:
        return np.empty((0,), dtype=np.int64)
    return np.linspace(0, point_count - 1, num=target, dtype=np.int64)


def _quantize_intensity(values: np.ndarray, low: float, high: float) -> np.ndarray:
    if not math.isfinite(low) or not math.isfinite(high) or high - low <= 1e-6:
        return np.zeros((len(values),), dtype=np.uint8)
    normalized = np.asarray(values, dtype=np.float32).copy()
    np.subtract(normalized, np.float32(low), out=normalized)
    np.multiply(normalized, np.float32(255.0 / (high - low)), out=normalized)
    np.clip(normalized, 0.0, 255.0, out=normalized)
    np.nan_to_num(normalized, copy=False, nan=0.0, posinf=255.0, neginf=0.0)
    return np.ascontiguousarray(normalized.astype(np.uint8))


def _write_tile_payload(
    path: Path,
    records: np.ndarray,
    *,
    include_intensity: bool,
    intensity_low: float,
    intensity_high: float,
) -> dict[str, Any]:
    # Store Three.js coordinates directly: map (x, y, z) -> (x, z, -y).
    # This avoids a second full position buffer in the browser.
    positions = np.empty((len(records), 3), dtype="<f4")
    positions[:, 0] = records[:, 0]
    positions[:, 1] = records[:, 2]
    positions[:, 2] = -records[:, 1]
    with path.open("wb") as target:
        positions.tofile(target)
        if include_intensity:
            _quantize_intensity(records[:, 3], intensity_low, intensity_high).tofile(target)
    byte_length = len(records) * (13 if include_intensity else 12)
    return {
        "file": path.name,
        "point_count": int(len(records)),
        "byte_length": int(byte_length),
        "has_intensity": include_intensity,
    }


def _iter_split_records(
    records: np.ndarray,
    max_points: int,
    path: str = "r",
    depth: int = 0,
) -> Iterator[tuple[str, np.ndarray]]:
    if len(records) <= max_points or depth >= 12:
        yield path, records
        return
    span = np.ptp(records[:, :3], axis=0)
    axis = int(np.argmax(span))
    order = np.argsort(records[:, axis], kind="stable")
    midpoint = max(1, len(order) // 2)
    yield from _iter_split_records(records[order[:midpoint]], max_points, f"{path}0", depth + 1)
    yield from _iter_split_records(records[order[midpoint:]], max_points, f"{path}1", depth + 1)


def _update_intensity_sample(current: np.ndarray, values: np.ndarray | None) -> np.ndarray:
    if values is None or len(values) == 0:
        return current
    finite = np.asarray(values, dtype=np.float32)
    finite = finite[np.isfinite(finite)]
    if len(finite) == 0:
        return current
    sample = finite[_sample_indices(len(finite), min(2048, len(finite)))]
    combined = sample if len(current) == 0 else np.concatenate((current, sample))
    if len(combined) > 65_536:
        combined = combined[_sample_indices(len(combined), 65_536)]
    return np.ascontiguousarray(combined, dtype=np.float32)


def _partition_role_source(
    source_path: Path,
    role: str,
    partition_dir: Path,
) -> tuple[list[Path], np.ndarray, int]:
    header, data_start_offset = parse_pcd_header(source_path)
    normalized = normalize_pcd_header(header)
    if normalized["data_type"] not in ("ascii", "binary"):
        raise PcdMapError(f"当前分层点云不支持 DATA {normalized['data_type']} PCD")

    partition_dir.mkdir(parents=True, exist_ok=True)
    tile_size = max(0.5, float(settings.PCD_SCENE_TILE_SIZE_M))
    chunk_points = max(1, int(settings.PCD_SCENE_TILE_BUILD_CHUNK_POINTS))
    intensity_sample = np.empty((0,), dtype=np.float32)
    retained_before_final = 0

    for points, intensity in iter_pcd_xyz_intensity_float32(
        source_path,
        header,
        data_start_offset,
        chunk_points=chunk_points,
    ):
        if len(points) == 0:
            continue
        retained_before_final += len(points)
        if role == "wall":
            intensity_sample = _update_intensity_sample(intensity_sample, intensity)

        records = np.empty((len(points), 4), dtype="<f4")
        records[:, :3] = points
        records[:, 3] = intensity if intensity is not None else np.nan
        keys = np.floor(points / tile_size).astype(np.int32)
        order = np.lexsort((keys[:, 2], keys[:, 1], keys[:, 0]))
        ordered_keys = keys[order]
        ordered_records = records[order]
        group_starts = np.flatnonzero(
            np.r_[True, np.any(ordered_keys[1:] != ordered_keys[:-1], axis=1)],
        )
        group_ends = np.r_[group_starts[1:], len(ordered_records)]
        for start, end in zip(group_starts, group_ends):
            key = ordered_keys[start]
            bucket_path = partition_dir / f"x{int(key[0])}_y{int(key[1])}_z{int(key[2])}.part"
            with bucket_path.open("ab") as bucket:
                ordered_records[start:end].tofile(bucket)

    return sorted(partition_dir.glob("*.part")), intensity_sample, retained_before_final


def _build_role_tiles(
    source_path: Path,
    role: str,
    temporary_dir: Path,
    tiles_dir: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, dict[str, float] | None, dict[str, Any]]:
    partition_paths, intensity_sample, partition_points = _partition_role_source(
        source_path,
        role,
        temporary_dir / "partitions" / role,
    )
    if not partition_paths:
        return [], None, None, {
            "source_points": 0,
            "original_points": 0,
            "balanced_points": 0,
            "performance_points": 0,
            "retained_points": 0,
        }

    has_intensity = role == "wall" and len(intensity_sample) >= 2
    if has_intensity:
        intensity_low, intensity_high = np.percentile(intensity_sample, [2.0, 98.0])
        intensity_low = float(intensity_low)
        intensity_high = float(intensity_high)
        has_intensity = math.isfinite(intensity_low) and math.isfinite(intensity_high) and intensity_high > intensity_low
    else:
        intensity_low = 0.0
        intensity_high = 1.0

    max_points = max(4096, int(settings.PCD_SCENE_TILE_MAX_POINTS))
    balanced_voxel_size = max(0.0, float(settings.PCD_SCENE_TILE_BALANCED_VOXEL_SIZE_M))
    balanced_points_per_voxel = max(1, int(settings.PCD_SCENE_TILE_BALANCED_POINTS_PER_VOXEL))
    performance_voxel_size = max(0.0, float(settings.PCD_SCENE_TILE_PERFORMANCE_VOXEL_SIZE_M))
    performance_points_per_voxel = max(1, int(settings.PCD_SCENE_TILE_PERFORMANCE_POINTS_PER_VOXEL))
    nodes: list[dict[str, Any]] = []
    role_bounds: list[dict[str, float]] = []
    root_candidates_path = temporary_dir / f"{role}.root-candidates"
    tier_point_counts = {"original": 0, "balanced": 0, "performance": 0}

    for partition_index, partition_path in enumerate(partition_paths):
        raw = np.fromfile(partition_path, dtype="<f4")
        if len(raw) == 0 or len(raw) % 4 != 0:
            partition_path.unlink(missing_ok=True)
            continue
        records = raw.reshape((-1, 4))
        for split_path, leaf_records in _iter_split_records(records, max_points):
            if len(leaf_records) == 0:
                continue
            node_id = f"{role}-{partition_index:06d}-{split_path}"
            bounds = _bounds_from_points(leaf_records[:, :3])
            role_bounds.append(bounds)
            original_path = tiles_dir / f"{node_id}.original.bin"
            original = _write_tile_payload(
                original_path,
                leaf_records,
                include_intensity=has_intensity,
                intensity_low=intensity_low,
                intensity_high=intensity_high,
            )

            def downsample_records(
                source_records: np.ndarray,
                voxel_size: float,
                points_per_voxel: int,
            ) -> np.ndarray:
                selected_indices = spatial_downsample_indices(
                    source_records[:, :3],
                    voxel_size,
                    points_per_voxel,
                )
                if selected_indices is None or len(selected_indices) == len(source_records):
                    return source_records
                return np.ascontiguousarray(source_records[selected_indices], dtype="<f4")

            def write_density_payload(name: str, density_records: np.ndarray) -> dict[str, Any]:
                if density_records is leaf_records:
                    return dict(original)
                return _write_tile_payload(
                    tiles_dir / f"{node_id}.{name}.bin",
                    density_records,
                    include_intensity=has_intensity,
                    intensity_low=intensity_low,
                    intensity_high=intensity_high,
                )

            balanced_records = downsample_records(
                leaf_records,
                balanced_voxel_size,
                balanced_points_per_voxel,
            )
            balanced = write_density_payload("balanced", balanced_records)
            performance_records = downsample_records(
                balanced_records,
                performance_voxel_size,
                performance_points_per_voxel,
            )
            performance = (
                dict(balanced)
                if performance_records is balanced_records
                else write_density_payload("performance", performance_records)
            )
            tier_point_counts["original"] += original["point_count"]
            tier_point_counts["balanced"] += balanced["point_count"]
            tier_point_counts["performance"] += performance["point_count"]
            candidate_records = leaf_records[
                _sample_indices(len(leaf_records), PCD_TILE_ROOT_CANDIDATES_PER_LEAF)
            ]
            with root_candidates_path.open("ab") as root_candidates:
                candidate_records.tofile(root_candidates)

            center = [
                (bounds["min_x"] + bounds["max_x"]) / 2,
                (bounds["min_y"] + bounds["max_y"]) / 2,
                (bounds["min_z"] + bounds["max_z"]) / 2,
            ]
            radius = 0.5 * math.sqrt(
                (bounds["max_x"] - bounds["min_x"]) ** 2
                + (bounds["max_y"] - bounds["min_y"]) ** 2
                + (bounds["max_z"] - bounds["min_z"]) ** 2
            )
            nodes.append({
                "id": node_id,
                "role": role,
                "bounds": bounds,
                "center": center,
                "radius": radius,
                "performance": performance,
                "balanced": balanced,
                "original": original,
            })
        partition_path.unlink(missing_ok=True)

    root_tile = None
    if root_candidates_path.is_file():
        root_raw = np.fromfile(root_candidates_path, dtype="<f4")
        if len(root_raw) % 4 == 0 and len(root_raw) > 0:
            root_records = root_raw.reshape((-1, 4))
            role_root_budget = max(1, int(settings.PCD_SCENE_TILE_ROOT_POINTS) // len(PCD_TILE_ROLE_ORDER))
            root_records = root_records[_sample_indices(len(root_records), role_root_budget)]
            root_path = tiles_dir / f"{role}.root.bin"
            root_tile = {
                "id": f"{role}-root",
                "role": role,
                "bounds": _merge_bounds(role_bounds),
                **_write_tile_payload(
                    root_path,
                    root_records,
                    include_intensity=has_intensity,
                    intensity_low=intensity_low,
                    intensity_high=intensity_high,
                ),
            }

    stats: dict[str, Any] = {
        "source_points": int(partition_points),
        "original_points": int(tier_point_counts["original"]),
        "balanced_points": int(tier_point_counts["balanced"]),
        "performance_points": int(tier_point_counts["performance"]),
        # 兼容旧前端字段；原始档只清理无效点，不做空间降采样。
        "retained_points": int(tier_point_counts["original"]),
        "tile_count": len(nodes),
    }
    if has_intensity:
        stats["intensity_percentile_2_98"] = [intensity_low, intensity_high]
    return nodes, root_tile, _merge_bounds(role_bounds) if role_bounds else None, stats


def _trim_tile_cache(cache_root: Path, keep: Path) -> None:
    max_scenes = max(1, int(settings.PCD_SCENE_TILE_CACHE_MAX_SCENES))
    max_bytes = max(1024 * 1024 * 1024, int(settings.PCD_SCENE_TILE_CACHE_MAX_BYTES))
    entries = sorted(
        (
            path for path in cache_root.iterdir()
            if path.is_dir() and (path / "manifest.json").is_file()
        ),
        key=lambda path: (path / "manifest.json").stat().st_mtime_ns,
        reverse=True,
    )
    sizes = {
        path: sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
        for path in entries
    }
    retained_bytes = 0
    retained_count = 0
    for entry in entries:
        entry_size = sizes[entry]
        should_keep = entry == keep or (
            retained_count < max_scenes
            and retained_bytes + entry_size <= max_bytes
        )
        if should_keep:
            retained_count += 1
            retained_bytes += entry_size
            continue
        shutil.rmtree(entry, ignore_errors=True)


def _build_scene_tiles(scene_id: str, cache_dir: Path, files: dict[str, Path | None]) -> None:
    temporary_dir = cache_dir.with_name(
        f".{cache_dir.name}.{os.getpid()}.{threading.get_ident()}.tmp",
    )
    if temporary_dir.exists():
        shutil.rmtree(temporary_dir)
    tiles_dir = temporary_dir / "tiles"
    tiles_dir.mkdir(parents=True, exist_ok=True)
    all_nodes: list[dict[str, Any]] = []
    root_tiles: list[dict[str, Any]] = []
    layer_bounds: dict[str, dict[str, float] | None] = {}
    layer_stats: dict[str, dict[str, Any] | None] = {}
    try:
        for role in PCD_TILE_ROLE_ORDER:
            source_path = files.get(role)
            if source_path is None:
                layer_bounds[role] = None
                layer_stats[role] = None
                continue
            tile_logger.info("开始构建场景 {} 的 {} 分层瓦片", scene_id, role)
            nodes, root_tile, bounds, stats = _build_role_tiles(
                source_path,
                role,
                temporary_dir,
                tiles_dir,
            )
            all_nodes.extend(nodes)
            if root_tile is not None:
                root_tiles.append(root_tile)
            layer_bounds[role] = bounds
            layer_stats[role] = stats
            tile_logger.info(
                "场景 {} 的 {} 瓦片完成：{} 个节点，保留 {} 点",
                scene_id,
                role,
                len(nodes),
                stats["original_points"],
            )

        manifest = {
            "version": PCD_TILE_CACHE_VERSION,
            "cache_key": cache_dir.name,
            "scene_id": scene_id,
            "frame_id": settings.PCD_FRAME_ID,
            "bounds": _merge_bounds(list(layer_bounds.values())),
            "layer_bounds": layer_bounds,
            "root_tiles": root_tiles,
            "nodes": all_nodes,
            "stats": layer_stats,
            "settings": {
                "tile_size_m": float(settings.PCD_SCENE_TILE_SIZE_M),
                "balanced_voxel_size_m": float(settings.PCD_SCENE_TILE_BALANCED_VOXEL_SIZE_M),
                "balanced_points_per_voxel": int(settings.PCD_SCENE_TILE_BALANCED_POINTS_PER_VOXEL),
                "performance_voxel_size_m": float(settings.PCD_SCENE_TILE_PERFORMANCE_VOXEL_SIZE_M),
                "performance_points_per_voxel": int(settings.PCD_SCENE_TILE_PERFORMANCE_POINTS_PER_VOXEL),
                "max_points_per_tile": int(settings.PCD_SCENE_TILE_MAX_POINTS),
            },
        }
        (temporary_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temporary_dir, cache_dir)
    finally:
        if temporary_dir.exists():
            shutil.rmtree(temporary_dir, ignore_errors=True)


def prepare_scene_tile_manifest(scene_id: str) -> Path:
    cache_dir, files = _cache_key(scene_id)
    manifest_path = cache_dir / "manifest.json"
    if manifest_path.is_file():
        return manifest_path
    with _tile_cache_lock:
        if manifest_path.is_file():
            return manifest_path
        _build_scene_tiles(scene_id, cache_dir, files)
        _trim_tile_cache(cache_dir.parent, cache_dir)
    return manifest_path


def resolve_scene_tile_file(scene_id: str, tile_file: str) -> Path:
    if not PCD_TILE_FILE_PATTERN.fullmatch(tile_file):
        raise PcdMapError("点云瓦片文件名非法")
    manifest_path = prepare_scene_tile_manifest(scene_id)
    tiles_dir = (manifest_path.parent / "tiles").resolve()
    target = (tiles_dir / tile_file).resolve()
    if target.parent != tiles_dir:
        raise PcdMapError("禁止访问点云瓦片目录以外的文件")
    if not target.is_file():
        raise FileNotFoundError(f"点云瓦片不存在: {tile_file}")
    return target
