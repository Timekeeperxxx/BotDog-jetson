from __future__ import annotations

import copy
import threading
import time
from typing import Any

from .config import settings


_lock = threading.RLock()
_latest_robot_pose: dict[str, Any] | None = None
_latest_global_path: dict[str, Any] | None = None
_latest_navigation_status: dict[str, Any] = {
    "status": "idle",
    "target_waypoint_id": None,
    "target_name": None,
    "message": "导航空闲",
    "timestamp": None,
}
_latest_localization_status: dict[str, Any] = {
    "status": "unknown",
    "frame_id": settings.ROS_NAV_FRAME_ID,
    "source": None,
    "message": "尚未收到定位数据",
    "timestamp": None,
}


def update_robot_pose(pose: dict[str, Any]) -> dict[str, Any]:
    global _latest_robot_pose

    next_pose = copy.deepcopy(pose)
    next_pose.setdefault("timestamp", time.time())

    with _lock:
        _latest_robot_pose = next_pose

    return copy.deepcopy(next_pose)


def update_global_path(path: dict[str, Any]) -> dict[str, Any]:
    global _latest_global_path

    next_path = copy.deepcopy(path)
    next_path.setdefault("timestamp", time.time())

    with _lock:
        _latest_global_path = next_path

    return copy.deepcopy(next_path)


def clear_global_path() -> None:
    global _latest_global_path

    with _lock:
        _latest_global_path = None


def update_navigation_status(status: dict[str, Any]) -> dict[str, Any]:
    global _latest_navigation_status

    next_status = {
        **_latest_navigation_status,
        **copy.deepcopy(status),
        "timestamp": status.get("timestamp", time.time()),
    }

    with _lock:
        _latest_navigation_status = next_status

    return copy.deepcopy(next_status)


def set_navigation_idle(message: str = "导航空闲") -> dict[str, Any]:
    return update_navigation_status(
        {
            "status": "idle",
            "target_waypoint_id": None,
            "target_name": None,
            "message": message,
        }
    )


def update_localization_status(status: dict[str, Any]) -> dict[str, Any]:
    global _latest_localization_status

    next_status = {
        **_latest_localization_status,
        **copy.deepcopy(status),
        "timestamp": status.get("timestamp", time.time()),
    }

    with _lock:
        _latest_localization_status = next_status

    return copy.deepcopy(next_status)


def get_robot_pose() -> dict[str, Any] | None:
    with _lock:
        return copy.deepcopy(_latest_robot_pose)


def get_global_path() -> dict[str, Any] | None:
    with _lock:
        return copy.deepcopy(_latest_global_path)


def get_nav_state() -> dict[str, Any]:
    with _lock:
        return {
            "robot_pose": copy.deepcopy(_latest_robot_pose),
            "navigation_status": copy.deepcopy(_latest_navigation_status),
            "localization_status": copy.deepcopy(_latest_localization_status),
            "global_path": copy.deepcopy(_latest_global_path),
        }
