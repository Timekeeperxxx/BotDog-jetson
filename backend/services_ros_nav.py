from __future__ import annotations

import asyncio
import json
import math
import threading
import time
from typing import Any

from .config import settings
from .logging_config import get_logger
from .services_nav_state import (
    update_global_path,
    get_robot_pose,
    get_nav_state,
    update_localization_status,
    update_robot_pose,
    update_navigation_status,
)
from .ws_event_broadcaster import EventBroadcaster

nav_logger = get_logger("ROS导航")
tf_logger = get_logger("ROS TF")


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
        self._page_open_publisher: Any | None = None
        self._nav_start_publisher: Any | None = None
        self._goal_xyz_publisher: Any | None = None
        self._goal_yaw_publisher: Any | None = None
        self._global_path_subscription: Any | None = None
        self._nav_status_subscription: Any | None = None
        self._estop_publisher: Any | None = None
        self._set_pose_publisher: Any | None = None
        self._mapping_publisher: Any | None = None
        self._publisher_lock = threading.RLock()
        self._last_broadcast_at = 0.0
        self._last_localization_broadcast_at = 0.0
        self._tf_available = False
        self._tf_wait_started_at = 0.0
        self._last_tf_warning_at = 0.0

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
                nav_logger.warning("ROS2 导航节点销毁失败：{}", exc)

        if self._rclpy is not None:
            try:
                self._rclpy.shutdown()
            except Exception as exc:
                nav_logger.warning("rclpy shutdown 失败：{}", exc)

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def _run(self) -> None:
        try:
            import rclpy
            from nav_msgs.msg import Odometry
            from nav_msgs.msg import Path
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
            nav_logger.warning("ROS2 导航订阅未启动：{}", exc)
            return

        self._rclpy = rclpy

        try:
            rclpy.init(args=None)
            self._node = rclpy.create_node("botdog_nav_state_bridge")
            self._setup_publishers()
            self._setup_global_path_subscription(Path)
            self._setup_nav_status_subscription()

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
                nav_logger.info(
                    "ROS2 TF 查询已启动：target_frame={}，source_frame={}",
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
                nav_logger.info(
                    "ROS2 导航订阅已启动：topic={}，type={}",
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
            nav_logger.exception("ROS2 导航订阅异常：{}", exc)
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
            nav_logger.info("ROS2 导航订阅线程已退出")

    def _setup_publishers(self) -> None:
        try:
            from geometry_msgs.msg import PointStamped
            from std_msgs.msg import Bool, Float64
        except Exception as exc:
            raise RuntimeError(f"导航发布消息类型不可用: {exc}") from exc

        self._page_open_publisher = self._node.create_publisher(
            Bool,
            settings.ROS_NAV_PAGE_OPEN_TOPIC,
            10,
        )
        self._nav_start_publisher = self._node.create_publisher(
            Bool,
            settings.ROS_NAV_START_TOPIC,
            10,
        )
        self._goal_xyz_publisher = self._node.create_publisher(
            PointStamped,
            settings.ROS_NAV_GOAL_XYZ_TOPIC,
            1,
        )
        self._goal_yaw_publisher = self._node.create_publisher(
            Float64,
            settings.ROS_NAV_GOAL_YAW_TOPIC,
            10,
        )
        self._estop_publisher = self._node.create_publisher(
            Bool,
            settings.ROS_NAV_STOP_TOPIC,
            10,
        )
        self._set_pose_publisher = self._node.create_publisher(
            Bool,
            settings.ROS_NAV_SET_POSE_TOPIC,
            10,
        )
        self._mapping_publisher = self._node.create_publisher(
            Bool,
            settings.ROS_NAV_MAPPING_TOPIC,
            10,
        )
        nav_logger.info(
            "ROS2 导航发布器已启动：page_open_topic={}，nav_start_topic={}，clicked_point_topic={}，goal_yaw_topic={}，stop_topic={}，set_pose_topic={}，mapping_topic={}，status_topic={}，global_path_topic={}",
            settings.ROS_NAV_PAGE_OPEN_TOPIC,
            settings.ROS_NAV_START_TOPIC,
            settings.ROS_NAV_GOAL_XYZ_TOPIC,
            settings.ROS_NAV_GOAL_YAW_TOPIC,
            settings.ROS_NAV_STOP_TOPIC,
            settings.ROS_NAV_SET_POSE_TOPIC,
            settings.ROS_NAV_MAPPING_TOPIC,
            settings.ROS_NAV_STATUS_TOPIC,
            settings.ROS_NAV_GLOBAL_PATH_TOPIC,
        )

    def publish_navigation_page_open(self) -> dict[str, Any]:
        if self._node is None or self._page_open_publisher is None:
            raise RuntimeError("ROS2 导航页面启动发布器未就绪")

        from std_msgs.msg import Bool

        msg = Bool()
        msg.data = True
        with self._publisher_lock:
            self._page_open_publisher.publish(msg)

        return {
            "success": True,
            "topic": settings.ROS_NAV_PAGE_OPEN_TOPIC,
            "data": True,
        }

    def publish_navigation_start(self, enabled: bool = True) -> dict[str, Any]:
        if self._node is None or self._nav_start_publisher is None:
            raise RuntimeError("ROS2 nav_start 发布器未就绪")

        from std_msgs.msg import Bool

        msg = Bool()
        msg.data = bool(enabled)
        with self._publisher_lock:
            self._nav_start_publisher.publish(msg)

        return {
            "success": True,
            "topic": settings.ROS_NAV_START_TOPIC,
            "data": bool(enabled),
        }

    def publish_goal_xyz_yaw(self, waypoint: dict[str, Any]) -> dict[str, Any]:
        if self._node is None:
            raise RuntimeError("ROS2 导航节点未就绪")
        if self._goal_xyz_publisher is None:
            raise RuntimeError("ROS2 clicked_point 发布器未就绪")
        if self._goal_yaw_publisher is None:
            raise RuntimeError("ROS2 goal_yaw 发布器未就绪")

        from geometry_msgs.msg import PointStamped
        from std_msgs.msg import Float64

        yaw = float(waypoint.get("yaw", 0.0))

        yaw_msg = Float64()
        yaw_msg.data = yaw

        point_msg = PointStamped()
        point_msg.header.stamp = self._node.get_clock().now().to_msg()
        point_msg.header.frame_id = str(waypoint.get("frame_id") or settings.ROS_NAV_FRAME_ID)
        point_msg.point.x = float(waypoint["x"])
        point_msg.point.y = float(waypoint["y"])
        point_msg.point.z = float(waypoint.get("z", 0.0))

        with self._publisher_lock:
            self._goal_yaw_publisher.publish(yaw_msg)
            self._goal_xyz_publisher.publish(point_msg)

        return {
            "success": True,
            "xyz_topic": settings.ROS_NAV_GOAL_XYZ_TOPIC,
            "yaw_topic": settings.ROS_NAV_GOAL_YAW_TOPIC,
            "waypoint_id": waypoint.get("id"),
            "x": point_msg.point.x,
            "y": point_msg.point.y,
            "z": point_msg.point.z,
            "yaw": yaw,
            "frame_id": point_msg.header.frame_id,
        }

    def publish_emergency_stop(self) -> dict[str, Any]:
        if self._node is None or self._estop_publisher is None:
            raise RuntimeError("ROS2 急停发布器未就绪")

        from std_msgs.msg import Bool

        msg = Bool()
        msg.data = True
        with self._publisher_lock:
            self._estop_publisher.publish(msg)

        return {
            "success": True,
            "topic": settings.ROS_NAV_STOP_TOPIC,
        }

    def publish_set_pose(self) -> dict[str, Any]:
        if self._node is None or self._set_pose_publisher is None:
            raise RuntimeError("ROS2 重定位发布器未就绪")

        from std_msgs.msg import Bool

        msg = Bool()
        msg.data = True
        with self._publisher_lock:
            self._set_pose_publisher.publish(msg)

        return {
            "success": True,
            "topic": settings.ROS_NAV_SET_POSE_TOPIC,
            "data": True,
        }

    def publish_mapping_enabled(self, enabled: bool) -> dict[str, Any]:
        if self._node is None or self._mapping_publisher is None:
            raise RuntimeError("ROS2 建图发布器未就绪")

        from std_msgs.msg import Bool

        msg = Bool()
        msg.data = bool(enabled)
        with self._publisher_lock:
            self._mapping_publisher.publish(msg)

        return {
            "success": True,
            "topic": settings.ROS_NAV_MAPPING_TOPIC,
            "enabled": bool(enabled),
        }

    def _setup_global_path_subscription(self, path_cls: Any) -> None:
        if self._node is None:
            return

        self._global_path_subscription = self._node.create_subscription(
            path_cls,
            settings.ROS_NAV_GLOBAL_PATH_TOPIC,
            self._handle_global_path_message,
            10,
        )
        nav_logger.info(
            "ROS2 global_path 订阅已启动：topic={}",
            settings.ROS_NAV_GLOBAL_PATH_TOPIC,
        )

    def _setup_nav_status_subscription(self) -> None:
        if self._node is None:
            return

        try:
            from std_msgs.msg import String
        except Exception as exc:
            raise RuntimeError(f"nav_status 消息类型不可用: {exc}") from exc

        self._nav_status_subscription = self._node.create_subscription(
            String,
            settings.ROS_NAV_STATUS_TOPIC,
            self._handle_nav_status_message,
            10,
        )
        nav_logger.info(
            "ROS2 nav_status 订阅已启动：topic={}",
            settings.ROS_NAV_STATUS_TOPIC,
        )

    def _handle_global_path_message(self, msg: Any) -> None:
        try:
            path = self._extract_global_path(msg)
        except Exception as exc:
            nav_logger.warning("global_path 消息解析失败：{}", exc)
            return

        update_global_path(path)
        self._submit_broadcast("nav.global_path", path)

    def _handle_nav_status_message(self, msg: Any) -> None:
        raw_data = str(getattr(msg, "data", "") or "").strip()
        if not raw_data:
            nav_logger.warning("nav_status 消息为空")
            return

        try:
            payload = json.loads(raw_data)
        except Exception as exc:
            nav_logger.warning("nav_status JSON 解析失败：{}", exc)
            return

        if not isinstance(payload, dict):
            nav_logger.warning("nav_status JSON 结构错误：期望对象，实际为 {}", type(payload).__name__)
            return

        nav_status = self._normalize_nav_status(payload)
        updated_status = update_navigation_status(nav_status)
        self._submit_broadcast("nav.navigation_status", updated_status)

    def _normalize_nav_status(self, payload: dict[str, Any]) -> dict[str, Any]:
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
            nav_logger.warning("收到未知 nav_status：{}", raw_status or "<empty>")

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

        waypoint_id = _to_optional_str(payload.get("waypoint_id"))
        target_waypoint_id = _to_optional_str(payload.get("target_waypoint_id")) or waypoint_id
        target_name = _to_optional_str(payload.get("target_name") or payload.get("waypoint_name"))
        message = _to_optional_str(payload.get("message")) or ""
        timestamp_value = _to_optional_float(payload.get("timestamp"))
        timestamp = timestamp_value if timestamp_value is not None else time.time()

        return {
            "status": mapped_status,
            "target_waypoint_id": target_waypoint_id,
            "target_name": target_name,
            "message": message,
            "timestamp": timestamp,
            "ros_status": raw_status or None,
            "task_id": _to_optional_str(payload.get("task_id")),
            "waypoint_id": waypoint_id,
            "distance_to_goal": _to_optional_float(payload.get("distance_to_goal")),
            "error_code": _to_optional_str(payload.get("error_code")),
            "source": settings.ROS_NAV_STATUS_TOPIC,
        }

    def _extract_global_path(self, msg: Any) -> dict[str, Any]:
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
            "frame_id": _header_frame_id(msg),
            "timestamp": _header_timestamp(msg),
            "points": points,
        }

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
            message = (
                f"TF 暂未就绪：target={settings.ROS_NAV_FRAME_ID}，"
                f"source={settings.ROS_NAV_BASE_FRAME_ID}，原因={exc}"
            )
            update_localization_status(
                {
                    "status": "initializing",
                    "frame_id": settings.ROS_NAV_FRAME_ID,
                    "source": self._tf_source(),
                    "message": message,
                }
            )

            if self._tf_wait_started_at == 0.0:
                self._tf_wait_started_at = now
                self._last_tf_warning_at = now
                self._tf_available = False
                tf_logger.warning(
                    "TF 暂未就绪：target={}，source={}，原因={}",
                    settings.ROS_NAV_FRAME_ID,
                    settings.ROS_NAV_BASE_FRAME_ID,
                    exc,
                )
            elif now - self._last_tf_warning_at >= 30.0:
                self._last_tf_warning_at = now
                waited = int(now - self._tf_wait_started_at)
                tf_logger.warning(
                    "TF 仍未就绪：target={}，source={}，已等待={}s",
                    settings.ROS_NAV_FRAME_ID,
                    settings.ROS_NAV_BASE_FRAME_ID,
                    waited,
                )
            return

        if not self._tf_available and self._tf_wait_started_at > 0.0:
            tf_logger.info(
                "TF 已恢复：target={}，source={}",
                settings.ROS_NAV_FRAME_ID,
                settings.ROS_NAV_BASE_FRAME_ID,
            )
        self._tf_available = True
        self._tf_wait_started_at = 0.0
        self._last_tf_warning_at = 0.0

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
            nav_logger.warning("位姿消息解析失败：{}", exc)
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
            nav_logger.warning("导航 WebSocket 广播失败：{}", exc)
