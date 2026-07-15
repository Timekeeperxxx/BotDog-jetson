from __future__ import annotations

import threading
from typing import Any

from .config import settings
from .logging_config import get_logger
from .services_nav_state import update_localization_status

nav_logger = get_logger("ROS导航")


class RosNavLifecycleMixin:
    _thread: threading.Thread | None
    _node: Any | None
    _paused: bool
    _pause_event: threading.Event
    _lifecycle_cv: threading.Condition
    _lifecycle_request: dict[str, Any] | None
    _publisher_lock: threading.RLock
    _rclpy: Any | None
    _tf_available: bool
    _tf_wait_started_at: float
    _last_tf_lookup_at: float

    def pause(self) -> None:
        """建图前调用：销毁 ROS2 node 以退出 DDS 网络，保留 rclpy context 以便恢复。"""
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
            self._nav_task_start_publisher = None
            self._cmd_vel_publisher = None
            self._goal_xyz_publisher = None
            self._goal_yaw_publisher = None
            self._global_path_subscription = None
            self._execution_path_subscription = None
            self._nav_status_subscription = None
            self._estop_publisher = None
            self._initial_pose_publisher = None
            self._cloud_subscription = None
            if node is not None:
                try:
                    node.destroy_node()
                except Exception as exc:
                    nav_logger.warning("{}销毁失败：{}", action, exc)
