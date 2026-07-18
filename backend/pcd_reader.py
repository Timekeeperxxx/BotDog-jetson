from __future__ import annotations

import math
import struct
from pathlib import Path
from collections.abc import Iterator
from typing import Any

try:
    import numpy as np
    _NUMPY_AVAILABLE = True
except ImportError:
    _NUMPY_AVAILABLE = False

from .logging_config import get_logger
from .pcd_errors import PcdMapError


pcd_logger = get_logger("场景点云服务")

# 内存缓存：key=(path_str, mtime, max_points) -> (points, bounds)
# 后端进程存活期间有效；文件修改后 mtime 变化自动失效
_preview_cache: dict[tuple, tuple] = {}


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


def empty_bounds() -> dict[str, float]:
    return {
        "min_x": float("inf"),
        "max_x": float("-inf"),
        "min_y": float("inf"),
        "max_y": float("-inf"),
        "min_z": float("inf"),
        "max_z": float("-inf"),
    }


def update_bounds(bounds: dict[str, float], x: float, y: float, z: float) -> None:
    bounds["min_x"] = min(bounds["min_x"], x)
    bounds["max_x"] = max(bounds["max_x"], x)
    bounds["min_y"] = min(bounds["min_y"], y)
    bounds["max_y"] = max(bounds["max_y"], y)
    bounds["min_z"] = min(bounds["min_z"], z)
    bounds["max_z"] = max(bounds["max_z"], z)


def finalize_bounds(bounds: dict[str, float]) -> dict[str, float]:
    if bounds["min_x"] == float("inf"):
        raise PcdMapError("PCD 文件没有可解析点")
    return bounds


def merge_bounds(bounds_list: list[dict[str, float] | None]) -> dict[str, float]:
    merged = empty_bounds()
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

    bounds = empty_bounds()
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

            update_bounds(bounds, x, y, z)

            if parsed_index % step == 0 and len(points) < max_points:
                points.append([x, y, z])

            parsed_index += 1

    return points, finalize_bounds(bounds)


def binary_struct_format(size: int, data_type: str) -> str:
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


def binary_layout(header: dict[str, list[str]]) -> tuple[struct.Struct, dict[str, int]]:
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

        field_format = binary_struct_format(size, data_type)
        value_offsets[field] = value_index
        format_parts.append(field_format * count)
        value_index += count

    return struct.Struct("".join(format_parts)), value_offsets


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

    type_map: dict[str, dict[int, Any]] = {
        "F": {4: np.float32, 8: np.float64},
        "I": {1: np.int8, 2: np.int16, 4: np.int32, 8: np.int64},
        "U": {1: np.uint8, 2: np.uint16, 4: np.uint32, 8: np.uint64},
    }
    try:
        np_dtype = np.dtype([(f, type_map[t][s]) for f, s, t in zip(fields, sizes, types)])
    except KeyError:
        return _read_binary_preview_python(path, header, data_start_offset, max_points)

    if "x" not in fields or "y" not in fields or "z" not in fields:
        raise PcdMapError("PCD 文件缺少 x/y/z 字段")

    normalized = normalize_pcd_header(header)
    point_count = max(0, normalized["point_count"])
    step = max(1, math.ceil(point_count / max_points))

    # 预览只需要等间隔样本。memmap 直接访问这些记录，避免为了少量预览点
    # 把数 GB 的二进制 PCD 从头到尾读入 page cache。
    available_bytes = max(0, path.stat().st_size - data_start_offset)
    available_points = available_bytes // np_dtype.itemsize
    readable_points = min(point_count, available_points)
    if readable_points <= 0:
        return [], finalize_bounds(empty_bounds())

    arr = np.memmap(
        path,
        dtype=np_dtype,
        mode="r",
        offset=data_start_offset,
        shape=(readable_points,),
    )
    target_count = min(max_points, math.ceil(readable_points / step))
    # 单点等距跳读会让超大文件产生近十万次稀疏页访问。把相同数量的样本
    # 合并为少量、均匀分布的连续块，既覆盖整个文件，也显著减少 page fault。
    block_count = min(2_048, target_count)
    base_block_size, extra_points = divmod(target_count, block_count)
    skipped_points = readable_points - target_count
    base_gap_size, extra_gaps = divmod(skipped_points, block_count)
    chunks: list[Any] = []
    cursor = 0
    for block_index in range(block_count):
        cursor += base_gap_size + (1 if block_index < extra_gaps else 0)
        block_size = base_block_size + (1 if block_index < extra_points else 0)
        chunks.append(arr[cursor:cursor + block_size])
        cursor += block_size
    sampled = np.concatenate(chunks)
    all_x = np.asarray(sampled["x"], dtype=np.float64)
    all_y = np.asarray(sampled["y"], dtype=np.float64)
    all_z = np.asarray(sampled["z"], dtype=np.float64)

    # 过滤建图工具产生的脏数据（天文坐标）
    sane = (np.abs(all_x) < 1e6) & (np.abs(all_y) < 1e6) & (np.abs(all_z) < 1e6)
    all_x, all_y, all_z = all_x[sane], all_y[sane], all_z[sane]

    if len(all_x) == 0:
        return [], finalize_bounds(empty_bounds())

    points: list[list[float]] = np.column_stack([all_x, all_y, all_z]).tolist()
    bounds = {
        "min_x": float(all_x.min()),
        "max_x": float(all_x.max()),
        "min_y": float(all_y.min()),
        "max_y": float(all_y.max()),
        "min_z": float(all_z.min()),
        "max_z": float(all_z.max()),
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
    point_struct, value_offsets = binary_layout(header)

    try:
        x_idx = value_offsets["x"]
        y_idx = value_offsets["y"]
        z_idx = value_offsets["z"]
    except KeyError as exc:
        raise PcdMapError(f"PCD 文件不包含字段: {exc.args[0]}") from exc

    step = max(1, math.ceil(point_count / max_points))
    bounds = empty_bounds()
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

            update_bounds(bounds, x, y, z)

            if point_index % step == 0 and len(points) < max_points:
                points.append([x, y, z])

    return points, finalize_bounds(bounds)


def read_pcd_preview(
    path: Path,
    header: dict[str, list[str]],
    data_start_offset: int,
    max_points: int,
) -> tuple[list[list[float]], dict[str, float]]:
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

    stale = [k for k in _preview_cache if k[0] == str(path) and k != cache_key]
    for k in stale:
        del _preview_cache[k]
    _preview_cache[cache_key] = result
    pcd_logger.debug("点云预览已缓存：{}，采样点数={}", path.name, len(result[0]))
    return result


def read_pcd_xyz_float32(
    path: Path,
    header: dict[str, list[str]],
    data_start_offset: int,
    max_points: int | None = None,
    voxel_size_m: float | None = None,
    max_points_per_voxel: int = 1,
) -> tuple[Any, dict[str, float]]:
    points, _intensity, bounds = read_pcd_xyz_intensity_uint8(
        path=path,
        header=header,
        data_start_offset=data_start_offset,
        max_points=max_points,
        voxel_size_m=voxel_size_m,
        max_points_per_voxel=max_points_per_voxel,
    )
    return points, bounds


def iter_pcd_xyz_intensity_float32(
    path: Path,
    header: dict[str, list[str]],
    data_start_offset: int,
    chunk_points: int = 400_000,
) -> Iterator[tuple[Any, Any | None]]:
    """Yield finite XYZ and optional raw intensity without loading a PCD whole.

    Navigation scenes may contain multi-gigabyte PCD files.  The tile builder
    therefore scans binary files through a memmap and ASCII files line by line.
    Returned arrays are independent contiguous float32 chunks and are safe to
    process after the iterator advances.
    """
    if not _NUMPY_AVAILABLE:
        raise PcdMapError("分层点云构建需要 NumPy")

    normalized = normalize_pcd_header(header)
    chunk_size = max(1, int(chunk_points))
    data_type = normalized["data_type"]
    fields = header["FIELDS"]
    field_lookup = {name: index for index, name in enumerate(fields)}
    intensity_index = field_lookup.get("intensity")

    def sanitize(
        x_values: Any,
        y_values: Any,
        z_values: Any,
        intensity_values: Any | None,
    ) -> tuple[Any, Any | None] | None:
        x = np.asarray(x_values, dtype=np.float32).reshape((-1,))
        y = np.asarray(y_values, dtype=np.float32).reshape((-1,))
        z = np.asarray(z_values, dtype=np.float32).reshape((-1,))
        valid = (
            np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
            & (np.abs(x) < 1e6) & (np.abs(y) < 1e6) & (np.abs(z) < 1e6)
        )
        if not np.any(valid):
            return None
        points = np.empty((int(np.count_nonzero(valid)), 3), dtype="<f4")
        points[:, 0] = x[valid]
        points[:, 1] = y[valid]
        points[:, 2] = z[valid]
        intensity = None
        if intensity_values is not None:
            raw_intensity = np.asarray(intensity_values, dtype=np.float32).reshape((-1,))
            intensity = np.ascontiguousarray(raw_intensity[valid], dtype="<f4")
        return points, intensity

    if data_type == "ascii":
        x_index = field_lookup["x"]
        y_index = field_lookup["y"]
        z_index = field_lookup["z"]
        buffered: list[list[float]] = []
        with path.open("rb") as source:
            source.seek(data_start_offset)
            for raw_line in source:
                values = raw_line.decode("utf-8", errors="ignore").strip().split()
                if len(values) < len(fields):
                    continue
                try:
                    row = [
                        float(values[x_index]),
                        float(values[y_index]),
                        float(values[z_index]),
                    ]
                    if intensity_index is not None:
                        row.append(float(values[intensity_index]))
                except (ValueError, IndexError):
                    continue
                buffered.append(row)
                if len(buffered) < chunk_size:
                    continue
                packed = np.asarray(buffered, dtype=np.float32)
                result = sanitize(
                    packed[:, 0],
                    packed[:, 1],
                    packed[:, 2],
                    packed[:, 3] if intensity_index is not None else None,
                )
                buffered = []
                if result is not None:
                    yield result
        if buffered:
            packed = np.asarray(buffered, dtype=np.float32)
            result = sanitize(
                packed[:, 0],
                packed[:, 1],
                packed[:, 2],
                packed[:, 3] if intensity_index is not None else None,
            )
            if result is not None:
                yield result
        return

    if data_type != "binary":
        raise PcdMapError(f"当前分层点云不支持 DATA {data_type} PCD")

    sizes = [int(value) for value in header.get("SIZE", [])]
    types = [value.upper() for value in header.get("TYPE", [])]
    counts = [int(value) for value in header.get("COUNT", ["1"] * len(fields))]
    if not (len(fields) == len(sizes) == len(types) == len(counts)):
        raise PcdMapError("PCD header 中 FIELDS/SIZE/TYPE/COUNT 数量不一致")
    type_map: dict[str, dict[int, Any]] = {
        "F": {4: np.float32, 8: np.float64},
        "I": {1: np.int8, 2: np.int16, 4: np.int32, 8: np.int64},
        "U": {1: np.uint8, 2: np.uint16, 4: np.uint32, 8: np.uint64},
    }
    dtype_fields: list[tuple[Any, ...]] = []
    try:
        for field, size, scalar_type, count in zip(fields, sizes, types, counts):
            value_type = type_map[scalar_type][size]
            dtype_fields.append((field, value_type) if count == 1 else (field, value_type, (count,)))
        record_dtype = np.dtype(dtype_fields)
    except KeyError as exc:
        raise PcdMapError("PCD binary 字段类型不受支持") from exc

    point_count = max(0, int(normalized["point_count"]))
    available_bytes = max(0, path.stat().st_size - data_start_offset)
    readable_points = min(point_count, available_bytes // record_dtype.itemsize)
    if readable_points <= 0:
        raise PcdMapError("PCD 文件没有可解析点")
    records = np.memmap(
        path,
        dtype=record_dtype,
        mode="r",
        offset=data_start_offset,
        shape=(readable_points,),
    )
    try:
        for start in range(0, readable_points, chunk_size):
            selected = records[start:min(readable_points, start + chunk_size)]
            result = sanitize(
                selected["x"],
                selected["y"],
                selected["z"],
                selected["intensity"] if "intensity" in fields else None,
            )
            if result is not None:
                yield result
    finally:
        del records


def read_pcd_xyz_intensity_uint8(
    path: Path,
    header: dict[str, list[str]],
    data_start_offset: int,
    max_points: int | None = None,
    voxel_size_m: float | None = None,
    max_points_per_voxel: int = 1,
) -> tuple[Any, Any | None, dict[str, float]]:
    """Read XYZ and, when available, percentile-normalized uint8 intensity.

    ``max_points=None`` means all valid points. This path is intended for the
    binary HTTP response so full PCD files do not expand into millions of
    Python lists before being encoded again.
    """
    if not _NUMPY_AVAILABLE:
        normalized = normalize_pcd_header(header)
        point_limit = max(1, normalized["point_count"]) if max_points is None else max(1, max_points)
        points, bounds = read_pcd_preview(
            path=path,
            header=header,
            data_start_offset=data_start_offset,
            max_points=point_limit,
        )
        return points, None, bounds

    normalized = normalize_pcd_header(header)
    data_type = normalized["data_type"]
    point_limit = None if max_points is None else max(1, max_points)

    if data_type != "binary":
        effective_limit = max(1, normalized["point_count"]) if point_limit is None else point_limit
        points, bounds = read_pcd_preview(
            path=path,
            header=header,
            data_start_offset=data_start_offset,
            max_points=effective_limit,
        )
        packed = np.asarray(points, dtype="<f4").reshape((-1, 3))
        return spatial_downsample_xyz(packed, voxel_size_m, max_points_per_voxel), None, bounds

    fields = header["FIELDS"]
    sizes = [int(value) for value in header.get("SIZE", [])]
    types = [value.upper() for value in header.get("TYPE", [])]
    counts = [int(value) for value in header.get("COUNT", ["1"] * len(fields))]
    if not (len(fields) == len(sizes) == len(types) == len(counts)):
        raise PcdMapError("PCD header 中 FIELDS/SIZE/TYPE/COUNT 数量不一致")

    # Multi-value fields need the general struct parser to preserve record
    # alignment. This is uncommon for navigation maps but remains supported.
    if any(count != 1 for count in counts):
        effective_limit = max(1, normalized["point_count"]) if point_limit is None else point_limit
        points, bounds = _read_binary_preview_python(
            path,
            header,
            data_start_offset,
            effective_limit,
        )
        packed = np.asarray(points, dtype="<f4").reshape((-1, 3))
        return spatial_downsample_xyz(packed, voxel_size_m, max_points_per_voxel), None, bounds

    type_map: dict[str, dict[int, Any]] = {
        "F": {4: np.float32, 8: np.float64},
        "I": {1: np.int8, 2: np.int16, 4: np.int32, 8: np.int64},
        "U": {1: np.uint8, 2: np.uint16, 4: np.uint32, 8: np.uint64},
    }
    try:
        np_dtype = np.dtype([(field, type_map[data_type][size]) for field, size, data_type in zip(fields, sizes, types)])
    except KeyError as exc:
        raise PcdMapError("PCD binary 字段类型不受支持") from exc

    point_count = max(0, normalized["point_count"])
    available_bytes = max(0, path.stat().st_size - data_start_offset)
    readable_points = min(point_count, available_bytes // np_dtype.itemsize)
    if readable_points <= 0:
        raise PcdMapError("PCD 文件没有可解析点")

    records = np.memmap(
        path,
        dtype=np_dtype,
        mode="r",
        offset=data_start_offset,
        shape=(readable_points,),
    )
    if point_limit is None or point_limit >= readable_points:
        selected = records
    else:
        step = max(1, math.ceil(point_count / point_limit))
        target_count = min(point_limit, math.ceil(readable_points / step))
        block_count = min(2_048, target_count)
        base_block_size, extra_points = divmod(target_count, block_count)
        skipped_points = readable_points - target_count
        base_gap_size, extra_gaps = divmod(skipped_points, block_count)
        chunks: list[Any] = []
        cursor = 0
        for block_index in range(block_count):
            cursor += base_gap_size + (1 if block_index < extra_gaps else 0)
            block_size = base_block_size + (1 if block_index < extra_points else 0)
            chunks.append(records[cursor:cursor + block_size])
            cursor += block_size
        selected = np.concatenate(chunks)

    all_x = np.asarray(selected["x"], dtype=np.float32)
    all_y = np.asarray(selected["y"], dtype=np.float32)
    all_z = np.asarray(selected["z"], dtype=np.float32)
    all_intensity = (
        np.asarray(selected["intensity"], dtype=np.float32)
        if "intensity" in fields
        else None
    )
    sane = (
        np.isfinite(all_x) & np.isfinite(all_y) & np.isfinite(all_z)
        & (np.abs(all_x) < 1e6) & (np.abs(all_y) < 1e6) & (np.abs(all_z) < 1e6)
    )
    all_x, all_y, all_z = all_x[sane], all_y[sane], all_z[sane]
    if all_intensity is not None:
        all_intensity = all_intensity[sane]
    if len(all_x) == 0:
        raise PcdMapError("PCD 文件没有可解析点")

    points = np.empty((len(all_x), 3), dtype="<f4")
    points[:, 0] = all_x
    points[:, 1] = all_y
    points[:, 2] = all_z
    bounds = {
        "min_x": float(all_x.min()),
        "max_x": float(all_x.max()),
        "min_y": float(all_y.min()),
        "max_y": float(all_y.max()),
        "min_z": float(all_z.min()),
        "max_z": float(all_z.max()),
    }
    selected_indices = spatial_downsample_indices(points, voxel_size_m, max_points_per_voxel)
    if selected_indices is not None:
        points = np.ascontiguousarray(points[selected_indices], dtype="<f4")
        if all_intensity is not None:
            all_intensity = all_intensity[selected_indices]

    intensity_uint8 = quantize_intensity_uint8(all_intensity)
    return points, intensity_uint8, bounds


def quantize_intensity_uint8(values: Any | None) -> Any | None:
    """Normalize robust intensity percentiles into one byte per point."""
    if not _NUMPY_AVAILABLE or values is None:
        return None

    intensity = np.asarray(values, dtype=np.float32).reshape((-1,))
    if len(intensity) < 2:
        return None

    sample_stride = max(1, math.ceil(len(intensity) / 65_536))
    sample = intensity[::sample_stride]
    sample = sample[np.isfinite(sample)]
    if len(sample) < 2:
        return None

    low, high = np.percentile(sample, [2.0, 98.0])
    if not (np.isfinite(low) and np.isfinite(high)) or float(high - low) <= 1e-6:
        return None

    normalized = np.empty_like(intensity, dtype=np.float32)
    np.subtract(intensity, np.float32(low), out=normalized)
    np.multiply(normalized, np.float32(255.0 / float(high - low)), out=normalized)
    np.clip(normalized, 0.0, 255.0, out=normalized)
    np.nan_to_num(normalized, copy=False, nan=0.0, posinf=255.0, neginf=0.0)
    return np.ascontiguousarray(normalized.astype(np.uint8))


def spatial_downsample_indices(
    points: Any,
    voxel_size_m: float | None,
    max_points_per_voxel: int = 1,
) -> Any | None:
    """Return retained source indices, or ``None`` when sampling is disabled."""
    if not _NUMPY_AVAILABLE or voxel_size_m is None or voxel_size_m <= 0:
        return None

    packed = np.asarray(points, dtype="<f4").reshape((-1, 3))
    point_count = len(packed)
    per_voxel = max(1, int(max_points_per_voxel))
    if point_count <= per_voxel:
        return None

    voxel_keys = np.floor(packed / float(voxel_size_m)).astype(np.int32)
    key_min = voxel_keys.min(axis=0)
    shifted = (voxel_keys - key_min).astype(np.int64)
    dimensions = shifted.max(axis=0) + 1
    grid_cell_count = int(dimensions[0]) * int(dimensions[1]) * int(dimensions[2])

    if grid_cell_count <= np.iinfo(np.int64).max:
        linear_keys = (
            (shifted[:, 0] * dimensions[1] + shifted[:, 1]) * dimensions[2]
            + shifted[:, 2]
        )
        order = np.argsort(linear_keys, kind="stable")
        ordered_keys = linear_keys[order]
        group_start_mask = np.empty(point_count, dtype=bool)
        group_start_mask[0] = True
        group_start_mask[1:] = ordered_keys[1:] != ordered_keys[:-1]
    else:
        order = np.lexsort((voxel_keys[:, 2], voxel_keys[:, 1], voxel_keys[:, 0]))
        ordered_keys = voxel_keys[order]
        group_start_mask = np.empty(point_count, dtype=bool)
        group_start_mask[0] = True
        group_start_mask[1:] = np.any(ordered_keys[1:] != ordered_keys[:-1], axis=1)

    ordered_positions = np.arange(point_count, dtype=np.int64)
    group_starts = np.maximum.accumulate(
        np.where(group_start_mask, ordered_positions, 0),
    )
    ranks_in_voxel = ordered_positions - group_starts
    return np.sort(order[ranks_in_voxel < per_voxel])


def spatial_downsample_xyz(
    points: Any,
    voxel_size_m: float | None,
    max_points_per_voxel: int = 1,
) -> Any:
    """Limit local density while preserving the cloud's global coverage.

    Space is divided into fixed-size 3D voxels. Up to
    ``max_points_per_voxel`` source points are retained in every occupied
    voxel. There is deliberately no whole-map point-count ceiling.
    """
    if not _NUMPY_AVAILABLE:
        return points

    packed = np.asarray(points, dtype="<f4").reshape((-1, 3))
    selected_indices = spatial_downsample_indices(
        packed,
        voxel_size_m,
        max_points_per_voxel,
    )
    if selected_indices is None:
        return packed
    return np.ascontiguousarray(packed[selected_indices], dtype="<f4")
