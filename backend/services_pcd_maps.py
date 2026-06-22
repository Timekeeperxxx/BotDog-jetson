from __future__ import annotations

import math
import re
import struct
import shutil
import heapq
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import numpy as np
    _NUMPY_AVAILABLE = True
except ImportError:
    _NUMPY_AVAILABLE = False

# 内存缓存：key=(path_str, mtime, max_points) → (points, bounds)
# 后端进程存活期间有效；文件修改后 mtime 变化自动失效
_preview_cache: dict[tuple, tuple] = {}
_GROUND_GRID_CELL_SIZE_M = 0.5
_ground_xyz_cache: dict[tuple[str, float], tuple[Any, Any, Any, dict[tuple[int, int], Any], float]] = {}

from .config import settings
from .logging_config import get_logger


pcd_logger = get_logger("场景点云服务")
SCENE_ID_PATTERN = re.compile(r"^Scene\d+_")


class PcdMapError(Exception):
    pass


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
    pcd_logger.info("准备删除场景目录：{}", scene_path)
    shutil.rmtree(scene_path)
    pcd_logger.info("场景目录已删除：{}", scene_path)
    return {
        "success": True,
        "scene_id": scene_id,
        "deleted_path": str(scene_path),
        "message": "场景目录已删除",
    }


def parse_pcd_header(path: Path) -> tuple[dict[str, list[str]], int]:
    header_lines: list[str] = []
    data_start_offset = 0

    with path.open("rb") as f:
        while True:
            line = f.readline()
            if not line:
                break

            decoded = line.decode("utf-8", errors="ignore").strip()
            header_lines.append(decoded)
            data_start_offset = f.tell()

            if decoded.upper().startswith("DATA "):
                break

    header: dict[str, list[str]] = {}

    for line in header_lines:
        if not line or line.startswith("#"):
            continue

        parts = line.split()
        if not parts:
            continue

        key = parts[0].upper()
        header[key] = parts[1:]

    if "FIELDS" not in header:
        raise PcdMapError("PCD header 缺少 FIELDS")

    if "DATA" not in header:
        raise PcdMapError("PCD header 缺少 DATA")

    fields = header["FIELDS"]
    for required in ("x", "y", "z"):
        if required not in fields:
            raise PcdMapError(f"PCD 文件不包含字段: {required}")

    return header, data_start_offset


def normalize_pcd_header(header: dict[str, list[str]]) -> dict[str, Any]:
    fields = header.get("FIELDS", [])
    data_type = header.get("DATA", ["unknown"])[0].lower()

    if "POINTS" in header:
        point_count = int(header["POINTS"][0])
    else:
        width = int(header.get("WIDTH", ["0"])[0])
        height = int(header.get("HEIGHT", ["1"])[0])
        point_count = width * height

    return {
        "fields": fields,
        "data_type": data_type,
        "point_count": point_count,
    }


def _empty_bounds() -> dict[str, float]:
    return {
        "min_x": float("inf"),
        "max_x": float("-inf"),
        "min_y": float("inf"),
        "max_y": float("-inf"),
        "min_z": float("inf"),
        "max_z": float("-inf"),
    }


def _update_bounds(bounds: dict[str, float], x: float, y: float, z: float) -> None:
    bounds["min_x"] = min(bounds["min_x"], x)
    bounds["max_x"] = max(bounds["max_x"], x)
    bounds["min_y"] = min(bounds["min_y"], y)
    bounds["max_y"] = max(bounds["max_y"], y)
    bounds["min_z"] = min(bounds["min_z"], z)
    bounds["max_z"] = max(bounds["max_z"], z)


def _finalize_bounds(bounds: dict[str, float]) -> dict[str, float]:
    if bounds["min_x"] == float("inf"):
        raise PcdMapError("PCD 文件没有可解析点")
    return bounds


def _merge_bounds(bounds_list: list[dict[str, float] | None]) -> dict[str, float]:
    merged = _empty_bounds()
    has_any = False
    for bounds in bounds_list:
        if not bounds:
            continue
        if bounds["min_x"] == float("inf"):
            continue
        if not has_any:
            merged = dict(bounds)
            has_any = True
            continue
        merged["min_x"] = min(merged["min_x"], bounds["min_x"])
        merged["max_x"] = max(merged["max_x"], bounds["max_x"])
        merged["min_y"] = min(merged["min_y"], bounds["min_y"])
        merged["max_y"] = max(merged["max_y"], bounds["max_y"])
        merged["min_z"] = min(merged["min_z"], bounds["min_z"])
        merged["max_z"] = max(merged["max_z"], bounds["max_z"])

    return merged if has_any else {
        "min_x": 0.0,
        "max_x": 0.0,
        "min_y": 0.0,
        "max_y": 0.0,
        "min_z": 0.0,
        "max_z": 0.0,
    }


def read_ascii_preview(
    path: Path,
    header: dict[str, list[str]],
    data_start_offset: int,
    max_points: int,
) -> tuple[list[list[float]], dict[str, float]]:
    fields = header["FIELDS"]
    x_idx = fields.index("x")
    y_idx = fields.index("y")
    z_idx = fields.index("z")

    normalized = normalize_pcd_header(header)
    point_count = max(1, normalized["point_count"])
    step = max(1, math.ceil(point_count / max_points))

    bounds = _empty_bounds()
    points: list[list[float]] = []
    parsed_index = 0

    with path.open("rb") as f:
        f.seek(data_start_offset)

        for raw in f:
            line = raw.decode("utf-8", errors="ignore").strip()
            if not line:
                continue

            parts = line.split()
            if len(parts) <= max(x_idx, y_idx, z_idx):
                continue

            try:
                x = float(parts[x_idx])
                y = float(parts[y_idx])
                z = float(parts[z_idx])
            except ValueError:
                continue

            _update_bounds(bounds, x, y, z)

            if parsed_index % step == 0 and len(points) < max_points:
                points.append([x, y, z])

            parsed_index += 1

    return points, _finalize_bounds(bounds)


def _binary_struct_format(size: int, data_type: str) -> str:
    if data_type == "F":
        if size == 4:
            return "f"
        if size == 8:
            return "d"
    elif data_type == "I":
        if size == 1:
            return "b"
        if size == 2:
            return "h"
        if size == 4:
            return "i"
        if size == 8:
            return "q"
    elif data_type == "U":
        if size == 1:
            return "B"
        if size == 2:
            return "H"
        if size == 4:
            return "I"
        if size == 8:
            return "Q"

    raise PcdMapError(f"暂不支持的 PCD 字段类型: TYPE={data_type}, SIZE={size}")


def _binary_layout(header: dict[str, list[str]]) -> tuple[struct.Struct, dict[str, int]]:
    fields = header["FIELDS"]
    sizes = [int(value) for value in header.get("SIZE", [])]
    types = [value.upper() for value in header.get("TYPE", [])]
    counts = [int(value) for value in header.get("COUNT", ["1"] * len(fields))]

    if not (len(fields) == len(sizes) == len(types) == len(counts)):
        raise PcdMapError("PCD header 中 FIELDS/SIZE/TYPE/COUNT 数量不一致")

    format_parts: list[str] = ["<"]
    value_offsets: dict[str, int] = {}
    value_index = 0

    for field, size, data_type, count in zip(fields, sizes, types, counts):
        if count < 1:
            raise PcdMapError(f"PCD 字段 COUNT 非法: {field}")

        field_format = _binary_struct_format(size, data_type)
        value_offsets[field] = value_index
        format_parts.append(field_format * count)
        value_index += count

    return struct.Struct("".join(format_parts)), value_offsets


def _push_nearest_candidate(
    heap: list[tuple[float, float, float, float, float]],
    limit: int,
    dist_sq: float,
    x: float,
    y: float,
    z: float,
) -> None:
    if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z) and math.isfinite(dist_sq)):
        return
    if abs(x) >= 1e6 or abs(y) >= 1e6 or abs(z) >= 1e6:
        return

    item = (-dist_sq, x, y, z, dist_sq)
    if len(heap) < limit:
        heapq.heappush(heap, item)
        return

    if dist_sq < heap[0][4]:
        heapq.heapreplace(heap, item)


def _nearest_from_heap(
    heap: list[tuple[float, float, float, float, float]],
) -> list[tuple[float, float, float, float]]:
    return sorted(((item[4], item[1], item[2], item[3]) for item in heap), key=lambda item: item[0])


def _ground_cache_key(path: Path) -> tuple[str, float]:
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    return str(path), mtime


def _store_ground_xyz_cache(
    path: Path,
    cache_key: tuple[str, float],
    result: tuple[Any, Any, Any],
) -> tuple[Any, Any, Any, dict[tuple[int, int], Any], float]:
    stale = [key for key in _ground_xyz_cache if key[0] == str(path) and key != cache_key]
    for key in stale:
        del _ground_xyz_cache[key]
    indexed_result = (*result, _build_ground_grid_index(result[0], result[1], _GROUND_GRID_CELL_SIZE_M), _GROUND_GRID_CELL_SIZE_M)
    _ground_xyz_cache[cache_key] = indexed_result
    pcd_logger.info(
        "ground 吸附缓存已加载：{}，点数={}，网格={}",
        path.name,
        len(result[0]),
        len(indexed_result[3]),
    )
    return indexed_result


def _build_ground_grid_index(
    x_all: Any,
    y_all: Any,
    cell_size_m: float,
) -> dict[tuple[int, int], Any]:
    if not _NUMPY_AVAILABLE or len(x_all) == 0:
        return {}

    cell_x = np.floor(x_all / cell_size_m).astype(np.int32)
    cell_y = np.floor(y_all / cell_size_m).astype(np.int32)
    buckets: dict[tuple[int, int], list[int]] = {}
    for index, key in enumerate(zip(cell_x.tolist(), cell_y.tolist())):
        buckets.setdefault(key, []).append(index)
    return {key: np.array(indexes, dtype=np.int32) for key, indexes in buckets.items()}


def _nearest_from_xyz_arrays(
    x_all: Any,
    y_all: Any,
    z_all: Any,
    target_x: float,
    target_y: float,
    limit: int,
) -> list[tuple[float, float, float, float]]:
    if len(x_all) == 0:
        return []

    dist_sq = (x_all - target_x) ** 2 + (y_all - target_y) ** 2
    local_count = min(limit, len(dist_sq))
    indexes = np.argpartition(dist_sq, local_count - 1)[:local_count]
    return sorted(
        (
            (float(dist_sq[index]), float(x_all[index]), float(y_all[index]), float(z_all[index]))
            for index in indexes
        ),
        key=lambda item: item[0],
    )


def _nearest_from_ground_grid(
    x_all: Any,
    y_all: Any,
    z_all: Any,
    grid_index: dict[tuple[int, int], Any],
    cell_size_m: float,
    target_x: float,
    target_y: float,
    limit: int,
    max_distance_m: float,
) -> list[tuple[float, float, float, float]]:
    if not _NUMPY_AVAILABLE or len(x_all) == 0:
        return []
    if not grid_index:
        return _nearest_from_xyz_arrays(x_all, y_all, z_all, target_x, target_y, limit)

    center_x = math.floor(target_x / cell_size_m)
    center_y = math.floor(target_y / cell_size_m)
    search_radius = max(1, math.ceil(max_distance_m / cell_size_m))
    index_parts: list[Any] = []
    for cell_x in range(center_x - search_radius, center_x + search_radius + 1):
        for cell_y in range(center_y - search_radius, center_y + search_radius + 1):
            indexes = grid_index.get((cell_x, cell_y))
            if indexes is not None and len(indexes) > 0:
                index_parts.append(indexes)

    if not index_parts:
        return _nearest_from_xyz_arrays(x_all, y_all, z_all, target_x, target_y, limit)

    indexes = index_parts[0] if len(index_parts) == 1 else np.concatenate(index_parts)
    dist_sq = (x_all[indexes] - target_x) ** 2 + (y_all[indexes] - target_y) ** 2
    local_count = min(limit, len(dist_sq))
    nearest_local = np.argpartition(dist_sq, local_count - 1)[:local_count]
    return sorted(
        (
            (
                float(dist_sq[local_index]),
                float(x_all[indexes[local_index]]),
                float(y_all[indexes[local_index]]),
                float(z_all[indexes[local_index]]),
            )
            for local_index in nearest_local
        ),
        key=lambda item: item[0],
    )


def _collect_nearest_ascii_xyz(
    path: Path,
    header: dict[str, list[str]],
    data_start_offset: int,
    target_x: float,
    target_y: float,
    limit: int,
    max_distance_m: float,
) -> list[tuple[float, float, float, float]]:
    if _NUMPY_AVAILABLE:
        x_all, y_all, z_all, grid_index, cell_size_m = _load_ascii_xyz_numpy_cached(path, header, data_start_offset)
        return _nearest_from_ground_grid(
            x_all,
            y_all,
            z_all,
            grid_index,
            cell_size_m,
            target_x,
            target_y,
            limit,
            max_distance_m,
        )

    fields = header["FIELDS"]
    x_idx = fields.index("x")
    y_idx = fields.index("y")
    z_idx = fields.index("z")
    heap: list[tuple[float, float, float, float, float]] = []

    with path.open("rb") as f:
        f.seek(data_start_offset)
        for raw in f:
            line = raw.decode("utf-8", errors="ignore").strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) <= max(x_idx, y_idx, z_idx):
                continue
            try:
                x = float(parts[x_idx])
                y = float(parts[y_idx])
                z = float(parts[z_idx])
            except ValueError:
                continue
            dist_sq = (x - target_x) ** 2 + (y - target_y) ** 2
            _push_nearest_candidate(heap, limit, dist_sq, x, y, z)

    return _nearest_from_heap(heap)


def _load_ascii_xyz_numpy_cached(
    path: Path,
    header: dict[str, list[str]],
    data_start_offset: int,
) -> tuple[Any, Any, Any, dict[tuple[int, int], Any], float]:
    cache_key = _ground_cache_key(path)
    cached = _ground_xyz_cache.get(cache_key)
    if cached is not None:
        pcd_logger.debug("ground 吸附缓存命中：{}", path.name)
        return cached

    fields = header["FIELDS"]
    x_idx = fields.index("x")
    y_idx = fields.index("y")
    z_idx = fields.index("z")
    x_values: list[float] = []
    y_values: list[float] = []
    z_values: list[float] = []

    with path.open("rb") as f:
        f.seek(data_start_offset)
        for raw in f:
            line = raw.decode("utf-8", errors="ignore").strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) <= max(x_idx, y_idx, z_idx):
                continue
            try:
                x = float(parts[x_idx])
                y = float(parts[y_idx])
                z = float(parts[z_idx])
            except ValueError:
                continue
            if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
                continue
            if abs(x) >= 1e6 or abs(y) >= 1e6 or abs(z) >= 1e6:
                continue
            x_values.append(x)
            y_values.append(y)
            z_values.append(z)

    result = (
        np.array(x_values, dtype=np.float32),
        np.array(y_values, dtype=np.float32),
        np.array(z_values, dtype=np.float32),
    )
    return _store_ground_xyz_cache(path, cache_key, result)


def _numpy_xyz_dtype(header: dict[str, list[str]]) -> Any | None:
    if not _NUMPY_AVAILABLE:
        return None

    fields = header["FIELDS"]
    sizes = [int(value) for value in header.get("SIZE", [])]
    types = [value.upper() for value in header.get("TYPE", [])]
    counts = [int(value) for value in header.get("COUNT", ["1"] * len(fields))]
    if not (len(fields) == len(sizes) == len(types) == len(counts)):
        raise PcdMapError("PCD header 中 FIELDS/SIZE/TYPE/COUNT 数量不一致")
    if any(count != 1 for count in counts):
        return None

    type_map: dict[str, dict[int, Any]] = {
        "F": {4: np.float32, 8: np.float64},
        "I": {1: np.int8, 2: np.int16, 4: np.int32, 8: np.int64},
        "U": {1: np.uint8, 2: np.uint16, 4: np.uint32, 8: np.uint64},
    }
    try:
        return np.dtype([(field, type_map[data_type][size]) for field, size, data_type in zip(fields, sizes, types)])
    except KeyError:
        return None


def _collect_nearest_binary_xyz_numpy(
    path: Path,
    header: dict[str, list[str]],
    data_start_offset: int,
    target_x: float,
    target_y: float,
    limit: int,
    dtype: Any,
    max_distance_m: float,
) -> list[tuple[float, float, float, float]]:
    x_all, y_all, z_all, grid_index, cell_size_m = _load_binary_xyz_numpy_cached(path, header, data_start_offset, dtype)
    return _nearest_from_ground_grid(
        x_all,
        y_all,
        z_all,
        grid_index,
        cell_size_m,
        target_x,
        target_y,
        limit,
        max_distance_m,
    )


def _load_binary_xyz_numpy_cached(
    path: Path,
    header: dict[str, list[str]],
    data_start_offset: int,
    dtype: Any,
) -> tuple[Any, Any, Any, dict[tuple[int, int], Any], float]:
    cache_key = _ground_cache_key(path)
    cached = _ground_xyz_cache.get(cache_key)
    if cached is not None:
        pcd_logger.debug("ground 吸附缓存命中：{}", path.name)
        return cached

    normalized = normalize_pcd_header(header)
    point_count = max(0, normalized["point_count"])
    batch_points = 500_000
    x_parts: list[Any] = []
    y_parts: list[Any] = []
    z_parts: list[Any] = []

    with path.open("rb") as f:
        f.seek(data_start_offset)
        remaining = point_count
        while remaining > 0:
            count = min(batch_points, remaining)
            raw = f.read(count * dtype.itemsize)
            if len(raw) < dtype.itemsize:
                break

            arr = np.frombuffer(raw, dtype=dtype)
            x_values = arr["x"].astype(np.float64)
            y_values = arr["y"].astype(np.float64)
            z_values = arr["z"].astype(np.float64)
            valid = (
                np.isfinite(x_values)
                & np.isfinite(y_values)
                & np.isfinite(z_values)
                & (np.abs(x_values) < 1e6)
                & (np.abs(y_values) < 1e6)
                & (np.abs(z_values) < 1e6)
            )
            if np.any(valid):
                x_parts.append(x_values[valid].astype(np.float32))
                y_parts.append(y_values[valid].astype(np.float32))
                z_parts.append(z_values[valid].astype(np.float32))

            remaining -= len(arr)

    if not x_parts:
        result = (np.array([], dtype=np.float32), np.array([], dtype=np.float32), np.array([], dtype=np.float32))
    else:
        result = (
            np.concatenate(x_parts),
            np.concatenate(y_parts),
            np.concatenate(z_parts),
        )

    return _store_ground_xyz_cache(path, cache_key, result)


def _collect_nearest_binary_xyz_python(
    path: Path,
    header: dict[str, list[str]],
    data_start_offset: int,
    target_x: float,
    target_y: float,
    limit: int,
    max_distance_m: float,
) -> list[tuple[float, float, float, float]]:
    if _NUMPY_AVAILABLE:
        x_all, y_all, z_all, grid_index, cell_size_m = _load_binary_xyz_python_cached(path, header, data_start_offset)
        return _nearest_from_ground_grid(
            x_all,
            y_all,
            z_all,
            grid_index,
            cell_size_m,
            target_x,
            target_y,
            limit,
            max_distance_m,
        )

    normalized = normalize_pcd_header(header)
    point_count = max(0, normalized["point_count"])
    point_struct, value_offsets = _binary_layout(header)
    try:
        x_idx = value_offsets["x"]
        y_idx = value_offsets["y"]
        z_idx = value_offsets["z"]
    except KeyError as exc:
        raise PcdMapError(f"PCD 文件不包含字段: {exc.args[0]}") from exc

    heap: list[tuple[float, float, float, float, float]] = []
    with path.open("rb") as f:
        f.seek(data_start_offset)
        for _ in range(point_count):
            raw = f.read(point_struct.size)
            if len(raw) < point_struct.size:
                break
            values = point_struct.unpack(raw)
            x = float(values[x_idx])
            y = float(values[y_idx])
            z = float(values[z_idx])
            dist_sq = (x - target_x) ** 2 + (y - target_y) ** 2
            _push_nearest_candidate(heap, limit, dist_sq, x, y, z)

    return _nearest_from_heap(heap)


def _load_binary_xyz_python_cached(
    path: Path,
    header: dict[str, list[str]],
    data_start_offset: int,
) -> tuple[Any, Any, Any, dict[tuple[int, int], Any], float]:
    cache_key = _ground_cache_key(path)
    cached = _ground_xyz_cache.get(cache_key)
    if cached is not None:
        pcd_logger.debug("ground 吸附缓存命中：{}", path.name)
        return cached

    normalized = normalize_pcd_header(header)
    point_count = max(0, normalized["point_count"])
    point_struct, value_offsets = _binary_layout(header)
    try:
        x_idx = value_offsets["x"]
        y_idx = value_offsets["y"]
        z_idx = value_offsets["z"]
    except KeyError as exc:
        raise PcdMapError(f"PCD 文件不包含字段: {exc.args[0]}") from exc

    x_values: list[float] = []
    y_values: list[float] = []
    z_values: list[float] = []
    with path.open("rb") as f:
        f.seek(data_start_offset)
        for _ in range(point_count):
            raw = f.read(point_struct.size)
            if len(raw) < point_struct.size:
                break
            values = point_struct.unpack(raw)
            x = float(values[x_idx])
            y = float(values[y_idx])
            z = float(values[z_idx])
            if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
                continue
            if abs(x) >= 1e6 or abs(y) >= 1e6 or abs(z) >= 1e6:
                continue
            x_values.append(x)
            y_values.append(y)
            z_values.append(z)

    result = (
        np.array(x_values, dtype=np.float32),
        np.array(y_values, dtype=np.float32),
        np.array(z_values, dtype=np.float32),
    )
    return _store_ground_xyz_cache(path, cache_key, result)


def _collect_nearest_ground_points(
    path: Path,
    header: dict[str, list[str]],
    data_start_offset: int,
    target_x: float,
    target_y: float,
    limit: int,
    max_distance_m: float,
) -> list[tuple[float, float, float, float]]:
    data_type = normalize_pcd_header(header)["data_type"]
    if data_type == "ascii":
        return _collect_nearest_ascii_xyz(path, header, data_start_offset, target_x, target_y, limit, max_distance_m)
    if data_type == "binary":
        dtype = _numpy_xyz_dtype(header)
        if dtype is not None:
            return _collect_nearest_binary_xyz_numpy(
                path,
                header,
                data_start_offset,
                target_x,
                target_y,
                limit,
                dtype,
                max_distance_m,
            )
        return _collect_nearest_binary_xyz_python(
            path,
            header,
            data_start_offset,
            target_x,
            target_y,
            limit,
            max_distance_m,
        )
    raise PcdMapError(f"当前 Demo 暂不支持 DATA {data_type} PCD")


def _estimate_ground_z(
    target_x: float,
    target_y: float,
    candidates: list[tuple[float, float, float, float]],
    max_distance_m: float,
) -> tuple[float, str]:
    if not candidates:
        raise PcdMapError("ground.pcd 没有可用于吸附的点")

    nearest_dist_sq, _, _, nearest_z = candidates[0]
    if nearest_dist_sq <= 1e-8:
        return nearest_z, "nearest"

    fit_points = [item for item in candidates if math.sqrt(item[0]) <= max_distance_m]
    if _NUMPY_AVAILABLE and len(fit_points) >= 3:
        xs = np.array([item[1] for item in fit_points], dtype=np.float64)
        ys = np.array([item[2] for item in fit_points], dtype=np.float64)
        zs = np.array([item[3] for item in fit_points], dtype=np.float64)
        matrix = np.column_stack([xs, ys, np.ones_like(xs)])
        coeffs, _, rank, _ = np.linalg.lstsq(matrix, zs, rcond=None)
        z = float(coeffs[0] * target_x + coeffs[1] * target_y + coeffs[2])
        if rank >= 3 and math.isfinite(z) and zs.min() - 0.5 <= z <= zs.max() + 0.5:
            return z, "plane"

    weighted_points = fit_points or candidates
    total_weight = 0.0
    weighted_z = 0.0
    for dist_sq, _, _, z in weighted_points:
        weight = 1.0 / max(dist_sq, 1e-6)
        total_weight += weight
        weighted_z += z * weight
    return weighted_z / total_weight, "weighted"


def snap_xy_to_ground(
    scene_id: str,
    x: float,
    y: float,
    *,
    fallback_z: float | None = None,
    max_distance_m: float | None = None,
    neighbor_count: int | None = None,
) -> dict[str, Any]:
    """Return map x/y using the 3D ground preview z when provided."""

    target_x = float(x)
    target_y = float(y)
    max_distance = float(settings.NAV_WAYPOINT_GROUND_SNAP_MAX_DISTANCE_M if max_distance_m is None else max_distance_m)
    if max_distance <= 0:
        raise PcdMapError("ground 吸附距离必须大于 0")

    limit = int(settings.NAV_WAYPOINT_GROUND_SNAP_NEIGHBORS if neighbor_count is None else neighbor_count)
    limit = max(3, min(limit, 128))

    ground_path = resolve_scene_ground_path(scene_id)
    if fallback_z is not None and math.isfinite(fallback_z):
        pcd_logger.debug(
            "使用 3D 预览 ground 落点 z，跳过后端 ground.pcd 吸附：{}",
            ground_path.name,
        )
        return {
            "x": target_x,
            "y": target_y,
            "z": float(fallback_z),
            "nearest_distance_m": 0.0,
            "source_file": ground_path.name,
            "method": "preview-z",
        }

    header, data_start_offset = parse_pcd_header(ground_path)
    candidates = _collect_nearest_ground_points(
        ground_path,
        header,
        data_start_offset,
        target_x,
        target_y,
        limit,
        max_distance,
    )
    if not candidates:
        raise PcdMapError("ground.pcd 没有可用于吸附的点")

    nearest_distance = math.sqrt(candidates[0][0])
    if nearest_distance > max_distance:
        raise PcdMapError(
            f"点位不在 ground.pcd 附近：最近地面点距离 {nearest_distance:.3f}m，"
            f"超过允许 {max_distance:.3f}m"
        )

    snapped_z, method = _estimate_ground_z(target_x, target_y, candidates, max_distance)
    return {
        "x": target_x,
        "y": target_y,
        "z": float(snapped_z),
        "nearest_distance_m": nearest_distance,
        "source_file": ground_path.name,
        "method": method,
    }


def read_binary_preview(
    path: Path,
    header: dict[str, list[str]],
    data_start_offset: int,
    max_points: int,
) -> tuple[list[list[float]], dict[str, float]]:
    if _NUMPY_AVAILABLE:
        return _read_binary_preview_numpy(path, header, data_start_offset, max_points)
    return _read_binary_preview_python(path, header, data_start_offset, max_points)


def _read_binary_preview_numpy(
    path: Path,
    header: dict[str, list[str]],
    data_start_offset: int,
    max_points: int,
) -> tuple[list[list[float]], dict[str, float]]:
    fields = header["FIELDS"]
    sizes = [int(s) for s in header.get("SIZE", [])]
    types = [t.upper() for t in header.get("TYPE", [])]
    counts = [int(value) for value in header.get("COUNT", ["1"] * len(fields))]

    if not (len(fields) == len(sizes) == len(types) == len(counts)):
        raise PcdMapError("PCD header 中 FIELDS/SIZE/TYPE/COUNT 数量不一致")

    # NumPy 快速路径当前只支持 COUNT=1 的标量字段。若存在直方图/法向量等
    # 多值字段，退回到 Python 解析以避免 itemsize 错位导致 x/y/z 读错。
    if any(count != 1 for count in counts):
        return _read_binary_preview_python(path, header, data_start_offset, max_points)

    _type_map: dict[str, dict[int, Any]] = {
        "F": {4: np.float32, 8: np.float64},
        "I": {1: np.int8,   2: np.int16,  4: np.int32,  8: np.int64},
        "U": {1: np.uint8,  2: np.uint16, 4: np.uint32, 8: np.uint64},
    }
    try:
        np_dtype = np.dtype([
            (f, _type_map[t][s])
            for f, s, t in zip(fields, sizes, types)
        ])
    except KeyError:
        return _read_binary_preview_python(path, header, data_start_offset, max_points)

    if "x" not in fields or "y" not in fields or "z" not in fields:
        raise PcdMapError("PCD 文件缺少 x/y/z 字段")

    normalized = normalize_pcd_header(header)
    point_count = max(1, normalized["point_count"])
    step = max(1, math.ceil(point_count / max_points))

    batch_points = 500_000
    x_parts: list[np.ndarray] = []
    y_parts: list[np.ndarray] = []
    z_parts: list[np.ndarray] = []
    global_idx = 0  # 跨 batch 的绝对点索引

    with path.open("rb") as f:
        f.seek(data_start_offset)
        remaining = point_count

        while remaining > 0:
            n = min(batch_points, remaining)
            raw = f.read(n * np_dtype.itemsize)
            if len(raw) < np_dtype.itemsize:
                break

            arr = np.frombuffer(raw, dtype=np_dtype)
            m = len(arr)

            first = (step - (global_idx % step)) % step
            idx = np.arange(first, m, step)
            global_idx += m

            if len(idx) > 0:
                x = arr["x"][idx].astype(np.float64)
                y = arr["y"][idx].astype(np.float64)
                z = arr["z"][idx].astype(np.float64)
                valid = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
                x_parts.append(x[valid])
                y_parts.append(y[valid])
                z_parts.append(z[valid])

            remaining -= m

    if not x_parts:
        return [], _finalize_bounds(_empty_bounds())

    all_x = np.concatenate(x_parts)
    all_y = np.concatenate(y_parts)
    all_z = np.concatenate(z_parts)

    # 过滤建图工具产生的脏数据（天文坐标）
    sane = (np.abs(all_x) < 1e6) & (np.abs(all_y) < 1e6) & (np.abs(all_z) < 1e6)
    all_x, all_y, all_z = all_x[sane], all_y[sane], all_z[sane]

    if len(all_x) == 0:
        return [], _finalize_bounds(_empty_bounds())

    points: list[list[float]] = np.column_stack([all_x, all_y, all_z]).tolist()
    bounds = {
        "min_x": float(all_x.min()), "max_x": float(all_x.max()),
        "min_y": float(all_y.min()), "max_y": float(all_y.max()),
        "min_z": float(all_z.min()), "max_z": float(all_z.max()),
    }
    return points, bounds


def _read_binary_preview_python(
    path: Path,
    header: dict[str, list[str]],
    data_start_offset: int,
    max_points: int,
) -> tuple[list[list[float]], dict[str, float]]:
    normalized = normalize_pcd_header(header)
    point_count = max(1, normalized["point_count"])
    point_struct, value_offsets = _binary_layout(header)

    try:
        x_idx = value_offsets["x"]
        y_idx = value_offsets["y"]
        z_idx = value_offsets["z"]
    except KeyError as exc:
        raise PcdMapError(f"PCD 文件不包含字段: {exc.args[0]}") from exc

    step = max(1, math.ceil(point_count / max_points))
    bounds = _empty_bounds()
    points: list[list[float]] = []

    with path.open("rb") as f:
        f.seek(data_start_offset)

        for point_index in range(point_count):
            raw = f.read(point_struct.size)
            if len(raw) < point_struct.size:
                break

            values = point_struct.unpack(raw)
            x = float(values[x_idx])
            y = float(values[y_idx])
            z = float(values[z_idx])

            if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
                continue

            _update_bounds(bounds, x, y, z)

            if point_index % step == 0 and len(points) < max_points:
                points.append([x, y, z])

    return points, _finalize_bounds(bounds)


def _read_preview_by_type(
    path: Path,
    header: dict[str, list[str]],
    data_start_offset: int,
    max_points: int,
) -> tuple[list[list[float]], dict[str, float]]:
    # 缓存命中：以文件 mtime 为失效依据，文件更新后自动重读
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    cache_key = (str(path), mtime, max_points)
    cached = _preview_cache.get(cache_key)
    if cached is not None:
        pcd_logger.debug("点云预览缓存命中：{}", path.name)
        return cached

    data_type = normalize_pcd_header(header)["data_type"]

    if data_type == "ascii":
        result = read_ascii_preview(
            path=path,
            header=header,
            data_start_offset=data_start_offset,
            max_points=max_points,
        )
    elif data_type == "binary":
        result = read_binary_preview(
            path=path,
            header=header,
            data_start_offset=data_start_offset,
            max_points=max_points,
        )
    else:
        raise PcdMapError(f"当前 Demo 暂不支持 DATA {data_type} PCD")

    # 写入缓存，同时清除同一文件的旧 mtime 条目
    stale = [k for k in _preview_cache if k[0] == str(path) and k != cache_key]
    for k in stale:
        del _preview_cache[k]
    _preview_cache[cache_key] = result
    pcd_logger.debug("点云预览已缓存：{}，采样点数={}", path.name, len(result[0]))
    return result


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

    _, bounds = _read_preview_by_type(
        path=path,
        header=header,
        data_start_offset=data_start_offset,
        max_points=settings.PCD_PREVIEW_MAX_POINTS,
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

    _, bounds = _read_preview_by_type(
        path=path,
        header=header,
        data_start_offset=data_start_offset,
        max_points=settings.PCD_PREVIEW_MAX_POINTS,
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

    points, bounds = _read_preview_by_type(
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
            points, bounds = _read_preview_by_type(
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
