from __future__ import annotations

import asyncio
import json
import math
import threading
import time
from typing import Any

import numpy as np

from .config import settings
from .logging_config import get_logger
from .services_nav_state import (
    clear_robot_pose,
    update_global_path,
    get_robot_pose,
    get_nav_state,
    update_localization_status,
    update_robot_pose,
    update_navigation_status,
)
from .services_nav_goal import planner_goal_z
from .ws_event_broadcaster import EventBroadcaster

nav_logger = get_logger("ROS导航")
tf_logger = get_logger("ROS TF")
GLOBAL_PATH_BROADCAST_MIN_INTERVAL_S = 1.0
MAPPING_CLOUD_LIVE_MIN_INTERVAL_S = 3.0
MAPPING_CLOUD_BROADCAST_MIN_INTERVAL_S = 3.0
MAPPING_CLOUD_ACCUMULATED_VOXEL_SIZE_M = 0.10
MAPPING_CLOUD_ACCUMULATED_MAX_BROADCAST_POINTS = 15000
MAPPING_CLOUD_ACCUMULATE_MAX_INPUT_POINTS = 1500
MAPPING_CLOUD_LIVE_MAX_BROADCAST_POINTS = 600
INITIAL_POSE_PUBLISH_COUNT = 20
INITIAL_POSE_PUBLISH_INTERVAL_S = 0.2
INITIAL_POSE_SUBSCRIBER_WAIT_S = 5.0
GOAL_PUBLISH_COUNT = 3
GOAL_PUBLISH_INTERVAL_S = 0.15


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
        mapping_cloud_broadcaster: EventBroadcaster | None = None,
    ) -> None:
        self._broadcaster = broadcaster
        self._mapping_cloud_broadcaster = mapping_cloud_broadcaster or broadcaster
        self._loop = loop
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._paused = False
        self._lifecycle_cv = threading.Condition()
        self._lifecycle_request: dict[str, Any] | None = None
        self._thread: threading.Thread | None = None
        self._node: Any | None = None
        self._rclpy: Any | None = None
        self._tf_buffer: Any | None = None
        self._tf_listener: Any | None = None
        self._nav_start_publisher: Any | None = None
        self._cmd_vel_publisher: Any | None = None
        self._goal_xyz_publisher: Any | None = None
        self._goal_yaw_publisher: Any | None = None
        self._global_path_subscription: Any | None = None
        self._nav_status_subscription: Any | None = None
        self._estop_publisher: Any | None = None
        self._initial_pose_publisher: Any | None = None
        self._cloud_subscription: Any | None = None
        self._publisher_lock = threading.RLock()
        self._last_broadcast_at = 0.0
        self._last_tf_lookup_at = 0.0
        self._last_localization_broadcast_at = 0.0
        self._last_global_path_broadcast_at = 0.0
        self._last_global_path_signature: tuple[Any, ...] | None = None
        self._last_cloud_broadcast_at = 0.0
        self._accumulated_cloud: np.ndarray = np.empty((0, 3), dtype=np.float32)
        self._accumulated_cloud_voxels: dict[tuple[int, int, int], tuple[float, float, float]] = {}
        self._last_full_map_broadcast_at = 0.0
        self._mapping_cloud_broadcast_future: Any | None = None
        self._tf_available = False
        self._tf_wait_started_at = 0.0
        self._last_tf_warning_at = 0.0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._pause_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="botdog-ros-nav-bridge",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop_event.set()
        with self._lifecycle_cv:
            self._lifecycle_cv.notify_all()

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

    def pause(self) -> None:
        """建图前调用：销毁 ROS2 node 以退出 DDS 网络，保留 rclpy context 以便恢复。

        CLI 手动建图时后端 ROS2 节点不存在；前端建图时后端节点仍在 DDS
        网络里可能干扰 SuperLIO 的 IMU 消息发现与时序，导致重力方向估计偏差。
        销毁 node 后该进程不再参与 DDS 发现，建图环境与 CLI 完全一致。
        """
        if self._paused or self._node is None:
            return
        self._request_lifecycle("pause")

    def resume(self) -> None:
        """建图结束后调用：重新创建 ROS2 node 并恢复所有订阅/发布。"""
        if not self._paused:
            return
        if not self._thread or not self._thread.is_alive():
            nav_logger.warning("ROS2 导航线程未运行，尝试重新启动")
            self._paused = False
            self.start()
            self._wait_for_backend_initial_pose_publisher(timeout_s=5.0)
            return
        self._request_lifecycle("resume")
        self._wait_for_backend_initial_pose_publisher(timeout_s=3.0)

    def _request_lifecycle(self, command: str, timeout_s: float = 8.0) -> None:
        if threading.current_thread() is self._thread:
            self._handle_lifecycle_command(command)
            return
        if not self._thread or not self._thread.is_alive():
            raise RuntimeError("ROS2 导航线程未运行")

        done = threading.Event()
        request: dict[str, Any] = {"command": command, "done": done, "error": None}
        with self._lifecycle_cv:
            if self._lifecycle_request is not None:
                raise RuntimeError("ROS2 导航节点生命周期操作正在进行中")
            self._lifecycle_request = request
            self._lifecycle_cv.notify_all()

        if not done.wait(timeout_s):
            with self._lifecycle_cv:
                if self._lifecycle_request is request:
                    self._lifecycle_request = None
                    self._lifecycle_cv.notify_all()
            raise RuntimeError(f"等待 ROS2 导航节点{command}超时")
        if request["error"] is not None:
            raise RuntimeError(str(request["error"]))

    def _handle_lifecycle_request(self) -> None:
        with self._lifecycle_cv:
            request = self._lifecycle_request
            self._lifecycle_request = None
            self._lifecycle_cv.notify_all()
        if request is None:
            return

        try:
            self._handle_lifecycle_command(str(request["command"]))
        except Exception as exc:
            request["error"] = exc
        finally:
            request["done"].set()

    def _handle_lifecycle_command(self, command: str) -> None:
        if command == "pause":
            self._pause_ros_node_for_mapping()
            return
        if command == "resume":
            self._resume_ros_node_after_mapping()
            return
        raise ValueError(f"未知 ROS2 导航节点生命周期操作: {command}")

    def _pause_ros_node_for_mapping(self) -> None:
        if self._paused or self._node is None:
            self._paused = True
            self._pause_event.set()
            return

        self._destroy_ros_node("暂停 ROS2 节点")
        self._paused = True
        self._pause_event.set()
        update_localization_status(
            {
                "status": "paused",
                "frame_id": settings.ROS_NAV_FRAME_ID,
                "source": self._tf_source() if self._use_tf_pose() else settings.ROS_NAV_POSE_TOPIC,
                "message": "建图进行中，导航定位已暂停",
            }
        )
        nav_logger.info("ROS2 导航节点已暂停（node 销毁，rclpy 保持初始化）")

    def _resume_ros_node_after_mapping(self) -> None:
        if not self._paused and self._node is not None:
            return
        if self._rclpy is None:
            self._paused = False
            raise RuntimeError("rclpy 未初始化，无法恢复节点")

        source = self._create_ros_node()
        self._pause_event.clear()
        self._paused = False
        self._tf_available = False
        self._tf_wait_started_at = 0.0
        self._last_tf_lookup_at = 0.0

        update_localization_status(
            {
                "status": "initializing",
                "frame_id": settings.ROS_NAV_FRAME_ID,
                "source": source,
                "message": "建图已结束，导航定位恢复中",
            }
        )
        nav_logger.info("ROS2 导航节点已恢复")

    def _destroy_ros_node(self, action: str) -> None:
        with self._publisher_lock:
            node = self._node
            self._node = None
            self._tf_buffer = None
            self._tf_listener = None
            self._nav_start_publisher = None
            self._cmd_vel_publisher = None
            self._goal_xyz_publisher = None
            self._goal_yaw_publisher = None
            self._global_path_subscription = None
            self._nav_status_subscription = None
            self._estop_publisher = None
            self._initial_pose_publisher = None
            self._cloud_subscription = None
            if node is not None:
                try:
                    node.destroy_node()
                except Exception as exc:
                    nav_logger.warning("{}销毁失败：{}", action, exc)

    def _create_ros_node(self) -> str:
        if self._rclpy is None:
            raise RuntimeError("rclpy 未初始化")

        try:
            from nav_msgs.msg import Odometry
            from nav_msgs.msg import Path
            from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped
        except Exception as exc:
            raise RuntimeError(f"导航消息类型不可用: {exc}") from exc

        with self._publisher_lock:
            self._node = self._rclpy.create_node("botdog_nav_state_bridge")
            self._setup_publishers()
            self._setup_global_path_subscription(Path)
            self._setup_nav_status_subscription()
            self._setup_cloud_subscription()

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
                source = settings.ROS_NAV_POSE_TOPIC
                update_localization_status(
                    {
                        "status": "initializing",
                        "frame_id": settings.ROS_NAV_FRAME_ID,
                        "source": source,
                        "message": "ROS2 位姿订阅已启动，等待定位数据",
                    }
                )
                nav_logger.info(
                    "ROS2 导航订阅已启动：topic={}，type={}",
                    settings.ROS_NAV_POSE_TOPIC,
                    settings.ROS_NAV_POSE_TYPE,
                )

        return source

    def _wait_for_backend_initial_pose_publisher(self, timeout_s: float = 3.0) -> bool:
        deadline = time.time() + max(0.1, float(timeout_s))
        while time.time() < deadline:
            if self.get_backend_initial_pose_publisher_count() > 0:
                return True
            time.sleep(0.1)
        nav_logger.warning(
            "后端 /initialpose publisher 未进入 ROS graph：topic={}",
            settings.ROS_NAV_INITIAL_POSE_TOPIC,
        )
        return False

    def _run(self) -> None:
        try:
            import rclpy
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
            self._create_ros_node()

            while not self._stop_event.is_set():
                self._handle_lifecycle_request()
                if self._pause_event.is_set() or self._node is None:
                    time.sleep(0.1)
                    continue
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
            self._destroy_ros_node("退出 ROS2 导航线程")
            try:
                rclpy.shutdown()
            except Exception:
                pass
            nav_logger.info("ROS2 导航订阅线程已退出")

    def _setup_publishers(self) -> None:
        try:
            from geometry_msgs.msg import PointStamped, Twist
            from std_msgs.msg import Bool, Float64
        except Exception as exc:
            raise RuntimeError(f"导航发布消息类型不可用: {exc}") from exc

        self._nav_start_publisher = self._node.create_publisher(
            Bool,
            settings.ROS_NAV_START_TOPIC,
            10,
        )
        self._cmd_vel_publisher = self._node.create_publisher(
            Twist,
            "/cmd_vel",
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
        try:
            from geometry_msgs.msg import PoseWithCovarianceStamped as _PwCS
        except Exception as exc:
            raise RuntimeError(f"PoseWithCovarianceStamped 不可用: {exc}") from exc
        from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy

        initial_pose_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self._initial_pose_publisher = self._node.create_publisher(
            _PwCS,
            settings.ROS_NAV_INITIAL_POSE_TOPIC,
            initial_pose_qos,
        )
        nav_logger.info(
            "ROS2 导航发布器已启动：nav_start_topic={}，clicked_point_topic={}，goal_yaw_topic={}，stop_topic={}，initial_pose_topic={}，status_topic={}，global_path_topic={}",
            settings.ROS_NAV_START_TOPIC,
            settings.ROS_NAV_GOAL_XYZ_TOPIC,
            settings.ROS_NAV_GOAL_YAW_TOPIC,
            settings.ROS_NAV_STOP_TOPIC,
            settings.ROS_NAV_INITIAL_POSE_TOPIC,
            settings.ROS_NAV_STATUS_TOPIC,
            settings.ROS_NAV_GLOBAL_PATH_TOPIC,
        )

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

    def publish_zero_cmd_vel(self, publish_count: int = 10, interval_s: float = 0.03) -> dict[str, Any]:
        if self._node is None or self._cmd_vel_publisher is None:
            raise RuntimeError("ROS2 cmd_vel 发布器未就绪")

        from geometry_msgs.msg import Twist

        count = max(1, int(publish_count))
        interval = max(0.0, float(interval_s))
        msg = Twist()
        with self._publisher_lock:
            for _ in range(count):
                self._cmd_vel_publisher.publish(msg)
                if interval > 0:
                    time.sleep(interval)

        return {
            "success": True,
            "topic": "/cmd_vel",
            "publish_count": count,
            "linear": {"x": 0.0, "y": 0.0, "z": 0.0},
            "angular": {"x": 0.0, "y": 0.0, "z": 0.0},
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
        original_z = float(waypoint.get("z", 0.0))
        point_msg.point.z = planner_goal_z(original_z)

        publish_count = 0
        for index in range(GOAL_PUBLISH_COUNT):
            point_msg.header.stamp = self._node.get_clock().now().to_msg()
            with self._publisher_lock:
                self._goal_yaw_publisher.publish(yaw_msg)
                self._goal_xyz_publisher.publish(point_msg)
            publish_count += 1
            if index < GOAL_PUBLISH_COUNT - 1:
                time.sleep(GOAL_PUBLISH_INTERVAL_S)

        return {
            "success": True,
            "xyz_topic": settings.ROS_NAV_GOAL_XYZ_TOPIC,
            "yaw_topic": settings.ROS_NAV_GOAL_YAW_TOPIC,
            "publish_count": publish_count,
            "waypoint_id": waypoint.get("id"),
            "x": point_msg.point.x,
            "y": point_msg.point.y,
            "z": point_msg.point.z,
            "ground_z": original_z,
            "planner_goal_z": point_msg.point.z,
            "planner_goal_z_offset_m": float(settings.ROS_NAV_GOAL_Z_SEARCH_OFFSET_M),
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

    def get_current_robot_pose(self) -> dict[str, Any] | None:
        if self._use_tf_pose():
            try:
                pose = self._lookup_tf_pose()
            except Exception as exc:
                nav_logger.warning("读取当前 TF 位姿失败：{}", exc)
                return get_robot_pose()

            update_robot_pose(pose)
            return pose

        return get_robot_pose()

    def publish_initial_pose(
        self,
        x: float,
        y: float,
        z: float,
        roll: float = 0.0,
        pitch: float = 0.0,
        yaw: float = 0.0,
        frame_id: str | None = None,
    ) -> dict[str, Any]:
        if self._node is None or self._initial_pose_publisher is None:
            raise RuntimeError("ROS2 initial_pose 发布器未就绪")

        from geometry_msgs.msg import PoseWithCovarianceStamped

        subscriber_status = self.wait_for_initial_pose_subscribers(INITIAL_POSE_SUBSCRIBER_WAIT_S)
        if not subscriber_status["ready"]:
            raise RuntimeError(subscriber_status["message"])

        # Euler ZYX -> quaternion
        cr = math.cos(float(roll) / 2.0)
        sr = math.sin(float(roll) / 2.0)
        cp = math.cos(float(pitch) / 2.0)
        sp = math.sin(float(pitch) / 2.0)
        cy = math.cos(float(yaw) / 2.0)
        sy = math.sin(float(yaw) / 2.0)
        frame = frame_id or settings.ROS_NAV_FRAME_ID
        publish_count = 0

        for index in range(INITIAL_POSE_PUBLISH_COUNT):
            msg = PoseWithCovarianceStamped()
            msg.header.stamp = self._node.get_clock().now().to_msg()
            msg.header.frame_id = frame

            msg.pose.pose.position.x = float(x)
            msg.pose.pose.position.y = float(y)
            msg.pose.pose.position.z = float(z)
            msg.pose.pose.orientation.w = cr * cp * cy + sr * sp * sy
            msg.pose.pose.orientation.x = sr * cp * cy - cr * sp * sy
            msg.pose.pose.orientation.y = cr * sp * cy + sr * cp * sy
            msg.pose.pose.orientation.z = cr * cp * sy - sr * sp * cy

            with self._publisher_lock:
                self._initial_pose_publisher.publish(msg)
            publish_count += 1

            if index < INITIAL_POSE_PUBLISH_COUNT - 1:
                time.sleep(INITIAL_POSE_PUBLISH_INTERVAL_S)

        nav_logger.info(
            "已发布 initial_pose：topic={} count={} interval={:.3f}s x={:.3f} y={:.3f} z={:.3f} roll={:.3f} pitch={:.3f} yaw={:.3f} frame={}",
            settings.ROS_NAV_INITIAL_POSE_TOPIC, publish_count, INITIAL_POSE_PUBLISH_INTERVAL_S, x, y, z, roll, pitch, yaw, frame,
        )
        return {
            "success": True,
            "topic": settings.ROS_NAV_INITIAL_POSE_TOPIC,
            "publish_count": publish_count,
            "subscriber_count": subscriber_status["subscriber_count"],
            "x": float(x),
            "y": float(y),
            "z": float(z),
            "roll": float(roll),
            "pitch": float(pitch),
            "yaw": float(yaw),
            "frame_id": frame,
        }

    def get_initial_pose_subscription_counts(self) -> dict[str, int]:
        if self._node is None or self._initial_pose_publisher is None:
            raise RuntimeError("ROS2 initial_pose 发布器未就绪")

        graph_count = 0
        matched_count = 0

        count_subscribers = getattr(self._node, "count_subscribers", None)
        if callable(count_subscribers):
            graph_count = int(count_subscribers(settings.ROS_NAV_INITIAL_POSE_TOPIC))

        get_count = getattr(self._initial_pose_publisher, "get_subscription_count", None)
        if callable(get_count):
            matched_count = int(get_count())

        if not callable(count_subscribers) and not callable(get_count):
            raise RuntimeError("ROS2 initial_pose 发布器不支持订阅者计数")

        return {
            "graph_count": graph_count,
            "matched_count": matched_count,
            "subscriber_count": max(graph_count, matched_count),
        }

    def get_initial_pose_subscription_count(self) -> int:
        return self.get_initial_pose_subscription_counts()["subscriber_count"]

    def get_backend_initial_pose_publisher_count(self) -> int:
        if self._node is None or self._initial_pose_publisher is None:
            return 0

        count_publishers = getattr(self._node, "count_publishers", None)
        if callable(count_publishers):
            return int(count_publishers(settings.ROS_NAV_INITIAL_POSE_TOPIC))
        return 1

    def wait_for_initial_pose_subscribers(self, timeout_s: float = INITIAL_POSE_SUBSCRIBER_WAIT_S) -> dict[str, Any]:
        deadline = time.time() + max(0.1, float(timeout_s))
        last_counts = {
            "graph_count": 0,
            "matched_count": 0,
            "subscriber_count": 0,
            "backend_publisher_count": 0,
        }

        while time.time() < deadline:
            subscription_counts = self.get_initial_pose_subscription_counts()
            backend_publisher_count = self.get_backend_initial_pose_publisher_count()
            last_counts = {
                **subscription_counts,
                "backend_publisher_count": backend_publisher_count,
            }
            if last_counts["subscriber_count"] > 0 and backend_publisher_count > 0:
                return {
                    "ready": True,
                    "topic": settings.ROS_NAV_INITIAL_POSE_TOPIC,
                    **last_counts,
                    "message": (
                        f"{settings.ROS_NAV_INITIAL_POSE_TOPIC} 已发现订阅者 "
                        f"{last_counts['subscriber_count']} 个"
                        f"（graph={last_counts['graph_count']} matched={last_counts['matched_count']} "
                        f"publisher={backend_publisher_count}）"
                    ),
                }
            time.sleep(0.2)

        if last_counts["backend_publisher_count"] <= 0:
            message = (
                f"后端 {settings.ROS_NAV_INITIAL_POSE_TOPIC} publisher 未进入 ROS graph"
                f"（publisher={last_counts['backend_publisher_count']} "
                f"graph={last_counts['graph_count']} matched={last_counts['matched_count']}），"
                "请检查后端 ROS 导航桥是否已恢复"
            )
        else:
            message = (
                f"{settings.ROS_NAV_INITIAL_POSE_TOPIC} 暂无订阅者"
                f"（graph={last_counts['graph_count']} matched={last_counts['matched_count']} "
                f"publisher={last_counts['backend_publisher_count']}），"
                "Super-LIO 还未准备接收 initialpose 或后端 ROS graph 与导航进程不一致"
            )

        return {
            "ready": False,
            "topic": settings.ROS_NAV_INITIAL_POSE_TOPIC,
            **last_counts,
            "message": message,
        }

    def _setup_cloud_subscription(self) -> None:
        if self._node is None:
            return
        if not settings.ROS_NAV_MAPPING_CLOUD_FORWARD_ENABLED:
            nav_logger.info("建图实时点云转发已禁用，跳过 {} 订阅", settings.ROS_NAV_MAPPING_CLOUD_TOPIC)
            return
        try:
            from sensor_msgs.msg import PointCloud2
        except Exception as exc:
            nav_logger.warning("PointCloud2 不可用，跳过建图点云订阅：{}", exc)
            return

        from rclpy.qos import qos_profile_sensor_data

        cloud_topic = settings.ROS_NAV_MAPPING_CLOUD_TOPIC
        self.clear_accumulated_cloud()
        self._cloud_subscription = self._node.create_subscription(
            PointCloud2,
            cloud_topic,
            self._handle_cloud_message,
            qos_profile_sensor_data,
        )
        nav_logger.info("ROS2 建图实时点云订阅已启动：topic={}", cloud_topic)

    def reset_mapping_cloud_subscription(self) -> bool:
        """Recreate the mapping cloud subscription after the mapping stack starts."""
        with self._publisher_lock:
            if self._node is None:
                nav_logger.warning(
                    "无法重建建图实时点云订阅：ROS2 节点未就绪，topic={}",
                    settings.ROS_NAV_MAPPING_CLOUD_TOPIC,
                )
                return False

            if self._cloud_subscription is not None:
                try:
                    self._node.destroy_subscription(self._cloud_subscription)
                except Exception as exc:
                    nav_logger.warning("销毁旧建图实时点云订阅失败：{}", exc)
                self._cloud_subscription = None

            self._setup_cloud_subscription()
            return self._cloud_subscription is not None

    def clear_accumulated_cloud(self) -> None:
        self._accumulated_cloud = np.empty((0, 3), dtype=np.float32)
        self._accumulated_cloud_voxels = {}
        self._last_full_map_broadcast_at = 0.0
        nav_logger.info("建图累积点云已清空")

    def _handle_cloud_message(self, msg: Any) -> None:
        now = time.monotonic()
        if not self._mapping_cloud_broadcaster.has_connections():
            has_voxel_cloud = bool(getattr(self, "_accumulated_cloud_voxels", None))
            if len(self._accumulated_cloud) > 0 or has_voxel_cloud:
                self.clear_accumulated_cloud()
            return

        if self._is_navigation_active():
            has_voxel_cloud = bool(getattr(self, "_accumulated_cloud_voxels", None))
            if len(self._accumulated_cloud) > 0 or has_voxel_cloud:
                self.clear_accumulated_cloud()
            return

        if now - self._last_cloud_broadcast_at < MAPPING_CLOUD_LIVE_MIN_INTERVAL_S:
            return
        self._last_cloud_broadcast_at = now

        cloud_pts = self._extract_cloud_xyz_np(msg, max_points=MAPPING_CLOUD_ACCUMULATE_MAX_INPUT_POINTS)
        if cloud_pts is None or len(cloud_pts) == 0:
            return

        self._merge_mapping_cloud_voxels(cloud_pts)

        live_pts = self._limit_cloud_points(cloud_pts, MAPPING_CLOUD_LIVE_MAX_BROADCAST_POINTS)
        if live_pts is None or len(live_pts) == 0:
            return

        payload: dict[str, Any] = {
            "live_points": live_pts.tolist(),
            "timestamp": time.time(),
        }

        if now - self._last_full_map_broadcast_at >= MAPPING_CLOUD_BROADCAST_MIN_INTERVAL_S:
            self._last_full_map_broadcast_at = now
            accumulated_preview = self._mapping_cloud_voxel_preview()
            if len(accumulated_preview) > 0:
                accumulated_points = accumulated_preview.tolist()
                payload["accumulated_points"] = accumulated_points
                payload["points"] = accumulated_points

        self._submit_broadcast("nav.mapping_cloud", payload)

    @staticmethod
    def _is_navigation_active() -> bool:
        try:
            nav_status = get_nav_state().get("navigation_status", {})
            status = str(nav_status.get("status") or "").strip().lower()
        except Exception:
            return False
        return status == "navigating"

    @staticmethod
    def _limit_cloud_points(points: np.ndarray, max_points: int) -> np.ndarray:
        if max_points <= 0 or len(points) <= max_points:
            return points
        step = max(1, math.ceil(len(points) / max_points))
        return points[::step][:max_points]

    def _merge_mapping_cloud_voxels(self, points: np.ndarray) -> None:
        if len(points) == 0:
            return
        if not hasattr(self, "_accumulated_cloud_voxels"):
            self._accumulated_cloud_voxels = {}

        voxel_size = MAPPING_CLOUD_ACCUMULATED_VOXEL_SIZE_M
        keys = np.floor(points / voxel_size).astype(np.int32)
        for key, point in zip(keys, points, strict=False):
            self._accumulated_cloud_voxels[(int(key[0]), int(key[1]), int(key[2]))] = (
                float(point[0]),
                float(point[1]),
                float(point[2]),
            )

    def _mapping_cloud_voxel_preview(self) -> np.ndarray:
        if not hasattr(self, "_accumulated_cloud_voxels") or not self._accumulated_cloud_voxels:
            return np.empty((0, 3), dtype=np.float32)
        points = np.fromiter(
            (coord for point in self._accumulated_cloud_voxels.values() for coord in point),
            dtype=np.float32,
        ).reshape((-1, 3))
        return self._limit_cloud_points(points, MAPPING_CLOUD_ACCUMULATED_MAX_BROADCAST_POINTS)

    @staticmethod
    def _voxel_downsample(points: np.ndarray, voxel_size: float) -> np.ndarray:
        if len(points) == 0:
            return points
        keys = np.floor(points / voxel_size).astype(np.int32)
        _, unique_indices = np.unique(keys, axis=0, return_index=True)
        return points[np.sort(unique_indices)]

    @staticmethod
    def _extract_cloud_xyz_np(msg: Any, max_points: int | None = None) -> np.ndarray | None:
        import struct as _struct
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
                x = _struct.unpack_from("<f", raw, base + x_off)[0]
                y = _struct.unpack_from("<f", raw, base + y_off)[0]
                z = _struct.unpack_from("<f", raw, base + z_off)[0]
                if math.isnan(x) or math.isnan(y) or math.isnan(z):
                    continue
                if math.isinf(x) or math.isinf(y) or math.isinf(z):
                    continue
                result.append([x, y, z])
            return np.array(result, dtype=np.float32) if result else None
        except Exception as exc:
            nav_logger.warning("点云消息解析失败：{}", exc)
            return None

    @staticmethod
    def _extract_cloud_xyz(msg: Any, max_points: int = 1500) -> list[list[float]]:
        import struct as _struct
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
                x = _struct.unpack_from("<f", raw, base + x_off)[0]
                y = _struct.unpack_from("<f", raw, base + y_off)[0]
                z = _struct.unpack_from("<f", raw, base + z_off)[0]
                if math.isnan(x) or math.isnan(y) or math.isnan(z):
                    continue
                if math.isinf(x) or math.isinf(y) or math.isinf(z):
                    continue
                result.append([round(x, 3), round(y, 3), round(z, 3)])
            return result
        except Exception as exc:
            nav_logger.warning("点云消息解析失败：{}", exc)
            return []

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
        if self._should_broadcast_global_path(path):
            self._submit_broadcast("nav.global_path", path)

    def _global_path_signature(self, path: dict[str, Any]) -> tuple[Any, ...]:
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

    def _should_broadcast_global_path(self, path: dict[str, Any]) -> bool:
        now = time.monotonic()
        signature = self._global_path_signature(path)
        last_signature = getattr(self, "_last_global_path_signature", None)
        last_broadcast_at = float(getattr(self, "_last_global_path_broadcast_at", 0.0))

        if signature == last_signature:
            return False

        if now - last_broadcast_at < GLOBAL_PATH_BROADCAST_MIN_INTERVAL_S:
            return False

        self._last_global_path_signature = signature
        self._last_global_path_broadcast_at = now
        return True

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
        self._release_navigation_control_on_terminal_status(nav_status)
        self._submit_broadcast("nav.navigation_status", updated_status)

    @staticmethod
    def _release_navigation_control_on_terminal_status(nav_status: dict[str, Any]) -> None:
        status = str(nav_status.get("status") or "").strip().lower()
        if status not in {"reached", "idle", "error", "estop"}:
            return
        try:
            from .nav_auto_track_coordinator import get_nav_auto_track_coordinator

            coordinator = get_nav_auto_track_coordinator()
            if coordinator is not None:
                coordinator.release_navigation_control()
        except Exception as exc:
            nav_logger.debug("释放导航控制权失败：{}", exc)

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

        interrupted_navigation = None
        if raw_status == "canceled":
            interrupted_navigation = self._auto_track_interrupted_navigation()
            if interrupted_navigation is not None:
                mapped_status = "paused"

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
        error_code = _to_optional_str(payload.get("error_code"))
        if interrupted_navigation is not None:
            message = "导航任务已暂停，正在自动跟踪陌生人"
            target_waypoint_id = interrupted_navigation.get("target_waypoint_id") or target_waypoint_id
            target_name = interrupted_navigation.get("target_name") or target_name
        if mapped_status == "error":
            diagnosis = self._diagnose_navigation_failure()
            if diagnosis is not None:
                message = str(diagnosis["message"])
                error_code = str(diagnosis["error_code"])

        timestamp_value = _to_optional_float(payload.get("timestamp"))
        timestamp = timestamp_value if timestamp_value is not None else time.time()

        payload_task_id = _to_optional_str(payload.get("task_id"))
        if payload_task_id is None and mapped_status in {"navigating", "paused"}:
            try:
                current_nav_status = get_nav_state().get("navigation_status") or {}
                current_task_id = _to_optional_str(current_nav_status.get("task_id"))
                current_status = str(current_nav_status.get("status") or "").strip().lower()
                if current_task_id and current_status in {"navigating", "paused"}:
                    payload_task_id = current_task_id
            except Exception:
                payload_task_id = None

        return {
            "status": mapped_status,
            "target_waypoint_id": target_waypoint_id,
            "target_name": target_name,
            "message": message,
            "timestamp": timestamp,
            "ros_status": raw_status or None,
            "task_id": (
                interrupted_navigation.get("task_id")
                if interrupted_navigation is not None
                else payload_task_id
            ),
            "waypoint_id": waypoint_id,
            "distance_to_goal": _to_optional_float(payload.get("distance_to_goal")),
            "error_code": error_code,
            "source": settings.ROS_NAV_STATUS_TOPIC,
        }

    @staticmethod
    def _auto_track_interrupted_navigation() -> dict[str, str | None] | None:
        try:
            from .nav_auto_track_coordinator import get_nav_auto_track_coordinator

            coordinator = get_nav_auto_track_coordinator()
            if coordinator is None:
                return None
            status = coordinator.get_status()
            task_id = status.get("interrupted_task_id")
            if not task_id:
                return None
            return {
                "task_id": str(task_id),
                "target_waypoint_id": status.get("interrupted_target_waypoint_id"),
                "target_name": status.get("interrupted_target_name"),
            }
        except Exception:
            return None

    def _diagnose_navigation_failure(self) -> dict[str, Any] | None:
        try:
            from .services_nav_localization import diagnose_recent_navigation_failure

            return diagnose_recent_navigation_failure()
        except Exception as exc:
            nav_logger.warning("导航失败诊断失败：{}", exc)
            return None

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

    def _tf_source_for(self, source_frame: str) -> str:
        return f"tf:{settings.ROS_NAV_FRAME_ID}->{source_frame}"

    def _base_frame_candidates(self) -> list[str]:
        configured = [
            item.strip()
            for item in str(settings.ROS_NAV_BASE_FRAME_ID).split(",")
            if item.strip()
        ]
        candidates: list[str] = []
        for frame in [*configured, "base_footprint", "base_link"]:
            if frame and frame not in candidates:
                candidates.append(frame)
        return candidates

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
        if now - self._last_tf_lookup_at < min_interval:
            return
        self._last_tf_lookup_at = now

        try:
            pose = self._lookup_tf_pose()
        except Exception as exc:
            clear_robot_pose()
            message = (
                f"TF 暂未就绪：target={settings.ROS_NAV_FRAME_ID}，"
                f"source={','.join(self._base_frame_candidates())}，原因={exc}"
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
                    ",".join(self._base_frame_candidates()),
                    exc,
                )
            elif now - self._last_tf_warning_at >= 30.0:
                self._last_tf_warning_at = now
                waited = int(now - self._tf_wait_started_at)
                tf_logger.warning(
                    "TF 仍未就绪：target={}，source={}，已等待={}s",
                    settings.ROS_NAV_FRAME_ID,
                    ",".join(self._base_frame_candidates()),
                    waited,
                )
            return

        if not self._tf_available and self._tf_wait_started_at > 0.0:
            tf_logger.info(
                "TF 已恢复：target={}，source={}",
                settings.ROS_NAV_FRAME_ID,
                pose["source_frame"],
            )
        self._tf_available = True
        self._tf_wait_started_at = 0.0
        self._last_tf_warning_at = 0.0

        update_robot_pose(pose)
        update_localization_status(
            {
                "status": "ok",
                "frame_id": settings.ROS_NAV_FRAME_ID,
                "source": self._tf_source_for(pose["source_frame"]),
                "message": "TF 定位正常",
                "timestamp": pose["timestamp"],
            }
        )

    def _lookup_tf_pose(self) -> dict[str, Any]:
        if self._tf_buffer is None or self._rclpy is None:
            raise RuntimeError("TF buffer 未初始化")

        from rclpy.time import Time

        errors: list[str] = []
        transform_stamped = None
        source_frame = ""
        for candidate in self._base_frame_candidates():
            try:
                transform_stamped = self._tf_buffer.lookup_transform(
                    settings.ROS_NAV_FRAME_ID,
                    candidate,
                    Time(),
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
            "frame_id": settings.ROS_NAV_FRAME_ID,
            "source": self._tf_source_for(source_frame),
            "source_frame": source_frame,
            "timestamp": received_at,
            "ros_timestamp": _stamp_to_seconds(header.stamp),
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
            "timestamp": time.time(),
            "ros_timestamp": _header_timestamp(msg),
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

        if event_type == "nav.mapping_cloud":
            previous = getattr(self, "_mapping_cloud_broadcast_future", None)
            if previous is not None and not previous.done():
                return

        broadcaster = self._broadcaster_for_event(event_type)
        future = asyncio.run_coroutine_threadsafe(
            broadcaster.broadcast_event(event_type, data),
            self._loop,
        )
        if event_type == "nav.mapping_cloud":
            self._mapping_cloud_broadcast_future = future
        future.add_done_callback(self._log_broadcast_error)

    def _broadcaster_for_event(self, event_type: str) -> EventBroadcaster:
        if event_type == "nav.mapping_cloud":
            return self._mapping_cloud_broadcaster
        return self._broadcaster

    @staticmethod
    def _log_broadcast_error(future: asyncio.Future[Any]) -> None:
        try:
            future.result()
        except Exception as exc:
            nav_logger.warning("导航 WebSocket 广播失败：{}", exc)
