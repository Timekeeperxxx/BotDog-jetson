from __future__ import annotations

import math
from typing import Any

from .config import settings


def planner_goal_z(ground_z: float) -> float:
    """返回发布给 global_planner 的 clicked_point z。

    global_planner 会先在降采样后的 ground KD-tree 中做 3D 半径搜索。
    虽然源码里打印了向下搜索日志，但当前实现没有把向下搜索结果作为有效目标返回。
    因此默认必须发布真实 ground z，避免把原本可规划的点排除在 0.5m 搜索半径外。
    这个函数只保留一个可配置偏移入口，便于后续拿到 planner 内部 ground z 后做小范围校准。
    """

    z = float(ground_z)
    offset = float(settings.ROS_NAV_GOAL_Z_SEARCH_OFFSET_M)
    if not math.isfinite(z):
        z = 0.0
    if not math.isfinite(offset):
        offset = 0.0
    return z + offset


def waypoint_with_planner_goal_z(waypoint: dict[str, Any]) -> dict[str, Any]:
    """复制导航点，并把 z 替换为实际发布给规划器的 z。"""

    original_z = float(waypoint.get("z", 0.0))
    publish_z = planner_goal_z(original_z)
    return {
        **waypoint,
        "z": publish_z,
        "ground_z": original_z,
        "planner_goal_z": publish_z,
        "planner_goal_z_offset_m": float(settings.ROS_NAV_GOAL_Z_SEARCH_OFFSET_M),
    }
