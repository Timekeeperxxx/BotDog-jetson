from __future__ import annotations

import heapq
import math
from pathlib import Path
from typing import Any

try:
    import numpy as np
    _NUMPY_AVAILABLE = True
except ImportError:
    _NUMPY_AVAILABLE = False

from .logging_config import get_logger
from .pcd_errors import PcdMapError
from .pcd_reader import binary_layout, normalize_pcd_header, parse_pcd_header


pcd_logger = get_logger("场景点云服务")

_GROUND_GRID_CELL_SIZE_M = 0.5
_ground_xyz_cache: dict[tuple[str, float], tuple[Any, Any, Any, dict[tuple[int, int], Any], float]] = {}


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
    point_struct, value_offsets = binary_layout(header)
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
    point_struct, value_offsets = binary_layout(header)
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


def snap_xy_to_ground_file(
    ground_path: Path,
    x: float,
    y: float,
    *,
    fallback_z: float | None = None,
    max_distance_m: float,
    neighbor_count: int,
) -> dict[str, Any]:
    """Return map x/y using the 3D ground preview z when provided."""

    target_x = float(x)
    target_y = float(y)
    max_distance = float(max_distance_m)
    if max_distance <= 0:
        raise PcdMapError("ground 吸附距离必须大于 0")

    limit = max(3, min(int(neighbor_count), 128))

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
