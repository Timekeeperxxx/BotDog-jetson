from __future__ import annotations

import asyncio
import copy
import math
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable

import cv2
import numpy as np

from .config import settings
from .logging_config import get_logger
from .pcd_errors import PcdMapError
from .pose_detection import (
    LEFT_WRIST,
    RIGHT_WRIST,
    PoseObservation,
    Posture,
)
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
    NOT_FOUND = "not_found"
    OUT_OF_RANGE = "out_of_range"
    LOCALIZATION_UNAVAILABLE = "localization_unavailable"
    CALIBRATION_UNAVAILABLE = "calibration_unavailable"


class FenceBehavior(str, Enum):
    NORMAL = "normal"
    APPROACHING = "approaching"
    DWELLING = "dwelling"
    CONTACT = "contact"
    CLIMBING_SUSPECTED = "climbing_suspected"
    TAMPERING_SUSPECTED = "tampering_suspected"
    TAMPERING_CONFIRMED = "tampering_confirmed"


@dataclass(frozen=True)
class FenceBehaviorEvent:
    behavior: FenceBehavior
    track_id: int
    confidence: float
    duration_seconds: float
    fence_id: str
    action_score: float = 0.0
    structure_change_ratio: float = 0.0
    evidence_level: str = "behavior"


@dataclass(frozen=True)
class _SynchronizedSample:
    monotonic_at: float
    pose: dict[str, Any]
    gimbal: Z2MiniStatus


@dataclass
class _PersonFenceState:
    track_id: int
    last_seen_at: float
    behavior: FenceBehavior = FenceBehavior.NORMAL
    near_hits: int = 0
    contact_hits: int = 0
    cross_hits: int = 0
    near_since: float | None = None
    baseline_side: int | None = None
    tamper_hits: int = 0
    tamper_action_score: float = 0.0
    tamper_confirmed: bool = False
    wrist_history: dict[int, deque[tuple[float, float, float]]] = field(
        default_factory=dict
    )
    last_events: dict[FenceBehavior, float] = field(default_factory=dict)


@dataclass
class _PendingTamper:
    track_id: int
    started_at: float
    last_action_at: float
    expires_at: float
    contact_pixel: tuple[float, float]
    person_height: float
    action_score: float


def repetitive_motion_score(
    samples: Iterable[tuple[float, float, float]],
    *,
    min_duration_seconds: float,
    min_travel_ratio: float,
    min_reversals: int,
) -> tuple[float, float, int]:
    """Score repeated wrist motion using person-height-normalized coordinates."""
    points = list(samples)
    if len(points) < 3:
        return 0.0, 0.0, 0
    duration = max(0.0, points[-1][0] - points[0][0])
    vectors: list[tuple[float, float, float]] = []
    total_travel = 0.0
    for previous, current in zip(points, points[1:]):
        dx = current[1] - previous[1]
        dy = current[2] - previous[2]
        distance = math.hypot(dx, dy)
        total_travel += distance
        # Ignore sub-pixel pose jitter after normalization by the person height.
        if distance >= 0.015:
            vectors.append((dx, dy, distance))

    reversals = 0
    for previous, current in zip(vectors, vectors[1:]):
        cosine = (
            previous[0] * current[0] + previous[1] * current[1]
        ) / max(1e-9, previous[2] * current[2])
        if cosine <= -0.25:
            reversals += 1

    duration_score = min(1.0, duration / max(0.1, min_duration_seconds))
    travel_score = min(1.0, total_travel / max(0.01, min_travel_ratio))
    reversal_score = min(1.0, reversals / max(1, min_reversals))
    return min(duration_score, travel_score, reversal_score), total_travel, reversals


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


def _signed_line_distance(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length <= 1e-6:
        return 0.0
    return (dx * (point[1] - start[1]) - dy * (point[0] - start[0])) / length


Mat3 = tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]
Vec3 = tuple[float, float, float]
CameraIntrinsics = tuple[float, float, float, float]


def _mat_mul(first: Mat3, second: Mat3) -> Mat3:
    return tuple(
        tuple(sum(first[row][k] * second[k][column] for k in range(3)) for column in range(3))
        for row in range(3)
    )  # type: ignore[return-value]


def _mat_vec(matrix: Mat3, vector: Vec3) -> Vec3:
    return tuple(sum(matrix[row][k] * vector[k] for k in range(3)) for row in range(3))  # type: ignore[return-value]


def _rx(roll: float) -> Mat3:
    c, s = math.cos(roll), math.sin(roll)
    return ((1.0, 0.0, 0.0), (0.0, c, -s), (0.0, s, c))


def _ry_up(pitch: float) -> Mat3:
    # Positive pitch raises the forward optical axis in the x-forward/y-left/z-up frame.
    c, s = math.cos(pitch), math.sin(pitch)
    return ((c, 0.0, -s), (0.0, 1.0, 0.0), (s, 0.0, c))


def _rz(yaw: float) -> Mat3:
    c, s = math.cos(yaw), math.sin(yaw)
    return ((c, -s, 0.0), (s, c, 0.0), (0.0, 0.0, 1.0))


def _rpy(roll_deg: float, pitch_deg: float, yaw_deg: float) -> Mat3:
    return _mat_mul(
        _mat_mul(_rz(math.radians(yaw_deg)), _ry_up(math.radians(pitch_deg))),
        _rx(math.radians(roll_deg)),
    )


_OPTICAL_TO_FORWARD_LEFT_UP: Mat3 = (
    (0.0, 0.0, 1.0),
    (-1.0, 0.0, 0.0),
    (0.0, -1.0, 0.0),
)


def _bbox_iou(first: tuple[int, int, int, int], second: tuple[int, int, int, int]) -> float:
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    intersection = max(0, right - left) * max(0, bottom - top)
    if intersection <= 0:
        return 0.0
    first_area = max(0, first[2] - first[0]) * max(0, first[3] - first[1])
    second_area = max(0, second[2] - second[0]) * max(0, second[3] - second[1])
    union = first_area + second_area - intersection
    return intersection / union if union > 0 else 0.0


class FenceDetectionService:
    def __init__(self, *, gimbal_service: Z2MiniGimbal) -> None:
        self._gimbal_service = gimbal_service
        self._control_lock = asyncio.Lock()
        self._enabled = False
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
        self._samples: deque[_SynchronizedSample] = deque(maxlen=80)
        self._person_states: dict[int, _PersonFenceState] = {}
        self._last_gimbal_error: str | None = None
        self._missing_calibration: list[str] = []
        self._structure_reference_gray: np.ndarray | None = None
        self._structure_reference_mask: np.ndarray | None = None
        self._structure_reference_at: float | None = None
        self._reference_clear_hits = 0
        self._pending_tamper: _PendingTamper | None = None
        self._structure_change_hits = 0
        self._last_structure_change_ratio = 0.0
        self._last_tamper_behavior: FenceBehavior | None = None
        self._last_tamper_at: float | None = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _set_state(self, state: FenceDetectionState, detail: str) -> None:
        if state != self._state or detail != self._detail:
            logger.info("围栏检测状态：{}，{}", state.value, detail)
        self._state = state
        self._detail = detail

    def get_status(self) -> dict[str, Any]:
        persons = sorted(
            (
                {
                    "track_id": item.track_id,
                    "behavior": item.behavior.value,
                    "tamper_action_score": round(item.tamper_action_score, 4),
                    "duration_seconds": round(
                        max(0.0, time.monotonic() - item.near_since)
                        if item.near_since is not None
                        else 0.0,
                        1,
                    ),
                }
                for item in self._person_states.values()
            ),
            key=lambda item: item["track_id"],
        )
        priority = {
            FenceBehavior.NORMAL.value: 0,
            FenceBehavior.APPROACHING.value: 1,
            FenceBehavior.DWELLING.value: 2,
            FenceBehavior.CONTACT.value: 3,
            FenceBehavior.CLIMBING_SUSPECTED.value: 4,
            FenceBehavior.TAMPERING_SUSPECTED.value: 5,
            FenceBehavior.TAMPERING_CONFIRMED.value: 6,
        }
        highest = max(persons, key=lambda item: priority[item["behavior"]], default=None)
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
            "behavior": highest["behavior"] if highest else FenceBehavior.NORMAL.value,
            "behavior_track_id": highest["track_id"] if highest else None,
            "persons": persons,
            "tamper": {
                "enabled": bool(settings.FENCE_TAMPER_ENABLED),
                "structure_check_enabled": bool(
                    settings.FENCE_TAMPER_STRUCTURE_ENABLED
                ),
                "reference_ready": self._structure_reference_gray is not None,
                "reference_age_seconds": round(
                    max(0.0, time.monotonic() - self._structure_reference_at),
                    1,
                )
                if self._structure_reference_at is not None
                else None,
                "pending": self._pending_tamper is not None,
                "pending_track_id": (
                    self._pending_tamper.track_id
                    if self._pending_tamper is not None
                    else None
                ),
                "action_score": round(
                    self._pending_tamper.action_score
                    if self._pending_tamper is not None
                    else max(
                        (item.tamper_action_score for item in self._person_states.values()),
                        default=0.0,
                    ),
                    4,
                ),
                "structure_change_ratio": round(
                    self._last_structure_change_ratio,
                    4,
                ),
                "last_result": (
                    self._last_tamper_behavior.value
                    if self._last_tamper_behavior is not None
                    else None
                ),
                "last_result_age_seconds": round(
                    max(0.0, time.monotonic() - self._last_tamper_at),
                    1,
                )
                if self._last_tamper_at is not None
                else None,
            },
            "missing_calibration": list(self._missing_calibration),
            "gimbal_error": self._last_gimbal_error,
        }

    async def enable(self) -> dict[str, Any]:
        async with self._control_lock:
            self._enabled = True
            self._scene_id = None
            self._clear_lock()
            self._person_states.clear()
            self._samples.clear()
            self._reset_tamper_evidence()
            self._invalidated_at = None
            self._last_pose_ros_timestamp = None
            self._last_gimbal_error = None
            self._set_state(FenceDetectionState.FINDING, "正在读取当前场景围栏")
            return self.get_status()

    async def disable(self, *, center_gimbal: bool = True) -> dict[str, Any]:
        async with self._control_lock:
            was_enabled = self._enabled
            self._enabled = False
            self._clear_lock()
            self._person_states.clear()
            self._samples.clear()
            self._reset_tamper_evidence()
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
        self._reset_tamper_evidence()

    def _reset_tamper_evidence(self) -> None:
        self._structure_reference_gray = None
        self._structure_reference_mask = None
        self._structure_reference_at = None
        self._reference_clear_hits = 0
        self._pending_tamper = None
        self._structure_change_hits = 0
        self._last_structure_change_ratio = 0.0
        self._last_tamper_behavior = None
        self._last_tamper_at = None

    def _invalidate_structure_reference(self) -> None:
        self._structure_reference_gray = None
        self._structure_reference_mask = None
        self._structure_reference_at = None
        self._reference_clear_hits = 0
        self._structure_change_hits = 0

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
            self._finite_setting("FENCE_GIMBAL_MOUNT_Z_M", "NAV_LIDAR_MOUNT_Z_M"),
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
            await self._control_step_locked(now)

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
                    self._person_states.clear()
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
            self._person_states.clear()
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
            self._person_states.clear()
            logger.info("已锁定最近围栏：id={} distance={:.3f}m", fence["id"], distance)

        try:
            status = await self._gimbal_service.status()
        except (OSError, GcuProtocolError, ValueError) as exc:
            self._last_gimbal_error = str(exc)
            self._set_state(FenceDetectionState.CALIBRATION_UNAVAILABLE, f"云台状态不可用：{exc}")
            return

        # GCU 查询可能阻塞数百毫秒；查询完成后重新取一次定位，并以同一
        # monotonic 时刻记录成对样本，供 AI 帧按采集时刻就近匹配。
        sample_pose = get_nav_state().get("robot_pose") or pose
        sampled_at = time.monotonic()
        self._samples.append(
            _SynchronizedSample(sampled_at, copy.deepcopy(sample_pose), status)
        )
        # 围栏控制没有俯仰目标；后续只发送 yaw 速度，pitch/roll 速度恒为 0。
        self._desired_pitch_deg = None
        self._last_gimbal_error = None
        await self._apply_gimbal_control(status, sampled_at)

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
            self._invalidate_structure_reference()
            self._pending_tamper = None
            control_hz = max(1.0, float(settings.FENCE_CONTROL_HZ))
            alpha = max(0.0, min(1.0, float(settings.FENCE_GIMBAL_SMOOTHING_ALPHA)))
            max_speed = float(settings.FENCE_GIMBAL_MAX_SPEED_DPS)
            yaw_velocity = max(
                -max_speed,
                min(max_speed, yaw_error * control_hz * alpha),
            )
            try:
                command_status = await self._gimbal_service.jog(
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
            command_pose = get_nav_state().get("robot_pose") or self._samples[-1].pose
            self._samples.append(
                _SynchronizedSample(
                    time.monotonic(),
                    copy.deepcopy(command_pose),
                    command_status,
                )
            )
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
            command_pose = get_nav_state().get("robot_pose") or self._samples[-1].pose
            self._samples.append(
                _SynchronizedSample(time.monotonic(), copy.deepcopy(command_pose), status)
            )

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
        self._set_state(FenceDetectionState.DETECTING, "正在检测围栏附近人员行为")

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

    def _camera_pose(self, sample: _SynchronizedSample) -> tuple[Vec3, Mat3]:
        pose = sample.pose
        status = sample.gimbal
        body_rotation = _rz(float(pose["yaw"]))
        mount_rotation = _rpy(
            float(settings.FENCE_GIMBAL_MOUNT_ROLL_DEG),
            float(settings.FENCE_GIMBAL_MOUNT_PITCH_DEG),
            float(settings.FENCE_GIMBAL_MOUNT_YAW_DEG),
        )
        gimbal_rotation = _mat_mul(
            _rz(math.radians(float(settings.FENCE_GIMBAL_YAW_SIGN) * float(status.relative_yaw_deg))),
            _ry_up(math.radians(float(settings.FENCE_GIMBAL_PITCH_SIGN) * float(status.relative_pitch_deg))),
        )
        camera_rotation = _rpy(
            float(settings.FENCE_CAMERA_ROLL_DEG),
            float(settings.FENCE_CAMERA_PITCH_DEG),
            float(settings.FENCE_CAMERA_YAW_DEG),
        )
        body_mount = _mat_mul(body_rotation, mount_rotation)
        body_mount_gimbal = _mat_mul(body_mount, gimbal_rotation)
        optical_rotation = _mat_mul(
            _mat_mul(body_mount_gimbal, camera_rotation),
            _OPTICAL_TO_FORWARD_LEFT_UP,
        )
        mount_offset = _mat_vec(
            body_rotation,
            self._mount_xyz(),
        )
        camera_offset = _mat_vec(
            body_mount_gimbal,
            (
                float(settings.FENCE_CAMERA_OFFSET_X_M),
                float(settings.FENCE_CAMERA_OFFSET_Y_M),
                float(settings.FENCE_CAMERA_OFFSET_Z_M),
            ),
        )
        origin = (
            float(pose["x"]) + mount_offset[0] + camera_offset[0],
            float(pose["y"]) + mount_offset[1] + camera_offset[1],
            float(pose["z"]) + mount_offset[2] + camera_offset[2],
        )
        return origin, optical_rotation

    def _camera_intrinsics(self, zoom_ratio: float | None) -> CameraIntrinsics:
        explicit = (
            settings.FENCE_CAMERA_FX_PX,
            settings.FENCE_CAMERA_FY_PX,
            settings.FENCE_CAMERA_CX_PX,
            settings.FENCE_CAMERA_CY_PX,
        )
        zoom = max(1.0, float(zoom_ratio or 1.0))
        if all(value is not None for value in explicit):
            calibrated_zoom = max(
                1.0,
                float(settings.FENCE_CAMERA_CALIBRATED_ZOOM_RATIO or 1.0),
            )
            scale = zoom / calibrated_zoom
            return (
                float(explicit[0]) * scale,
                float(explicit[1]) * scale,
                float(explicit[2]),
                float(explicit[3]),
            )

        width = float(settings.AI_FRAME_WIDTH)
        height = float(settings.AI_FRAME_HEIGHT)
        base_half_fov = math.radians(float(settings.AUTO_TRACK_GIMBAL_HORIZONTAL_FOV_DEG)) / 2.0
        effective_half_fov = math.atan(math.tan(base_half_fov) / zoom)
        focal = (width / 2.0) / math.tan(effective_half_fov)
        return focal, focal, width / 2.0, height / 2.0

    @staticmethod
    def _pixel_ray_world(
        pixel: tuple[float, float],
        rotation: Mat3,
        intrinsics: CameraIntrinsics,
    ) -> Vec3:
        fx, fy, cx, cy = intrinsics
        return _mat_vec(
            rotation,
            ((pixel[0] - cx) / fx, (pixel[1] - cy) / fy, 1.0),
        )

    def _ground_point_from_pixel(
        self,
        pixel: tuple[float, float],
        ground_z: float,
        origin: Vec3,
        rotation: Mat3,
        intrinsics: CameraIntrinsics,
    ) -> tuple[float, float] | None:
        ray_world = self._pixel_ray_world(pixel, rotation, intrinsics)
        if abs(ray_world[2]) <= 1e-6:
            return None
        scale = (ground_z - origin[2]) / ray_world[2]
        if scale <= 0:
            return None
        return origin[0] + scale * ray_world[0], origin[1] + scale * ray_world[1]

    def _sample_for_frame(self, frame_monotonic: float) -> _SynchronizedSample | None:
        if not self._samples:
            return None
        sample = min(self._samples, key=lambda item: abs(item.monotonic_at - frame_monotonic))
        if abs(sample.monotonic_at - frame_monotonic) > float(settings.FENCE_FRAME_SAMPLE_TOLERANCE_SECONDS):
            return None
        return sample

    def process_frame(
        self,
        *,
        detections: Iterable[Any],
        poses: Iterable[PoseObservation],
        frame_monotonic: float,
        frame_bgr: bytes | None = None,
    ) -> list[FenceBehaviorEvent]:
        if not self._enabled or self._state is not FenceDetectionState.DETECTING or self._target_fence is None:
            return []
        sample = self._sample_for_frame(frame_monotonic)
        if sample is None:
            return []
        origin, rotation = self._camera_pose(sample)
        intrinsics = self._camera_intrinsics(sample.gimbal.zoom_ratio)
        ground_z = float(sample.pose["z"])
        start_map = self._target_fence["start"]
        end_map = self._target_fence["end"]

        now = frame_monotonic
        persons = [
            item for item in detections
            if str(getattr(item, "label", getattr(item, "class_name", ""))) == "person"
            and getattr(item, "bbox", None) is not None
            and int(getattr(item, "track_id", -1)) >= 0
        ]
        pose_by_track = self._associate_poses(persons, list(poses))
        events: list[FenceBehaviorEvent] = []
        near_bboxes: list[tuple[int, int, int, int]] = []
        seen: set[int] = set()
        for person in persons:
            track_id = int(person.track_id)
            if track_id in seen:
                continue
            seen.add(track_id)
            bbox = tuple(int(value) for value in person.bbox)
            foot_pixel = ((bbox[0] + bbox[2]) / 2.0, float(bbox[3]))
            ground_point = self._ground_point_from_pixel(
                foot_pixel,
                ground_z,
                origin,
                rotation,
                intrinsics,
            )
            if ground_point is None:
                continue
            _, world_distance = closest_point_on_segment(
                ground_point[0], ground_point[1], start_map, end_map
            )
            person_state = self._person_states.get(track_id)
            if person_state is None:
                person_state = _PersonFenceState(track_id=track_id, last_seen_at=now)
                self._person_states[track_id] = person_state
            person_state.last_seen_at = now

            near = world_distance <= float(settings.FENCE_WARNING_DISTANCE_M)
            if near:
                near_bboxes.append(bbox)
                person_state.near_hits += 1
                if person_state.near_since is None:
                    person_state.near_since = now
            else:
                person_state.near_hits = 0
                person_state.contact_hits = 0
                person_state.cross_hits = 0
                person_state.tamper_hits = 0
                person_state.tamper_action_score = 0.0
                person_state.tamper_confirmed = False
                person_state.wrist_history.clear()
                person_state.near_since = None
                person_state.baseline_side = None

            pose = pose_by_track.get(track_id)
            contact = False
            crossing = False
            contact_points: list[tuple[int, tuple[float, float]]] = []
            if near and pose is not None:
                contact_points = self._contact_wrist_points(
                    pose,
                    start_map,
                    end_map,
                    ground_z,
                    origin,
                    rotation,
                    intrinsics,
                )
                contact = bool(contact_points)
                crossing = self._crossing_motion(
                    person_state,
                    pose,
                    ground_point,
                    start_map,
                    end_map,
                )
            person_state.contact_hits = person_state.contact_hits + 1 if contact else 0
            person_state.cross_hits = person_state.cross_hits + 1 if crossing else 0
            action_score, action_point = self._update_tamper_motion(
                person_state,
                pose,
                contact_points,
                now,
            )
            person_state.tamper_action_score = action_score
            action_candidate = (
                bool(settings.FENCE_TAMPER_ENABLED)
                and contact
                and pose is not None
                and pose.posture is not Posture.CLIMBING
                and action_score
                >= float(settings.FENCE_TAMPER_ACTION_SCORE_THRESHOLD)
            )
            if action_candidate:
                person_state.tamper_hits += 1
            else:
                person_state.tamper_hits = max(0, person_state.tamper_hits - 1)
                person_state.tamper_confirmed = False

            next_behavior = FenceBehavior.NORMAL
            if person_state.near_hits >= int(settings.FENCE_NEAR_STABLE_FRAMES):
                next_behavior = FenceBehavior.APPROACHING
                dwell = max(0.0, now - (person_state.near_since or now))
                if dwell >= float(settings.FENCE_DWELL_SECONDS):
                    next_behavior = FenceBehavior.DWELLING
                if person_state.contact_hits >= int(settings.FENCE_CONTACT_STABLE_FRAMES):
                    next_behavior = FenceBehavior.CONTACT
                if person_state.cross_hits >= int(settings.FENCE_CROSS_STABLE_FRAMES):
                    next_behavior = FenceBehavior.CLIMBING_SUSPECTED
                elif (
                    action_point is not None
                    and person_state.tamper_hits
                    >= int(settings.FENCE_TAMPER_STABLE_FRAMES)
                ):
                    if person_state.tamper_confirmed:
                        next_behavior = FenceBehavior.TAMPERING_CONFIRMED
                    else:
                        next_behavior = FenceBehavior.TAMPERING_SUSPECTED
                        self._start_pending_tamper(
                            person_state,
                            now=now,
                            contact_pixel=action_point,
                            person_height=max(1.0, float(bbox[3] - bbox[1])),
                        )

            if next_behavior != person_state.behavior:
                person_state.behavior = next_behavior
                event = self._event_for_transition(person_state, now)
                if event is not None:
                    events.append(event)

        confirmed = self._update_structure_evidence(
            frame_bgr=frame_bgr,
            origin=origin,
            rotation=rotation,
            intrinsics=intrinsics,
            ground_z=ground_z,
            near_bboxes=near_bboxes,
            now=now,
        )
        if confirmed is not None:
            state = self._person_states.get(confirmed.track_id)
            if state is not None:
                state.tamper_confirmed = True
                state.behavior = FenceBehavior.TAMPERING_CONFIRMED
            events.append(confirmed)

        ttl = float(settings.FENCE_TRACK_TTL_SECONDS)
        for track_id in [
            track_id
            for track_id, item in self._person_states.items()
            if now - item.last_seen_at > ttl
        ]:
            self._person_states.pop(track_id, None)
        return events

    def _associate_poses(
        self,
        persons: list[Any],
        poses: list[PoseObservation],
    ) -> dict[int, PoseObservation]:
        matches: list[tuple[float, int, int]] = []
        for person_index, person in enumerate(persons):
            bbox = tuple(int(value) for value in person.bbox)
            for pose_index, pose in enumerate(poses):
                score = _bbox_iou(bbox, pose.bbox)
                if score >= 0.1:
                    matches.append((score, person_index, pose_index))
        result: dict[int, PoseObservation] = {}
        used_persons: set[int] = set()
        used_poses: set[int] = set()
        for _, person_index, pose_index in sorted(matches, reverse=True):
            if person_index in used_persons or pose_index in used_poses:
                continue
            used_persons.add(person_index)
            used_poses.add(pose_index)
            result[int(persons[person_index].track_id)] = poses[pose_index]
        return result

    def _visible_points(self, pose: PoseObservation, indexes: tuple[int, ...]) -> list[tuple[float, float]]:
        result: list[tuple[float, float]] = []
        for index in indexes:
            if index >= len(pose.keypoints):
                continue
            point = pose.keypoints[index]
            if point.confidence >= float(settings.FENCE_KEYPOINT_CONFIDENCE):
                result.append((float(point.x), float(point.y)))
        return result

    def _contact_wrist_points(
        self,
        pose: PoseObservation,
        start: dict[str, Any],
        end: dict[str, Any],
        ground_z: float,
        origin: Vec3,
        rotation: Mat3,
        intrinsics: CameraIntrinsics,
    ) -> list[tuple[int, tuple[float, float]]]:
        wrists: list[tuple[int, tuple[float, float]]] = []
        for index in (LEFT_WRIST, RIGHT_WRIST):
            if index >= len(pose.keypoints):
                continue
            point = pose.keypoints[index]
            if point.confidence >= float(settings.FENCE_KEYPOINT_CONFIDENCE):
                wrists.append((index, (float(point.x), float(point.y))))
        if not wrists:
            return []
        segment_dx = float(end["x"]) - float(start["x"])
        segment_dy = float(end["y"]) - float(start["y"])
        length = math.hypot(segment_dx, segment_dy)
        if length <= 1e-6:
            return []
        normal_x, normal_y = -segment_dy / length, segment_dx / length
        numerator = (
            normal_x * (float(start["x"]) - origin[0])
            + normal_y * (float(start["y"]) - origin[1])
        )
        result: list[tuple[int, tuple[float, float]]] = []
        for index, wrist in wrists:
            ray = self._pixel_ray_world(wrist, rotation, intrinsics)
            denominator = normal_x * ray[0] + normal_y * ray[1]
            if abs(denominator) <= 1e-6:
                continue
            scale = numerator / denominator
            if scale <= 0:
                continue
            intersection = (
                origin[0] + scale * ray[0],
                origin[1] + scale * ray[1],
                origin[2] + scale * ray[2],
            )
            if intersection[2] < ground_z - 0.15:
                continue
            _, segment_distance = closest_point_on_segment(
                intersection[0], intersection[1], start, end
            )
            if segment_distance <= float(settings.FENCE_CONTACT_SEGMENT_MARGIN_M):
                result.append((index, wrist))
        return result

    def _update_tamper_motion(
        self,
        state: _PersonFenceState,
        pose: PoseObservation | None,
        contact_points: list[tuple[int, tuple[float, float]]],
        now: float,
    ) -> tuple[float, tuple[float, float] | None]:
        window = max(0.2, float(settings.FENCE_TAMPER_WINDOW_SECONDS))
        cutoff = now - window
        for history in state.wrist_history.values():
            while history and history[0][0] < cutoff:
                history.popleft()
        if pose is None or not contact_points:
            return 0.0, None

        x1, y1, x2, y2 = pose.bbox
        height = max(1.0, float(y2 - y1))
        center_x = (x1 + x2) / 2.0
        center_y = (y1 + y2) / 2.0
        current_by_index = dict(contact_points)
        for index, point in contact_points:
            history = state.wrist_history.setdefault(index, deque())
            history.append(
                (
                    now,
                    (point[0] - center_x) / height,
                    (point[1] - center_y) / height,
                )
            )

        best_score = 0.0
        best_point: tuple[float, float] | None = None
        for index, history in state.wrist_history.items():
            score, _, _ = repetitive_motion_score(
                history,
                min_duration_seconds=float(
                    settings.FENCE_TAMPER_MIN_DURATION_SECONDS
                ),
                min_travel_ratio=float(settings.FENCE_TAMPER_MIN_TRAVEL_RATIO),
                min_reversals=int(settings.FENCE_TAMPER_MIN_REVERSALS),
            )
            if score > best_score and index in current_by_index:
                best_score = score
                best_point = current_by_index[index]
        return best_score, best_point

    def _start_pending_tamper(
        self,
        state: _PersonFenceState,
        *,
        now: float,
        contact_pixel: tuple[float, float],
        person_height: float,
    ) -> None:
        grace = max(0.5, float(settings.FENCE_TAMPER_CONFIRM_GRACE_SECONDS))
        current = self._pending_tamper
        if current is not None and current.track_id != state.track_id:
            if state.tamper_action_score <= current.action_score:
                return
            started_at = now
        else:
            started_at = current.started_at if current is not None else now
        self._pending_tamper = _PendingTamper(
            track_id=state.track_id,
            started_at=started_at,
            last_action_at=now,
            expires_at=now + grace,
            contact_pixel=contact_pixel,
            person_height=person_height,
            action_score=state.tamper_action_score,
        )

    @staticmethod
    def _world_point_to_pixel(
        point: Vec3,
        origin: Vec3,
        rotation: Mat3,
        intrinsics: CameraIntrinsics,
    ) -> tuple[float, float] | None:
        delta = tuple(point[index] - origin[index] for index in range(3))
        # _camera_pose returns the optical-to-world rotation, so projection uses
        # its transpose to recover camera x/y/z.
        camera = tuple(
            sum(rotation[row][column] * delta[row] for row in range(3))
            for column in range(3)
        )
        if camera[2] <= 0.05:
            return None
        fx, fy, cx, cy = intrinsics
        return (
            fx * camera[0] / camera[2] + cx,
            fy * camera[1] / camera[2] + cy,
        )

    def _fence_image_mask(
        self,
        *,
        origin: Vec3,
        rotation: Mat3,
        intrinsics: CameraIntrinsics,
        ground_z: float,
    ) -> np.ndarray | None:
        if self._target_fence is None:
            return None
        raw_start = self._target_fence["start"]
        raw_end = self._target_fence["end"]
        start_x, start_y = float(raw_start["x"]), float(raw_start["y"])
        end_x, end_y = float(raw_end["x"]), float(raw_end["y"])
        segment_dx, segment_dy = end_x - start_x, end_y - start_y
        segment_length = math.hypot(segment_dx, segment_dy)
        if segment_length <= 1e-6:
            return None
        # A hand-drawn fence may be much longer than the current field of view.
        # Project only the eight-metre neighborhood around the point aimed at by
        # the gimbal so remote endpoints behind the camera do not invalidate it.
        if self._target_point is not None:
            along = max(
                0.0,
                min(
                    segment_length,
                    (
                        (self._target_point["x"] - start_x) * segment_dx
                        + (self._target_point["y"] - start_y) * segment_dy
                    )
                    / segment_length,
                ),
            )
            local_start = max(0.0, along - 4.0) / segment_length
            local_end = min(segment_length, along + 4.0) / segment_length
            start = {
                "x": start_x + segment_dx * local_start,
                "y": start_y + segment_dy * local_start,
            }
            end = {
                "x": start_x + segment_dx * local_end,
                "y": start_y + segment_dy * local_end,
            }
        else:
            start = raw_start
            end = raw_end
        top_z = ground_z + max(
            0.5,
            float(settings.FENCE_TAMPER_STRUCTURE_HEIGHT_M),
        )
        world_points: tuple[Vec3, ...] = (
            (float(start["x"]), float(start["y"]), ground_z),
            (float(end["x"]), float(end["y"]), ground_z),
            (float(end["x"]), float(end["y"]), top_z),
            (float(start["x"]), float(start["y"]), top_z),
        )
        projected = [
            self._world_point_to_pixel(point, origin, rotation, intrinsics)
            for point in world_points
        ]
        if any(point is None for point in projected):
            return None
        width = int(settings.AI_FRAME_WIDTH)
        height = int(settings.AI_FRAME_HEIGHT)
        polygon = np.asarray(
            [
                (
                    int(round(max(-width * 4, min(width * 5, point[0])))),
                    int(round(max(-height * 4, min(height * 5, point[1])))),
                )
                for point in projected
                if point is not None
            ],
            dtype=np.int32,
        )
        mask = np.zeros((height, width), dtype=np.uint8)
        cv2.fillConvexPoly(mask, polygon, 255)
        if int(cv2.countNonZero(mask)) < int(
            settings.FENCE_TAMPER_STRUCTURE_MIN_EDGE_PIXELS
        ):
            return None
        return mask

    @staticmethod
    def _gray_frame(frame_bgr: bytes) -> np.ndarray | None:
        width = int(settings.AI_FRAME_WIDTH)
        height = int(settings.AI_FRAME_HEIGHT)
        if len(frame_bgr) != width * height * 3:
            return None
        frame = np.frombuffer(frame_bgr, dtype=np.uint8).reshape((height, width, 3))
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return cv2.GaussianBlur(gray, (3, 3), 0)

    def _structure_change_ratio(
        self,
        current_gray: np.ndarray,
        current_mask: np.ndarray,
        near_bboxes: list[tuple[int, int, int, int]],
        pending: _PendingTamper,
    ) -> float | None:
        reference_gray = self._structure_reference_gray
        reference_mask = self._structure_reference_mask
        if reference_gray is None or reference_mask is None:
            return None

        reference_float = reference_gray.astype(np.float32)
        current_float = current_gray.astype(np.float32)
        window = cv2.createHanningWindow(
            (reference_gray.shape[1], reference_gray.shape[0]),
            cv2.CV_32F,
        )
        shift, response = cv2.phaseCorrelate(
            reference_float,
            current_float,
            window,
        )
        if (
            not math.isfinite(shift[0])
            or not math.isfinite(shift[1])
            or response < 0.03
            or math.hypot(*shift)
            > float(settings.FENCE_TAMPER_ALIGN_MAX_SHIFT_PX)
        ):
            return None

        transform = np.asarray(
            ((1.0, 0.0, -shift[0]), (0.0, 1.0, -shift[1])),
            dtype=np.float32,
        )
        size = (reference_gray.shape[1], reference_gray.shape[0])
        aligned_gray = cv2.warpAffine(
            current_gray,
            transform,
            size,
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        )
        aligned_mask = cv2.warpAffine(
            current_mask,
            transform,
            size,
            flags=cv2.INTER_NEAREST,
            borderMode=cv2.BORDER_CONSTANT,
        )
        valid_mask = cv2.bitwise_and(reference_mask, aligned_mask)

        patch_radius = max(
            24,
            int(
                round(
                    pending.person_height
                    * float(settings.FENCE_TAMPER_STRUCTURE_PATCH_RATIO)
                )
            ),
        )
        patch_mask = np.zeros_like(valid_mask)
        patch_center = (
            int(round(pending.contact_pixel[0] - shift[0])),
            int(round(pending.contact_pixel[1] - shift[1])),
        )
        cv2.circle(patch_mask, patch_center, patch_radius, 255, thickness=-1)
        valid_mask = cv2.bitwise_and(valid_mask, patch_mask)

        for bbox in near_bboxes:
            padding = max(6, int(round((bbox[3] - bbox[1]) * 0.08)))
            left = max(0, int(round(bbox[0] - shift[0])) - padding)
            top = max(0, int(round(bbox[1] - shift[1])) - padding)
            right = min(size[0], int(round(bbox[2] - shift[0])) + padding)
            bottom = min(size[1], int(round(bbox[3] - shift[1])) + padding)
            valid_mask[top:bottom, left:right] = 0

        reference_edges = cv2.Canny(reference_gray, 60, 150)
        current_edges = cv2.Canny(aligned_gray, 60, 150)
        reference_edges = cv2.bitwise_and(reference_edges, valid_mask)
        reference_count = int(cv2.countNonZero(reference_edges))
        if reference_count < int(settings.FENCE_TAMPER_STRUCTURE_MIN_EDGE_PIXELS):
            return None
        current_dilated = cv2.dilate(
            current_edges,
            np.ones((3, 3), dtype=np.uint8),
            iterations=1,
        )
        lost_edges = cv2.bitwise_and(
            reference_edges,
            cv2.bitwise_not(current_dilated),
        )
        return min(1.0, cv2.countNonZero(lost_edges) / reference_count)

    def _update_structure_evidence(
        self,
        *,
        frame_bgr: bytes | None,
        origin: Vec3,
        rotation: Mat3,
        intrinsics: CameraIntrinsics,
        ground_z: float,
        near_bboxes: list[tuple[int, int, int, int]],
        now: float,
    ) -> FenceBehaviorEvent | None:
        pending = self._pending_tamper
        if pending is not None and now > pending.expires_at:
            self._pending_tamper = None
            self._structure_change_hits = 0
            pending = None
        if (
            not bool(settings.FENCE_TAMPER_ENABLED)
            or not bool(settings.FENCE_TAMPER_STRUCTURE_ENABLED)
            or frame_bgr is None
        ):
            return None

        current_gray = self._gray_frame(frame_bgr)
        current_mask = self._fence_image_mask(
            origin=origin,
            rotation=rotation,
            intrinsics=intrinsics,
            ground_z=ground_z,
        )
        if current_gray is None or current_mask is None:
            return None

        if pending is not None and self._structure_reference_gray is not None:
            ratio = self._structure_change_ratio(
                current_gray,
                current_mask,
                near_bboxes,
                pending,
            )
            if ratio is not None:
                self._last_structure_change_ratio = ratio
                if ratio >= float(
                    settings.FENCE_TAMPER_STRUCTURE_CHANGE_THRESHOLD
                ):
                    self._structure_change_hits += 1
                else:
                    self._structure_change_hits = 0
            if self._structure_change_hits >= int(
                settings.FENCE_TAMPER_STRUCTURE_STABLE_FRAMES
            ):
                event = self._confirmed_tamper_event(pending, now)
                self._pending_tamper = None
                self._invalidate_structure_reference()
                return event

        if self._pending_tamper is None and not near_bboxes:
            self._reference_clear_hits += 1
            if self._reference_clear_hits >= int(
                settings.FENCE_TAMPER_REFERENCE_CLEAR_FRAMES
            ):
                self._structure_reference_gray = current_gray.copy()
                self._structure_reference_mask = current_mask.copy()
                self._structure_reference_at = now
                self._last_structure_change_ratio = 0.0
        else:
            self._reference_clear_hits = 0
        return None

    def _confirmed_tamper_event(
        self,
        pending: _PendingTamper,
        now: float,
    ) -> FenceBehaviorEvent | None:
        state = self._person_states.get(pending.track_id)
        if state is not None:
            state.tamper_confirmed = True
            state.behavior = FenceBehavior.TAMPERING_CONFIRMED
            last_at = state.last_events.get(FenceBehavior.TAMPERING_CONFIRMED, 0.0)
            state.last_events[FenceBehavior.TAMPERING_CONFIRMED] = now
        else:
            last_at = 0.0
        self._last_tamper_behavior = FenceBehavior.TAMPERING_CONFIRMED
        self._last_tamper_at = now
        if now - last_at < float(settings.FENCE_ALERT_COOLDOWN_SECONDS):
            return None
        threshold = max(
            0.01,
            float(settings.FENCE_TAMPER_STRUCTURE_CHANGE_THRESHOLD),
        )
        structure_score = min(1.0, self._last_structure_change_ratio / threshold)
        confidence = min(
            0.99,
            0.55 + 0.25 * pending.action_score + 0.20 * structure_score,
        )
        return FenceBehaviorEvent(
            behavior=FenceBehavior.TAMPERING_CONFIRMED,
            track_id=pending.track_id,
            confidence=confidence,
            duration_seconds=max(0.0, now - pending.started_at),
            fence_id=str(self._target_fence["id"]),
            action_score=pending.action_score,
            structure_change_ratio=self._last_structure_change_ratio,
            evidence_level="action_and_structure",
        )

    def _crossing_motion(
        self,
        state: _PersonFenceState,
        pose: PoseObservation,
        ground_point: tuple[float, float],
        start: dict[str, Any],
        end: dict[str, Any],
    ) -> bool:
        margin = float(settings.FENCE_CROSS_MARGIN_M)
        foot_side_value = _signed_line_distance(
            ground_point,
            (float(start["x"]), float(start["y"])),
            (float(end["x"]), float(end["y"])),
        )
        if state.baseline_side is None and abs(foot_side_value) >= margin:
            state.baseline_side = 1 if foot_side_value > 0 else -1
        if state.baseline_side is None:
            return False
        if (
            abs(foot_side_value) < margin
            or (1 if foot_side_value > 0 else -1) == state.baseline_side
        ):
            return False
        return (
            not bool(settings.FENCE_CROSS_REQUIRE_CLIMBING_POSTURE)
            or pose.posture is Posture.CLIMBING
        )

    def _event_for_transition(
        self,
        state: _PersonFenceState,
        now: float,
    ) -> FenceBehaviorEvent | None:
        if state.behavior not in {
            FenceBehavior.DWELLING,
            FenceBehavior.CONTACT,
            FenceBehavior.CLIMBING_SUSPECTED,
            FenceBehavior.TAMPERING_SUSPECTED,
        }:
            return None
        last_at = state.last_events.get(state.behavior, 0.0)
        if now - last_at < float(settings.FENCE_ALERT_COOLDOWN_SECONDS):
            return None
        state.last_events[state.behavior] = now
        confidence = {
            FenceBehavior.DWELLING: 0.7,
            FenceBehavior.CONTACT: 0.8,
            FenceBehavior.CLIMBING_SUSPECTED: 0.9,
            FenceBehavior.TAMPERING_SUSPECTED: min(
                0.9,
                0.55 + 0.35 * state.tamper_action_score,
            ),
        }[state.behavior]
        if state.behavior is FenceBehavior.TAMPERING_SUSPECTED:
            self._last_tamper_behavior = state.behavior
            self._last_tamper_at = now
        return FenceBehaviorEvent(
            behavior=state.behavior,
            track_id=state.track_id,
            confidence=confidence,
            duration_seconds=max(0.0, now - (state.near_since or now)),
            fence_id=str(self._target_fence["id"]),
            action_score=state.tamper_action_score,
            evidence_level=(
                "repetitive_contact"
                if state.behavior is FenceBehavior.TAMPERING_SUSPECTED
                else "behavior"
            ),
        )


_fence_detection_service: FenceDetectionService | None = None


def get_fence_detection_service() -> FenceDetectionService | None:
    return _fence_detection_service


def set_fence_detection_service(service: FenceDetectionService | None) -> None:
    global _fence_detection_service
    _fence_detection_service = service
