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
from datetime import datetime
from pathlib import Path
from typing import Optional, TYPE_CHECKING

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
from .zone_service import ZoneService

if TYPE_CHECKING:
    from .control_service import ControlService
    from .state_machine import StateMachine
    from .ws_event_broadcaster import EventBroadcaster
    from .target_manager import TargetManager
    from .control_arbiter import ControlArbiter


class AutoTrackService:
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
        command_interval_ms: float = 200.0,
        yaw_deadband_px: int = 80,
        forward_area_ratio: float = 0.15,
        anchor_y_stop_ratio: float = 0.20,
        stop_snapshot_enabled: bool = True,
        default_enabled: bool = False,
        yaw_pulse_ms: float = 0.0,
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

        self._stable_hits = stable_hits
        self._reset_misses = reset_misses
        self._out_of_zone_frames = out_of_zone_frames
        self._lost_timeout_frames = lost_timeout_frames
        self._stop_snapshot_enabled = stop_snapshot_enabled

        # 运行时开关
        self._enabled: bool = default_enabled
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

        # ── 活跃目标（FOLLOWING / LOST 阶段） ──────────────────────────────
        self._active_target: Optional[ActiveTarget] = None
        self._stop_reason: Optional[TrackStopReason] = None

        # 阶段 2 多目标管理
        self._target_manager: "TargetManager | None" = target_manager
        self._control_arbiter: "ControlArbiter | None" = control_arbiter
        if self._control_arbiter and default_enabled:
            self._control_arbiter.request_control(ControlOwner.AUTO_TRACK)

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

        # 调试状态
        self._last_status_broadcast: float = 0.0
        self._last_command: Optional[str] = None
        self._last_decision_reason: Optional[str] = None
        self._frames_processed: int = 0

        # 决策日志
        self._decision_log_file = None
        self._decision_log_path: Optional[Path] = None

        logger.info(
            f"[AutoTrackService] 初始化完成，默认启用={default_enabled}，"
            f"stable_hits={stable_hits}，lost_timeout_frames={lost_timeout_frames}，"
            f"yaw_pulse_ms={yaw_pulse_ms}"
        )

    # ─── 公共控制接口 ────────────────────────────────────────────────────────

    def enable(self) -> None:
        self._enabled = True
        self._paused = False
        if self._state == AutoTrackState.DISABLED:
            self._state = AutoTrackState.IDLE
        if self._control_arbiter:
            self._control_arbiter.request_control(ControlOwner.AUTO_TRACK)
        logger.info("[AutoTrackService] 自动跟踪已启用")

    def disable(self) -> None:
        if self._enabled:
            logger.info("[AutoTrackService] 自动跟踪已禁用")
        self._enabled = False
        self._paused = False
        self._do_stop(TrackStopReason.DISABLED, send_stop_command=True)
        self._state = AutoTrackState.DISABLED
        if self._control_arbiter:
            self._control_arbiter.release_control(ControlOwner.AUTO_TRACK)

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

    def update_params(self, key: str, value: Any) -> None:
        """
        热更新系统参数（支持从数据库前台设置面板修改传入）。
        """
        try:
            if key == "auto_track_stable_hits":
                self._stable_hits = int(value)
                logger.info(f"[AutoTrackService] 热更新 stable_hits={self._stable_hits}")
            elif key == "auto_track_lost_timeout_frames":
                self._lost_timeout_frames = int(value)
                logger.info(f"[AutoTrackService] 热更新 lost_timeout_frames={self._lost_timeout_frames}")
            elif key == "auto_track_yaw_deadband_px":
                self._yaw_deadband_px = int(value)
                self._decision_engine._yaw_deadband_px = self._yaw_deadband_px
                logger.info(f"[AutoTrackService] 热更新 yaw_deadband_px={self._yaw_deadband_px}")
            elif key == "auto_track_forward_area_ratio":
                self._forward_area_ratio = float(value)
                self._decision_engine._forward_area_ratio = self._forward_area_ratio
                logger.info(f"[AutoTrackService] 热更新 forward_area_ratio={self._forward_area_ratio}")
            elif key == "auto_track_anchor_y_stop_ratio":
                self._anchor_y_stop_ratio = float(value)
                self._decision_engine._anchor_y_stop_ratio = self._anchor_y_stop_ratio
                logger.info(f"[AutoTrackService] 热更新 anchor_y_stop_ratio={self._anchor_y_stop_ratio}")
            else:
                logger.debug(f"[AutoTrackService] 忽略未知参数更新: {key}={value}")
        except Exception as e:
            logger.error(f"[AutoTrackService] 热更新参数 {key}={value} 失败: {e}")

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
            }
        arbiter_status = (
            self._control_arbiter.get_status()
            if self._control_arbiter else {"owner": "N/A"}
        )
        return {
            "enabled": self._enabled,
            "paused": self._paused,
            "state": self._state.value,
            "active_target": target_info,
            "stop_reason": self._stop_reason.value if self._stop_reason else None,
            "last_command": self._last_command,
            "frames_processed": self._frames_processed,
            "candidate_count": len(self._candidates),
            "stable_hits_threshold": self._stable_hits,
            "control_arbiter": arbiter_status,
        }

    # ─── 核心处理入口 ────────────────────────────────────────────────────────

    async def process_frame(
        self,
        detections: list[DetectionResult],
        frame: bytes,
        frame_index: int,
        current_task_id: Optional[int] = None,
        t_start: float = 0.0,
        t_detect_end: float = 0.0,
    ) -> None:
        """
        处理单帧检测结果，驱动 7 态状态机。
        由 AIWorker 在每帧推理后调用。
        """
        self._frames_processed += 1

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

        # 过滤只要 person
        persons = [d for d in detections if d.class_name == "person"]

        # 为无 track_id 的检测结果分配降级 IOU ID
        persons = self._assign_fallback_ids(persons)

        # 只有在启用且未暂停的情况下，才执行状态机和跟踪逻辑
        if self._enabled and not self._paused:
            if not self._is_mission_active(current_task_id):
                if self._state not in (AutoTrackState.DISABLED, AutoTrackState.IDLE):
                    self._do_stop(TrackStopReason.MISSION_ENDED, send_stop_command=True)
                    self._state = AutoTrackState.IDLE
            else:
                # ── 状态机分发 ────────────────────────────────────────────────────
                if self._state == AutoTrackState.IDLE:
                    await self._on_idle(persons, frame, current_task_id)
                elif self._state == AutoTrackState.DETECTING:
                    await self._on_detecting(persons, frame, current_task_id)
                elif self._state == AutoTrackState.FOLLOWING:
                    await self._on_following(persons, frame, current_task_id)
                elif self._state == AutoTrackState.LOST:
                    await self._on_lost(persons, frame, current_task_id)
                elif self._state == AutoTrackState.STOPPED:
                    # 自动回到 IDLE，等待下一个目标
                    self._reset_tracking_state()
                    self._state = AutoTrackState.IDLE

        # 叠层广播（每帧）
        # 即使不开跟踪，你也可以在前端看到绿色/灰色的框
        # 注意：只有 FOLLOWING 状态才显示红框；LOST 状态目标已消失，不显示幽灵框
        active_bbox = (
            list(self._active_target.bbox)
            if self._active_target and self._state == AutoTrackState.FOLLOWING
            else None
        )
        await self._broadcast_event("TRACK_OVERLAY", {
            "persons": [
                {
                    "bbox": list(d.bbox),
                    "conf": round(d.confidence, 2),
                    "track_id": d.track_id,
                    "is_stranger": self._is_stranger(d.track_id)
                }
                for d in persons
            ],
            "active_bbox": active_bbox,
            "command": self._last_command,
            "reason": self._last_decision_reason or "",
            "state": self._state.value,
            "frame_w": self._frame_width,
            "frame_h": self._frame_height,
            "deadband_px": self._yaw_deadband_px,
            "anchor_y_stop_ratio": self._anchor_y_stop_ratio,
            "forward_area_ratio": self._forward_area_ratio,
        })

        await self._maybe_broadcast_debug_status()

        # ── 延迟日志 ───────────────────────────────────────────────
        if t_start > 0:
            t_track_done = time.monotonic()
            self._write_latency_log(
                frame_index=frame_index,
                t_start=t_start,
                t_detect_end=t_detect_end,
                t_track_done=t_track_done,
            )

    # ─── 状态机各态处理 ──────────────────────────────────────────────────────

    async def _on_idle(
        self,
        persons: list[DetectionResult],
        frame: bytes,
        task_id: Optional[int],
    ) -> None:
        """IDLE：无目标，等待发现候选。"""
        if not persons:
            self._candidates.clear()
            return

        # 发现 person → 检查区域 → 开始积累候选
        now = time.monotonic()
        found_candidate = False
        print("IDLE: persons", persons)
        for det in persons:
            print("det", det)
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
                print("IDLE→DETECTING: 发现候选 track_id=", det.track_id)
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
        task_id: Optional[int],
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
        frame: bytes,
        task_id: Optional[int],
    ) -> None:
        """FOLLOWING：目标锁定，发送控制命令。"""
        assert self._active_target is not None
        target = self._active_target
        now = time.monotonic()

        # 在当前帧中找到匹配的 track_id
        matched = self._find_by_track_id(persons, target.track_id)
        if matched is None:
            # 目标丢失 → 进入 LOST
            target.lost_count = 1
            self._state = AutoTrackState.LOST
            logger.info(
                f"[AutoTrackService] FOLLOWING→LOST: track_id={target.track_id}"
            )
            await self._send_command_safe("stop")
            self._write_frame_log(persons, reason="FOLLOWING→LOST")
            return

        # 更新目标状态
        target.bbox = matched.bbox
        x1, y1, x2, y2 = matched.bbox
        anchor = ((x1 + x2) // 2, y2)
        target.anchor_point = anchor
        target.last_seen_ts = now
        target.lost_count = 0

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
            # 生成控制命令
            decision = self._decision_engine.decide(
                bbox=matched.bbox,
                image_width=self._frame_width,
                image_height=self._frame_height,
            )
            if decision.should_send and decision.command:
                if decision.command == "stop":
                    await self._send_command_safe("stop")
                else:
                    await self._send_velocity_safe(decision.vx, decision.vyaw, decision.command)
                
                if self._yaw_pulse_s > 0 and decision.command in ("left", "right"):
                    asyncio.create_task(self._send_stop_after(self._yaw_pulse_s))

            self._last_decision_reason = decision.reason
            await self._broadcast_event("TRACK_DECISION", {
                "command": decision.command,
                "should_send": decision.should_send,
                "reason": decision.reason,
                "vx": decision.vx,
                "vyaw": decision.vyaw,
                "bbox": list(matched.bbox),
                "anchor": list(target.anchor_point),
                "track_id": target.track_id,
            })
            self._write_frame_log(
                persons,
                command=decision.command,
                should_send=decision.should_send,
                reason=decision.reason,
                bbox=matched.bbox,
                anchor=target.anchor_point,
            )

    async def _on_lost(
        self,
        persons: list[DetectionResult],
        frame: bytes,
        task_id: Optional[int],
    ) -> None:
        """LOST：等待重新发现同一 track_id，或超时回到 IDLE。"""
        assert self._active_target is not None
        target = self._active_target

        # 尝试重新发现
        matched = self._find_by_track_id(persons, target.track_id)
        if matched is not None:
            # 重新发现 → 直接恢复 FOLLOWING
            target.lost_count = 0
            target.bbox = matched.bbox
            x1, y1, x2, y2 = matched.bbox
            target.anchor_point = ((x1 + x2) // 2, y2)
            target.last_seen_ts = time.monotonic()
            self._state = AutoTrackState.FOLLOWING
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
                f"[AutoTrackService] LOST→DETECTING(超时): track_id={target.track_id} "
                f"连续丢失 {target.lost_count} 帧，重新进入检测"
            )
            # 不发 stop 指令，不结束任务，直接重置目标并回到检测状态
            self._active_target = None
            self._candidates.clear()
            self._last_command = None
            self._state = AutoTrackState.DETECTING
        # 否则保持 LOST，下帧继续

    # ─── 内部工具 ────────────────────────────────────────────────────────────

    def _assign_fallback_ids(self, persons: list[DetectionResult]) -> list[DetectionResult]:
        """
        为 track_id == -1 的检测结果分配降级 IOU ID，保持帧间连续性。
        YOLO track 模式正常工作时此函数基本是空操作。
        """
        no_id = [d for d in persons if d.track_id == -1]
        if not no_id:
            return persons

        result = [d for d in persons if d.track_id != -1]
        for det in no_id:
            if self._last_iou_bbox is not None:
                iou = _calc_iou(det.bbox, self._last_iou_bbox)
                if iou >= 0.4:
                    # 视为同一目标，复用当前 IOU ID
                    det.track_id = self._iou_id_counter
                else:
                    # 新目标
                    self._iou_id_counter += 1
                    det.track_id = self._iou_id_counter
            else:
                self._iou_id_counter += 1
                det.track_id = self._iou_id_counter

            self._last_iou_bbox = det.bbox
            result.append(det)

        return result

    def _find_by_track_id(
        self,
        persons: list[DetectionResult],
        track_id: int,
    ) -> Optional[DetectionResult]:
        """在检测结果中精确查找指定 track_id。"""
        for det in persons:
            if det.track_id == track_id:
                return det
        return None

    def _is_stranger(self, track_id: int) -> bool:
        """通过 StrangerPolicy 判断是否为陌生人（已知人员不跟踪）。"""
        try:
            from .stranger_policy import get_stranger_policy
            policy = get_stranger_policy()
            if policy is not None:
                return policy.is_stranger(track_id)
        except Exception:
            pass
        return True  # 默认视为陌生人

    async def _lock_and_follow(
        self,
        candidate: TargetCandidate,
        frame: bytes,
        task_id: Optional[int],
    ) -> None:
        """候选稳定命中，锁定目标并立即进入 FOLLOWING。"""
        ts = time.monotonic()
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

    def _reset_tracking_state(self) -> None:
        """完全重置跟踪状态（STOPPED → IDLE 时调用）。"""
        self._active_target = None
        self._candidates.clear()
        self._last_iou_bbox = None
        self._decision_engine.reset()
        self._last_command = None
        self._last_decision_reason = None

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
        logger.info(f"[AutoTrackService] 跟踪停止，原因={reason.value}")

    async def _stop_with_snapshot(
        self,
        reason: TrackStopReason,
        frame: bytes,
        task_id: Optional[int],
    ) -> None:
        if self._stop_snapshot_enabled:
            await self._take_snapshot_safe(frame, "stopped", task_id)
        await self._broadcast_event("AUTO_TRACK_STOPPED", {
            "track_id": self._active_target.track_id if self._active_target else None,
            "reason": reason.value,
        })
        self._do_stop(reason, send_stop_command=True)
        self._state = AutoTrackState.STOPPED
        # STOPPED 将在下一帧 process_frame 自动回到 IDLE

    async def _send_stop_after(self, delay_s: float) -> None:
        """延迟 delay_s 秒后发 stop，用于脉冲式转向截断。"""
        await asyncio.sleep(delay_s)
        await self._send_command_safe("stop")

    async def _send_command_safe(self, cmd: str) -> None:
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
            await self._control_service.handle_command(cmd)
        except Exception as exc:
            logger.debug(f"[AutoTrackService] 发送命令 {cmd!r} 失败: {exc}")

    async def _send_velocity_safe(self, vx: float, vyaw: float, raw_cmd: str) -> None:
        """通过 ControlService 发送连续速度控制命令，发前检查权限。"""
        try:
            if self._control_arbiter is not None:
                if not self._control_arbiter.can_auto_track_send():
                    owner = self._control_arbiter.owner
                    if self._state not in (
                        AutoTrackState.PAUSED,
                        AutoTrackState.DISABLED,
                        AutoTrackState.STOPPED,
                    ):
                        logger.info(
                            f"[AutoTrackService] 控制权被 {owner.value} 接管，"
                            f"自动速度已被拦截，进入 PAUSED"
                        )
                        self._state = AutoTrackState.PAUSED
                        await self._broadcast_event("AUTO_TRACK_MANUAL_OVERRIDE", {
                            "control_owner": owner.value,
                        })
                        return

            self._last_command = raw_cmd
            await self._control_service.handle_velocity(vx, vyaw)
        except Exception as exc:
            logger.debug(f"[AutoTrackService] 发送速度 (vx={vx}, vyaw={vyaw}) 失败: {exc}")

    async def _take_snapshot_safe(
        self,
        frame: bytes,
        label: str,
        task_id: Optional[int],
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
                        task_id=task_id,
                        session=session,
                    )
        except Exception as exc:
            logger.debug(f"[AutoTrackService] 抓拍失败（不影响跟踪）: {exc}")

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
                            await conn.send_json(msg)
                        except Exception:
                            failed.append(conn)
                    for c in failed:
                        broadcaster._connections.discard(c)
        except Exception as exc:
            logger.debug(f"[AutoTrackService] 广播 {msg_type} 失败: {exc}")

    async def _maybe_broadcast_debug_status(self) -> None:
        now = time.monotonic()
        if now - self._last_status_broadcast < 2.0:
            return
        self._last_status_broadcast = now
        await self._broadcast_event("AUTO_TRACK_STATUS", self.get_status())

    def _is_mission_active(self, task_id: Optional[int]) -> bool:
        # 与 AI Worker 保持一致：
        # 解除对 state_machine.state == SystemState.IN_MISSION（需要下位机心跳）的强依赖
        # 只要前端启动了任务 (task_id 存在)，AI 就进入工作状态。
        return task_id is not None

    # ─── 决策日志 ────────────────────────────────────────────────────────────

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

    def _write_frame_log(
        self,
        persons: list,
        *,
        command: Optional[str] = None,
        should_send: bool = False,
        reason: str = "",
        bbox: Optional[tuple] = None,
        anchor: Optional[tuple] = None,
    ) -> None:
        try:
            self._ensure_decision_log()
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            person_count = len(persons)
            detected = "YES" if person_count > 0 else "NO"
            persons_str = ";".join(
                f"{d.track_id}:{d.bbox[0]},{d.bbox[1]},{d.bbox[2]},{d.bbox[3]}"
                for d in persons
            ) if person_count > 0 else "-"
            cmd_str = command or "-"
            sent_str = "Y" if should_send else "N"
            reason_str = reason or "-"
            bbox_str = f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}" if bbox else "-"
            anchor_str = f"{anchor[0]},{anchor[1]}" if anchor else "-"
            line = (
                f"{now_str} | {self._frames_processed:06d} | {self._state.value}"
                f" | {detected} | {person_count}"
                f" | {persons_str} | {cmd_str} | {sent_str} | {reason_str}"
                f" | {bbox_str} | {anchor_str}\n"
            )
            assert self._decision_log_file is not None
            self._decision_log_file.write(line)
        except Exception as exc:
            logger.warning(f"[AutoTrackService] Failed to write decision log: {exc}")

    def _close_decision_log(self) -> None:
        if self._decision_log_file is not None:
            try:
                self._decision_log_file.flush()
                self._decision_log_file.close()
            except Exception:
                pass
            self._decision_log_file = None

    # ─── 延迟日志 ────────────────────────────────────────────────────────────

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

    def _write_latency_log(
        self,
        *,
        frame_index: int,
        t_start: float,
        t_detect_end: float,
        t_track_done: float,
    ) -> None:
        try:
            self._ensure_latency_log()
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            detect_ms = (t_detect_end - t_start) * 1000
            track_ms = (t_track_done - t_detect_end) * 1000
            total_ms = (t_track_done - t_start) * 1000
            cmd_str = self._last_command or "-"
            persons = len(self._candidates) + (1 if self._active_target else 0)
            line = (
                f"{now_str} | {frame_index:06d} | {self._state.value}"
                f" | {persons} | {cmd_str}"
                f" | {detect_ms:.1f} | {track_ms:.1f} | {total_ms:.1f}\n"
            )
            self._latency_log_file.write(line)  # type: ignore
        except Exception as exc:
            logger.warning(f"[AutoTrackService] Failed to write latency log: {exc}")



# ─── 全局单例 ────────────────────────────────────────────────────────────────

_auto_track_service: Optional[AutoTrackService] = None


def get_auto_track_service() -> Optional[AutoTrackService]:
    return _auto_track_service


def set_auto_track_service(service: AutoTrackService) -> None:
    global _auto_track_service
    _auto_track_service = service


# ─── 几何工具（降级 IOU 使用） ───────────────────────────────────────────────

def _calc_iou(
    bbox_a: tuple[int, int, int, int],
    bbox_b: tuple[int, int, int, int],
) -> float:
    ax1, ay1, ax2, ay2 = bbox_a
    bx1, by1, bx2, by2 = bbox_b
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    if inter == 0:
        return 0.0
    area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    area_b = max(0, bx2 - bx1) * max(0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


async def _save_snapshot_to_disk(
    *,
    frame: bytes,
    snapshot_dir: Path,
    frame_width: int,
    frame_height: int,
) -> tuple[Path, str]:
    import numpy as np
    from PIL import Image

    now = datetime.utcnow()
    date_dir = now.strftime("%Y-%m-%d")
    filename = now.strftime("%H-%M-%S-%f") + ".jpg"
    target_dir = snapshot_dir / date_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    image_path = target_dir / filename
    image_url = f"/api/v1/static/{date_dir}/{filename}"

    frame_array = np.frombuffer(frame, dtype=np.uint8)
    frame_array = frame_array.reshape((frame_height, frame_width, 3))
    frame_array = frame_array[:, :, ::-1]
    image = Image.fromarray(frame_array)
    image.save(image_path, format="JPEG", quality=90)

    return image_path, image_url
