from __future__ import annotations

import asyncio
import copy
import math
import time
from enum import Enum
from typing import Any

from .config import settings
from .logging_config import get_logger
from .pcd_errors import PcdMapError
from .services_nav_fences import list_fences
from .services_nav_localization_scene import load_current_scene
from .services_nav_state import get_nav_state
from .z2mini_gimbal import GcuProtocolError, Z2MiniGimbal, Z2MiniStatus


logger = get_logger("自动围栏检测")


class FenceDetectionState(str, Enum):
    DISABLED = "disabled"
    FINDING = "finding"
    GIMBAL_MOVING = "gimbal_moving"
    DETECTING = "detecting"
    TRACKING = "tracking"
    NOT_FOUND = "not_found"
    OUT_OF_RANGE = "out_of_range"
    LOCALIZATION_UNAVAILABLE = "localization_unavailable"
    CALIBRATION_UNAVAILABLE = "calibration_unavailable"


def closest_point_on_segment(
    px: float,
    py: float,
    start: dict[str, Any],
    end: dict[str, Any],
) -> tuple[dict[str, float], float]:
    """Return the nearest point on a finite map-XY segment and its distance."""
    ax, ay = float(start["x"]), float(start["y"])
    bx, by = float(end["x"]), float(end["y"])
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-12:
        point = {"x": ax, "y": ay}
        return point, math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    point = {"x": ax + t * dx, "y": ay + t * dy}
    return point, math.hypot(px - point["x"], py - point["y"])


def _normalize_degrees(value: float) -> float:
    return (value + 180.0) % 360.0 - 180.0


Vec3 = tuple[float, float, float]


class FenceDetectionService:
    """管理围栏观察方向；人员动作由 PoseEventEngine 独立判断。"""

    def __init__(self, *, gimbal_service: Z2MiniGimbal) -> None:
        self._gimbal_service = gimbal_service
        self._control_lock = asyncio.Lock()
        self._enabled = False
        self._tracking_override = False
        self._state = FenceDetectionState.DISABLED
        self._detail = "围栏检测未开启"
        self._scene_id: str | None = None
        self._target_fence: dict[str, Any] | None = None
        self._target_point: dict[str, float] | None = None
        self._distance_m: float | None = None
        self._desired_yaw_deg: float | None = None
        self._desired_pitch_deg: float | None = None
        self._last_yaw_velocity_dps = 0.0
        self._yaw_motion_active = False
        self._settled_since: float | None = None
        self._invalidated_at: float | None = None
        self._last_pose_ros_timestamp: float | None = None
        self._last_gimbal_error: str | None = None
        self._missing_calibration: list[str] = []

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def tracking_override(self) -> bool:
        return self._tracking_override

    def _set_state(self, state: FenceDetectionState, detail: str) -> None:
        if state != self._state or detail != self._detail:
            logger.info("围栏检测状态：{}，{}", state.value, detail)
        self._state = state
        self._detail = detail

    def get_status(self) -> dict[str, Any]:
        return {
            "enabled": self._enabled,
            "state": self._state.value,
            "detail": self._detail,
            "scene_id": self._scene_id,
            "target_fence_id": self._target_fence.get("id") if self._target_fence else None,
            "target_point": copy.deepcopy(self._target_point),
            "distance_m": round(self._distance_m, 3) if self._distance_m is not None else None,
            "desired_yaw_deg": self._desired_yaw_deg,
            "desired_pitch_deg": self._desired_pitch_deg,
            # 保留旧状态字段供客户端兼容，动作结果通过 POSE_OVERLAY 发布。
            "behavior_mode": "action_only",
            "behavior": "normal",
            "behavior_track_id": None,
            "persons": [],
            "tamper": {
                "enabled": False,
                "structure_check_enabled": False,
                "reference_ready": False,
                "reference_age_seconds": None,
                "pending": False,
                "pending_track_id": None,
                "action_score": 0.0,
                "structure_change_ratio": 0.0,
                "last_result": None,
                "last_result_age_seconds": None,
            },
            "missing_calibration": list(self._missing_calibration),
            "gimbal_error": self._last_gimbal_error,
        }

    def process_frame(self, **_unused: Any) -> list[Any]:
        """兼容旧调用，不产生几何行为事件；动作告警统一由姿态通道生成。"""
        return []

    async def enable(self) -> dict[str, Any]:
        async with self._control_lock:
            from .auto_track_service import get_auto_track_service

            self._enabled = True
            auto_track = get_auto_track_service()
            self._tracking_override = bool(
                auto_track is not None and auto_track.get_status()["enabled"]
            )
            self._scene_id = None
            self._clear_lock()
            self._invalidated_at = None
            self._last_pose_ros_timestamp = None
            self._last_gimbal_error = None
            if self._tracking_override:
                self._set_state(FenceDetectionState.TRACKING, "跟踪联动已接管云台；关闭联动后恢复围栏观察")
            else:
                self._set_state(FenceDetectionState.FINDING, "正在读取当前场景围栏")
            return self.get_status()

    async def disable(self, *, center_gimbal: bool = True) -> dict[str, Any]:
        async with self._control_lock:
            return await self._disable_locked(center_gimbal=center_gimbal)

    async def _disable_locked(self, *, center_gimbal: bool) -> dict[str, Any]:
        was_enabled = self._enabled and not self._tracking_override
        self._tracking_override = False
        if was_enabled and not center_gimbal:
            await self._gimbal_service.jog(pitch_velocity_dps=0.0, yaw_velocity_dps=0.0)
        self._enabled = False
        self._clear_lock()
        self._scene_id = None
        self._invalidated_at = None
        self._last_pose_ros_timestamp = None
        self._set_state(FenceDetectionState.DISABLED, "围栏检测未开启")
        if center_gimbal and was_enabled:
            try:
                await self._return_yaw_to_default()
                self._last_gimbal_error = None
            except (OSError, GcuProtocolError, ValueError) as exc:
                self._last_gimbal_error = str(exc)
                logger.warning("关闭围栏检测后云台 yaw 归中失败：{}", exc)
        return self.get_status()

    def _clear_lock(self) -> None:
        self._target_fence = None
        self._target_point = None
        self._distance_m = None
        self._desired_yaw_deg = None
        self._desired_pitch_deg = None
        self._last_yaw_velocity_dps = 0.0
        self._yaw_motion_active = False
        self._settled_since = None

    @staticmethod
    def _finite_setting(name: str, fallback_name: str | None = None) -> float:
        value = getattr(settings, name)
        if value is None and fallback_name is not None:
            value = getattr(settings, fallback_name)
        return float(value)

    def _mount_xyz(self) -> Vec3:
        return (
            self._finite_setting("FENCE_GIMBAL_MOUNT_X_M", "NAV_LIDAR_MOUNT_X_M"),
            self._finite_setting("FENCE_GIMBAL_MOUNT_Y_M", "NAV_LIDAR_MOUNT_Y_M"),
            (float(settings.NAV_LIDAR_MOUNT_Z_M)
             if settings.FENCE_GIMBAL_MOUNT_Z_M is None
             else float(settings.FENCE_GIMBAL_MOUNT_Z_M)),
        )

    def _check_calibration(self) -> bool:
        missing: list[str] = []
        try:
            mount_xyz = self._mount_xyz()
        except (TypeError, ValueError):
            mount_xyz = (math.nan, math.nan, math.nan)
        for index, name in enumerate(
            ("NAV_LIDAR_MOUNT_X_M", "NAV_LIDAR_MOUNT_Y_M", "NAV_LIDAR_MOUNT_Z_M")
        ):
            if not math.isfinite(mount_xyz[index]):
                missing.append(name)
        for name in (
            "FENCE_GIMBAL_MOUNT_ROLL_DEG",
            "FENCE_GIMBAL_MOUNT_PITCH_DEG",
            "FENCE_GIMBAL_MOUNT_YAW_DEG",
            "FENCE_GIMBAL_YAW_SIGN",
            "FENCE_GIMBAL_PITCH_SIGN",
            "FENCE_CAMERA_OFFSET_X_M",
            "FENCE_CAMERA_OFFSET_Y_M",
            "FENCE_CAMERA_OFFSET_Z_M",
            "FENCE_CAMERA_ROLL_DEG",
            "FENCE_CAMERA_PITCH_DEG",
            "FENCE_CAMERA_YAW_DEG",
            "AUTO_TRACK_GIMBAL_HORIZONTAL_FOV_DEG",
        ):
            try:
                value = float(getattr(settings, name))
            except (TypeError, ValueError):
                value = math.nan
            if not math.isfinite(value):
                missing.append(name)
        try:
            yaw_sign = float(settings.FENCE_GIMBAL_YAW_SIGN)
        except (TypeError, ValueError):
            yaw_sign = 0.0
        if abs(yaw_sign) < 1e-6:
            missing.append("FENCE_GIMBAL_YAW_SIGN")
        try:
            frame_width = int(settings.AI_FRAME_WIDTH)
        except (TypeError, ValueError):
            frame_width = 0
        try:
            frame_height = int(settings.AI_FRAME_HEIGHT)
        except (TypeError, ValueError):
            frame_height = 0
        try:
            horizontal_fov = float(settings.AUTO_TRACK_GIMBAL_HORIZONTAL_FOV_DEG)
        except (TypeError, ValueError):
            horizontal_fov = math.nan
        if frame_width <= 0:
            missing.append("AI_FRAME_WIDTH")
        if frame_height <= 0:
            missing.append("AI_FRAME_HEIGHT")
        if not 0.0 < horizontal_fov < 180.0:
            missing.append("AUTO_TRACK_GIMBAL_HORIZONTAL_FOV_DEG")
        self._missing_calibration = sorted(set(missing))
        return not self._missing_calibration

    async def run(self, stop_event: asyncio.Event) -> None:
        interval = 1.0 / max(1.0, float(settings.FENCE_CONTROL_HZ))
        try:
            while not stop_event.is_set():
                started = time.monotonic()
                if self._enabled:
                    try:
                        await self._control_step(started)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # noqa: BLE001
                        logger.exception("围栏自动控制循环异常：{}", exc)
                        self._last_gimbal_error = str(exc)
                elapsed = time.monotonic() - started
                await asyncio.sleep(max(0.02, interval - elapsed))
        finally:
            if self._enabled:
                await self.disable(center_gimbal=True)

    async def _control_step(self, now: float) -> None:
        async with self._control_lock:
            if not self._enabled:
                return
            if self._tracking_override:
                from .auto_track_service import get_auto_track_service

                auto_track = get_auto_track_service()
                if auto_track is not None and not auto_track.get_status()["enabled"]:
                    await self._resume_after_tracking_locked(auto_track)
                return
            await self._control_step_locked(now)

    async def _suspend_for_tracking_locked(self) -> None:
        if self._tracking_override:
            return
        await self._gimbal_service.jog(pitch_velocity_dps=0.0, yaw_velocity_dps=0.0)
        self._tracking_override = True
        self._settled_since = None
        self._yaw_motion_active = False
        self._set_state(FenceDetectionState.TRACKING, "跟踪联动已接管云台；关闭联动后恢复围栏观察")

    async def _resume_after_tracking_locked(self, auto_track) -> None:
        await auto_track.disable_for_fence()
        self._tracking_override = False
        self._settled_since = None
        self._set_state(FenceDetectionState.FINDING, "跟踪已停止，正在恢复围栏观察")

    async def _control_step_locked(self, now: float) -> None:
        if not self._check_calibration():
            self._clear_lock()
            self._set_state(
                FenceDetectionState.CALIBRATION_UNAVAILABLE,
                "围栏检测所需的现有安装或相机参数不可用，已禁止自动转动",
            )
            return

        nav_state = get_nav_state()
        pose = nav_state.get("robot_pose")
        localization = nav_state.get("localization_status") or {}
        if pose is None or localization.get("status") != "ok":
            self._clear_lock()
            self._invalidated_at = now
            self._last_pose_ros_timestamp = None
            self._set_state(FenceDetectionState.LOCALIZATION_UNAVAILABLE, "定位不可用")
            return

        ros_timestamp_raw = pose.get("ros_timestamp")
        if ros_timestamp_raw is not None:
            try:
                ros_timestamp = float(ros_timestamp_raw)
            except (TypeError, ValueError):
                ros_timestamp = 0.0
            if math.isfinite(ros_timestamp) and ros_timestamp > 0.0:
                if (
                    self._last_pose_ros_timestamp is not None
                    and ros_timestamp + 1e-3 < self._last_pose_ros_timestamp
                ):
                    self._clear_lock()
                    self._invalidated_at = now
                    self._last_pose_ros_timestamp = ros_timestamp
                    self._set_state(FenceDetectionState.FINDING, "定位已重新初始化，等待重新选择围栏")
                    return
                self._last_pose_ros_timestamp = ros_timestamp

        try:
            current_scene = load_current_scene(strict=False)
            scene_id = str(current_scene["scene_id"])
        except (FileNotFoundError, KeyError, TypeError, ValueError) as exc:
            self._clear_lock()
            self._set_state(FenceDetectionState.NOT_FOUND, f"当前场景不可用：{exc}")
            return

        if self._scene_id is not None and scene_id != self._scene_id:
            self._clear_lock()
            self._invalidated_at = now
        self._scene_id = scene_id

        try:
            fences = list_fences(scene_id)["items"]
        except (FileNotFoundError, PcdMapError, ValueError) as exc:
            self._clear_lock()
            self._set_state(FenceDetectionState.NOT_FOUND, f"当前场景围栏不可用：{exc}")
            return
        enabled_fences = [item for item in fences if bool(item.get("enabled", True))]
        current = None
        if self._target_fence is not None:
            current = next(
                (item for item in enabled_fences if item.get("id") == self._target_fence.get("id")),
                None,
            )

        if current is not None:
            target_point, distance = closest_point_on_segment(
                float(pose["x"]),
                float(pose["y"]),
                current["start"],
                current["end"],
            )
            desired_yaw = self._aim_yaw(pose, target_point)
            if distance > float(settings.FENCE_DETECTION_MAX_DISTANCE_M) or desired_yaw is None:
                self._clear_lock()
                self._invalidated_at = now
                current = None
                self._set_state(FenceDetectionState.OUT_OF_RANGE, "锁定围栏已超出检测或云台范围")
            else:
                self._target_fence = current
                self._target_point = target_point
                self._distance_m = distance
                self._desired_yaw_deg = desired_yaw
                self._desired_pitch_deg = None
        elif self._target_fence is not None:
            self._clear_lock()
            self._invalidated_at = now
            self._set_state(FenceDetectionState.FINDING, "当前围栏已删除或禁用，等待重新选择")

        if self._target_fence is None:
            if self._invalidated_at is not None and now - self._invalidated_at < float(settings.FENCE_SWITCH_DELAY_SECONDS):
                return
            candidates: list[tuple[float, dict[str, Any], dict[str, float], float]] = []
            any_within_distance = False
            for fence in enabled_fences:
                target_point, distance = closest_point_on_segment(
                    float(pose["x"]),
                    float(pose["y"]),
                    fence["start"],
                    fence["end"],
                )
                if distance > float(settings.FENCE_DETECTION_MAX_DISTANCE_M):
                    continue
                any_within_distance = True
                desired_yaw = self._aim_yaw(pose, target_point)
                if desired_yaw is not None:
                    candidates.append((distance, fence, target_point, desired_yaw))

            if not candidates:
                if not enabled_fences:
                    self._set_state(FenceDetectionState.NOT_FOUND, "当前场景没有启用的围栏")
                elif any_within_distance:
                    self._set_state(FenceDetectionState.OUT_OF_RANGE, "围栏超出云台可转动范围")
                else:
                    self._set_state(FenceDetectionState.OUT_OF_RANGE, "围栏超过最大检测距离")
                return

            distance, fence, target_point, desired_yaw = min(candidates, key=lambda item: item[0])
            self._target_fence = fence
            self._target_point = target_point
            self._distance_m = distance
            self._desired_yaw_deg = desired_yaw
            self._desired_pitch_deg = None
            self._invalidated_at = None
            logger.info("已锁定最近围栏：id={} distance={:.3f}m", fence["id"], distance)

        try:
            status = await self._gimbal_service.status()
        except (OSError, GcuProtocolError, ValueError) as exc:
            self._last_gimbal_error = str(exc)
            self._set_state(FenceDetectionState.CALIBRATION_UNAVAILABLE, f"云台状态不可用：{exc}")
            return

        # 围栏控制没有俯仰目标；后续只发送 yaw 速度，pitch/roll 速度恒为 0。
        self._desired_pitch_deg = None
        self._last_gimbal_error = None
        await self._apply_gimbal_control(status, time.monotonic())

    def _aim_yaw(
        self,
        pose: dict[str, Any],
        target_point: dict[str, float],
    ) -> float | None:
        body_yaw = float(pose["yaw"])
        mount_x, mount_y, _ = self._mount_xyz()
        pivot_x = float(pose["x"]) + math.cos(body_yaw) * mount_x - math.sin(body_yaw) * mount_y
        pivot_y = float(pose["y"]) + math.sin(body_yaw) * mount_x + math.cos(body_yaw) * mount_y
        dx = target_point["x"] - pivot_x
        dy = target_point["y"] - pivot_y
        horizontal = math.hypot(dx, dy)
        if horizontal <= 1e-5:
            return None

        bearing_body_deg = math.degrees(math.atan2(dy, dx) - body_yaw)
        yaw = _normalize_degrees(
            (
                bearing_body_deg
                - float(settings.FENCE_GIMBAL_MOUNT_YAW_DEG)
                - float(settings.FENCE_CAMERA_YAW_DEG)
            )
            / float(settings.FENCE_GIMBAL_YAW_SIGN)
        )
        if not float(settings.FENCE_GIMBAL_MIN_YAW_DEG) <= yaw <= float(settings.FENCE_GIMBAL_MAX_YAW_DEG):
            return None
        return yaw

    async def _apply_gimbal_control(self, status: Z2MiniStatus, now: float) -> None:
        if not self._enabled:
            return
        desired_yaw = float(self._desired_yaw_deg)
        current_yaw = float(status.relative_yaw_deg)
        yaw_error = _normalize_degrees(desired_yaw - current_yaw)
        needs_command = abs(yaw_error) > float(settings.FENCE_GIMBAL_YAW_DEADBAND_DEG)

        if needs_command:
            control_hz = max(1.0, float(settings.FENCE_CONTROL_HZ))
            alpha = max(0.0, min(1.0, float(settings.FENCE_GIMBAL_SMOOTHING_ALPHA)))
            max_speed = float(settings.FENCE_GIMBAL_MAX_SPEED_DPS)
            yaw_velocity = max(
                -max_speed,
                min(max_speed, yaw_error * control_hz * alpha),
            )
            try:
                await self._gimbal_service.jog(
                    pitch_velocity_dps=0.0,
                    yaw_velocity_dps=yaw_velocity,
                )
            except (OSError, GcuProtocolError, ValueError) as exc:
                self._last_gimbal_error = str(exc)
                self._set_state(FenceDetectionState.GIMBAL_MOVING, f"云台控制失败：{exc}")
                return
            self._last_yaw_velocity_dps = yaw_velocity
            self._yaw_motion_active = True
            self._settled_since = None
            self._set_state(FenceDetectionState.GIMBAL_MOVING, "云台正在平滑转向锁定围栏")
            return

        if self._yaw_motion_active:
            try:
                status = await self._gimbal_service.jog(
                    pitch_velocity_dps=0.0,
                    yaw_velocity_dps=0.0,
                )
            except (OSError, GcuProtocolError, ValueError) as exc:
                self._last_gimbal_error = str(exc)
                self._set_state(FenceDetectionState.GIMBAL_MOVING, f"云台停止失败：{exc}")
                return
            self._last_yaw_velocity_dps = 0.0
            self._yaw_motion_active = False
        stable = (
            abs(yaw_error) <= float(settings.FENCE_GIMBAL_SETTLE_ERROR_DEG)
            and abs(float(status.angular_velocity_yaw_dps)) <= float(settings.FENCE_GIMBAL_SETTLE_VELOCITY_DPS)
        )
        if not stable:
            self._settled_since = None
            self._set_state(FenceDetectionState.GIMBAL_MOVING, "等待云台稳定")
            return
        if self._settled_since is None:
            self._settled_since = now
        if now - self._settled_since < float(settings.FENCE_GIMBAL_SETTLE_SECONDS):
            self._set_state(FenceDetectionState.GIMBAL_MOVING, "等待云台稳定")
            return
        self._set_state(FenceDetectionState.DETECTING, "云台已对准围栏；人员行为依据动作判断")

    async def _return_yaw_to_default(self) -> None:
        """只用 yaw 速度把水平角归零，不给 roll/pitch 发送位置目标。"""
        control_hz = max(1.0, float(settings.FENCE_CONTROL_HZ))
        interval = 1.0 / control_hz
        max_speed = float(settings.FENCE_GIMBAL_MAX_SPEED_DPS)
        alpha = max(0.0, min(1.0, float(settings.FENCE_GIMBAL_SMOOTHING_ALPHA)))
        timeout = 180.0 / max(1.0, max_speed) + 1.0
        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                status = await self._gimbal_service.status()
                yaw_error = _normalize_degrees(-float(status.relative_yaw_deg))
                if abs(yaw_error) <= float(settings.FENCE_GIMBAL_YAW_DEADBAND_DEG):
                    return
                yaw_velocity = max(
                    -max_speed,
                    min(max_speed, yaw_error * control_hz * alpha),
                )
                await self._gimbal_service.jog(
                    pitch_velocity_dps=0.0,
                    yaw_velocity_dps=yaw_velocity,
                )
                await asyncio.sleep(interval)
        finally:
            await self._gimbal_service.jog(
                pitch_velocity_dps=0.0,
                yaw_velocity_dps=0.0,
            )

_fence_detection_service: FenceDetectionService | None = None


def get_fence_detection_service() -> FenceDetectionService | None:
    return _fence_detection_service


def set_fence_detection_service(service: FenceDetectionService | None) -> None:
    global _fence_detection_service
    _fence_detection_service = service


async def enable_auto_tracking(*, for_navigation: bool = False) -> None:
    """围栏保持开启，跟踪联动临时接管云台。"""
    from .auto_track_service import get_auto_track_service

    auto_track = get_auto_track_service()
    if auto_track is None:
        raise RuntimeError("自动跟踪服务未初始化")
    enable = (
        getattr(auto_track, "enable_for_navigation", auto_track.enable)
        if for_navigation else auto_track.enable
    )
    fence = get_fence_detection_service()
    if fence is None:
        enable()
        if for_navigation and hasattr(auto_track, "resume"):
            auto_track.resume()
        return
    async with fence._control_lock:
        if fence.enabled:
            await fence._suspend_for_tracking_locked()
        enable()
        if for_navigation and hasattr(auto_track, "resume"):
            auto_track.resume()


async def disable_auto_tracking() -> None:
    """停止跟踪后，恢复仍处于开启状态的围栏观察。"""
    from .auto_track_service import get_auto_track_service

    auto_track = get_auto_track_service()
    if auto_track is None:
        raise RuntimeError("自动跟踪服务未初始化")
    fence = get_fence_detection_service()
    if fence is None:
        auto_track.disable()
        return
    async with fence._control_lock:
        if fence.enabled and fence.tracking_override:
            await fence._resume_after_tracking_locked(auto_track)
        else:
            auto_track.disable()
