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

    try:
        z = float(ground_z)
    except (TypeError, ValueError) as exc:
        raise ValueError("导航目标缺少有效的同层 z 高度") from exc
    offset = float(settings.ROS_NAV_GOAL_Z_SEARCH_OFFSET_M)
    if not math.isfinite(z):
        raise ValueError("导航目标的同层 z 高度必须是有限数值")
    if not math.isfinite(offset):
        raise ValueError("ROS_NAV_GOAL_Z_SEARCH_OFFSET_M 必须是有限数值")
    publish_z = z + offset
    if not math.isfinite(publish_z):
        raise ValueError("导航目标计算后的 z 高度必须是有限数值")
    return publish_z


def waypoint_with_planner_goal_z(waypoint: dict[str, Any]) -> dict[str, Any]:
    """复制导航点，并把 z 替换为实际发布给规划器的 z。"""

    if "z" not in waypoint or waypoint["z"] is None:
        raise ValueError("导航点缺少同层 z 高度，拒绝按 z=0 发布")
    original_z = float(waypoint["z"])
    publish_z = planner_goal_z(original_z)
    return {
        **waypoint,
        "z": publish_z,
        "ground_z": original_z,
        "planner_goal_z": publish_z,
        "planner_goal_z_offset_m": float(settings.ROS_NAV_GOAL_Z_SEARCH_OFFSET_M),
    }
