from __future__ import annotations

import asyncio
import math
import threading
import time
from typing import Any

from .config import settings
from .logging_config import logger
from .services_nav_state import (
    get_robot_pose,
    update_localization_status,
    update_robot_pose,
)
from .ws_event_broadcaster import EventBroadcaster


def quaternion_to_yaw(x: float, y: float, z: float, w: float) -> float:
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(siny_cosp, cosy_cosp)


def _stamp_to_seconds(stamp: Any) -> float:
    sec = float(getattr(stamp, "sec", 0.0))
    nanosec = float(getattr(stamp, "nanosec", 0.0))
    value = sec + nanosec / 1_000_000_000.0
    return value or time.time()


def _header_frame_id(msg: Any) -> str:
    header = getattr(msg, "header", None)
    return getattr(header, "frame_id", "") or settings.ROS_NAV_FRAME_ID


def _header_timestamp(msg: Any) -> float:
    header = getattr(msg, "header", None)
    stamp = getattr(header, "stamp", None)
    if stamp is None:
        return time.time()
    return _stamp_to_seconds(stamp)


class RosNavBridge:
    def __init__(
        self,
        broadcaster: EventBroadcaster,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._broadcaster = broadcaster
        self._loop = loop
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._node: Any | None = None
        self._rclpy: Any | None = None
        self._tf_buffer: Any | None = None
        self._tf_listener: Any | None = None
        self._last_broadcast_at = 0.0
        self._last_localization_broadcast_at = 0.0
        self._last_tf_lookup_error_at = 0.0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        self._thread = threading.Thread(
            target=self._run,
            name="botdog-ros-nav-bridge",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop_event.set()

        if self._node is not None:
            try:
                self._node.destroy_node()
            except Exception as exc:
                logger.warning(f"ROS2 导航节点销毁失败: {exc}")

        if self._rclpy is not None:
            try:
                self._rclpy.shutdown()
            except Exception as exc:
                logger.warning(f"rclpy shutdown 失败: {exc}")

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def _run(self) -> None:
        try:
            import rclpy
            from nav_msgs.msg import Odometry
            from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped
        except Exception as exc:
            update_localization_status(
                {
                    "status": "error",
                    "frame_id": settings.ROS_NAV_FRAME_ID,
                    "source": settings.ROS_NAV_POSE_TOPIC,
                    "message": f"ROS2/rclpy 不可用: {exc}",
                }
            )
            logger.warning(f"ROS2 导航订阅未启动: {exc}")
            return

        self._rclpy = rclpy

        try:
            rclpy.init(args=None)
            self._node = rclpy.create_node("botdog_nav_state_bridge")

            if self._use_tf_pose():
                self._setup_tf_listener()
                source = self._tf_source()
                update_localization_status(
                    {
                        "status": "initializing",
                        "frame_id": settings.ROS_NAV_FRAME_ID,
                        "source": source,
                        "message": "ROS2 TF 查询已启动，等待坐标变换",
                    }
                )
                logger.info(
                    "ROS2 TF 导航查询已启动: target_frame={}, source_frame={}",
                    settings.ROS_NAV_FRAME_ID,
                    settings.ROS_NAV_BASE_FRAME_ID,
                )
            else:
                msg_type = self._resolve_msg_type(
                    pose_type=settings.ROS_NAV_POSE_TYPE,
                    pose_with_covariance_cls=PoseWithCovarianceStamped,
                    pose_stamped_cls=PoseStamped,
                    odometry_cls=Odometry,
                )

                self._node.create_subscription(
                    msg_type,
                    settings.ROS_NAV_POSE_TOPIC,
                    self._handle_pose_message,
                    10,
                )
                update_localization_status(
                    {
                        "status": "initializing",
                        "frame_id": settings.ROS_NAV_FRAME_ID,
                        "source": settings.ROS_NAV_POSE_TOPIC,
                        "message": "ROS2 位姿订阅已启动，等待定位数据",
                    }
                )
                logger.info(
                    "ROS2 导航订阅已启动: topic={}, type={}",
                    settings.ROS_NAV_POSE_TOPIC,
                    settings.ROS_NAV_POSE_TYPE,
                )

            while not self._stop_event.is_set():
                rclpy.spin_once(self._node, timeout_sec=0.1)
                if self._use_tf_pose():
                    self._update_pose_from_tf_if_needed()
                self._broadcast_latest_if_needed()

        except Exception as exc:
            update_localization_status(
                {
                    "status": "error",
                    "frame_id": settings.ROS_NAV_FRAME_ID,
                    "source": settings.ROS_NAV_POSE_TOPIC,
                    "message": f"ROS2 导航订阅异常: {exc}",
                }
            )
            logger.exception(f"ROS2 导航订阅异常: {exc}")
        finally:
            if self._node is not None:
                try:
                    self._node.destroy_node()
                except Exception:
                    pass
                self._node = None
            try:
                rclpy.shutdown()
            except Exception:
                pass
            logger.info("ROS2 导航订阅线程已退出")

    def _use_tf_pose(self) -> bool:
        return settings.ROS_NAV_POSE_TYPE.strip().lower() in (
            "tf",
            "tf2",
            "transform",
            "transformstamped",
        )

    def _tf_source(self) -> str:
        return f"tf:{settings.ROS_NAV_FRAME_ID}->{settings.ROS_NAV_BASE_FRAME_ID}"

    def _setup_tf_listener(self) -> None:
        try:
            from tf2_ros import Buffer, TransformListener
        except Exception as exc:
            raise RuntimeError(f"tf2_ros 不可用: {exc}") from exc

        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(self._tf_buffer, self._node)

    def _update_pose_from_tf_if_needed(self) -> None:
        now = time.monotonic()
        min_interval = 1.0 / max(0.1, settings.ROS_NAV_BROADCAST_HZ)
        if now - self._last_broadcast_at < min_interval:
            return

        try:
            pose = self._lookup_tf_pose()
        except Exception as exc:
            if now - self._last_tf_lookup_error_at >= 1.0:
                self._last_tf_lookup_error_at = now
                message = (
                    f"等待 TF 变换 {settings.ROS_NAV_FRAME_ID} -> "
                    f"{settings.ROS_NAV_BASE_FRAME_ID}: {exc}"
                )
                update_localization_status(
                    {
                        "status": "initializing",
                        "frame_id": settings.ROS_NAV_FRAME_ID,
                        "source": self._tf_source(),
                        "message": message,
                    }
                )
                logger.debug(message)
            return

        update_robot_pose(pose)
        update_localization_status(
            {
                "status": "ok",
                "frame_id": settings.ROS_NAV_FRAME_ID,
                "source": self._tf_source(),
                "message": "TF 定位正常",
                "timestamp": pose["timestamp"],
            }
        )

    def _lookup_tf_pose(self) -> dict[str, Any]:
        if self._tf_buffer is None or self._rclpy is None:
            raise RuntimeError("TF buffer 未初始化")

        from rclpy.time import Time

        transform_stamped = self._tf_buffer.lookup_transform(
            settings.ROS_NAV_FRAME_ID,
            settings.ROS_NAV_BASE_FRAME_ID,
            Time(),
        )
        transform = transform_stamped.transform
        translation = transform.translation
        rotation = transform.rotation
        header = transform_stamped.header

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
            "frame_id": settings.ROS_NAV_FRAME_ID,
            "source": self._tf_source(),
            "timestamp": _stamp_to_seconds(header.stamp),
        }

    def _resolve_msg_type(
        self,
        pose_type: str,
        pose_with_covariance_cls: Any,
        pose_stamped_cls: Any,
        odometry_cls: Any,
    ) -> Any:
        normalized = pose_type.strip().lower()
        if normalized in ("posewithcovariancestamped", "geometry_msgs/msg/posewithcovariancestamped"):
            return pose_with_covariance_cls
        if normalized in ("posestamped", "geometry_msgs/msg/posestamped"):
            return pose_stamped_cls
        if normalized in ("odometry", "nav_msgs/msg/odometry"):
            return odometry_cls
        if self._use_tf_pose():
            return None
        raise ValueError(f"不支持的 ROS_NAV_POSE_TYPE: {pose_type}")

    def _handle_pose_message(self, msg: Any) -> None:
        try:
            pose = self._extract_pose(msg)
        except Exception as exc:
            update_localization_status(
                {
                    "status": "error",
                    "frame_id": _header_frame_id(msg),
                    "source": settings.ROS_NAV_POSE_TOPIC,
                    "message": f"位姿消息解析失败: {exc}",
                }
            )
            logger.warning(f"位姿消息解析失败: {exc}")
            return

        update_robot_pose(pose)

        if pose["frame_id"] == settings.ROS_NAV_FRAME_ID:
            status = "ok"
            message = "定位正常"
        else:
            status = "error"
            message = f"当前位姿坐标系是 {pose['frame_id']}，不是 {settings.ROS_NAV_FRAME_ID}"

        update_localization_status(
            {
                "status": status,
                "frame_id": pose["frame_id"],
                "source": settings.ROS_NAV_POSE_TOPIC,
                "message": message,
                "timestamp": pose["timestamp"],
            }
        )

        self._broadcast_latest_if_needed()

    def _extract_pose(self, msg: Any) -> dict[str, Any]:
        pose_type = settings.ROS_NAV_POSE_TYPE.strip().lower()
        if "odometry" in pose_type or hasattr(msg, "child_frame_id"):
            pose = msg.pose.pose
        elif hasattr(msg, "pose") and hasattr(msg.pose, "pose"):
            pose = msg.pose.pose
        else:
            pose = msg.pose

        position = pose.position
        orientation = pose.orientation
        frame_id = _header_frame_id(msg)

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
            "source": settings.ROS_NAV_POSE_TOPIC,
            "timestamp": _header_timestamp(msg),
        }

    def _broadcast_latest_if_needed(self) -> None:
        now = time.monotonic()
        min_interval = 1.0 / max(0.1, settings.ROS_NAV_BROADCAST_HZ)
        pose = get_robot_pose()

        if pose and now - self._last_broadcast_at >= min_interval:
            self._last_broadcast_at = now
            self._submit_broadcast("nav.robot_pose", pose)

        if now - self._last_localization_broadcast_at >= 1.0:
            self._last_localization_broadcast_at = now
            from .services_nav_state import get_nav_state

            localization_status = get_nav_state()["localization_status"]
            self._submit_broadcast("nav.localization_status", localization_status)

    def _submit_broadcast(self, event_type: str, data: dict[str, Any]) -> None:
        if self._loop.is_closed():
            return

        future = asyncio.run_coroutine_threadsafe(
            self._broadcaster.broadcast_event(event_type, data),
            self._loop,
        )
        future.add_done_callback(self._log_broadcast_error)

    @staticmethod
    def _log_broadcast_error(future: asyncio.Future[Any]) -> None:
        try:
            future.result()
        except Exception as exc:
            logger.warning(f"导航 WebSocket 广播失败: {exc}")
