from __future__ import annotations

import time
from typing import Any

from .ros_nav_messages import quaternion_to_yaw, stamp_to_seconds

TF_POSE_TYPES = {
    "tf",
    "tf2",
    "transform",
    "transformstamped",
}


def use_tf_pose(pose_type: str) -> bool:
    return pose_type.strip().lower() in TF_POSE_TYPES


def tf_source(target_frame: str, source_frame: str) -> str:
    return f"tf:{target_frame}->{source_frame}"


def base_frame_candidates(configured_base_frames: str) -> list[str]:
    configured = [
        item.strip()
        for item in str(configured_base_frames).split(",")
        if item.strip()
    ]
    candidates: list[str] = []
    for frame in [*configured, "base_footprint", "base_link"]:
        if frame and frame not in candidates:
            candidates.append(frame)
    return candidates


def lookup_tf_pose(
    *,
    tf_buffer: Any,
    rclpy_time_cls: Any,
    target_frame: str,
    source_frames: list[str],
) -> dict[str, Any]:
    if tf_buffer is None or rclpy_time_cls is None:
        raise RuntimeError("TF buffer 未初始化")

    errors: list[str] = []
    transform_stamped = None
    source_frame = ""
    for candidate in source_frames:
        try:
            transform_stamped = tf_buffer.lookup_transform(
                target_frame,
                candidate,
                rclpy_time_cls(),
            )
            source_frame = candidate
            break
        except Exception as exc:
            errors.append(f"{candidate}: {exc}")

    if transform_stamped is None:
        raise RuntimeError("; ".join(errors) or "没有可用 base frame")

    transform = transform_stamped.transform
    translation = transform.translation
    rotation = transform.rotation
    header = transform_stamped.header
    received_at = time.time()

    return {
        "x": float(translation.x),
        "y": float(translation.y),
        "z": float(translation.z),
        "yaw": quaternion_to_yaw(
            float(rotation.x),
            float(rotation.y),
            float(rotation.z),
            float(rotation.w),
        ),
        "frame_id": target_frame,
        "source": tf_source(target_frame, source_frame),
        "source_frame": source_frame,
        "timestamp": received_at,
        "ros_timestamp": stamp_to_seconds(header.stamp),
    }
