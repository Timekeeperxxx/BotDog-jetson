from __future__ import annotations

import math
import struct
from typing import Any

import numpy as np

MAPPING_CLOUD_ACCUMULATED_VOXEL_SIZE_M = 0.10
MAPPING_CLOUD_ACCUMULATED_MAX_BROADCAST_POINTS = 15000
MAPPING_CLOUD_ACCUMULATE_MAX_INPUT_POINTS = 1500
MAPPING_CLOUD_LIVE_MAX_BROADCAST_POINTS = 600

VoxelMap = dict[tuple[int, int, int], tuple[float, float, float]]


def limit_cloud_points(points: np.ndarray, max_points: int) -> np.ndarray:
    if max_points <= 0 or len(points) <= max_points:
        return points
    step = max(1, math.ceil(len(points) / max_points))
    return points[::step][:max_points]


def merge_mapping_cloud_voxels(
    voxels: VoxelMap,
    points: np.ndarray,
    voxel_size: float = MAPPING_CLOUD_ACCUMULATED_VOXEL_SIZE_M,
) -> None:
    if len(points) == 0:
        return

    keys = np.floor(points / voxel_size).astype(np.int32)
    for key, point in zip(keys, points, strict=False):
        voxels[(int(key[0]), int(key[1]), int(key[2]))] = (
            float(point[0]),
            float(point[1]),
            float(point[2]),
        )


def mapping_cloud_voxel_preview(
    voxels: VoxelMap,
    max_points: int = MAPPING_CLOUD_ACCUMULATED_MAX_BROADCAST_POINTS,
) -> np.ndarray:
    if not voxels:
        return np.empty((0, 3), dtype=np.float32)
    points = np.fromiter(
        (coord for point in voxels.values() for coord in point),
        dtype=np.float32,
    ).reshape((-1, 3))
    return limit_cloud_points(points, max_points)


def voxel_downsample(points: np.ndarray, voxel_size: float) -> np.ndarray:
    if len(points) == 0:
        return points
    keys = np.floor(points / voxel_size).astype(np.int32)
    _, unique_indices = np.unique(keys, axis=0, return_index=True)
    return points[np.sort(unique_indices)]


def extract_cloud_xyz_np(msg: Any, max_points: int | None = None) -> np.ndarray | None:
    try:
        point_step: int = msg.point_step
        n_points: int = msg.width * msg.height
        if n_points == 0 or point_step < 12:
            return None

        fields = {f.name: f.offset for f in msg.fields}
        if not all(k in fields for k in ("x", "y", "z")):
            return None

        x_off, y_off, z_off = fields["x"], fields["y"], fields["z"]
        raw = bytes(msg.data)
        step = 1 if max_points is None or max_points <= 0 else max(1, math.ceil(n_points / max_points))
        result: list[list[float]] = []
        for i in range(0, n_points, step):
            base = i * point_step
            x = struct.unpack_from("<f", raw, base + x_off)[0]
            y = struct.unpack_from("<f", raw, base + y_off)[0]
            z = struct.unpack_from("<f", raw, base + z_off)[0]
            if math.isnan(x) or math.isnan(y) or math.isnan(z):
                continue
            if math.isinf(x) or math.isinf(y) or math.isinf(z):
                continue
            result.append([x, y, z])
        return np.array(result, dtype=np.float32) if result else None
    except Exception:
        return None


def extract_cloud_xyz(msg: Any, max_points: int = 1500) -> list[list[float]]:
    try:
        point_step: int = msg.point_step
        n_points: int = msg.width * msg.height
        if n_points == 0 or point_step < 12:
            return []

        fields = {f.name: f.offset for f in msg.fields}
        if not all(k in fields for k in ("x", "y", "z")):
            return []

        x_off, y_off, z_off = fields["x"], fields["y"], fields["z"]
        raw = bytes(msg.data)
        step = max(1, n_points // max_points)
        result: list[list[float]] = []
        for i in range(0, n_points, step):
            base = i * point_step
            x = struct.unpack_from("<f", raw, base + x_off)[0]
            y = struct.unpack_from("<f", raw, base + y_off)[0]
            z = struct.unpack_from("<f", raw, base + z_off)[0]
            if math.isnan(x) or math.isnan(y) or math.isnan(z):
                continue
            if math.isinf(x) or math.isinf(y) or math.isinf(z):
                continue
            result.append([round(x, 3), round(y, 3), round(z, 3)])
        return result
    except Exception:
        return []
