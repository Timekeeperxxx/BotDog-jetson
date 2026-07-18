from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import settings
from .logging_config import get_logger
from .pcd_errors import PcdMapError
from .pcd_ground import snap_xy_to_ground_file
from .pcd_reader import (
    merge_bounds as _merge_bounds,
    normalize_pcd_header,
    parse_pcd_header,
    read_pcd_preview,
    read_pcd_xyz_intensity_uint8,
)
from .repositories.json_store import read_json


pcd_logger = get_logger("场景点云服务")
SCENE_ID_PATTERN = re.compile(r"^Scene\d+_")
PCD_SCENE_BINARY_MAGIC = b"BDPCD001"
PCD_SCENE_BINARY_CACHE_VERSION = 2
_scene_preview_cache_lock = threading.Lock()


def _utc_from_timestamp(ts: float) -> str:
    return datetime.utcfromtimestamp(ts).isoformat(timespec="milliseconds") + "Z"


def _file_info(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "name": path.name,
        "size_bytes": stat.st_size,
        "modified_at": _utc_from_timestamp(stat.st_mtime),
    }


def _normalize_scene_id(scene_id: str) -> str:
    normalized = str(scene_id).strip()
    if not normalized:
        raise PcdMapError("scene_id 不能为空")
    if normalized in {".", ".."}:
        raise PcdMapError("scene_id 非法")
    if "/" in normalized or "\\" in normalized:
        raise PcdMapError("scene_id 不能包含 / 或 \\")
    if ".." in normalized:
        raise PcdMapError("scene_id 不能包含 ..")
    if any(ord(ch) < 32 for ch in normalized):
        raise PcdMapError("scene_id 不能包含控制字符")
    if not SCENE_ID_PATTERN.match(normalized):
        raise PcdMapError("scene_id 必须匹配 ^Scene\\d+_")
    return normalized


def get_pcd_root() -> Path:
    root = Path(settings.PCD_MAP_ROOT).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_scene_root() -> Path:
    root = Path(settings.SCENE_MAP_ROOT).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def validate_scene_id(scene_id: str) -> None:
    _normalize_scene_id(scene_id)


def resolve_scene_path(scene_id: str) -> Path:
    normalized = _normalize_scene_id(scene_id)
    root = get_scene_root()
    path = (root / normalized).resolve()

    if path.parent != root or path.name != normalized:
        raise PcdMapError("禁止访问场景根目录以外的路径")
    if not path.exists():
        raise FileNotFoundError(f"场景目录不存在: {normalized}")
    if not path.is_dir():
        raise PcdMapError("scene_id 不是目录")
    return path


def resolve_scene_ground_path(scene_id: str) -> Path:
    try:
        scene_path = resolve_scene_path(scene_id)
    except PcdMapError:
        if str(scene_id).strip().lower().endswith(".pcd"):
            return resolve_pcd_path(scene_id)
        raise

    files = find_scene_pcd_files(scene_path)
    ground_file = files["ground"]
    if ground_file is None:
        raise FileNotFoundError(f"场景缺少 ground.pcd: {scene_id}")
    return ground_file


def resolve_pcd_path(map_id: str) -> Path:
    if not map_id:
        raise PcdMapError("map_id 不能为空")

    if "/" in map_id or "\\" in map_id or ".." in map_id:
        raise PcdMapError("非法 map_id")

    if not map_id.lower().endswith(".pcd"):
        raise PcdMapError("只允许读取 .pcd 文件")

    root = get_pcd_root()
    path = (root / map_id).resolve()

    if path.parent != root:
        raise PcdMapError("禁止读取 PCD_MAP_ROOT 以外的文件")

    if not path.exists():
        raise FileNotFoundError(f"PCD 文件不存在: {map_id}")

    if not path.is_file():
        raise PcdMapError("map_id 不是文件")

    return path


def _latest_path(paths: list[Path], label: str, scene_name: str) -> Path | None:
    if not paths:
        return None

    if len(paths) > 1:
        pcd_logger.debug("场景 {} 发现多个 {} 候选文件，将选择最近修改的文件", scene_name, label)
        for candidate in paths:
            pcd_logger.debug(
                "候选 {}：{}，mtime={}",
                label,
                candidate.name,
                _utc_from_timestamp(candidate.stat().st_mtime),
            )

    return max(paths, key=lambda item: item.stat().st_mtime)


def _preferred_scene_pcd(
    paths: list[Path],
    exact_name: str,
    label: str,
    scene_name: str,
) -> Path | None:
    exact_candidates = [path for path in paths if path.name.lower() == exact_name.lower()]
    if exact_candidates:
        return _latest_path(exact_candidates, label, scene_name)
    return _latest_path(paths, label, scene_name)


def find_scene_pcd_files(scene_path: Path) -> dict[str, Path | None]:
    if not scene_path.exists():
        raise FileNotFoundError(f"场景目录不存在: {scene_path.name}")
    if not scene_path.is_dir():
        raise PcdMapError("scene_path 不是目录")

    ground_candidates: list[Path] = []
    wall_candidates: list[Path] = []
    footprint_fill_candidates: list[Path] = []

    for path in scene_path.iterdir():
        if not path.is_file() or path.suffix.lower() != ".pcd":
            continue

        lower_name = path.name.lower()
        if lower_name.endswith("footprint_fill.pcd"):
            footprint_fill_candidates.append(path)
            continue
        if lower_name.endswith("ground.pcd"):
            ground_candidates.append(path)
            continue
        if lower_name.endswith("map.pcd") and not lower_name.endswith("ground.pcd"):
            wall_candidates.append(path)

    return {
        "wall": _preferred_scene_pcd(wall_candidates, "map.pcd", "wall/map.pcd", scene_path.name),
        "ground": _preferred_scene_pcd(ground_candidates, "ground.pcd", "ground.pcd", scene_path.name),
        "footprint_fill": _latest_path(footprint_fill_candidates, "*footprint_fill.pcd", scene_path.name),
    }


def list_pcd_maps() -> dict[str, Any]:
    root = get_pcd_root()
    items = []

    for path in root.iterdir():
        if not path.is_file() or path.suffix.lower() != ".pcd":
            continue

        stat = path.stat()
        items.append(
            {
                "id": path.name,
                "name": path.name,
                "size_bytes": stat.st_size,
                "modified_at": _utc_from_timestamp(stat.st_mtime),
            }
        )

    items.sort(key=lambda item: item["modified_at"], reverse=True)
    return {"root": str(root), "items": items}


def list_pcd_scenes() -> dict[str, Any]:
    root = get_scene_root()
    items: list[dict[str, Any]] = []

    for path in root.iterdir():
        if not path.is_dir() or not SCENE_ID_PATTERN.match(path.name):
            continue

        scene_stat = path.stat()
        files = find_scene_pcd_files(path)
        wall_info = _file_info(files["wall"]) if files["wall"] else None
        ground_info = _file_info(files["ground"]) if files["ground"] else None
        footprint_fill_info = _file_info(files["footprint_fill"]) if files["footprint_fill"] else None
        ready = wall_info is not None and ground_info is not None
        navigable = ground_info is not None

        if not wall_info and not ground_info:
            message = "缺少 map.pcd，缺少 ground.pcd"
        elif not wall_info:
            message = "缺少 map.pcd"
        elif not ground_info:
            message = "缺少 ground.pcd"
        else:
            message = None

        items.append(
            {
                "id": path.name,
                "name": path.name,
                "path": str(path),
                "modified_at": _utc_from_timestamp(scene_stat.st_mtime),
                "wall": wall_info,
                "ground": ground_info,
                "footprint_fill": footprint_fill_info,
                "ready": ready,
                "navigable": navigable,
                "message": message,
            }
        )

    items.sort(key=lambda item: item["modified_at"], reverse=True)
    return {"root": str(root), "items": items}


def delete_pcd_scene(scene_id: str) -> dict[str, Any]:
    scene_path = resolve_scene_path(scene_id)
    cleanup: dict[str, Any] = {}

    from .services_nav_localization import delete_scene_localization_data
    from .services_nav_tasks import delete_nav_tasks_for_scene
    from .services_nav_waypoints import delete_scene_waypoint_data

    cleanup["waypoints"] = delete_scene_waypoint_data(scene_id)
    cleanup["localization"] = delete_scene_localization_data(scene_id)
    cleanup["tasks"] = delete_nav_tasks_for_scene(scene_id)
    cleanup["runtime"] = _delete_scene_runtime_json(scene_id)

    pcd_logger.info("准备删除场景目录：{}", scene_path)
    shutil.rmtree(scene_path)
    pcd_logger.info("场景目录已删除：{}", scene_path)
    return {
        "success": True,
        "scene_id": scene_id,
        "deleted_path": str(scene_path),
        "cleanup": cleanup,
        "message": "场景目录及关联 JSON 已删除",
    }


def _delete_scene_runtime_json(scene_id: str) -> dict[str, Any]:
    runtime_dir = Path(settings.NAV_RUNTIME_DIR).resolve()
    deleted_files: list[str] = []
    runtime_files = {
        "current_scene.json": ("scene_id",),
        "current_task.json": ("scene_id", "map_id", "mapId", "sceneId"),
        "current_goal.json": ("map_id", "mapId", "sceneId"),
    }

    for filename, fields in runtime_files.items():
        path = runtime_dir / filename
        data = read_json(path, None)
        if not isinstance(data, dict):
            continue
        if any(str(data.get(field) or "").strip() == scene_id for field in fields):
            path.unlink(missing_ok=True)
            deleted_files.append(str(path))

    return {"deleted_files": deleted_files}


def snap_xy_to_ground(
    scene_id: str,
    x: float,
    y: float,
    *,
    fallback_z: float | None = None,
    max_distance_m: float | None = None,
    neighbor_count: int | None = None,
) -> dict[str, Any]:
    max_distance = float(settings.NAV_WAYPOINT_GROUND_SNAP_MAX_DISTANCE_M if max_distance_m is None else max_distance_m)
    limit = int(settings.NAV_WAYPOINT_GROUND_SNAP_NEIGHBORS if neighbor_count is None else neighbor_count)
    ground_path = resolve_scene_ground_path(scene_id)
    return snap_xy_to_ground_file(
        ground_path,
        x,
        y,
        fallback_z=fallback_z,
        max_distance_m=max_distance,
        neighbor_count=limit,
    )


def _build_file_metadata(path: Path) -> dict[str, Any]:
    header, data_start_offset = parse_pcd_header(path)
    normalized = normalize_pcd_header(header)
    file_info = _file_info(path)
    data_type = normalized["data_type"]

    payload: dict[str, Any] = {
        **file_info,
        "frame_id": settings.PCD_FRAME_ID,
        "type": "pcd",
        "point_count": normalized["point_count"],
        "fields": normalized["fields"],
        "data_type": data_type,
        "bounds": None,
        "supported": False,
        "message": None,
    }

    if data_type not in ("ascii", "binary"):
        payload["message"] = f"当前暂不支持 DATA {data_type} PCD"
        return payload

    _, bounds = read_pcd_preview(
        path=path,
        header=header,
        data_start_offset=data_start_offset,
        # 与前端默认 preview 使用同一采样量，使后续 preview 直接命中缓存。
        max_points=settings.PCD_PREVIEW_DEFAULT_POINTS,
    )

    payload["bounds"] = bounds
    payload["supported"] = True
    return payload


def get_pcd_metadata(map_id: str) -> dict[str, Any]:
    path = resolve_pcd_path(map_id)
    header, data_start_offset = parse_pcd_header(path)
    normalized = normalize_pcd_header(header)

    data_type = normalized["data_type"]
    if data_type not in ("ascii", "binary"):
        return {
            "map_id": map_id,
            "name": map_id,
            "frame_id": settings.PCD_FRAME_ID,
            "type": "pcd",
            "point_count": normalized["point_count"],
            "fields": normalized["fields"],
            "data_type": data_type,
            "bounds": None,
            "supported": False,
            "message": f"当前 Demo 暂不支持 DATA {data_type} PCD",
        }

    _, bounds = read_pcd_preview(
        path=path,
        header=header,
        data_start_offset=data_start_offset,
        max_points=settings.PCD_PREVIEW_DEFAULT_POINTS,
    )

    return {
        "map_id": map_id,
        "name": map_id,
        "frame_id": settings.PCD_FRAME_ID,
        "type": "pcd",
        "point_count": normalized["point_count"],
        "fields": normalized["fields"],
        "data_type": data_type,
        "bounds": bounds,
        "supported": True,
        "message": None,
    }


def get_pcd_preview(map_id: str, max_points: int | None = None) -> dict[str, Any]:
    path = resolve_pcd_path(map_id)
    header, data_start_offset = parse_pcd_header(path)
    normalized = normalize_pcd_header(header)

    data_type = normalized["data_type"]
    if data_type not in ("ascii", "binary"):
        raise PcdMapError(f"当前 Demo 暂不支持 DATA {data_type} PCD")

    if max_points is None:
        max_points = settings.PCD_PREVIEW_DEFAULT_POINTS

    max_points = max(1000, min(max_points, settings.PCD_PREVIEW_MAX_POINTS))

    points, bounds = read_pcd_preview(
        path=path,
        header=header,
        data_start_offset=data_start_offset,
        max_points=max_points,
    )

    return {
        "map_id": map_id,
        "frame_id": settings.PCD_FRAME_ID,
        "points": points,
        "bounds": bounds,
    }


def get_scene_metadata(scene_id: str) -> dict[str, Any]:
    scene_path = resolve_scene_path(scene_id)
    files = find_scene_pcd_files(scene_path)
    wall_meta = _build_file_metadata(files["wall"]) if files["wall"] else None
    ground_meta = _build_file_metadata(files["ground"]) if files["ground"] else None
    footprint_fill_meta = _build_file_metadata(files["footprint_fill"]) if files["footprint_fill"] else None
    summary_meta = ground_meta or wall_meta

    bounds = _merge_bounds(
        [
            wall_meta["bounds"] if wall_meta else None,
            ground_meta["bounds"] if ground_meta else None,
            footprint_fill_meta["bounds"] if footprint_fill_meta else None,
        ],
    )

    if ground_meta is None:
        supported = False
        message = "缺少 ground.pcd，不能用于导航"
    elif not ground_meta["supported"]:
        supported = False
        message = ground_meta["message"] or "地面点云暂不支持预览"
    elif wall_meta is None:
        supported = True
        message = "缺少墙壁点云，仅显示地面点云"
    else:
        supported = True
        message = wall_meta["message"] if wall_meta and wall_meta.get("supported") is False else None

    return {
        "scene_id": scene_id,
        "name": scene_path.name,
        "frame_id": settings.PCD_FRAME_ID,
        "type": "scene_pcd",
        "point_count": int(summary_meta["point_count"]) if summary_meta else 0,
        "fields": list(summary_meta["fields"]) if summary_meta else [],
        "data_type": str(summary_meta["data_type"]) if summary_meta else "unknown",
        "files": {
            "wall": wall_meta,
            "ground": ground_meta,
            "footprint_fill": footprint_fill_meta,
        },
        "bounds": bounds,
        "supported": supported,
        "message": message,
    }


def get_scene_preview(scene_id: str, max_points: int | None = None) -> dict[str, Any]:
    if max_points is None:
        max_points = settings.PCD_PREVIEW_DEFAULT_POINTS

    max_points = max(1000, min(max_points, settings.PCD_PREVIEW_MAX_POINTS))

    scene_path = resolve_scene_path(scene_id)
    files = find_scene_pcd_files(scene_path)

    layers: dict[str, dict[str, Any] | None] = {"ground": None, "wall": None, "footprint_fill": None}
    layer_bounds: list[dict[str, float] | None] = []

    for role in ("ground", "wall", "footprint_fill"):
        path = files[role]
        if path is None:
            continue

        try:
            header, data_start_offset = parse_pcd_header(path)
            normalized = normalize_pcd_header(header)
            if normalized["data_type"] not in ("ascii", "binary"):
                raise PcdMapError(f"当前 Demo 暂不支持 DATA {normalized['data_type']} PCD")
            points, bounds = read_pcd_preview(
                path=path,
                header=header,
                data_start_offset=data_start_offset,
                max_points=max_points,
            )
        except PcdMapError as exc:
            pcd_logger.warning("场景 {} 的 {} 图层预览失败：{}", scene_id, role, exc)
            continue

        layers[role] = {
            "role": role,
            "file_name": path.name,
            "points": points,
            "bounds": bounds,
        }
        layer_bounds.append(bounds)

    return {
        "scene_id": scene_id,
        "frame_id": settings.PCD_FRAME_ID,
        "layers": layers,
        "bounds": _merge_bounds(layer_bounds),
    }


def get_scene_preview_binary(scene_id: str, max_points: int | None = None) -> bytes:
    """Encode a spatially density-limited scene as compact float32 data.

    With no explicit legacy ``max_points``, every occupied 3D voxel retains up
    to the configured number of points. There is no whole-scene point limit.
    """
    import numpy as np

    if max_points is not None:
        max_points = max(1000, min(max_points, settings.PCD_PREVIEW_MAX_POINTS))
        voxel_size_m = None
        max_points_per_voxel = 1
    else:
        voxel_size_m = max(0.0, float(settings.PCD_SCENE_PREVIEW_VOXEL_SIZE_M))
        max_points_per_voxel = max(1, int(settings.PCD_SCENE_PREVIEW_POINTS_PER_VOXEL))

    scene_path = resolve_scene_path(scene_id)
    files = find_scene_pcd_files(scene_path)
    binary_layers: dict[str, dict[str, Any] | None] = {}
    chunks: list[bytes] = []
    layer_bounds: list[dict[str, float] | None] = []
    byte_offset = 0

    for role in ("ground", "wall", "footprint_fill"):
        path = files[role]
        if path is None:
            binary_layers[role] = None
            continue

        try:
            pcd_header, data_start_offset = parse_pcd_header(path)
            normalized = normalize_pcd_header(pcd_header)
            if normalized["data_type"] not in ("ascii", "binary"):
                raise PcdMapError(f"当前 Demo 暂不支持 DATA {normalized['data_type']} PCD")
            points, intensity, bounds = read_pcd_xyz_intensity_uint8(
                path=path,
                header=pcd_header,
                data_start_offset=data_start_offset,
                max_points=max_points,
                voxel_size_m=voxel_size_m,
                max_points_per_voxel=max_points_per_voxel,
            )
            points = np.asarray(points, dtype="<f4").reshape((-1, 3))
            if role != "wall":
                intensity = None
        except PcdMapError as exc:
            pcd_logger.warning("场景 {} 的 {} 二进制点云读取失败：{}", scene_id, role, exc)
            binary_layers[role] = None
            continue

        chunk = points.tobytes(order="C")
        intensity_chunk = (
            np.asarray(intensity, dtype=np.uint8).reshape((-1,)).tobytes(order="C")
            if intensity is not None and len(intensity) == len(points)
            else b""
        )
        intensity_offset = byte_offset + len(chunk) if intensity_chunk else None
        binary_layers[role] = {
            "role": role,
            "file_name": path.name,
            "bounds": bounds,
            "point_count": len(points),
            "byte_offset": byte_offset,
            "byte_length": len(chunk),
            "intensity_byte_offset": intensity_offset,
            "intensity_byte_length": len(intensity_chunk),
            "intensity_encoding": "uint8_percentile_2_98" if intensity_chunk else None,
        }
        chunks.append(chunk)
        if intensity_chunk:
            chunks.append(intensity_chunk)
            padding = b"\0" * (-len(intensity_chunk) % 4)
            if padding:
                chunks.append(padding)
        layer_bounds.append(bounds)
        byte_offset += len(chunk) + len(intensity_chunk) + (-len(intensity_chunk) % 4)

    header = json.dumps(
        {
            "scene_id": scene_id,
            "frame_id": settings.PCD_FRAME_ID,
            "layers": binary_layers,
            "bounds": _merge_bounds(layer_bounds),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    # 保证后续 Float32 数据按 4 字节对齐；JSON 允许尾随空白。
    header += b" " * (-len(header) % 4)
    return PCD_SCENE_BINARY_MAGIC + struct.pack("<I", len(header)) + header + b"".join(chunks)


def _scene_preview_cache_path(scene_id: str, max_points: int | None) -> Path:
    scene_path = resolve_scene_path(scene_id)
    files = find_scene_pcd_files(scene_path)
    source_versions: dict[str, dict[str, Any] | None] = {}
    for role, path in files.items():
        if path is None:
            source_versions[role] = None
            continue
        stat = path.stat()
        source_versions[role] = {
            "path": str(path.resolve()),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }

    cache_key = {
        "version": PCD_SCENE_BINARY_CACHE_VERSION,
        "scene_id": scene_id,
        "frame_id": settings.PCD_FRAME_ID,
        "max_points": max_points,
        "voxel_size_m": None if max_points is not None else float(settings.PCD_SCENE_PREVIEW_VOXEL_SIZE_M),
        "max_points_per_voxel": None if max_points is not None else int(settings.PCD_SCENE_PREVIEW_POINTS_PER_VOXEL),
        "sources": source_versions,
    }
    digest = hashlib.sha256(
        json.dumps(cache_key, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"),
    ).hexdigest()
    scene_digest = hashlib.sha1(scene_id.encode("utf-8")).hexdigest()[:12]
    cache_dir = Path(settings.PCD_SCENE_PREVIEW_CACHE_DIR).resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{scene_digest}-{digest}.bin"


def _trim_scene_preview_cache(cache_dir: Path) -> None:
    max_entries = max(1, int(settings.PCD_SCENE_PREVIEW_CACHE_MAX_ENTRIES))
    entries = sorted(
        cache_dir.glob("*.bin"),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    for stale_path in entries[max_entries:]:
        try:
            stale_path.unlink()
        except FileNotFoundError:
            pass


def prepare_scene_preview_binary(scene_id: str, max_points: int | None = None) -> Path:
    """Build once and return a cache file suitable for ``FileResponse``."""
    cache_path = _scene_preview_cache_path(scene_id, max_points)
    if cache_path.is_file():
        return cache_path

    with _scene_preview_cache_lock:
        if cache_path.is_file():
            return cache_path

        payload = get_scene_preview_binary(scene_id, max_points=max_points)
        temporary_path = cache_path.with_name(
            f".{cache_path.name}.{os.getpid()}.{threading.get_ident()}.tmp",
        )
        try:
            temporary_path.write_bytes(payload)
            os.replace(temporary_path, cache_path)
        finally:
            temporary_path.unlink(missing_ok=True)
        _trim_scene_preview_cache(cache_path.parent)
        return cache_path
