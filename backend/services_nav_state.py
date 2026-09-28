from __future__ import annotations

import copy
import threading
import time
from typing import Any

from .config import settings


_lock = threading.RLock()
_latest_robot_pose: dict[str, Any] | None = None
_latest_global_path: dict[str, Any] | None = None
_latest_task_route: dict[str, Any] | None = None
_task_route_acceptance = "retained"
_task_route_run_id: str | None = None
_latest_execution_path: dict[str, Any] | None = None
_latest_navigation_status: dict[str, Any] = {
    "status": "idle",
    "target_waypoint_id": None,
    "target_name": None,
    "message": "导航空闲",
    "timestamp": None,
    "ros_status": None,
    "task_id": None,
    "waypoint_id": None,
    "distance_to_goal": None,
    "error_code": None,
    "source": "backend",
}
_latest_localization_status: dict[str, Any] = {
    "status": "unknown",
    "frame_id": settings.ROS_NAV_FRAME_ID,
    "source": None,
    "message": "尚未收到定位数据",
    "timestamp": None,
}
ROBOT_POSE_STALE_SECONDS = 3.0


def _is_pose_stale(pose: dict[str, Any] | None, now: float | None = None) -> bool:
    if pose is None:
        return False
    timestamp = pose.get("timestamp")
    if timestamp is None:
        return True
    try:
        pose_time = float(timestamp)
    except Exception:
        return True
    return ((now or time.time()) - pose_time) > ROBOT_POSE_STALE_SECONDS


def _stale_localization_status(now: float) -> dict[str, Any]:
    return {
        **copy.deepcopy(_latest_localization_status),
        "status": "initializing",
        "frame_id": settings.ROS_NAV_FRAME_ID,
        "source": _latest_localization_status.get("source"),
        "message": "定位数据超时，等待 TF 恢复",
        "timestamp": now,
    }


def update_robot_pose(pose: dict[str, Any]) -> dict[str, Any]:
    global _latest_robot_pose

    next_pose = copy.deepcopy(pose)
    next_pose.setdefault("timestamp", time.time())

    with _lock:
        _latest_robot_pose = next_pose

    return copy.deepcopy(next_pose)


def clear_robot_pose() -> None:
    global _latest_robot_pose

    with _lock:
        _latest_robot_pose = None


def update_global_path(path: dict[str, Any]) -> dict[str, Any]:
    global _latest_global_path

    next_path = copy.deepcopy(path)
    next_path.setdefault("timestamp", time.time())

    with _lock:
        _latest_global_path = next_path

    return copy.deepcopy(next_path)


def clear_global_path() -> None:
    global _latest_execution_path, _latest_global_path, _latest_task_route, _task_route_acceptance

    with _lock:
        _latest_global_path = None
        _latest_execution_path = None
        _latest_task_route = None
        _task_route_acceptance = "blocked"


def update_execution_path(path: dict[str, Any]) -> dict[str, Any]:
    global _latest_execution_path

    next_path = copy.deepcopy(path)
    next_path.setdefault("timestamp", time.time())

    with _lock:
        _latest_execution_path = next_path

    return copy.deepcopy(next_path)


def clear_execution_path() -> None:
    global _latest_execution_path

    with _lock:
        _latest_execution_path = None


def reset_localization_tracking(message: str = "等待重定位数据") -> dict[str, Any]:
    clear_robot_pose()
    clear_global_path()
    return update_localization_status(
        {
            "status": "initializing",
            "frame_id": settings.ROS_NAV_FRAME_ID,
            "source": None,
            "message": message,
        }
    )


def update_navigation_status(status: dict[str, Any]) -> dict[str, Any]:
    global _latest_navigation_status

    next_status = {
        **_latest_navigation_status,
        **copy.deepcopy(status),
        "timestamp": status.get("timestamp", time.time()),
    }
    if next_status.get("source") in (None, ""):
        next_status["source"] = "backend"

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
            "ros_status": None,
            "task_id": None,
            "waypoint_id": None,
            "distance_to_goal": None,
            "error_code": None,
            "source": "backend",
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
        if _is_pose_stale(_latest_robot_pose):
            return None
        return copy.deepcopy(_latest_robot_pose)


def get_global_path() -> dict[str, Any] | None:
    with _lock:
        return copy.deepcopy(_latest_global_path)


def get_execution_path() -> dict[str, Any] | None:
    with _lock:
        return copy.deepcopy(_latest_execution_path)


def get_nav_state() -> dict[str, Any]:
    with _lock:
        now = time.time()
        pose = None if _is_pose_stale(_latest_robot_pose, now) else copy.deepcopy(_latest_robot_pose)
        localization_status = (
            _stale_localization_status(now)
            if pose is None and _latest_robot_pose is not None
            else copy.deepcopy(_latest_localization_status)
        )
        return {
            "robot_pose": pose,
            "navigation_status": copy.deepcopy(_latest_navigation_status),
            "localization_status": localization_status,
            "global_path": copy.deepcopy(_latest_global_path),
            "task_route": copy.deepcopy(_latest_task_route),
            "execution_path": copy.deepcopy(_latest_execution_path),
        }


def begin_task_route() -> None:
    global _task_route_acceptance
    with _lock:
        clear_global_path()
        _task_route_acceptance = "planning"


def update_task_route(route: dict[str, Any]) -> dict[str, Any] | None:
    global _latest_task_route, _task_route_acceptance, _task_route_run_id
    with _lock:
        if _task_route_acceptance == "blocked":
            return None
        if _task_route_acceptance == "planning":
            if route["status"] != "planning" or route["segments"] or route["run_id"] == _task_route_run_id:
                return None
        elif _task_route_acceptance == "active" and route["run_id"] != _task_route_run_id:
            return None
        _task_route_acceptance = "active"
        _task_route_run_id = route["run_id"]
        _latest_task_route = copy.deepcopy(route)
        _latest_task_route["timestamp"] = time.time()
        return copy.deepcopy(_latest_task_route)
