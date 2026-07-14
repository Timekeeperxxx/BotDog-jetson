from __future__ import annotations

import math
import time
from typing import Any, Callable


def quaternion_to_yaw(x: float, y: float, z: float, w: float) -> float:
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(siny_cosp, cosy_cosp)


def stamp_to_seconds(stamp: Any) -> float:
    sec = float(getattr(stamp, "sec", 0.0))
    nanosec = float(getattr(stamp, "nanosec", 0.0))
    value = sec + nanosec / 1_000_000_000.0
    return value or time.time()


def header_frame_id(msg: Any, default_frame_id: str) -> str:
    header = getattr(msg, "header", None)
    return getattr(header, "frame_id", "") or default_frame_id


def header_timestamp(msg: Any) -> float:
    header = getattr(msg, "header", None)
    stamp = getattr(header, "stamp", None)
    if stamp is None:
        return time.time()
    return stamp_to_seconds(stamp)


def global_path_signature(path: dict[str, Any]) -> tuple[Any, ...]:
    points = path.get("points") or []
    return (
        path.get("frame_id"),
        len(points),
        tuple(
            (
                round(float(point.get("x", 0.0)), 3),
                round(float(point.get("y", 0.0)), 3),
                round(float(point.get("z", 0.0)), 3),
            )
            for point in points
            if isinstance(point, dict)
        ),
    )


def extract_global_path(msg: Any, default_frame_id: str) -> dict[str, Any]:
    poses = getattr(msg, "poses", []) or []
    points: list[dict[str, float]] = []
    for pose_stamped in poses:
        pose = getattr(pose_stamped, "pose", None)
        position = getattr(pose, "position", None)
        if position is None:
            continue
        points.append(
            {
                "x": float(position.x),
                "y": float(position.y),
                "z": float(getattr(position, "z", 0.0)),
            }
        )

    return {
        "frame_id": header_frame_id(msg, default_frame_id),
        "timestamp": header_timestamp(msg),
        "points": points,
    }


def resolve_pose_msg_type(
    pose_type: str,
    pose_with_covariance_cls: Any,
    pose_stamped_cls: Any,
    odometry_cls: Any,
    *,
    use_tf_pose: bool,
) -> Any:
    normalized = pose_type.strip().lower()
    if normalized in ("posewithcovariancestamped", "geometry_msgs/msg/posewithcovariancestamped"):
        return pose_with_covariance_cls
    if normalized in ("posestamped", "geometry_msgs/msg/posestamped"):
        return pose_stamped_cls
    if normalized in ("odometry", "nav_msgs/msg/odometry"):
        return odometry_cls
    if use_tf_pose:
        return None
    raise ValueError(f"不支持的 ROS_NAV_POSE_TYPE: {pose_type}")


def extract_pose(
    msg: Any,
    *,
    pose_type: str,
    pose_topic: str,
    default_frame_id: str,
) -> dict[str, Any]:
    normalized_pose_type = pose_type.strip().lower()
    if "odometry" in normalized_pose_type or hasattr(msg, "child_frame_id"):
        pose = msg.pose.pose
    elif hasattr(msg, "pose") and hasattr(msg.pose, "pose"):
        pose = msg.pose.pose
    else:
        pose = msg.pose

    position = pose.position
    orientation = pose.orientation
    frame_id = header_frame_id(msg, default_frame_id)

    return {
        "x": float(position.x),
        "y": float(position.y),
        "z": float(position.z),
        "yaw": quaternion_to_yaw(
            float(orientation.x),
            float(orientation.y),
            float(orientation.z),
            float(orientation.w),
        ),
        "frame_id": frame_id,
        "source": pose_topic,
        "timestamp": time.time(),
        "ros_timestamp": header_timestamp(msg),
    }


def normalize_nav_status(
    payload: dict[str, Any],
    *,
    status_topic: str,
    current_navigation_status: Callable[[], dict[str, Any]],
    diagnose_navigation_failure: Callable[[], dict[str, Any] | None],
    interrupted_navigation: Callable[[], dict[str, str | None] | None],
    warn_unknown_status: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    raw_status = str(payload.get("status") or "").strip().lower()
    status_map = {
        "accepted": "navigating",
        "moving": "navigating",
        "reached": "reached",
        "failed": "error",
        "canceled": "idle",
        "estop": "estop",
    }
    mapped_status = status_map.get(raw_status)
    if mapped_status is None:
        mapped_status = "error"
        if warn_unknown_status is not None:
            warn_unknown_status(raw_status or "<empty>")

    interrupted = None
    if raw_status == "canceled":
        interrupted = interrupted_navigation()
        if interrupted is not None:
            mapped_status = "paused"

    waypoint_id = _to_optional_str(payload.get("waypoint_id"))
    target_waypoint_id = _to_optional_str(payload.get("target_waypoint_id")) or waypoint_id
    target_name = _to_optional_str(payload.get("target_name") or payload.get("waypoint_name"))
    message = _to_optional_str(payload.get("message")) or ""
    error_code = _to_optional_str(payload.get("error_code"))
    if interrupted is not None:
        message = "导航任务已暂停，正在自动跟踪陌生人"
        target_waypoint_id = interrupted.get("target_waypoint_id") or target_waypoint_id
        target_name = interrupted.get("target_name") or target_name
    if mapped_status == "error":
        diagnosis = diagnose_navigation_failure()
        if diagnosis is not None:
            message = str(diagnosis["message"])
            error_code = str(diagnosis["error_code"])

    timestamp_value = _to_optional_float(payload.get("timestamp"))
    timestamp = timestamp_value if timestamp_value is not None else time.time()

    payload_task_id = _to_optional_str(payload.get("task_id"))
    if payload_task_id is None and mapped_status in {"navigating", "paused"}:
        current_nav_status = current_navigation_status()
        current_task_id = _to_optional_str(current_nav_status.get("task_id"))
        current_status = str(current_nav_status.get("status") or "").strip().lower()
        if current_task_id and current_status in {"navigating", "paused"}:
            payload_task_id = current_task_id

    return {
        "status": mapped_status,
        "target_waypoint_id": target_waypoint_id,
        "target_name": target_name,
        "message": message,
        "timestamp": timestamp,
        "ros_status": raw_status or None,
        "task_id": interrupted.get("task_id") if interrupted is not None else payload_task_id,
        "waypoint_id": waypoint_id,
        "distance_to_goal": _to_optional_float(payload.get("distance_to_goal")),
        "error_code": error_code,
        "source": status_topic,
    }


def _to_optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except Exception:
        return None


def _to_optional_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)
