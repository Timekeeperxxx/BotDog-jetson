from __future__ import annotations

import asyncio
import json
import math
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
    clear_global_path,
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
GOAL_PUBLISH_INTERVAL_S = 0.15
GOAL_SUBSCRIBER_WAIT_S = 2.0
GOAL_SUBSCRIBER_POLL_INTERVAL_S = 0.05
# `/clicked_point` is a reliable event and every received event starts a new
# global plan. Publishing one goal three times queues three expensive plans and
# makes a later goal wait behind stale work, so single-point go-to publishes
# exactly once.
GOAL_PUBLISH_COUNT = 1
# Terminal acknowledgements from the replaced run (including a latched SCAN
# planner failure) can arrive after the new goal and must not release the
# freshly acquired NAVIGATION owner.
NAV_START_TERMINAL_RELEASE_GRACE_S = 2.0


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
        self._planning_status_subscription: Any | None = None
        self._auto_track_control_subscription: Any | None = None
        self._obstacle_status_subscription: Any | None = None
        # global_planner assigns a monotonically increasing generation to each
        # accepted goal.  Keep that identity alongside the UI state so a late
        # terminal result from a replaced goal cannot overwrite the new one.
        self._latest_planning_generation: int | None = None
        self._latest_planning_status: str | None = None
        self._planning_status_seen = False
        self._planning_status_accept_generation_reset = True
        self._planning_status_awaiting_new_generation = False
        self._planning_generation_floor: int | None = None
        self._planning_status_publisher_gid: bytes | None = None
        self._retired_planning_status_publisher_gids: set[bytes] = set()
        # /nav/obstacle_status 持续阻断跟踪：阻断状态首次出现的时间与是否已告警。
        self._obstacle_blocked_since: float | None = None
        self._obstacle_alert_sent = False
        # 自动重发目标：SCAN 连续重规划失败计满上限后会丢弃目标进入
        # WAIT_TARGET，此后它直接丢弃 replan_request，链路纯事件驱动，
        # 只有一个新 goal 能唤醒（goal -> 全局路径 -> /initial_path）。
        self._last_goal_waypoint: dict[str, Any] | None = None
        self._regoal_attempts = 0
        self._last_regoal_at = 0.0
        self._estop_publisher: Any | None = None
        self._initial_pose_publisher: Any | None = None
        self._publisher_lock = threading.RLock()
        # Serialize every single-goal submission from generation hand-off
        # through publication and state replacement.  In particular, an
        # automatic re-goal must never publish a stale waypoint after a newer
        # web goal has already been accepted.
        self._goal_submission_lock = threading.RLock()
        self._last_broadcast_at = 0.0
        self._last_tf_lookup_at = 0.0
        self._last_localization_broadcast_at = 0.0
        self._last_global_path_broadcast_at = 0.0
        self._last_global_path_signature: tuple[Any, ...] | None = None
        self._last_execution_path_broadcast_at = 0.0
        self._last_execution_path_signature: tuple[Any, ...] | None = None
        self._navigation_terminal_release_blocked_until = 0.0
        # True only while BotDog expects ROS navigation to own the base.  This
        # lets a later healthy `moving` heartbeat repair an owner that was
        # dropped by a racing terminal acknowledgement, without stealing the
        # base after an explicit stop or E-stop.
        self._navigation_control_expected = False
        # /nav_status reports every reached waypoint.  During a multi-waypoint
        # task those are progress events, not terminal navigation events.
        self._navigation_task_active = False
        self._navigation_status_before_blocked: str | None = None
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
            self._setup_planning_status_subscription()
            self._setup_obstacle_status_subscription()
            self._setup_auto_track_control_subscription()
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
            "ROS2 导航发布器已启动：nav_start_topic={}，nav_task_start_topic={}，clicked_point_topic={}，goal_yaw_topic={}，stop_topic={}，initial_pose_topic={}，status_topic={}，planning_status_topic={}，global_path_topic={}",
            settings.ROS_NAV_START_TOPIC,
            settings.ROS_NAV_TASK_START_TOPIC,
            settings.ROS_NAV_GOAL_XYZ_TOPIC,
            settings.ROS_NAV_GOAL_YAW_TOPIC,
            settings.ROS_NAV_STOP_TOPIC,
            settings.ROS_NAV_INITIAL_POSE_TOPIC,
            settings.ROS_NAV_STATUS_TOPIC,
            settings.ROS_NAV_PLANNING_STATUS_TOPIC,
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
        # Task navigation still uses /nav_start. Single-point go-to updates the
        # same ownership guard directly when it publishes its replacement goal.
        # Explicit stop/E-stop routes release their owner directly.
        self._navigation_control_expected = bool(enabled)
        self._navigation_terminal_release_blocked_until = (
            time.monotonic() + NAV_START_TERMINAL_RELEASE_GRACE_S
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
        # Stopping an old task is best-effort and must not delay a replacement
        # single-point goal for two seconds merely because the task navigator
        # is absent. Starting a task still requires a matched subscriber.
        if enabled and callable(get_subscription_count):
            deadline = time.monotonic() + 2.0
            subscriber_count = int(get_subscription_count())
            while subscriber_count <= 0 and time.monotonic() < deadline:
                time.sleep(0.1)
                subscriber_count = int(get_subscription_count())
            if subscriber_count <= 0:
                raise RuntimeError(
                    "任务导航器未就绪：/nav_task_start 没有订阅者，请重启导航定位"
                )
        elif callable(get_subscription_count):
            subscriber_count = int(get_subscription_count())

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
        with self._goal_submission_lock:
            planning_state = self._begin_planning_goal_submission()
            try:
                result = self._publish_goal_xyz_yaw_inner(waypoint)
            except Exception:
                self._rollback_planning_goal_submission(planning_state)
                raise
            if not result.get("success"):
                self._rollback_planning_goal_submission(planning_state)
            if result.get("success"):
                # A goal event itself starts/replaces single-point navigation.
                # `/nav_start` is reserved for inspection-task execution.
                self._last_goal_waypoint = dict(waypoint)
                self._regoal_attempts = 0
                self._last_regoal_at = 0.0
                self._obstacle_blocked_since = None
                self._obstacle_alert_sent = False
                self._navigation_control_expected = True
                self._navigation_terminal_release_blocked_until = (
                    time.monotonic() + NAV_START_TERMINAL_RELEASE_GRACE_S
                )
                self._navigation_status_before_blocked = None
                self._replace_paths_and_status_for_new_goal(waypoint, result)
            return result

    def _begin_planning_goal_submission(self) -> tuple[Any, ...]:
        """Install a generation barrier before publishing a replacement goal."""

        snapshot = (
            getattr(self, "_latest_planning_generation", None),
            getattr(self, "_latest_planning_status", None),
            bool(getattr(self, "_planning_status_seen", False)),
            bool(
                getattr(
                    self,
                    "_planning_status_accept_generation_reset",
                    False,
                )
            ),
            bool(
                getattr(
                    self,
                    "_planning_status_awaiting_new_generation",
                    False,
                )
            ),
            getattr(self, "_planning_generation_floor", None),
        )
        self._planning_status_awaiting_new_generation = True
        self._planning_generation_floor = getattr(
            self,
            "_latest_planning_generation",
            None,
        )
        # A local replacement handshake is stricter than accepting a latched
        # state after node recreation: an old failed/path_ready must wait for
        # the new generation's queued/planning acknowledgement.
        self._planning_status_accept_generation_reset = False
        return snapshot

    def _rollback_planning_goal_submission(
        self,
        snapshot: tuple[Any, ...],
    ) -> None:
        # If a new generation was already acknowledged during publish(), keep
        # it.  Otherwise restore the previous generation tracking atomically
        # enough for the Python ROS executor/API thread hand-off.
        if not bool(
            getattr(self, "_planning_status_awaiting_new_generation", False)
        ):
            return
        (
            self._latest_planning_generation,
            self._latest_planning_status,
            self._planning_status_seen,
            self._planning_status_accept_generation_reset,
            self._planning_status_awaiting_new_generation,
            self._planning_generation_floor,
        ) = snapshot

    def _replace_paths_and_status_for_new_goal(
        self,
        waypoint: dict[str, Any],
        goal_result: dict[str, Any],
    ) -> None:
        """Atomically expose the newest single goal to reconnecting/web clients."""

        clear_global_path()
        self._last_global_path_signature = None
        self._last_global_path_broadcast_at = 0.0
        self._last_execution_path_signature = None
        self._last_execution_path_broadcast_at = 0.0

        now = time.time()
        empty_path = {
            "frame_id": str(goal_result.get("frame_id") or settings.ROS_NAV_FRAME_ID),
            "timestamp": now,
            "points": [],
        }
        self._submit_broadcast("nav.global_path", empty_path)
        self._submit_broadcast("nav.execution_path", empty_path)
        self._update_live_navigation_status(
            {
                "status": "planning",
                "target_waypoint_id": waypoint.get("id"),
                "target_name": waypoint.get("name"),
                "message": (
                    "新目标已替换旧目标，正在生成全局路径："
                    f"x={float(goal_result['x']):.3f}, "
                    f"y={float(goal_result['y']):.3f}, "
                    f"z={float(goal_result['z']):.3f}"
                ),
                "ros_status": None,
                "task_id": None,
                "waypoint_id": waypoint.get("id"),
                "distance_to_goal": None,
                "error_code": None,
                "source": settings.ROS_NAV_GOAL_XYZ_TOPIC,
                "planning_status": (
                    getattr(self, "_latest_planning_status", None)
                    if not bool(
                        getattr(
                            self,
                            "_planning_status_awaiting_new_generation",
                            False,
                        )
                    )
                    else "submitted"
                ),
                "planning_generation": (
                    getattr(self, "_latest_planning_generation", None)
                    if not bool(
                        getattr(
                            self,
                            "_planning_status_awaiting_new_generation",
                            False,
                        )
                    )
                    else None
                ),
                "planning_elapsed_seconds": 0.0,
            }
        )

    def _update_live_navigation_status(
        self,
        status: dict[str, Any],
    ) -> dict[str, Any]:
        updated_status = update_navigation_status(status)
        self._submit_broadcast("nav.navigation_status", updated_status)
        return updated_status

    def _publish_goal_xyz_yaw_inner(self, waypoint: dict[str, Any]) -> dict[str, Any]:
        node = self._node
        xyz_publisher = self._goal_xyz_publisher
        yaw_publisher = self._goal_yaw_publisher
        self._wait_for_goal_subscribers(
            xyz_publisher=xyz_publisher,
            yaw_publisher=yaw_publisher,
        )
        with self._publisher_lock:
            if (
                self._node is not node
                or self._goal_xyz_publisher is not xyz_publisher
                or self._goal_yaw_publisher is not yaw_publisher
            ):
                raise RuntimeError("ROS2 单点导航发布器已重建，请重新提交目标")
            return publish_goal_xyz_yaw_message(
                node=node,
                xyz_publisher=xyz_publisher,
                yaw_publisher=yaw_publisher,
                lock=self._publisher_lock,
                waypoint=waypoint,
                frame_id=settings.ROS_NAV_FRAME_ID,
                xyz_topic=settings.ROS_NAV_GOAL_XYZ_TOPIC,
                yaw_topic=settings.ROS_NAV_GOAL_YAW_TOPIC,
                publish_count=GOAL_PUBLISH_COUNT,
                publish_interval_s=GOAL_PUBLISH_INTERVAL_S,
                planner_goal_z=planner_goal_z,
                planner_goal_z_offset_m=float(
                    settings.ROS_NAV_GOAL_Z_SEARCH_OFFSET_M
                ),
            )

    def _wait_for_goal_subscribers(
        self,
        *,
        xyz_publisher: Any,
        yaw_publisher: Any,
        timeout_s: float = GOAL_SUBSCRIBER_WAIT_S,
        poll_interval_s: float = GOAL_SUBSCRIBER_POLL_INTERVAL_S,
    ) -> dict[str, int]:
        """Wait briefly for both volatile goal channels to have a DDS match."""

        if self._node is None or xyz_publisher is None or yaw_publisher is None:
            raise RuntimeError("ROS2 单点导航发布器未就绪")

        xyz_count_getter = getattr(
            xyz_publisher,
            "get_subscription_count",
            None,
        )
        yaw_count_getter = getattr(
            yaw_publisher,
            "get_subscription_count",
            None,
        )
        if not callable(xyz_count_getter) or not callable(yaw_count_getter):
            raise RuntimeError("ROS2 单点导航发布器不支持订阅者状态检查")

        deadline = time.monotonic() + max(0.0, float(timeout_s))
        interval = max(0.01, float(poll_interval_s))
        xyz_count = 0
        yaw_count = 0
        while True:
            try:
                xyz_count = int(xyz_count_getter())
                yaw_count = int(yaw_count_getter())
            except Exception as exc:
                raise RuntimeError(
                    "读取 ROS2 单点导航订阅者状态失败"
                ) from exc

            if xyz_count > 0 and yaw_count > 0:
                return {
                    "xyz_subscriber_count": xyz_count,
                    "yaw_subscriber_count": yaw_count,
                }
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "导航目标接收端未就绪："
                    f"{settings.ROS_NAV_GOAL_XYZ_TOPIC} 订阅者={xyz_count}，"
                    f"{settings.ROS_NAV_GOAL_YAW_TOPIC} 订阅者={yaw_count}"
                )
            time.sleep(interval)

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

    def _setup_planning_status_subscription(self) -> None:
        if self._node is None:
            return

        try:
            from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
            from std_msgs.msg import String
        except Exception as exc:
            raise RuntimeError(f"planning_status 消息类型不可用: {exc}") from exc

        planning_status_qos = QoSProfile(
            depth=10,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        # A recreated BotDog subscription can receive a latched status from a
        # planner process whose generation restarted at zero.
        self._planning_status_accept_generation_reset = True
        self._planning_status_subscription = self._node.create_subscription(
            String,
            settings.ROS_NAV_PLANNING_STATUS_TOPIC,
            self._handle_planning_status_message,
            planning_status_qos,
        )
        nav_logger.info(
            "ROS2 planning_status 订阅已启动：topic={}",
            settings.ROS_NAV_PLANNING_STATUS_TOPIC,
        )

    def _setup_obstacle_status_subscription(self) -> None:
        if self._node is None:
            return

        try:
            from std_msgs.msg import String
        except Exception as exc:
            raise RuntimeError(f"obstacle_status 消息类型不可用: {exc}") from exc

        self._obstacle_status_subscription = self._node.create_subscription(
            String,
            settings.ROS_NAV_OBSTACLE_STATUS_TOPIC,
            self._handle_obstacle_status_message,
            10,
        )
        nav_logger.info(
            "ROS2 obstacle_status 订阅已启动：topic={}",
            settings.ROS_NAV_OBSTACLE_STATUS_TOPIC,
        )

    # 动态避障监控器把持续阻断上报为 replan_requested，但该请求只会触发
    # SCAN 的局部重规划；走廊被彻底堵死时机器人会原地无限等待。这里作为
    # 应用层兜底：阻断持续超过阈值就向前端推送 ALERT_RAISED 告警。
    _OBSTACLE_STUCK_STATUSES = frozenset(
        {"blocked", "replan_requested", "waiting_replan", "clearing", "sensor_lost"}
    )

    def _handle_obstacle_status_message(self, msg: Any) -> None:
        raw_data = str(getattr(msg, "data", "") or "").strip()
        if not raw_data:
            return

        try:
            payload = json.loads(raw_data)
        except Exception as exc:
            nav_logger.warning("obstacle_status JSON 解析失败：{}", exc)
            return
        if not isinstance(payload, dict):
            return

        status = str(payload.get("status") or "").strip().lower()
        now = time.time()
        status_updater = getattr(
            self,
            "_update_navigation_status_from_obstacle",
            None,
        )
        if callable(status_updater):
            status_updater(status, payload)

        if status not in self._OBSTACLE_STUCK_STATUSES:
            if self._obstacle_alert_sent:
                blocked_seconds = round(
                    now - (self._obstacle_blocked_since or now), 1
                )
                self._submit_alert(
                    event_type="NAVIGATION",
                    event_code="NAV_BLOCK_CLEARED",
                    severity="info",
                    message=f"导航阻断已解除（持续 {blocked_seconds} 秒），恢复执行",
                )
                nav_logger.info(
                    "导航阻断已解除：status={}，持续 {} 秒", status, blocked_seconds
                )
            self._obstacle_blocked_since = None
            self._obstacle_alert_sent = False
            self._regoal_attempts = 0
            return

        if self._obstacle_blocked_since is None:
            self._obstacle_blocked_since = now
        blocked_duration = now - self._obstacle_blocked_since

        if (
            not self._obstacle_alert_sent
            and blocked_duration >= settings.NAV_OBSTACLE_ALERT_SECONDS
        ):
            self._obstacle_alert_sent = True
            if status == "sensor_lost":
                event_code = "NAV_SENSOR_LOST"
                message = (
                    f"导航传感器数据持续超时 {round(blocked_duration, 1)} 秒，"
                    "机器人已停车，请检查雷达与定位链路"
                )
            else:
                event_code = "NAV_PATH_BLOCKED"
                message = (
                    f"导航路径持续受阻 {round(blocked_duration, 1)} 秒，"
                    "局部绕行未找到出路，可能需要人工处理或更换目标点"
                )
            self._submit_alert(
                event_type="NAVIGATION",
                event_code=event_code,
                severity="warning",
                message=message,
                obstacle_status=status,
                nearest_obstacle_distance=payload.get("nearest_obstacle_distance"),
            )
            nav_logger.warning("导航持续受阻告警已发送：{}", message)

        if self._obstacle_alert_sent:
            self._maybe_auto_regoal(now, blocked_duration, status)

    def _maybe_auto_regoal(
        self, now: float, blocked_duration: float, status: str
    ) -> None:
        """持续阻断超过阈值时重发最近一次目标点，唤醒已丢弃目标的 SCAN。

        SCAN 重规划失败计满 max_replan_fail_count 后进入 WAIT_TARGET 并丢弃
        目标；该状态下 replan_request 被直接忽略，只有新 goal（-> 全局路径
        -> /initial_path）能救活规划链。任务模式由 waypoint 导航器自行重试，
        这里不介入。
        """
        if not settings.NAV_OBSTACLE_AUTO_REGOAL_ENABLED:
            return
        if status == "sensor_lost":
            return  # 传感器断流时重发目标毫无意义
        if blocked_duration < settings.NAV_OBSTACLE_REGOAL_SECONDS:
            return
        with self._goal_submission_lock:
            # Re-read all mutable navigation state only after acquiring the
            # same lock used by web goal submission.  If a new goal won the
            # race, its planning barrier/waypoint prevents the old one from
            # being published late and replacing it.
            if bool(getattr(self, "_navigation_task_active", False)):
                return
            active_planning_statuses = {"submitted", "queued", "planning"}
            planning_status = (
                "submitted"
                if bool(
                    getattr(
                        self,
                        "_planning_status_awaiting_new_generation",
                        False,
                    )
                )
                else str(
                    getattr(self, "_latest_planning_status", None) or ""
                ).strip().lower()
            )
            if planning_status in active_planning_statuses:
                return
            waypoint = self._last_goal_waypoint
            if not waypoint:
                return
            if (
                self._regoal_attempts
                >= settings.NAV_OBSTACLE_REGOAL_MAX_ATTEMPTS
            ):
                return
            if (
                now - self._last_regoal_at
                < settings.NAV_OBSTACLE_REGOAL_COOLDOWN_SECONDS
            ):
                return

            self._regoal_attempts += 1
            self._last_regoal_at = now
            try:
                publisher = getattr(self, "_publish_goal_xyz_yaw_inner", None)
                if not callable(publisher):
                    publisher = self.publish_goal_xyz_yaw
                publisher(dict(waypoint))
            except Exception as exc:
                nav_logger.warning("自动重发目标点失败：{}", exc)
                return
        message = (
            f"导航持续受阻 {round(blocked_duration, 1)} 秒，已自动重发目标点"
            f"（第 {self._regoal_attempts}/"
            f"{settings.NAV_OBSTACLE_REGOAL_MAX_ATTEMPTS} 次）"
        )
        nav_logger.warning("{}", message)
        self._submit_alert(
            event_type="NAVIGATION",
            event_code="NAV_AUTO_REGOAL",
            severity="info",
            message=message,
        )

    def _setup_auto_track_control_subscription(self) -> None:
        if self._node is None:
            return

        try:
            from std_msgs.msg import String
        except Exception as exc:
            raise RuntimeError(f"自动跟踪联动消息类型不可用: {exc}") from exc

        self._auto_track_control_subscription = self._node.create_subscription(
            String,
            settings.ROS_NAV_AUTO_TRACK_CONTROL_TOPIC,
            self._handle_auto_track_control_message,
            10,
        )
        nav_logger.info(
            "ROS2 导航自动跟踪联动订阅已启动：topic={}",
            settings.ROS_NAV_AUTO_TRACK_CONTROL_TOPIC,
        )

    def _handle_auto_track_control_message(self, msg: Any) -> None:
        raw_data = str(getattr(msg, "data", "") or "").strip()
        if not raw_data:
            nav_logger.warning("导航自动跟踪联动消息为空")
            return

        try:
            payload = json.loads(raw_data)
        except Exception as exc:
            nav_logger.warning("导航自动跟踪联动 JSON 解析失败：{}", exc)
            return

        if not isinstance(payload, dict) or not isinstance(payload.get("enabled"), bool):
            nav_logger.warning("导航自动跟踪联动消息结构错误：enabled 必须是布尔值")
            return

        enabled = bool(payload["enabled"])
        task_id = str(payload.get("task_id") or "").strip() or None
        step_index = payload.get("step_index")
        try:
            self._loop.call_soon_threadsafe(
                self._apply_auto_track_workflow_control,
                enabled,
                task_id,
                step_index,
            )
        except RuntimeError as exc:
            nav_logger.warning("导航自动跟踪联动调度失败：{}", exc)

    def _apply_auto_track_workflow_control(
        self,
        enabled: bool,
        task_id: str | None,
        step_index: Any,
    ) -> None:
        try:
            from .api.routes.nav_auto_track_helpers import apply_auto_track_workflow_control

            result = apply_auto_track_workflow_control(enabled)
        except Exception as exc:
            nav_logger.exception(
                "任务流程自动跟踪联动执行失败：task_id={} step_index={} enabled={} error={}",
                task_id,
                step_index,
                enabled,
                exc,
            )
            return

        event = {
            "task_id": task_id,
            "step_index": step_index,
            "enabled": enabled,
            "state": result.get("state"),
            "success": bool(
                result.get(
                    "success",
                    bool(result.get("enabled")) == enabled,
                )
            ),
            "message": result.get("message"),
        }
        self._submit_broadcast("nav.auto_track_control", event)
        nav_logger.info(
            "任务流程自动跟踪联动已执行：task_id={} step_index={} enabled={} state={}",
            task_id,
            step_index,
            enabled,
            result.get("state"),
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
        if path.get("points") and self._has_active_navigation_context():
            self._navigation_status_before_blocked = "path_ready"
            current_status = get_nav_state().get("navigation_status") or {}
            current = str(current_status.get("status") or "").strip().lower()
            if current == "blocked":
                return
            if self._planning_terminal_error_is_active(current_status):
                return
            self._update_live_navigation_status(
                {
                    "status": "path_ready",
                    "message": f"全局路径已生成，共 {len(path['points'])} 个路径点",
                    "ros_status": None,
                    "error_code": None,
                    "source": settings.ROS_NAV_GLOBAL_PATH_TOPIC,
                    "path_point_count": len(path["points"]),
                }
            )

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

    @staticmethod
    def _parse_planning_status_payload(
        payload: dict[str, Any],
    ) -> tuple[str, str, int, float] | None:
        status = str(payload.get("status") or "").strip().lower()
        if status not in {
            "queued",
            "planning",
            "path_ready",
            "failed",
            "rejected",
        }:
            return None

        generation = payload.get("generation")
        if (
            isinstance(generation, bool)
            or not isinstance(generation, int)
            or generation < 0
        ):
            return None

        elapsed_raw = payload.get("elapsed_seconds")
        if isinstance(elapsed_raw, bool) or not isinstance(
            elapsed_raw,
            (int, float),
        ):
            return None
        elapsed_seconds = float(elapsed_raw)
        if not math.isfinite(elapsed_seconds) or elapsed_seconds < 0.0:
            return None

        message = str(payload.get("message") or "").strip()
        if not message:
            message = {
                "queued": "已接收目标，等待规划",
                "planning": "正在计算全局路径",
                "path_ready": "全局路径已生成",
                "failed": "全局路径规划失败",
                "rejected": "导航目标被规划器拒绝",
            }[status]
        return status, message, generation, elapsed_seconds

    def _accept_planning_status_generation(
        self,
        status: str,
        generation: int,
        *,
        allow_generation_reset: bool = False,
    ) -> bool:
        latest_generation = getattr(
            self,
            "_latest_planning_generation",
            None,
        )
        latest_status = getattr(self, "_latest_planning_status", None)
        awaiting_new = bool(
            getattr(
                self,
                "_planning_status_awaiting_new_generation",
                False,
            )
        )

        if awaiting_new:
            generation_floor = getattr(
                self,
                "_planning_generation_floor",
                None,
            )
            # A local goal is finite-validated before publish, so a rejected
            # event that reuses the old generation cannot belong to it.
            if status == "rejected":
                is_new = generation_floor is None or generation > generation_floor
            else:
                is_new = (
                    generation_floor is None
                    or generation > generation_floor
                    or (
                        allow_generation_reset
                        and status in {"queued", "planning"}
                        and generation <= generation_floor
                    )
                )
            if not is_new:
                nav_logger.debug(
                    "忽略新目标握手期间的旧规划状态：status={} generation={} floor={}",
                    status,
                    generation,
                    generation_floor,
                )
                return False
            self._planning_status_awaiting_new_generation = False
            self._planning_generation_floor = generation
            latest_generation = None
            latest_status = None

        accept_generation_reset = bool(
            getattr(
                self,
                "_planning_status_accept_generation_reset",
                False,
            )
        ) or allow_generation_reset
        if accept_generation_reset:
            self._planning_status_accept_generation_reset = False
            latest_generation = None
            latest_status = None

        if latest_generation is not None:
            if generation < latest_generation:
                nav_logger.debug(
                    "忽略过期规划状态：status={} generation={} latest={}",
                    status,
                    generation,
                    latest_generation,
                )
                return False
            elif generation == latest_generation:
                terminal_statuses = {"path_ready", "failed", "rejected"}
                if latest_status == status:
                    return False
                if latest_status in terminal_statuses:
                    nav_logger.debug(
                        "忽略同代终态之后的规划状态：status={} generation={} terminal={}",
                        status,
                        generation,
                        latest_status,
                    )
                    return False
                status_rank = {
                    "queued": 0,
                    "planning": 1,
                    "path_ready": 2,
                    "failed": 2,
                    "rejected": 2,
                }
                if (
                    latest_status in status_rank
                    and status_rank[status] < status_rank[latest_status]
                ):
                    return False

        self._latest_planning_generation = generation
        self._latest_planning_status = status
        self._planning_status_seen = True
        return True

    def _planning_status_publisher_epoch(
        self,
        message_info: Any,
    ) -> tuple[bool, bool]:
        publisher_gid = getattr(message_info, "publisher_gid", None)
        if publisher_gid is None:
            return True, False
        try:
            publisher_key = bytes(publisher_gid)
        except (TypeError, ValueError):
            return True, False
        if not publisher_key:
            return True, False

        retired = getattr(
            self,
            "_retired_planning_status_publisher_gids",
            None,
        )
        if retired is None:
            retired = set()
            self._retired_planning_status_publisher_gids = retired
        if publisher_key in retired:
            return False, False

        previous = getattr(self, "_planning_status_publisher_gid", None)
        if previous is None:
            self._planning_status_publisher_gid = publisher_key
            return True, False
        if publisher_key == previous:
            return True, False

        retired.add(previous)
        self._planning_status_publisher_gid = publisher_key
        nav_logger.info(
            "检测到 global_planner 发布器重启，允许 planning generation 重新计数"
        )
        return True, True

    def _handle_planning_status_message(
        self,
        msg: Any,
        message_info: Any = None,
    ) -> None:
        raw_data = str(getattr(msg, "data", "") or "").strip()
        if not raw_data:
            nav_logger.warning("planning_status 消息为空")
            return

        try:
            payload = json.loads(raw_data)
        except Exception as exc:
            nav_logger.warning("planning_status JSON 解析失败：{}", exc)
            return
        if not isinstance(payload, dict):
            nav_logger.warning(
                "planning_status JSON 结构错误：期望对象，实际为 {}",
                type(payload).__name__,
            )
            return

        parsed = self._parse_planning_status_payload(payload)
        if parsed is None:
            nav_logger.warning("planning_status 字段无效：{}", payload)
            return
        planner_status, message, generation, elapsed_seconds = parsed
        publisher_current, publisher_reset = self._planning_status_publisher_epoch(
            message_info
        )
        if not publisher_current:
            return
        if not self._accept_planning_status_generation(
            planner_status,
            generation,
            allow_generation_reset=publisher_reset,
        ):
            return

        current_status = get_nav_state().get("navigation_status") or {}
        current = str(current_status.get("status") or "").strip().lower()
        if current == "blocked" and planner_status in {
            "queued",
            "planning",
            "path_ready",
        }:
            self._navigation_status_before_blocked = (
                "path_ready"
                if planner_status == "path_ready"
                else "planning"
            )
            self._update_live_navigation_status(
                {
                    "status": "blocked",
                    "planning_status": planner_status,
                    "planning_generation": generation,
                    "planning_elapsed_seconds": elapsed_seconds,
                }
            )
            return

        if planner_status in {"queued", "planning"}:
            frontend_status = "planning"
            error_code = None
        elif planner_status == "path_ready":
            frontend_status = "path_ready"
            error_code = None
            self._navigation_status_before_blocked = "path_ready"
        else:
            frontend_status = "error"
            error_code = (
                "GLOBAL_PLANNER_GOAL_REJECTED"
                if planner_status == "rejected"
                else "GLOBAL_PLANNER_FAILED"
            )
            self._navigation_status_before_blocked = None

        if elapsed_seconds > 0.0 and planner_status in {
            "path_ready",
            "failed",
        }:
            message = f"{message}（耗时 {elapsed_seconds:.3f} 秒）"

        self._update_live_navigation_status(
            {
                "status": frontend_status,
                "message": message,
                "ros_status": planner_status,
                "error_code": error_code,
                "source": settings.ROS_NAV_PLANNING_STATUS_TOPIC,
                "planning_status": planner_status,
                "planning_generation": generation,
                "planning_elapsed_seconds": elapsed_seconds,
            }
        )

    @staticmethod
    def _planning_terminal_error_is_active(
        current_status: dict[str, Any],
    ) -> bool:
        return (
            str(current_status.get("status") or "").strip().lower() == "error"
            and current_status.get("source")
            == settings.ROS_NAV_PLANNING_STATUS_TOPIC
            and str(current_status.get("planning_status") or "").strip().lower()
            in {"failed", "rejected"}
        )

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
        planner_hard_failure = (
            str(nav_status.get("error_code") or "").strip().upper()
            == "SCAN_REPLAN_FAILED"
        )

        if (
            task_active
            and not task_complete
            and status in {"reached", "idle", "error"}
            and not planner_hard_failure
        ):
            current_status = get_nav_state().get("navigation_status") or {}
            nav_status["status"] = "navigating"
            nav_status["task_id"] = nav_status.get("task_id") or current_status.get("task_id")
            if status == "reached":
                nav_status["message"] = "当前航点已到达，正在切换任务中的下一个航点"
            elif status == "error":
                nav_status["message"] = "当前航点执行失败，任务导航器正在重试"
            else:
                nav_status["message"] = "任务航点切换中"

        if self._ignore_terminal_status_during_navigation_handoff(nav_status):
            return

        current_status = get_nav_state().get("navigation_status") or {}
        if (
            status == "navigating"
            and self._planning_terminal_error_is_active(current_status)
        ):
            nav_logger.debug(
                "忽略规划终态之后缺少 generation 的活动回执：ros_status={}",
                nav_status.get("ros_status"),
            )
            return

        updated_status = update_navigation_status(nav_status)
        if status in {"reached", "idle", "error", "estop"}:
            self._navigation_status_before_blocked = None
        self._restore_navigation_control_on_active_status(nav_status)
        self._release_navigation_control_on_terminal_status(
            nav_status,
            task_complete=task_complete,
        )
        self._submit_broadcast("nav.navigation_status", updated_status)

    @staticmethod
    def _navigation_status_is_active(status: str) -> bool:
        return status in {
            "planning",
            "path_ready",
            "navigating",
            "blocked",
            "paused",
        }

    def _has_active_navigation_context(self) -> bool:
        current_status = get_nav_state().get("navigation_status") or {}
        status = str(current_status.get("status") or "").strip().lower()
        return (
            self._navigation_status_is_active(status)
            or bool(getattr(self, "_last_goal_waypoint", None))
            or bool(getattr(self, "_navigation_task_active", False))
        )

    def _update_navigation_status_from_obstacle(
        self,
        obstacle_status: str,
        payload: dict[str, Any],
    ) -> None:
        current_status = get_nav_state().get("navigation_status") or {}
        current = str(current_status.get("status") or "").strip().lower()

        if obstacle_status in self._OBSTACLE_STUCK_STATUSES:
            if not self._has_active_navigation_context():
                return
            if current != "blocked":
                self._navigation_status_before_blocked = (
                    current if self._navigation_status_is_active(current) else "navigating"
                )
            message = str(payload.get("message") or "").strip()
            if not message:
                message = (
                    "导航传感器数据中断，机器人已停车"
                    if obstacle_status == "sensor_lost"
                    else "局部路径受阻，机器人已停车并等待重规划"
                )
            if (
                current == "blocked"
                and current_status.get("obstacle_status") == obstacle_status
                and current_status.get("message") == message
            ):
                return
            self._update_live_navigation_status(
                {
                    "status": "blocked",
                    "message": message,
                    "ros_status": obstacle_status,
                    "error_code": (
                        "NAV_SENSOR_LOST"
                        if obstacle_status == "sensor_lost"
                        else "NAV_PATH_BLOCKED"
                    ),
                    "source": settings.ROS_NAV_OBSTACLE_STATUS_TOPIC,
                    "obstacle_status": obstacle_status,
                    "nearest_obstacle_distance": payload.get(
                        "nearest_obstacle_distance"
                    ),
                }
            )
            return

        if current != "blocked":
            return
        previous = str(
            getattr(self, "_navigation_status_before_blocked", None) or ""
        ).strip().lower()
        if previous not in {"planning", "path_ready", "navigating", "paused"}:
            global_path = get_nav_state().get("global_path") or {}
            previous = "path_ready" if global_path.get("points") else "navigating"
        self._navigation_status_before_blocked = previous
        self._update_live_navigation_status(
            {
                "status": previous,
                "message": (
                    "导航阻断已解除，继续沿已生成路径执行"
                    if previous in {"path_ready", "navigating"}
                    else "导航阻断已解除，继续等待路径规划"
                ),
                "ros_status": obstacle_status or "clear",
                "error_code": None,
                "source": settings.ROS_NAV_OBSTACLE_STATUS_TOPIC,
                "obstacle_status": obstacle_status or "clear",
                "nearest_obstacle_distance": payload.get(
                    "nearest_obstacle_distance"
                ),
            }
        )

    def _ignore_terminal_status_during_navigation_handoff(
        self,
        nav_status: dict[str, Any],
    ) -> bool:
        status = str(nav_status.get("status") or "").strip().lower()
        if status not in {"reached", "idle", "error"}:
            return False
        if time.monotonic() >= float(
            getattr(self, "_navigation_terminal_release_blocked_until", 0.0)
        ):
            return False

        nav_logger.info(
            "忽略新导航交接窗口内的旧终态回执，保留当前导航状态和控制权："
            "status={} error_code={}",
            status,
            nav_status.get("error_code"),
        )
        return True

    def _restore_navigation_control_on_active_status(
        self,
        nav_status: dict[str, Any],
    ) -> None:
        status = str(nav_status.get("status") or "").strip().lower()
        if status != "navigating" or not bool(
            getattr(self, "_navigation_control_expected", False)
        ):
            return
        try:
            from .nav_auto_track_coordinator import get_nav_auto_track_coordinator

            coordinator = get_nav_auto_track_coordinator()
            if coordinator is not None:
                coordinator.request_navigation_control()
        except Exception as exc:
            nav_logger.debug("恢复导航控制权失败：{}", exc)

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
            status != "estop"
            and time.monotonic()
            < float(
                getattr(
                    self,
                    "_navigation_terminal_release_blocked_until",
                    0.0,
                )
            )
        ):
            nav_logger.info(
                "忽略新导航交接窗口内的旧终态回执，保留 NAVIGATION 控制权："
                "status={}",
                status,
            )
            return
        if status in {"reached", "estop"}:
            # 目标已完成或被急停，不再是自动重发的对象。
            self._last_goal_waypoint = None
            self._regoal_attempts = 0
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
        self._navigation_control_expected = False
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
            elif now - self._last_tf_warning_at >= max(30.0, settings.ROS_NAV_TF_WARNING_INTERVAL_SECONDS):
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

    def _submit_alert(
        self,
        *,
        event_type: str,
        event_code: str,
        severity: str,
        message: str,
        **extra: Any,
    ) -> None:
        # ALERT_RAISED 走前端既有告警 UI，无需新增前端事件类型。
        if self._loop.is_closed():
            return
        future = asyncio.run_coroutine_threadsafe(
            self._broadcaster.broadcast_alert(
                event_type=event_type,
                event_code=event_code,
                severity=severity,
                message=message,
                **extra,
            ),
            self._loop,
        )
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
