from __future__ import annotations

import time
from typing import Any

import numpy as np

from .config import settings
from .logging_config import get_logger
from .ros_nav_cloud import (
    MAPPING_CLOUD_ACCUMULATED_MAX_BROADCAST_POINTS,
    MAPPING_CLOUD_ACCUMULATED_VOXEL_SIZE_M,
    MAPPING_CLOUD_ACCUMULATE_MAX_INPUT_POINTS,
    MAPPING_CLOUD_LIVE_MAX_BROADCAST_POINTS,
    VoxelMap,
    extract_cloud_xyz_np,
    limit_cloud_points,
    mapping_cloud_voxel_preview,
    merge_mapping_cloud_voxels,
)
from .services_nav_state import get_nav_state

nav_logger = get_logger("ROS导航")

MAPPING_CLOUD_LIVE_MIN_INTERVAL_S = 3.0
MAPPING_CLOUD_BROADCAST_MIN_INTERVAL_S = 3.0


class RosNavCloudBridgeMixin:
    def _init_mapping_cloud_state(self) -> None:
        self._cloud_subscription: Any | None = None
        self._last_cloud_broadcast_at = 0.0
        self._accumulated_cloud: np.ndarray = np.empty((0, 3), dtype=np.float32)
        self._accumulated_cloud_voxels: VoxelMap = {}
        self._last_full_map_broadcast_at = 0.0
        self._mapping_cloud_broadcast_future: Any | None = None

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
        if not self._mapping_cloud_has_connections():
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

        cloud_pts = extract_cloud_xyz_np(msg, max_points=MAPPING_CLOUD_ACCUMULATE_MAX_INPUT_POINTS)
        if cloud_pts is None or len(cloud_pts) == 0:
            return

        self._merge_mapping_cloud_voxels(cloud_pts)

        live_pts = limit_cloud_points(cloud_pts, MAPPING_CLOUD_LIVE_MAX_BROADCAST_POINTS)
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

    def _mapping_cloud_has_connections(self) -> bool:
        broadcaster = getattr(self, "_mapping_cloud_broadcaster", None) or getattr(self, "_broadcaster", None)
        if broadcaster is None:
            return True

        has_connections = getattr(broadcaster, "has_connections", None)
        if has_connections is None:
            return True
        return bool(has_connections())

    def _merge_mapping_cloud_voxels(self, points: np.ndarray) -> None:
        if not hasattr(self, "_accumulated_cloud_voxels"):
            self._accumulated_cloud_voxels = {}
        merge_mapping_cloud_voxels(
            self._accumulated_cloud_voxels,
            points,
            voxel_size=MAPPING_CLOUD_ACCUMULATED_VOXEL_SIZE_M,
        )

    def _mapping_cloud_voxel_preview(self) -> np.ndarray:
        return mapping_cloud_voxel_preview(
            getattr(self, "_accumulated_cloud_voxels", {}),
            max_points=MAPPING_CLOUD_ACCUMULATED_MAX_BROADCAST_POINTS,
        )
