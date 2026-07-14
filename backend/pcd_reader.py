from __future__ import annotations

import math
import struct
from pathlib import Path
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
