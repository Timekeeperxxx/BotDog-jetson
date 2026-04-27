from __future__ import annotations

import math
import struct
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import settings


class PcdMapError(Exception):
    pass


def _utc_from_timestamp(ts: float) -> str:
    return datetime.utcfromtimestamp(ts).isoformat(timespec="milliseconds") + "Z"


def get_pcd_root() -> Path:
    root = Path(settings.PCD_MAP_ROOT).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


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


def read_binary_preview(
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
    data_type = normalize_pcd_header(header)["data_type"]

    if data_type == "ascii":
        return read_ascii_preview(
            path=path,
            header=header,
            data_start_offset=data_start_offset,
            max_points=max_points,
        )

    if data_type == "binary":
        return read_binary_preview(
            path=path,
            header=header,
            data_start_offset=data_start_offset,
            max_points=max_points,
        )

    raise PcdMapError(f"当前 Demo 暂不支持 DATA {data_type} PCD")


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
