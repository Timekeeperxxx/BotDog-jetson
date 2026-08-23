from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional

from .auto_track_snapshot import _save_snapshot_to_disk
from .config import settings
from .logging_config import logger
from .tracking_types import (
    ActiveTarget,
    AutoTrackState,
    ControlOwner,
    DetectionResult,
    TargetCandidate,
    TrackStopReason,
)


class AutoTrackRuntimeMixin:
    async def _stop_if_target_has_helmet(
        self,
        target: ActiveTarget,
        matched: DetectionResult,
        helmet_person_ids: set[int],
        helmets: list[DetectionResult],
        frame: bytes,
        task_id: Optional[int | str],
    ) -> bool:
        has_helmet = (
            target.track_id in helmet_person_ids
            or any(self._part_belongs_to_person(helmet.bbox, matched.bbox) for helmet in helmets)
        )
        if has_helmet:
            target.helmet_hits += 1
            if target.helmet_hits >= self._helmet_person_abort_frames:
                logger.info(
                    f"[AutoTrackService] FOLLOWING→STOPPED(helmet确认): "
                    f"track_id={target.track_id} 连续 {target.helmet_hits} 帧"
                )
                await self._stop_with_snapshot(TrackStopReason.HELMET_CONFIRMED, frame, task_id)
                return True
        else:
            target.helmet_hits = 0
        return False

    async def _lock_and_follow(
        self,
        candidate: TargetCandidate,
        frame: bytes,
        task_id: Optional[int | str],
    ) -> None:
        """候选稳定命中，锁定目标并立即进入 FOLLOWING。"""
        ts = time_monotonic()
        self._active_target = ActiveTarget(
            track_id=candidate.track_id,
            bbox=candidate.bbox,
            anchor_point=candidate.anchor_point,
            inside_zone=candidate.inside_zone,
            locked_at=ts,
            last_seen_ts=ts,
            follow_started_at=ts,
        )
        self._candidates.clear()
        self._state = AutoTrackState.FOLLOWING
        self._tracking_phase = "AIMING"
        self._initial_alignment_complete = False
        self._body_aligned_hits = 0
        self._gimbal_realign_hits = 0
        self._reset_alignment_motion_observation()
        self._decision_engine.reset()

        logger.info(
            f"[AutoTrackService] DETECTING→FOLLOWING: 锁定目标 track_id={candidate.track_id} "
            f"conf={candidate.confidence:.2f} 命中={candidate.stable_hits} 帧"
        )

        await self._take_snapshot_safe(frame, "locked", task_id)
        await self._broadcast_event("STRANGER_TARGET_LOCKED", {
            "track_id": candidate.track_id,
            "bbox": list(candidate.bbox),
            "confidence": candidate.confidence,
            "inside_zone": candidate.inside_zone,
        })
        await self._broadcast_event("AUTO_TRACK_STARTED", {
            "track_id": candidate.track_id,
        })
        await self._pause_navigation_for_tracking(candidate.track_id)

    def _reset_tracking_state(self) -> None:
        """完全重置跟踪状态（STOPPED → IDLE 时调用）。"""
        self._active_target = None
        self._candidates.clear()
        self._last_iou_bbox = None
        self._control_bbox = None
        self._decision_engine.reset()
        self._last_command = None
        self._last_decision_reason = None
        self._body_heading_error_deg = None
        self._gimbal_target_yaw_deg = None
        self._last_gimbal_yaw_velocity_dps = 0.0
        self._gimbal_centered_hits = 0
        self._body_turn_active = False
        self._body_aligned_hits = 0
        self._initial_alignment_complete = False
        self._gimbal_realign_hits = 0
        self._tracking_phase = "IDLE"
        self._gimbal_alignment_mode_set = False
        self._reset_alignment_motion_observation()

    def _do_stop(
        self,
        reason: TrackStopReason,
        send_stop_command: bool = True,
    ) -> None:
        """内部停止：重置活跃目标，不自动切换到 IDLE（由调用方决定后续状态）。"""
        self._stop_reason = reason
        self._reset_tracking_state()
        if send_stop_command:
            asyncio.create_task(self._send_command_safe("stop"))
        if reason in (
            TrackStopReason.DISABLED,
            TrackStopReason.E_STOP,
            TrackStopReason.MANUAL,
            TrackStopReason.MISSION_ENDED,
            TrackStopReason.MARKED_KNOWN,
        ):
            self._cancel_pending_navigation_resume(reason.value)
        logger.info(f"[AutoTrackService] 跟踪停止，原因={reason.value}")

    async def _stop_with_snapshot(
        self,
        reason: TrackStopReason,
        frame: bytes,
        task_id: Optional[int | str],
    ) -> None:
        if self._stop_snapshot_enabled:
            await self._take_snapshot_safe(frame, "stopped", task_id)
        await self._broadcast_event("AUTO_TRACK_STOPPED", {
            "track_id": self._active_target.track_id if self._active_target else None,
            "reason": reason.value,
        })
        self._do_stop(reason, send_stop_command=True)
        self._state = AutoTrackState.STOPPED
        await self._resume_navigation_after_tracking(reason.value)
        # STOPPED 将在下一帧 process_frame 自动回到 IDLE

    async def _stop_without_snapshot(
        self,
        reason: TrackStopReason,
        detail: str = "",
    ) -> None:
        await self._broadcast_event("AUTO_TRACK_STOPPED", {
            "track_id": self._active_target.track_id if self._active_target else None,
            "reason": reason.value,
            "detail": detail,
        })
        self._video_lost_since = None
        self._video_lost_reason = None
        self._do_stop(reason, send_stop_command=True)
        self._state = AutoTrackState.STOPPED
        await self._resume_navigation_after_tracking(reason.value)

    async def _send_stop_after(self, delay_s: float) -> None:
        """延迟 delay_s 秒后发 stop，用于脉冲式转向截断。"""
        await asyncio.sleep(delay_s)
        await self._send_command_safe("stop")

    async def _send_command_safe(
        self,
        cmd: str,
        *,
        yaw_speed: float | None = None,
    ) -> None:
        """通过 ControlService 发送命令，发前检查 ControlArbiter 权限。"""
        try:
            if cmd != "stop" and self._control_arbiter is not None:
                if not self._control_arbiter.can_auto_track_send():
                    owner = self._control_arbiter.owner
                    if self._state not in (
                        AutoTrackState.PAUSED,
                        AutoTrackState.DISABLED,
                        AutoTrackState.STOPPED,
                    ):
                        logger.info(
                            f"[AutoTrackService] 控制权被 {owner.value} 接管，"
                            f"自动命令已拦截，进入 PAUSED"
                        )
                        self._state = AutoTrackState.PAUSED
                        await self._broadcast_event("AUTO_TRACK_MANUAL_OVERRIDE", {
                            "control_owner": owner.value,
                        })
                    return
            self._last_command = cmd
            if cmd in {"forward", "backward"}:
                await self._control_service.handle_command(cmd, vx=settings.AUTO_TRACK_VX)
            elif cmd in {"left", "right"}:
                await self._control_service.handle_command(
                    cmd,
                    vyaw=settings.AUTO_TRACK_VYAW if yaw_speed is None else yaw_speed,
                )
            else:
                await self._control_service.handle_command(cmd)
        except Exception as exc:
            logger.debug(f"[AutoTrackService] 发送命令 {cmd!r} 失败: {exc}")

    async def _take_snapshot_safe(
        self,
        frame: bytes,
        label: str,
        task_id: Optional[int | str],
    ) -> None:
        try:
            image_path, image_url = await _save_snapshot_to_disk(
                frame=frame,
                snapshot_dir=self._snapshot_dir,
                frame_width=self._frame_width,
                frame_height=self._frame_height,
            )
            from .alert_service import get_alert_service
            alert_service = get_alert_service()
            if alert_service:
                async with self._session_factory() as session:
                    await alert_service.handle_ai_event(
                        event_type="AUTO_TRACK_SNAPSHOT",
                        event_code=f"E_AUTO_TRACK_{label.upper()}",
                        severity="INFO",
                        message=f"自动跟踪抓拍（{label}）",
                        confidence=1.0,
                        file_path=str(image_path),
                        image_url=image_url,
                        gps_lat=None,
                        gps_lon=None,
                        task_id=task_id if isinstance(task_id, int) else None,
                        session=session,
                    )
        except Exception as exc:
            logger.debug(f"[AutoTrackService] 抓拍失败（不影响跟踪）: {exc}")

    async def _pause_navigation_for_tracking(self, track_id: int) -> None:
        try:
            from .nav_auto_track_coordinator import get_nav_auto_track_coordinator

            coordinator = get_nav_auto_track_coordinator()
            if coordinator is not None:
                await coordinator.pause_navigation_for_tracking(track_id=track_id)
        except Exception as exc:
            logger.debug(f"[AutoTrackService] 暂停导航任务失败（不影响跟踪）: {exc}")

    async def _resume_navigation_after_tracking(self, reason: str) -> None:
        try:
            from .nav_auto_track_coordinator import get_nav_auto_track_coordinator

            coordinator = get_nav_auto_track_coordinator()
            if coordinator is not None:
                await coordinator.resume_navigation_after_tracking(reason=reason)
        except Exception as exc:
            logger.debug(f"[AutoTrackService] 恢复导航任务失败: {exc}")

    def _cancel_pending_navigation_resume(self, reason: str) -> None:
        try:
            from .nav_auto_track_coordinator import get_nav_auto_track_coordinator

            coordinator = get_nav_auto_track_coordinator()
            if coordinator is not None:
                coordinator.cancel_pending_resume(reason)
        except Exception as exc:
            logger.debug(f"[AutoTrackService] 取消导航恢复失败: {exc}")

    async def _broadcast_event(self, msg_type: str, payload: dict) -> None:
        try:
            from .schemas import utc_now_iso
            broadcaster = self._event_broadcaster
            if broadcaster and broadcaster.connection_count > 0:
                msg = {
                    "msg_type": msg_type,
                    "timestamp": utc_now_iso(),
                    "payload": payload,
                }
                async with broadcaster._lock:
                    failed = []
                    for conn in broadcaster._connections:
                        try:
                            await asyncio.wait_for(
                                conn.send_json(msg),
                                timeout=self._event_send_timeout_s,
                            )
                        except Exception:
                            failed.append(conn)
                    for c in failed:
                        broadcaster._connections.discard(c)
        except Exception as exc:
            logger.debug(f"[AutoTrackService] 广播 {msg_type} 失败: {exc}")

    async def _maybe_broadcast_debug_status(self) -> None:
        now = time_monotonic()
        if now - self._last_status_broadcast < 2.0:
            return
        self._last_status_broadcast = now
        await self._broadcast_event("AUTO_TRACK_STATUS", self.get_status())

    def _is_mission_active(self, task_id: Optional[int | str]) -> bool:
        # 与 AI Worker 保持一致：
        # 解除对 state_machine.state == SystemState.IN_MISSION（需要下位机心跳）的强依赖
        # 手动开启自动跟踪时允许独立工作；导航联动开启时仍要求有任务上下文。
        return self._standalone_enabled or task_id is not None

    def _is_stranger(self, target: int | DetectionResult) -> bool:
        """通过人脸库和会话白名单判断是否为陌生人。"""
        if isinstance(target, DetectionResult):
            track_id = target.track_id
            face_status = target.face_status
            identity_id = target.identity_id
        else:
            track_id = int(target)
            face_status = None
            identity_id = None
        try:
            from .stranger_policy import get_stranger_policy
            policy = get_stranger_policy()
            if policy is not None:
                return policy.is_stranger(
                    track_id,
                    face_status=face_status,
                    identity_id=identity_id,
                )
        except Exception:
            pass
        return True  # 默认视为陌生人

    def _ensure_decision_log(self) -> None:
        if self._decision_log_file is not None:
            return
        import io
        scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = scripts_dir / f"track_decisions_{ts}.log"
        self._decision_log_path = log_path
        self._decision_log_file = io.open(log_path, "w", encoding="utf-8", buffering=1)
        self._decision_log_file.write(
            "# BotDog tracking decision log (7-state refactor)\n"
            "# cols: timestamp | frame | state | detected | person_count"
            " | persons(track_id:bbox) | track_cmd | sent | reason | active_bbox | anchor\n"
        )
        logger.info(f"[AutoTrackService] Decision log: {log_path}")

    def _write_frame_log(self, persons: list, **kwargs) -> None:
        """决策日志已禁用（生产环境不需要）。"""
        pass

    def _close_decision_log(self) -> None:
        if self._decision_log_file is not None:
            try:
                self._decision_log_file.flush()
                self._decision_log_file.close()
            except Exception:
                pass
            self._decision_log_file = None

    def _ensure_latency_log(self) -> None:
        if hasattr(self, '_latency_log_file') and self._latency_log_file is not None:
            return
        import io
        logs_dir = Path(__file__).resolve().parent.parent / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = logs_dir / f"track_latency_{ts}.log"
        self._latency_log_file = io.open(log_path, "w", encoding="utf-8", buffering=1)
        self._latency_log_file.write(
            "# BotDog tracking latency log\n"
            "# time | frame | state | persons | cmd | detect_ms | track_ms | total_ms\n"
        )
        logger.info(f"[AutoTrackService] Latency log: {log_path}")

    def _write_latency_log(self, *, frame_index: int, t_start: float,
                            t_detect_end: float, t_track_done: float) -> None:
        """延迟日志已禁用（生产环境不需要）。"""
        pass


def time_monotonic() -> float:
    import time

    return time.monotonic()
