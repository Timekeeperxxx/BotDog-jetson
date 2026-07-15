from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any

from .config import settings
from .logging_config import get_logger
from .ros_nav_cloud_bridge import RosNavCloudBridgeMixin
from .ros_nav_messages import (
    extract_global_path,
    extract_pose,
    global_path_signature,
    header_frame_id,
    normalize_nav_status,
    resolve_pose_msg_type,
)
from .ros_nav_publishers import (
    backend_initial_pose_publisher_count,
    initial_pose_subscription_counts,
    publish_bool_message,
    publish_goal_xyz_yaw as publish_goal_xyz_yaw_message,
    publish_initial_pose_messages,
    publish_zero_cmd_vel as publish_zero_cmd_vel_message,
    wait_for_initial_pose_subscribers as wait_for_initial_pose_subscriber_ready,
)
from .ros_nav_tf import (
    base_frame_candidates,
    lookup_tf_pose,
    tf_source,
    use_tf_pose,
)
from .ros_nav_lifecycle import RosNavLifecycleMixin
from .services_nav_state import (
    clear_execution_path,
    clear_robot_pose,
    update_execution_path,
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
EXECUTION_PATH_BROADCAST_MIN_INTERVAL_S = 0.15
INITIAL_POSE_PUBLISH_COUNT = 20
INITIAL_POSE_PUBLISH_INTERVAL_S = 0.2
INITIAL_POSE_SUBSCRIBER_WAIT_S = 5.0
GOAL_PUBLISH_COUNT = 3
GOAL_PUBLISH_INTERVAL_S = 0.15
# A go-to request deliberately publishes nav_start=false before the new goal.
# The cancellation acknowledgement for that old run can arrive after the new
# nav_start=true and must not release the freshly acquired NAVIGATION owner.
NAV_START_IDLE_RELEASE_GRACE_S = 2.0


class RosNavBridge(RosNavCloudBridgeMixin, RosNavLifecycleMixin):
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
        self._nav_task_start_publisher: Any | None = None
        self._cmd_vel_publisher: Any | None = None
        self._goal_xyz_publisher: Any | None = None
        self._goal_yaw_publisher: Any | None = None
        self._global_path_subscription: Any | None = None
        self._execution_path_subscription: Any | None = None
        self._nav_status_subscription: Any | None = None
        self._estop_publisher: Any | None = None
        self._initial_pose_publisher: Any | None = None
        self._publisher_lock = threading.RLock()
        self._last_broadcast_at = 0.0
        self._last_tf_lookup_at = 0.0
        self._last_localization_broadcast_at = 0.0
        self._last_global_path_broadcast_at = 0.0
        self._last_global_path_signature: tuple[Any, ...] | None = None
        self._last_execution_path_broadcast_at = 0.0
        self._last_execution_path_signature: tuple[Any, ...] | None = None
        self._navigation_idle_release_blocked_until = 0.0
        # /nav_status reports every reached waypoint.  During a multi-waypoint
        # task those are progress events, not terminal navigation events.
        self._navigation_task_active = False
        self._init_mapping_cloud_state()
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
            self._setup_execution_path_subscription(Path)
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
            from rclpy.signals import SignalHandlerOptions

            # Uvicorn/systemd owns process signals. Installing rclpy's global
            # handlers here would consume SIGTERM and prevent FastAPI shutdown.
            rclpy.init(args=None, signal_handler_options=SignalHandlerOptions.NO)
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
            if self._stop_event.is_set():
                nav_logger.info("ROS2 导航线程收到关闭通知")
            else:
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
                rclpy.try_shutdown()
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
        self._nav_task_start_publisher = self._node.create_publisher(
            Bool,
            settings.ROS_NAV_TASK_START_TOPIC,
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
            "ROS2 导航发布器已启动：nav_start_topic={}，nav_task_start_topic={}，clicked_point_topic={}，goal_yaw_topic={}，stop_topic={}，initial_pose_topic={}，status_topic={}，global_path_topic={}",
            settings.ROS_NAV_START_TOPIC,
            settings.ROS_NAV_TASK_START_TOPIC,
            settings.ROS_NAV_GOAL_XYZ_TOPIC,
            settings.ROS_NAV_GOAL_YAW_TOPIC,
            settings.ROS_NAV_STOP_TOPIC,
            settings.ROS_NAV_INITIAL_POSE_TOPIC,
            settings.ROS_NAV_STATUS_TOPIC,
            settings.ROS_NAV_GLOBAL_PATH_TOPIC,
        )

    def publish_navigation_start(self, enabled: bool = True) -> dict[str, Any]:
        result = publish_bool_message(
            node=self._node,
            publisher=self._nav_start_publisher,
            lock=self._publisher_lock,
            topic=settings.ROS_NAV_START_TOPIC,
            value=enabled,
            not_ready_message="ROS2 nav_start 发布器未就绪",
        )
        # Protect both sides of the false -> goal -> true hand-off.  The old
        # run can acknowledge `canceled` while publish_goal_xyz_yaw is still
        # publishing the new goal, i.e. before nav_start=true is sent.
        # Explicit stop/E-stop routes release their owner directly.
        self._navigation_idle_release_blocked_until = (
            time.monotonic() + NAV_START_IDLE_RELEASE_GRACE_S
        )
        return result

    def publish_navigation_task_start(self, enabled: bool = True) -> dict[str, Any]:
        previous_task_active = bool(
            getattr(self, "_navigation_task_active", False)
        )
        # An explicit stop is authoritative even when the ROS task navigator
        # has already exited and therefore cannot receive the false message.
        if not enabled:
            self._navigation_task_active = False

        if self._node is None or self._nav_task_start_publisher is None:
            raise RuntimeError("ROS2 nav_task_start 发布器未就绪")

        get_subscription_count = getattr(
            self._nav_task_start_publisher,
            "get_subscription_count",
            None,
        )
        subscriber_count = 1
        if callable(get_subscription_count):
            deadline = time.monotonic() + 2.0
            subscriber_count = int(get_subscription_count())
            while subscriber_count <= 0 and time.monotonic() < deadline:
                time.sleep(0.1)
                subscriber_count = int(get_subscription_count())
            if subscriber_count <= 0:
                raise RuntimeError(
                    "任务导航器未就绪：/nav_task_start 没有订阅者，请重启导航定位"
                )

        # Set the guard before publishing.  A one-point task can report its
        # first waypoint very quickly on the ROS executor thread.
        if enabled:
            self._navigation_task_active = True
        try:
            result = publish_bool_message(
                node=self._node,
                publisher=self._nav_task_start_publisher,
                lock=self._publisher_lock,
                topic=settings.ROS_NAV_TASK_START_TOPIC,
                value=enabled,
                not_ready_message="ROS2 nav_task_start 发布器未就绪",
            )
        except Exception:
            if enabled:
                self._navigation_task_active = previous_task_active
            raise
        result["publish_count"] = 1
        result["subscriber_count"] = subscriber_count
        return result

    def publish_zero_cmd_vel(self, publish_count: int = 10, interval_s: float = 0.03) -> dict[str, Any]:
        return publish_zero_cmd_vel_message(
            node=self._node,
            publisher=self._cmd_vel_publisher,
            lock=self._publisher_lock,
            publish_count=publish_count,
            interval_s=interval_s,
        )

    def publish_goal_xyz_yaw(self, waypoint: dict[str, Any]) -> dict[str, Any]:
        return publish_goal_xyz_yaw_message(
            node=self._node,
            xyz_publisher=self._goal_xyz_publisher,
            yaw_publisher=self._goal_yaw_publisher,
            lock=self._publisher_lock,
            waypoint=waypoint,
            frame_id=settings.ROS_NAV_FRAME_ID,
            xyz_topic=settings.ROS_NAV_GOAL_XYZ_TOPIC,
            yaw_topic=settings.ROS_NAV_GOAL_YAW_TOPIC,
            publish_count=GOAL_PUBLISH_COUNT,
            publish_interval_s=GOAL_PUBLISH_INTERVAL_S,
            planner_goal_z=planner_goal_z,
            planner_goal_z_offset_m=float(settings.ROS_NAV_GOAL_Z_SEARCH_OFFSET_M),
        )

    def publish_emergency_stop(self) -> dict[str, Any]:
        result = publish_bool_message(
            node=self._node,
            publisher=self._estop_publisher,
            lock=self._publisher_lock,
            topic=settings.ROS_NAV_STOP_TOPIC,
            value=True,
            not_ready_message="ROS2 急停发布器未就绪",
        )
        result.pop("data", None)
        return result

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

        frame = frame_id or settings.ROS_NAV_FRAME_ID
        publish_count = publish_initial_pose_messages(
            node=self._node,
            publisher=self._initial_pose_publisher,
            lock=self._publisher_lock,
            pose_msg_cls=PoseWithCovarianceStamped,
            x=x,
            y=y,
            z=z,
            roll=roll,
            pitch=pitch,
            yaw=yaw,
            frame_id=frame,
            publish_count=INITIAL_POSE_PUBLISH_COUNT,
            publish_interval_s=INITIAL_POSE_PUBLISH_INTERVAL_S,
        )

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
        return initial_pose_subscription_counts(
            self._node,
            self._initial_pose_publisher,
            settings.ROS_NAV_INITIAL_POSE_TOPIC,
        )

    def get_initial_pose_subscription_count(self) -> int:
        return self.get_initial_pose_subscription_counts()["subscriber_count"]

    def get_backend_initial_pose_publisher_count(self) -> int:
        return backend_initial_pose_publisher_count(
            self._node,
            self._initial_pose_publisher,
            settings.ROS_NAV_INITIAL_POSE_TOPIC,
        )

    def wait_for_initial_pose_subscribers(self, timeout_s: float = INITIAL_POSE_SUBSCRIBER_WAIT_S) -> dict[str, Any]:
        return wait_for_initial_pose_subscriber_ready(
            topic=settings.ROS_NAV_INITIAL_POSE_TOPIC,
            timeout_s=timeout_s,
            subscription_counts=self.get_initial_pose_subscription_counts,
            backend_publisher_count=self.get_backend_initial_pose_publisher_count,
        )

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

    def _setup_execution_path_subscription(self, path_cls: Any) -> None:
        if self._node is None:
            return

        self._execution_path_subscription = self._node.create_subscription(
            path_cls,
            settings.ROS_NAV_EXECUTION_PATH_TOPIC,
            self._handle_execution_path_message,
            10,
        )
        nav_logger.info(
            "ROS2 SCAN execution_path 订阅已启动：topic={}",
            settings.ROS_NAV_EXECUTION_PATH_TOPIC,
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

        clear_execution_path()
        self._last_execution_path_signature = None
        self._last_execution_path_broadcast_at = 0.0
        self._submit_broadcast(
            "nav.execution_path",
            {
                "frame_id": path.get("frame_id", settings.ROS_NAV_FRAME_ID),
                "timestamp": time.time(),
                "points": [],
            },
        )
        update_global_path(path)
        if self._should_broadcast_global_path(path):
            self._submit_broadcast("nav.global_path", path)

    def _handle_execution_path_message(self, msg: Any) -> None:
        try:
            path = self._extract_global_path(msg)
        except Exception as exc:
            nav_logger.warning("SCAN execution_path 消息解析失败：{}", exc)
            return

        update_execution_path(path)
        if self._should_broadcast_execution_path(path):
            self._submit_broadcast("nav.execution_path", path)

    def _should_broadcast_global_path(self, path: dict[str, Any]) -> bool:
        now = time.monotonic()
        signature = global_path_signature(path)
        last_signature = getattr(self, "_last_global_path_signature", None)
        last_broadcast_at = float(getattr(self, "_last_global_path_broadcast_at", 0.0))

        if signature == last_signature:
            return False

        if now - last_broadcast_at < GLOBAL_PATH_BROADCAST_MIN_INTERVAL_S:
            return False

        self._last_global_path_signature = signature
        self._last_global_path_broadcast_at = now
        return True

    def _should_broadcast_execution_path(self, path: dict[str, Any]) -> bool:
        now = time.monotonic()
        signature = global_path_signature(path)
        last_signature = getattr(self, "_last_execution_path_signature", None)
        last_broadcast_at = float(
            getattr(self, "_last_execution_path_broadcast_at", 0.0)
        )

        if signature == last_signature:
            return False

        if now - last_broadcast_at < EXECUTION_PATH_BROADCAST_MIN_INTERVAL_S:
            return False

        self._last_execution_path_signature = signature
        self._last_execution_path_broadcast_at = now
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
        task_complete = bool(payload.get("task_complete", False))
        task_active = bool(getattr(self, "_navigation_task_active", False))
        status = str(nav_status.get("status") or "").strip().lower()

        if task_active and not task_complete and status in {"reached", "idle", "error"}:
            current_status = get_nav_state().get("navigation_status") or {}
            nav_status["status"] = "navigating"
            nav_status["task_id"] = nav_status.get("task_id") or current_status.get("task_id")
            if status == "reached":
                nav_status["message"] = "当前航点已到达，正在切换任务中的下一个航点"
            elif status == "error":
                nav_status["message"] = "当前航点执行失败，任务导航器正在重试"
            else:
                nav_status["message"] = "任务航点切换中"

        updated_status = update_navigation_status(nav_status)
        self._release_navigation_control_on_terminal_status(
            nav_status,
            task_complete=task_complete,
        )
        self._submit_broadcast("nav.navigation_status", updated_status)

    def _release_navigation_control_on_terminal_status(
        self,
        nav_status: dict[str, Any],
        *,
        task_complete: bool = False,
    ) -> None:
        status = str(nav_status.get("status") or "").strip().lower()
        if status not in {"reached", "idle", "error", "estop"}:
            return
        if (
            bool(getattr(self, "_navigation_task_active", False))
            and not task_complete
            and status != "estop"
        ):
            nav_logger.info(
                "忽略任务中间航点的终态回执，保留 NAVIGATION 控制权：status={}",
                status,
            )
            return
        if (
            status == "idle"
            and time.monotonic()
            < float(getattr(self, "_navigation_idle_release_blocked_until", 0.0))
        ):
            nav_logger.info(
                "忽略新导航启动窗口内的旧任务 idle 回执，保留 NAVIGATION 控制权"
            )
            return
        if task_complete or status == "estop":
            self._navigation_task_active = False
        try:
            from .nav_auto_track_coordinator import get_nav_auto_track_coordinator

            coordinator = get_nav_auto_track_coordinator()
            if coordinator is not None:
                coordinator.release_navigation_control()
        except Exception as exc:
            nav_logger.debug("释放导航控制权失败：{}", exc)

    def _normalize_nav_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        def current_navigation_status() -> dict[str, Any]:
            try:
                return get_nav_state().get("navigation_status") or {}
            except Exception:
                return {}

        return normalize_nav_status(
            payload,
            status_topic=settings.ROS_NAV_STATUS_TOPIC,
            current_navigation_status=current_navigation_status,
            diagnose_navigation_failure=self._diagnose_navigation_failure,
            interrupted_navigation=self._auto_track_interrupted_navigation,
            warn_unknown_status=lambda raw_status: nav_logger.warning("收到未知 nav_status：{}", raw_status),
        )

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
        return extract_global_path(msg, settings.ROS_NAV_FRAME_ID)

    def _use_tf_pose(self) -> bool:
        return use_tf_pose(settings.ROS_NAV_POSE_TYPE)

    def _tf_source(self) -> str:
        return tf_source(settings.ROS_NAV_FRAME_ID, settings.ROS_NAV_BASE_FRAME_ID)

    def _tf_source_for(self, source_frame: str) -> str:
        return tf_source(settings.ROS_NAV_FRAME_ID, source_frame)

    def _base_frame_candidates(self) -> list[str]:
        return base_frame_candidates(settings.ROS_NAV_BASE_FRAME_ID)

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
        from rclpy.time import Time

        pose = lookup_tf_pose(
            tf_buffer=self._tf_buffer,
            rclpy_time_cls=Time,
            target_frame=settings.ROS_NAV_FRAME_ID,
            source_frames=self._base_frame_candidates(),
        )
        ros_timestamp = float(pose.get("ros_timestamp") or 0.0)
        max_age_seconds = max(float(settings.ROS_NAV_TF_MAX_AGE_SECONDS), 0.0)
        tf_age = time.time() - ros_timestamp
        if ros_timestamp <= 0.0 or tf_age > max_age_seconds:
            raise RuntimeError(
                f"TF 时间戳已过期：age={tf_age:.3f}s，limit={max_age_seconds:.3f}s"
            )
        return pose

    def _resolve_msg_type(
        self,
        pose_type: str,
        pose_with_covariance_cls: Any,
        pose_stamped_cls: Any,
        odometry_cls: Any,
    ) -> Any:
        return resolve_pose_msg_type(
            pose_type,
            pose_with_covariance_cls,
            pose_stamped_cls,
            odometry_cls,
            use_tf_pose=self._use_tf_pose(),
        )

    def _handle_pose_message(self, msg: Any) -> None:
        try:
            pose = self._extract_pose(msg)
        except Exception as exc:
            update_localization_status(
                {
                    "status": "error",
                    "frame_id": header_frame_id(msg, settings.ROS_NAV_FRAME_ID),
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
        return extract_pose(
            msg,
            pose_type=settings.ROS_NAV_POSE_TYPE,
            pose_topic=settings.ROS_NAV_POSE_TOPIC,
            default_frame_id=settings.ROS_NAV_FRAME_ID,
        )

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
            return getattr(self, "_mapping_cloud_broadcaster", None) or self._broadcaster
        return self._broadcaster

    @staticmethod
    def _log_broadcast_error(future: asyncio.Future[Any]) -> None:
        try:
            future.result()
        except Exception as exc:
            nav_logger.warning("导航 WebSocket 广播失败：{}", exc)
