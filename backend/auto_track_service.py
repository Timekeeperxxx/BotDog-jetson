"""
自动跟踪主服务（状态机闭环重构版）。

7态闭环状态链：
    DISABLED → IDLE → DETECTING → FOLLOWING → LOST → FOLLOWING（重发现）
                                             └─超时→ IDLE
    FOLLOWING/LOST → STOPPED → IDLE
    任意 → PAUSED（人工接管）

职责边界：
- 以 YOLO track_id 为主键管理目标身份
- 维护 7 态跟踪状态机（任何时刻都能明确回答：有没有目标、是谁、为什么跟、什么时候停）
- 通过 ControlService 下发跟踪控制命令
- 广播跟踪状态事件
- 触发抓拍（锁定时 + 可选终止时）
- 接入 StrangerPolicy：已知人员不触发跟踪

设计原则：
- 状态转换集中在 process_frame() 一处，避免散落
- 不直接调用 robot_adapter，所有命令经过 ControlService
- 数据库/广播失败不阻塞控制主流程
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

from .auto_track_detection import AutoTrackDetectionMixin, _FallbackTrack
from .auto_track_runtime import AutoTrackRuntimeMixin
from .auto_track_snapshot import _save_snapshot_to_disk
from .config import settings
from .logging_config import logger
from .tracking_types import (
    AutoTrackState,
    TrackStopReason,
    TargetCandidate,
    ActiveTarget,
    DetectionResult,
    ControlOwner,
)
from .follow_decision_engine import FollowDecisionEngine
from .gimbal_follow_controller import GimbalGuidance, calculate_gimbal_guidance
from .zone_service import ZoneService

if TYPE_CHECKING:
    from .control_service import ControlService
    from .state_machine import StateMachine
    from .ws_event_broadcaster import EventBroadcaster
    from .target_manager import TargetManager
    from .control_arbiter import ControlArbiter
    from .z2mini_gimbal import Z2MiniGimbal


class AutoTrackService(AutoTrackRuntimeMixin, AutoTrackDetectionMixin):
    """
    自动跟踪主服务（7态闭环版）。

    与 AIWorker 的职责分工：
    - AIWorker 负责：视频采集 + 调用检测器（YOLO track） + 调用本服务 + 广播 AI_STATUS
    - AutoTrackService 负责：目标状态机 + 锁定 + 区内判断 + 控制决策 + 抓拍 + 事件广播
    """

    def __init__(
        self,
        *,
        zone_service: ZoneService,
        control_service: "ControlService",
        event_broadcaster: "EventBroadcaster",
        state_machine: "StateMachine",
        session_factory,
        snapshot_dir: Path,
        frame_width: int,
        frame_height: int,
        stable_hits: int = 3,
        reset_misses: int = 3,
        out_of_zone_frames: int = 10,
        lost_timeout_frames: int = 30,
        video_lost_grace_seconds: float = 8.0,
        command_interval_ms: float = 200.0,
        yaw_deadband_px: int = 80,
        forward_area_ratio: float = 0.15,
        anchor_y_stop_ratio: float = 0.20,
        stop_snapshot_enabled: bool = True,
        default_enabled: bool = False,
        yaw_pulse_ms: float = 0.0,
        gimbal_enabled: bool = False,
        gimbal_body_deadband_deg: float = 5.0,
        gimbal_forward_deadband_deg: float = 5.0,
        gimbal_horizontal_fov_deg: float = 60.0,
        gimbal_servo_gain: float = 0.75,
        gimbal_pixel_deadband_px: int = 20,
        gimbal_command_interval_ms: float = 180.0,
        gimbal_min_body_vyaw: float = 0.10,
        gimbal_service: "Z2MiniGimbal | None" = None,
        # 阶段 2 可选依赖
        target_manager: "TargetManager | None" = None,
        control_arbiter: "ControlArbiter | None" = None,
    ) -> None:
        self._zone_service = zone_service
        self._control_service = control_service
        self._event_broadcaster = event_broadcaster
        self._state_machine = state_machine
        self._session_factory = session_factory
        self._snapshot_dir = snapshot_dir
        self._frame_width = frame_width
        self._frame_height = frame_height

        self._stable_hits = max(5, int(stable_hits))
        self._helmet_person_abort_frames = 5
        self._reset_misses = reset_misses
        self._out_of_zone_frames = out_of_zone_frames
        self._lost_timeout_frames = lost_timeout_frames
        self._video_lost_grace_seconds = max(0.0, float(video_lost_grace_seconds))
        self._stop_snapshot_enabled = stop_snapshot_enabled

        # 运行时开关
        self._enabled: bool = default_enabled
        self._standalone_enabled: bool = default_enabled
        self._paused: bool = False
        self._state: AutoTrackState = (
            AutoTrackState.IDLE if default_enabled else AutoTrackState.DISABLED
        )

        # ── 候选目标（DETECTING 阶段） ──────────────────────────────────────
        # key = track_id, value = TargetCandidate
        self._candidates: dict[int, TargetCandidate] = {}
        # IOU 降级计数器（YOLO 无 track_id 时使用）
        self._iou_id_counter: int = 0
        self._last_iou_bbox: Optional[tuple[int, int, int, int]] = None
        self._fallback_tracks: dict[int, _FallbackTrack] = {}
        self._fallback_iou_threshold: float = 0.15
        self._fallback_max_age_frames: int = max(15, lost_timeout_frames)

        # ── 活跃目标（FOLLOWING / LOST 阶段） ──────────────────────────────
        self._active_target: Optional[ActiveTarget] = None
        self._control_bbox: Optional[tuple[int, int, int, int]] = None
        self._stop_reason: Optional[TrackStopReason] = None

        # 阶段 2 多目标管理
        self._target_manager: "TargetManager | None" = target_manager
        self._control_arbiter: "ControlArbiter | None" = control_arbiter

        # 决策引擎
        self._decision_engine = FollowDecisionEngine(
            yaw_deadband_px=yaw_deadband_px,
            forward_area_ratio=forward_area_ratio,
            anchor_y_stop_ratio=anchor_y_stop_ratio,
            command_interval_ms=command_interval_ms,
        )
        self._yaw_deadband_px = yaw_deadband_px
        self._forward_area_ratio = forward_area_ratio
        self._anchor_y_stop_ratio = anchor_y_stop_ratio
        self._yaw_pulse_s: float = yaw_pulse_ms / 1000.0
        self._gimbal_enabled = bool(gimbal_enabled)
        self._gimbal_service = gimbal_service
        self._gimbal_body_deadband_deg = max(0.5, float(gimbal_body_deadband_deg))
        self._gimbal_forward_deadband_deg = max(
            0.5,
            min(15.0, float(gimbal_forward_deadband_deg)),
        )
        self._gimbal_horizontal_fov_deg = max(10.0, min(170.0, float(gimbal_horizontal_fov_deg)))
        self._gimbal_servo_gain = max(0.0, min(1.5, float(gimbal_servo_gain)))
        self._gimbal_pixel_deadband_px = max(0, int(gimbal_pixel_deadband_px))
        self._gimbal_command_interval_s = max(0.05, float(gimbal_command_interval_ms) / 1000.0)
        self._gimbal_min_body_vyaw = max(0.05, min(0.8, float(gimbal_min_body_vyaw)))
        self._last_gimbal_command_time = 0.0
        self._last_gimbal_yaw_velocity_dps = 0.0
        self._gimbal_centered_hits = 0
        self._body_turn_active = False
        self._body_aligned_hits = 0
        self._initial_alignment_complete = False
        self._tracking_phase = "IDLE"
        self._gimbal_alignment_mode_set = False
        self._alignment_turn_started_at: float | None = None
        self._alignment_speed_override: float | None = None
        self._alignment_motion_confirmed = False
        self._alignment_motion_failed = False
        self._observed_body_yaw_speed_dps: float | None = None
        self._alignment_command_vyaw: float | None = None
        self._gimbal_connected = False
        self._camera_yaw_deg: float | None = None
        self._body_heading_error_deg: float | None = None
        self._gimbal_target_yaw_deg: float | None = None
        self._gimbal_error: str | None = None
        self._last_gimbal_error_log_time = 0.0

        # 调试状态
        self._last_status_broadcast: float = 0.0
        self._last_command: Optional[str] = None
        self._last_decision_reason: Optional[str] = None
        self._frames_processed: int = 0
        self._video_lost_since: Optional[float] = None
        self._video_lost_reason: Optional[str] = None
        self._event_send_timeout_s = max(0.005, float(settings.AI_EVENT_SEND_TIMEOUT_SECONDS))
        self._overlay_interval_s = max(0.05, float(settings.AUTO_TRACK_OVERLAY_INTERVAL_SECONDS))
        self._last_overlay_broadcast: float = 0.0

        # 决策日志
        self._decision_log_file = None
        self._decision_log_path: Optional[Path] = None

        logger.info(
            f"[AutoTrackService] 初始化完成，默认启用={default_enabled}，"
            f"stable_hits={self._stable_hits}，lost_timeout_frames={lost_timeout_frames}，"
            f"yaw_pulse_ms={yaw_pulse_ms}，gimbal_follow={self._gimbal_enabled}"
        )

    # ─── 公共控制接口 ────────────────────────────────────────────────────────

    def enable(self) -> None:
        """手动启用自动跟踪：不依赖巡检/导航任务也可以独立跟踪。"""
        self._enabled = True
        self._standalone_enabled = True
        self._paused = False
        if self._state == AutoTrackState.DISABLED:
            self._state = AutoTrackState.IDLE
        logger.info("[AutoTrackService] 自动跟踪已启用")

    def enable_for_navigation(self) -> None:
        """导航联动启用：只在存在导航/巡检任务上下文时处理跟踪帧。"""
        self._enabled = True
        self._paused = False
        if self._state == AutoTrackState.DISABLED:
            self._state = AutoTrackState.IDLE
        logger.info("[AutoTrackService] 自动跟踪已启用（导航联动）")

    def disable(self) -> None:
        if self._enabled:
            logger.info("[AutoTrackService] 自动跟踪已禁用")
        self._enabled = False
        self._standalone_enabled = False
        self._paused = False
        self._do_stop(TrackStopReason.DISABLED, send_stop_command=True)
        self._state = AutoTrackState.DISABLED
        if self._control_arbiter:
            self._control_arbiter.release_control(ControlOwner.AUTO_TRACK)
        if self._gimbal_enabled and self._gimbal_service is not None:
            asyncio.create_task(self._stop_gimbal_yaw())

    def pause(self) -> None:
        if not self._enabled:
            return
        self._paused = True
        self._state = AutoTrackState.PAUSED
        logger.info("[AutoTrackService] 自动跟踪已暂停")

    def resume(self) -> None:
        if not self._enabled:
            return
        self._paused = False
        if self._active_target is not None:
            self._state = AutoTrackState.FOLLOWING
        else:
            self._state = AutoTrackState.IDLE
        logger.info("[AutoTrackService] 自动跟踪已恢复")

    def stop(self, reason: TrackStopReason, send_stop_command: bool = True) -> None:
        self._do_stop(reason, send_stop_command=send_stop_command)

    def update_params(self, key: str, value: Any) -> bool:
        """
        热更新系统参数（支持从数据库前台设置面板修改传入）。
        """
        try:
            if key == "auto_track_stable_hits":
                self._stable_hits = max(5, int(value))
                logger.info(f"[AutoTrackService] 热更新 stable_hits={self._stable_hits}")
            elif key == "auto_track_enabled":
                enabled = str(value).strip().lower() in {"1", "true", "yes", "on"}
                self.enable() if enabled else self.disable()
            elif key == "auto_track_out_of_zone_frames":
                self._out_of_zone_frames = max(1, int(value))
                logger.info(f"[AutoTrackService] 热更新 out_of_zone_frames={self._out_of_zone_frames}")
            elif key == "auto_track_lost_timeout_frames":
                self._lost_timeout_frames = int(value)
                logger.info(f"[AutoTrackService] 热更新 lost_timeout_frames={self._lost_timeout_frames}")
            elif key == "auto_track_video_lost_grace_seconds":
                self._video_lost_grace_seconds = max(0.0, float(value))
                logger.info(f"[AutoTrackService] 热更新 video_lost_grace_seconds={self._video_lost_grace_seconds}")
            elif key == "auto_track_overlay_interval_seconds":
                self._overlay_interval_s = max(0.05, float(value))
                logger.info(f"[AutoTrackService] 热更新 overlay_interval_s={self._overlay_interval_s}")
            elif key == "auto_track_command_interval_ms":
                self._decision_engine._command_interval_s = max(0.0, float(value)) / 1000.0
                logger.info(f"[AutoTrackService] 热更新 command_interval_ms={value}")
            elif key == "auto_track_yaw_deadband_px":
                self._yaw_deadband_px = int(value)
                self._decision_engine._yaw_deadband_px = self._yaw_deadband_px
                logger.info(f"[AutoTrackService] 热更新 yaw_deadband_px={self._yaw_deadband_px}")
            elif key == "auto_track_forward_area_ratio":
                self._forward_area_ratio = float(value)
                self._decision_engine._forward_area_ratio = self._forward_area_ratio
                self._decision_engine._resume_area_ratio = self._forward_area_ratio * 0.85
                logger.info(f"[AutoTrackService] 热更新 forward_area_ratio={self._forward_area_ratio}")
            elif key == "auto_track_anchor_y_stop_ratio":
                self._anchor_y_stop_ratio = float(value)
                self._decision_engine._anchor_y_stop_ratio = self._anchor_y_stop_ratio
                logger.info(f"[AutoTrackService] 热更新 anchor_y_stop_ratio={self._anchor_y_stop_ratio}")
            elif key == "auto_track_stop_snapshot_enabled":
                self._stop_snapshot_enabled = str(value).strip().lower() in {"1", "true", "yes", "on"}
                logger.info(f"[AutoTrackService] 热更新 stop_snapshot_enabled={self._stop_snapshot_enabled}")
            elif key == "auto_track_yaw_pulse_ms":
                self._yaw_pulse_s = max(0.0, float(value)) / 1000.0
                logger.info(f"[AutoTrackService] 热更新 yaw_pulse_ms={value}")
            elif key == "auto_track_gimbal_enabled":
                self._gimbal_enabled = str(value).strip().lower() in {"1", "true", "yes", "on"}
                logger.info(f"[AutoTrackService] 热更新 gimbal_enabled={self._gimbal_enabled}")
            elif key == "auto_track_gimbal_body_deadband_deg":
                self._gimbal_body_deadband_deg = max(0.5, float(value))
            elif key == "auto_track_gimbal_forward_deadband_deg":
                self._gimbal_forward_deadband_deg = max(
                    0.5,
                    min(15.0, float(value)),
                )
            elif key == "auto_track_gimbal_horizontal_fov_deg":
                self._gimbal_horizontal_fov_deg = max(10.0, min(170.0, float(value)))
            elif key == "auto_track_gimbal_servo_gain":
                self._gimbal_servo_gain = max(0.0, min(1.5, float(value)))
            elif key == "auto_track_gimbal_pixel_deadband_px":
                self._gimbal_pixel_deadband_px = max(0, int(value))
            elif key == "auto_track_gimbal_command_interval_ms":
                self._gimbal_command_interval_s = max(0.05, float(value) / 1000.0)
            elif key == "auto_track_gimbal_min_body_vyaw":
                self._gimbal_min_body_vyaw = max(0.05, min(0.8, float(value)))
            elif key in {"auto_track_vx", "auto_track_vyaw"}:
                # 速度在每次下发命令时直接从 settings 读取，路由已完成同步。
                logger.info(f"[AutoTrackService] 热更新 {key}={value}")
            else:
                logger.debug(f"[AutoTrackService] 忽略未知参数更新: {key}={value}")
                return False
            return True
        except Exception as e:
            logger.error(f"[AutoTrackService] 热更新参数 {key}={value} 失败: {e}")
            return False

    def get_status(self) -> dict:
        target_info = None
        if self._active_target:
            t = self._active_target
            target_info = {
                "track_id": t.track_id,
                "bbox": t.bbox,
                "anchor_point": t.anchor_point,
                "inside_zone": t.inside_zone,
                "lost_count": t.lost_count,
                "out_of_zone_count": t.out_of_zone_count,
                "helmet_hits": t.helmet_hits,
            }
        arbiter_status = (
            self._control_arbiter.get_status()
            if self._control_arbiter else {"owner": "N/A"}
        )
        return {
            "enabled": self._enabled,
            "paused": self._paused,
            "standalone_enabled": self._standalone_enabled,
            "state": self._state.value,
            "tracking_phase": self._tracking_phase,
            "active_target": target_info,
            "stop_reason": self._stop_reason.value if self._stop_reason else None,
            "last_command": self._last_command,
            "frames_processed": self._frames_processed,
            "candidate_count": len(self._candidates),
            "stable_hits_threshold": self._stable_hits,
            "video_lost": self._video_lost_since is not None,
            "video_lost_reason": self._video_lost_reason,
            "control_arbiter": arbiter_status,
            "gimbal_tracking_enabled": self._gimbal_enabled,
            "gimbal_connected": self._gimbal_connected,
            "camera_yaw_deg": self._camera_yaw_deg,
            "camera_forward_deadband_deg": self._gimbal_forward_deadband_deg,
            "body_heading_error_deg": self._body_heading_error_deg,
            "gimbal_target_yaw_deg": self._gimbal_target_yaw_deg,
            "gimbal_error": self._gimbal_error,
            "observed_body_yaw_speed_dps": self._observed_body_yaw_speed_dps,
            "alignment_command_vyaw": self._alignment_command_vyaw,
            "alignment_motion_confirmed": self._alignment_motion_confirmed,
            "alignment_motion_failed": self._alignment_motion_failed,
        }

    async def notify_video_lost(self, reason: str = "unknown") -> None:
        """
        RTSP/解码链路短暂断流。

        这里不能按“目标丢失”处理：目标没变，只是没有新画面。
        因此先停住底盘并冻结当前跟踪状态；超过宽限时间才释放导航联动。
        """
        if not self._enabled or self._paused or self._active_target is None:
            return

        now = time.monotonic()
        if self._video_lost_since is None:
            self._video_lost_since = now
            self._video_lost_reason = reason
            self._state = AutoTrackState.LOST
            self._last_decision_reason = f"VIDEO_LOST: {reason}"
            await self._send_command_safe("stop")
            await self._broadcast_event("AUTO_TRACK_VIDEO_LOST", {
                "track_id": self._active_target.track_id,
                "reason": reason,
                "grace_seconds": self._video_lost_grace_seconds,
            })
            logger.warning(
                f"[AutoTrackService] 视频流断开，冻结自动跟踪：track_id={self._active_target.track_id} "
                f"reason={reason} grace={self._video_lost_grace_seconds:.1f}s"
            )
            return

        if now - self._video_lost_since < self._video_lost_grace_seconds:
            return

        logger.warning(
            f"[AutoTrackService] 视频流断开超过宽限时间，停止跟踪："
            f"elapsed={now - self._video_lost_since:.1f}s"
        )
        await self._stop_without_snapshot(TrackStopReason.VIDEO_LOST, reason)

    async def notify_video_restored(self) -> None:
        """视频流恢复：保留目标状态，交给后续检测帧重新匹配。"""
        if self._video_lost_since is None:
            return
        elapsed = time.monotonic() - self._video_lost_since
        self._video_lost_since = None
        reason = self._video_lost_reason
        self._video_lost_reason = None
        await self._broadcast_event("AUTO_TRACK_VIDEO_RESTORED", {
            "elapsed_seconds": round(elapsed, 2),
            "reason": reason,
        })
        logger.info(
            f"[AutoTrackService] 视频流恢复，继续自动跟踪匹配：elapsed={elapsed:.1f}s reason={reason}"
        )

    # ─── 核心处理入口 ────────────────────────────────────────────────────────

    async def process_frame(
        self,
        detections: list[DetectionResult],
        frame: bytes,
        frame_index: int,
        current_task_id: Optional[int | str] = None,
        t_start: float = 0.0,
        t_detect_end: float = 0.0,
    ) -> None:
        """
        处理单帧检测结果，驱动 7 态状态机。
        由 AIWorker 在每帧推理后调用。
        """
        self._frames_processed += 1
        if self._video_lost_since is not None:
            await self.notify_video_restored()

        # ── 仲裁器自动恢复：若控制权已归还给 AUTO_TRACK，自动解除 PAUSED ──────
        if (
            self._paused
            and self._control_arbiter is not None
            and self._control_arbiter.can_auto_track_send()
        ):
            self._paused = False
            if self._active_target is not None:
                self._state = AutoTrackState.FOLLOWING
            else:
                self._state = AutoTrackState.IDLE
            logger.info("[AutoTrackService] 仲裁器已释放人工覆盖，自动恢复跟踪")

        # 自动跟踪只选择“person + head 且没有 helmet”的 person 框。
        # 一旦锁定，后续跟踪仍使用全部 person 框续跟，不再要求每帧都能看到 head。
        persons = [d for d in detections if d.class_name == "person"]
        no_helmet_persons = self._filter_no_helmet_persons(detections)

        # 为无 track_id 的检测结果分配降级 IOU ID
        persons = self._assign_fallback_ids(persons, frame_index)
        no_helmet_ids = {d.track_id for d in no_helmet_persons if d.track_id >= 0}
        no_helmet_persons = [d for d in persons if d.track_id in no_helmet_ids]
        helmets = [d for d in detections if d.class_name == "helmet"]
        helmet_person_ids = self._filter_helmet_person_ids(detections, persons)

        # 只有在启用且未暂停的情况下，才执行状态机和跟踪逻辑
        if self._enabled and not self._paused:
            if not self._is_mission_active(current_task_id):
                if self._state not in (AutoTrackState.DISABLED, AutoTrackState.IDLE):
                    self._do_stop(TrackStopReason.MISSION_ENDED, send_stop_command=True)
                    self._state = AutoTrackState.IDLE
            else:
                # ── 状态机分发 ────────────────────────────────────────────────────
                if self._state == AutoTrackState.IDLE:
                    await self._on_idle(no_helmet_persons, frame, current_task_id)
                elif self._state == AutoTrackState.DETECTING:
                    await self._on_detecting(no_helmet_persons, frame, current_task_id)
                elif self._state == AutoTrackState.FOLLOWING:
                    await self._on_following(persons, helmet_person_ids, helmets, frame, current_task_id)
                elif self._state == AutoTrackState.LOST:
                    await self._on_lost(persons, helmet_person_ids, helmets, frame, current_task_id)
                elif self._state == AutoTrackState.STOPPED:
                    # 自动回到 IDLE，等待下一个目标
                    self._reset_tracking_state()
                    self._state = AutoTrackState.IDLE

        # 叠层广播（限频）。前端事件是旁路，不能反压 AI 拉流/推理。
        # 即使不开跟踪，你也可以在前端看到绿色/灰色的框
        # 注意：只有 FOLLOWING 状态才显示红框；LOST 状态目标已消失，不显示幽灵框
        now = time.monotonic()
        if now - self._last_overlay_broadcast >= self._overlay_interval_s:
            self._last_overlay_broadcast = now
            active_bbox = (
                list(self._active_target.bbox)
                if self._active_target and self._state == AutoTrackState.FOLLOWING
                else None
            )
            await self._broadcast_event("TRACK_OVERLAY", {
                "detections": [
                    {
                        "bbox": list(d.bbox),
                        "conf": round(d.confidence, 2),
                        "class_name": d.class_name,
                        "track_id": d.track_id,
                        "is_stranger": self._is_stranger(d.track_id) if d.class_name == "person" else None,
                        "safety_status": "no_helmet" if d.class_name == "person" and d.track_id in no_helmet_ids else None,
                    }
                    for d in detections
                ],
                "persons": [
                    {
                        "bbox": list(d.bbox),
                        "conf": round(d.confidence, 2),
                        "class_name": d.class_name,
                        "track_id": d.track_id,
                        "is_stranger": self._is_stranger(d.track_id),
                        "safety_status": "no_helmet" if d.track_id in no_helmet_ids else None,
                    }
                    for d in persons
                ],
                "active_bbox": active_bbox,
                "command": self._last_command,
                "reason": self._last_decision_reason or "",
                "state": self._state.value,
                "tracking_phase": self._tracking_phase,
                "frame_w": self._frame_width,
                "frame_h": self._frame_height,
                "deadband_px": self._yaw_deadband_px,
                "anchor_y_stop_ratio": self._anchor_y_stop_ratio,
                "forward_area_ratio": self._forward_area_ratio,
                "gimbal_tracking_enabled": self._gimbal_enabled,
                "gimbal_connected": self._gimbal_connected,
                "camera_yaw_deg": self._camera_yaw_deg,
                "body_heading_error_deg": self._body_heading_error_deg,
            })

        await self._maybe_broadcast_debug_status()



    # ─── 状态机各态处理 ──────────────────────────────────────────────────────

    async def _on_idle(
        self,
        persons: list[DetectionResult],
        frame: bytes,
        task_id: Optional[int | str],
    ) -> None:
        """IDLE：无目标，等待发现候选。"""
        if not persons:
            self._candidates.clear()
            return

        # 发现 person → 检查区域 → 开始积累候选
        now = time.monotonic()
        found_candidate = False
        for det in persons:
            x1, y1, x2, y2 = det.bbox
            anchor = ((x1 + x2) // 2, y2)
            if not self._zone_service.is_inside_zone(anchor):
                continue

            # 检查 StrangerPolicy
            if not self._is_stranger(det.track_id):
                continue

            # 新候选
            if det.track_id not in self._candidates:
                self._candidates[det.track_id] = TargetCandidate.from_detection(
                    track_id=det.track_id,
                    bbox=det.bbox,
                    confidence=det.confidence,
                    inside_zone=True,
                    ts=now,
                )
                logger.debug(
                    f"[AutoTrackService] IDLE→DETECTING: 发现候选 track_id={det.track_id} "
                    f"conf={det.confidence:.2f}"
                )
                found_candidate = True
            else:
                # 已知候选，更新
                self._candidates[det.track_id].stable_hits += 1
                self._candidates[det.track_id].last_seen_ts = now
                found_candidate = True

        if found_candidate:
            self._state = AutoTrackState.DETECTING
            self._write_frame_log(persons, reason="IDLE→DETECTING")

    async def _on_detecting(
        self,
        persons: list[DetectionResult],
        frame: bytes,
        task_id: Optional[int | str],
    ) -> None:
        """DETECTING：候选积累，等待 stable_hits 帧后锁定。"""
        now = time.monotonic()
        person_by_id = {d.track_id: d for d in persons}

        # 更新现有候选
        for tid in list(self._candidates.keys()):
            if tid in person_by_id:
                det = person_by_id[tid]
                cand = self._candidates[tid]
                cand.stable_hits += 1
                cand.last_seen_ts = now
                cand.bbox = det.bbox
                x1, y1, x2, y2 = det.bbox
                cand.anchor_point = ((x1 + x2) // 2, y2)
            else:
                # 未检测到，减少命中或移除
                self._candidates[tid].stable_hits -= 1
                if self._candidates[tid].stable_hits <= 0:
                    del self._candidates[tid]

        # 新发现的候选（IDLE 逻辑复用）
        for det in persons:
            if det.track_id not in self._candidates:
                anchor = ((det.bbox[0] + det.bbox[2]) // 2, det.bbox[3])
                if self._zone_service.is_inside_zone(anchor) and self._is_stranger(det.track_id):
                    self._candidates[det.track_id] = TargetCandidate.from_detection(
                        track_id=det.track_id,
                        bbox=det.bbox,
                        confidence=det.confidence,
                        inside_zone=True,
                        ts=now,
                    )

        if not self._candidates:
            # 所有候选消失
            self._state = AutoTrackState.IDLE
            return

        # 检查是否有候选达到 stable_hits 阈值
        best = max(self._candidates.values(), key=lambda c: c.stable_hits)
        if best.stable_hits >= self._stable_hits:
            await self._lock_and_follow(best, frame, task_id)

        self._write_frame_log(persons, reason=f"DETECTING hit={best.stable_hits}/{self._stable_hits}")

    async def _on_following(
        self,
        persons: list[DetectionResult],
        helmet_person_ids: set[int],
        helmets: list[DetectionResult],
        frame: bytes,
        task_id: Optional[int | str],
    ) -> None:
        """FOLLOWING：目标锁定，发送控制命令。"""
        assert self._active_target is not None
        target = self._active_target
        now = time.monotonic()

        # 在当前帧中找到目标；track_id 抖动时用 bbox 空间重关联兜底。
        matched = self._find_target_match(persons, target)
        if matched is None:
            # 视觉闭环断开后立即停机身，避免沿上一条转向命令继续旋转。
            await self._send_command_safe("stop")
            await self._stop_gimbal_yaw()
            self._gimbal_centered_hits = 0
            self._body_turn_active = False
            self._body_aligned_hits = 0
            self._initial_alignment_complete = False
            self._tracking_phase = "LOST"
            self._reset_alignment_motion_observation()
            target.lost_count = 1
            self._state = AutoTrackState.LOST
            logger.info(
                f"[AutoTrackService] FOLLOWING→LOST: track_id={target.track_id}"
            )
            self._write_frame_log(persons, reason="FOLLOWING→LOST")
            return

        target.bbox = matched.bbox
        # 控制坐标单独做 EMA；保留原始 bbox 供身份重关联和状态展示使用。
        self._control_bbox = _smooth_bbox(
            self._control_bbox or matched.bbox,
            matched.bbox,
            alpha=0.45,
        )
        control_bbox = self._control_bbox
        x1, y1, x2, y2 = matched.bbox
        anchor = ((x1 + x2) // 2, y2)
        target.anchor_point = anchor
        target.last_seen_ts = now
        target.lost_count = 0
        if await self._stop_if_target_has_helmet(target, matched, helmet_person_ids, helmets, frame, task_id):
            return

        # 区域判断
        inside = self._zone_service.is_inside_zone(anchor)
        target.inside_zone = inside

        if not inside:
            target.out_of_zone_count += 1
            if target.out_of_zone_count >= self._out_of_zone_frames:
                logger.info(
                    f"[AutoTrackService] FOLLOWING→STOPPED(出区): track_id={target.track_id} "
                    f"连续出区 {target.out_of_zone_count} 帧"
                )
                await self._stop_with_snapshot(TrackStopReason.OUT_OF_ZONE, frame, task_id)
                return
            await self._send_command_safe("stop")
        else:
            target.out_of_zone_count = 0
            guidance: GimbalGuidance | None = None
            if self._gimbal_enabled:
                # 初始对齐阶段冻结云台世界朝向，只允许机器狗旋转去追云台。
                if not self._initial_alignment_complete:
                    self._tracking_phase = "ALIGNING"
                    guidance = await self._get_gimbal_guidance(
                        control_bbox,
                        prepare_alignment=True,
                    )
                    if guidance is None:
                        await self._send_command_safe("stop")
                        return

                    camera_yaw_deg = float(self._camera_yaw_deg or 0.0)
                    alignment_deadband_deg = self._gimbal_forward_deadband_deg
                    if abs(camera_yaw_deg) <= alignment_deadband_deg:
                        self._body_aligned_hits += 1
                    else:
                        self._body_aligned_hits = 0

                    if self._body_aligned_hits >= 3:
                        await self._send_command_safe("stop")
                        await self._finish_gimbal_alignment()
                        self._initial_alignment_complete = True
                        self._tracking_phase = "FOLLOWING"
                        self._reset_alignment_motion_observation()
                        self._last_decision_reason = "机身已正对摄像头，下一帧开始跟踪"
                        return

                    if abs(camera_yaw_deg) <= alignment_deadband_deg:
                        await self._send_command_safe("stop")
                        self._reset_alignment_motion_observation()
                        self._last_decision_reason = (
                            f"ALIGNING 等待稳定：camera_yaw={camera_yaw_deg:.2f}°，"
                            f"deadband=±{alignment_deadband_deg:.1f}°，"
                            f"stable={self._body_aligned_hits}/3"
                        )
                        return

                    command = "left" if camera_yaw_deg < 0.0 else "right"
                    observed_yaw_speed_dps = self._read_body_yaw_speed_dps()
                    yaw_speed = self._alignment_body_yaw_speed(
                        camera_yaw_deg,
                        observed_yaw_speed_dps,
                    )
                    if yaw_speed is None:
                        await self._send_command_safe("stop")
                        self._last_decision_reason = (
                            "ALIGNING 底盘未响应转向命令，已停止："
                            f"camera_yaw={camera_yaw_deg:.2f}°，"
                            f"observed_yaw_speed={observed_yaw_speed_dps}"
                        )
                        await self._broadcast_event("TRACK_DECISION", {
                            "command": "stop",
                            "should_send": True,
                            "reason": self._last_decision_reason,
                            "phase": self._tracking_phase,
                            "track_id": target.track_id,
                            "camera_yaw_deg": camera_yaw_deg,
                            "observed_body_yaw_speed_dps": observed_yaw_speed_dps,
                            "alignment_motion_failed": True,
                        })
                        return
                    await self._send_command_safe(
                        command,
                        yaw_speed=yaw_speed,
                    )
                    self._last_decision_reason = (
                        f"ALIGNING 云台保持不动，机身追摄像头："
                        f"camera_yaw={camera_yaw_deg:.2f}° command={command} "
                        f"vyaw={yaw_speed:.2f}rad/s "
                        f"measured={observed_yaw_speed_dps}"
                    )
                    await self._broadcast_event("TRACK_DECISION", {
                        "command": command,
                        "should_send": True,
                        "reason": self._last_decision_reason,
                        "phase": self._tracking_phase,
                        "track_id": target.track_id,
                        "camera_yaw_deg": camera_yaw_deg,
                        "yaw_speed": yaw_speed,
                        "observed_body_yaw_speed_dps": observed_yaw_speed_dps,
                        "alignment_motion_confirmed": self._alignment_motion_confirmed,
                    })
                    return

                guidance = await self._get_gimbal_guidance(
                    control_bbox,
                    prepare_alignment=False,
                )
                if guidance is None:
                    reason = f"云台视线不可用，禁止盲目前进：{self._gimbal_error or 'unknown'}"
                    should_send_stop = self._last_command != "stop"
                    if should_send_stop:
                        await self._send_command_safe("stop")
                    self._last_decision_reason = reason
                    await self._broadcast_event("TRACK_DECISION", {
                        "command": "stop",
                        "should_send": should_send_stop,
                        "reason": reason,
                        "bbox": list(control_bbox),
                        "anchor": list(target.anchor_point),
                        "track_id": target.track_id,
                        "gimbal_connected": self._gimbal_connected,
                    })
                    self._write_frame_log(
                        persons,
                        command="stop",
                        should_send=True,
                        reason=reason,
                        bbox=control_bbox,
                        anchor=target.anchor_point,
                    )
                    return

                camera_yaw_deg = float(self._camera_yaw_deg or 0.0)
                if abs(camera_yaw_deg) > self._gimbal_forward_deadband_deg:
                    # 运行中人为转动云台或云台发生漂移时，先停止底盘，再锁住
                    # 相机当前世界朝向，重新让机身追到相机方向。未对齐时严禁前进。
                    await self._send_command_safe("stop")
                    self._initial_alignment_complete = False
                    self._body_aligned_hits = 0
                    self._tracking_phase = "ALIGNING"
                    self._reset_alignment_motion_observation()
                    try:
                        await self._prepare_gimbal_alignment()
                    except Exception as exc:
                        self._set_gimbal_error(str(exc))
                    self._last_decision_reason = (
                        "检测到相机偏离机身正前方，重新只转机身对齐："
                        f"camera_yaw={camera_yaw_deg:.2f}°，"
                        f"deadband=±{self._gimbal_forward_deadband_deg:.1f}°"
                    )
                    logger.info(
                        f"[AutoTrackService] FOLLOWING→ALIGNING: "
                        f"camera_yaw={camera_yaw_deg:.2f}°"
                    )
                    await self._broadcast_event("TRACK_DECISION", {
                        "command": "stop",
                        "should_send": True,
                        "reason": self._last_decision_reason,
                        "phase": self._tracking_phase,
                        "track_id": target.track_id,
                        "camera_yaw_deg": camera_yaw_deg,
                        "camera_forward_deadband_deg": self._gimbal_forward_deadband_deg,
                    })
                    return

                # 对齐后云台保持 head_follow，不发送任何非零云台速度。
                # 人物在画面中的左右偏差全部换算成相对机身方位，只转机器狗。
                self._tracking_phase = "FOLLOWING"

            # 生成控制命令
            decision = self._decision_engine.decide(
                bbox=control_bbox,
                image_width=self._frame_width,
                image_height=self._frame_height,
                # 云台不再转动时，完整的目标方位就是：
                # 云台相对机身 yaw + 人物相对画面中心的角度。
                heading_error_deg=guidance.body_heading_error_deg if guidance else None,
                heading_deadband_deg=self._gimbal_body_deadband_deg,
            )
            if decision.should_send and decision.command:
                yaw_speed = (
                    self._body_yaw_speed(decision.heading_error_deg)
                    if decision.command in ("left", "right")
                    else None
                )
                await self._send_command_safe(decision.command, yaw_speed=yaw_speed)
                if self._yaw_pulse_s > 0 and decision.command in ("left", "right"):
                    asyncio.create_task(self._send_stop_after(self._yaw_pulse_s))

            self._last_decision_reason = decision.reason
            await self._broadcast_event("TRACK_DECISION", {
                "command": decision.command,
                "should_send": decision.should_send,
                "reason": decision.reason,
                "phase": self._tracking_phase,
                "bbox": list(control_bbox),
                "anchor": list(target.anchor_point),
                "track_id": target.track_id,
                "camera_yaw_deg": self._camera_yaw_deg,
                "body_heading_error_deg": decision.heading_error_deg,
                "gimbal_target_yaw_deg": self._gimbal_target_yaw_deg,
            })
            self._write_frame_log(
                persons,
                command=decision.command,
                should_send=decision.should_send,
                reason=decision.reason,
                bbox=control_bbox,
                anchor=target.anchor_point,
            )

    async def _get_gimbal_guidance(
        self,
        bbox: tuple[int, int, int, int],
        *,
        prepare_alignment: bool = False,
    ) -> GimbalGuidance | None:
        """读取真实云台角度并计算目标相对机身方位。

        ``prepare_alignment`` 只在初始对齐阶段使用，将云台切到
        head_lock 保持当前世界朝向。对齐完成后只读状态，不再发送
        任何非零云台速度。
        """
        if self._gimbal_service is None:
            self._set_gimbal_error("云台服务未初始化")
            return None

        try:
            if prepare_alignment:
                await self._prepare_gimbal_alignment()
            status = await self._gimbal_service.status()
            if not status.connected:
                self._set_gimbal_error("云台状态为未连接")
                return None

            self._gimbal_connected = True
            self._gimbal_error = None
            self._camera_yaw_deg = status.relative_yaw_deg
            guidance = calculate_gimbal_guidance(
                bbox=bbox,
                image_width=self._frame_width,
                camera_yaw_deg=status.relative_yaw_deg,
                zoom_ratio=status.zoom_ratio,
                horizontal_fov_deg=self._gimbal_horizontal_fov_deg,
                servo_gain=self._gimbal_servo_gain,
                pixel_deadband_px=self._gimbal_pixel_deadband_px,
            )
            self._body_heading_error_deg = guidance.body_heading_error_deg
            # 视觉跟踪期间不再存在云台转动路径；这里只读角度。
            self._gimbal_target_yaw_deg = None
            return guidance
        except Exception as exc:
            self._set_gimbal_error(str(exc))
            return None

    async def _prepare_gimbal_alignment(self) -> None:
        """锁住摄像头当前世界朝向，随后只允许机身追到该方向。"""
        if self._gimbal_alignment_mode_set or self._gimbal_service is None:
            return
        await self._gimbal_service.jog(
            pitch_velocity_dps=0.0,
            yaw_velocity_dps=0.0,
        )
        await self._gimbal_service.set_mode("head_lock")
        self._last_gimbal_yaw_velocity_dps = 0.0
        self._gimbal_alignment_mode_set = True

    async def _finish_gimbal_alignment(self) -> None:
        """机身对齐后进入云台随动模式，后续只转机器狗。"""
        if self._gimbal_service is None:
            return
        await self._gimbal_service.jog(
            pitch_velocity_dps=0.0,
            yaw_velocity_dps=0.0,
        )
        await self._gimbal_service.set_mode("head_follow")
        self._last_gimbal_yaw_velocity_dps = 0.0
        self._gimbal_alignment_mode_set = False

    def _set_gimbal_error(self, message: str) -> None:
        self._gimbal_connected = False
        self._gimbal_error = message
        now = time.monotonic()
        if now - self._last_gimbal_error_log_time >= 5.0:
            self._last_gimbal_error_log_time = now
            logger.warning(f"[AutoTrackService] 云台视线不可用，自动跟踪停车：{message}")

    def _body_yaw_speed(self, heading_error_deg: float | None) -> float | None:
        if heading_error_deg is None:
            return None
        max_speed = max(0.0, min(0.8, float(settings.AUTO_TRACK_VYAW)))
        if self._gimbal_enabled:
            # B2 实机在 0.18~0.22rad/s 下会接受 SDK 命令但不产生可见转动。
            # 初始对齐必须高于该死区；仍限制在 0.5rad/s 内避免过快甩尾。
            max_speed = min(max_speed, 0.5)
        if max_speed == 0.0:
            return 0.0
        effective_min_speed = (
            max(0.35, self._gimbal_min_body_vyaw)
            if self._gimbal_enabled
            else self._gimbal_min_body_vyaw
        )
        min_speed = min(max_speed, effective_min_speed)
        proportional = abs(heading_error_deg) / 45.0 * max_speed
        return round(max(min_speed, min(max_speed, proportional)), 3)

    def _read_body_yaw_speed_dps(self) -> float | None:
        """读取 B2 实际偏航速度；数据缺失或过期时不做误判。"""
        try:
            from .workers_unitree_telemetry import get_unitree_telemetry_diagnostics

            sport = get_unitree_telemetry_diagnostics().get("sport")
            if not sport or float(sport.get("age_s", 99.0)) > 0.5:
                return None
            return round(float(sport.get("yaw_speed", 0.0)) * 180.0 / 3.141592653589793, 2)
        except (TypeError, ValueError):
            return None

    def _alignment_body_yaw_speed(
        self,
        heading_error_deg: float,
        observed_yaw_speed_dps: float | None,
    ) -> float | None:
        """初始对齐速度，并用实机遥测识别“命令已发但底盘未动”。"""
        now = time.monotonic()
        self._observed_body_yaw_speed_dps = observed_yaw_speed_dps
        if self._alignment_turn_started_at is None:
            self._alignment_turn_started_at = now
            logger.info(
                f"[AutoTrackService] ALIGNING 开始机身转向："
                f"camera_yaw={heading_error_deg:.2f}°"
            )

        if observed_yaw_speed_dps is not None and abs(observed_yaw_speed_dps) >= 2.0:
            self._alignment_motion_confirmed = True

        elapsed = now - self._alignment_turn_started_at
        base_speed = float(self._body_yaw_speed(heading_error_deg) or 0.0)
        if (
            observed_yaw_speed_dps is not None
            and not self._alignment_motion_confirmed
            and elapsed >= 1.0
            and self._alignment_speed_override is None
        ):
            self._alignment_speed_override = max(
                base_speed,
                min(0.5, float(settings.UNITREE_B2_VYAW)),
            )
            logger.warning(
                f"[AutoTrackService] ALIGNING 底盘 1 秒内未产生偏航，"
                f"转速提升至 {self._alignment_speed_override:.2f}rad/s"
            )

        if (
            observed_yaw_speed_dps is not None
            and not self._alignment_motion_confirmed
            and elapsed >= 3.0
        ):
            if not self._alignment_motion_failed:
                logger.error(
                    f"[AutoTrackService] ALIGNING 底盘连续 3 秒无偏航响应，停止转向："
                    f"command_vyaw={self._alignment_speed_override or base_speed:.2f}rad/s"
                )
            self._alignment_motion_failed = True
            self._alignment_command_vyaw = None
            return None

        speed = self._alignment_speed_override or base_speed
        self._alignment_command_vyaw = speed
        return speed

    def _reset_alignment_motion_observation(self) -> None:
        self._alignment_turn_started_at = None
        self._alignment_speed_override = None
        self._alignment_motion_confirmed = False
        self._alignment_motion_failed = False
        self._observed_body_yaw_speed_dps = None
        self._alignment_command_vyaw = None

    async def _on_lost(
        self,
        persons: list[DetectionResult],
        helmet_person_ids: set[int],
        helmets: list[DetectionResult],
        frame: bytes,
        task_id: Optional[int | str],
    ) -> None:
        """LOST：等待重新发现同一 track_id，或超时回到 IDLE。"""
        assert self._active_target is not None
        target = self._active_target

        # 尝试重新发现；track_id 抖动时用 bbox 空间重关联兜底。
        matched = self._find_target_match(persons, target)
        if matched is not None:
            # 重新发现 → 直接恢复 FOLLOWING
            target.lost_count = 0
            target.bbox = matched.bbox
            x1, y1, x2, y2 = matched.bbox
            target.anchor_point = ((x1 + x2) // 2, y2)
            target.last_seen_ts = time.monotonic()
            if await self._stop_if_target_has_helmet(target, matched, helmet_person_ids, helmets, frame, task_id):
                return
            self._state = AutoTrackState.FOLLOWING
            self._tracking_phase = "AIMING"
            self._initial_alignment_complete = False
            self._body_aligned_hits = 0
            self._reset_alignment_motion_observation()
            logger.info(
                f"[AutoTrackService] LOST→FOLLOWING: 重新发现 track_id={target.track_id}"
            )
            self._write_frame_log(persons, reason="LOST→FOLLOWING")
            return

        # 目标仍未出现
        target.lost_count += 1
        self._write_frame_log(
            persons,
            reason=f"LOST {target.lost_count}/{self._lost_timeout_frames}"
        )

        if target.lost_count >= self._lost_timeout_frames:
            logger.info(
                f"[AutoTrackService] LOST→STOPPED(超时): track_id={target.track_id} "
                f"连续丢失 {target.lost_count} 帧，恢复导航"
            )
            await self._stop_with_snapshot(TrackStopReason.TARGET_LOST, frame, task_id)
        # 否则保持 LOST，下帧继续

    async def _stop_gimbal_yaw(self) -> None:
        """停止云台水平运动并保持当前位置，不在无目标时盲目回零。"""
        if not self._gimbal_enabled or self._gimbal_service is None:
            return
        try:
            await self._gimbal_service.jog(
                pitch_velocity_dps=0.0,
                yaw_velocity_dps=0.0,
            )
            # jog(0, 0) 会把 Z2-Mini 切回 head_follow；下次重新锁人时
            # 必须再次显式进入 head_lock，不能沿用旧的内存标记。
            self._gimbal_alignment_mode_set = False
        except Exception as exc:
            self._set_gimbal_error(str(exc))
        finally:
            self._last_gimbal_yaw_velocity_dps = 0.0

# ─── 全局单例 ────────────────────────────────────────────────────────────────

_auto_track_service: Optional[AutoTrackService] = None


def get_auto_track_service() -> Optional[AutoTrackService]:
    return _auto_track_service


def set_auto_track_service(service: AutoTrackService) -> None:
    global _auto_track_service
    _auto_track_service = service


def _smooth_bbox(
    previous: tuple[int, int, int, int],
    current: tuple[int, int, int, int],
    *,
    alpha: float,
) -> tuple[int, int, int, int]:
    alpha = max(0.0, min(1.0, alpha))
    return tuple(
        int(round(old * (1.0 - alpha) + new * alpha))
        for old, new in zip(previous, current)
    )
