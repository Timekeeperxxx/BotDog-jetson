"""
自动跟踪主服务。

职责边界：
- 维护自动跟踪状态机
- 处理检测结果并决策是否锁定目标
- 通过 ControlService 下发跟踪控制命令
- 广播自动跟踪状态事件
- 触发抓拍（目标锁定时 + 可选终止时）

设计原则：
- 始终初始化（无论 AUTO_TRACK_ENABLED），装配与运行时开关分离
- enable()/disable() 只控制内部 _enabled 标志
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
    自动跟踪主服务。

    与 AIWorker 的职责分工：
    - AIWorker 负责：视频采集 + 调用检测器 + 调用本服务 + 广播 AI_STATUS
    - AutoTrackService 负责：目标稳定命中 + 锁定 + 区内判断 + 控制决策 + 抓拍 + 事件广播
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
        anchor_y_stop_ratio: float = 0.80,
        stop_snapshot_enabled: bool = True,
        default_enabled: bool = False,
        # 阶段 2 新增：可选依赖（None 时退回阶段 1 单目标路径）
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

        # 运行时开关（与装配是否存在无关）
        self._enabled: bool = default_enabled
        self._paused: bool = False
        self._state: AutoTrackState = (
            AutoTrackState.IDLE if default_enabled else AutoTrackState.DISABLED
        )

        # 目标跟踪状态（阶段 1 单目标）
        self._active_target: Optional[ActiveTarget] = None
        self._hit_count: int = 0          # 当前候选目标连续命中帧数
        self._miss_count: int = 0         # 当前候选目标连续未命中帧数
        self._candidate_iou_track_id: int = 0  # 阶段 1 帧间 IOU 生成的临时 ID
        self._last_candidate_bbox: Optional[tuple[int, int, int, int]] = None

        self._stop_reason: Optional[TrackStopReason] = None

        # 阶段 2：多目标管理和仲裁器（非 None 时启用多目标路径）
        self._target_manager: "TargetManager | None" = target_manager
        self._control_arbiter: "ControlArbiter | None" = control_arbiter

        # 若提供了 ControlArbiter 且默认启用，申请初始控制权
        if self._control_arbiter and default_enabled:
            self._control_arbiter.request_control(ControlOwner.AUTO_TRACK)

        # 决策引擎
        self._decision_engine = FollowDecisionEngine(
            yaw_deadband_px=yaw_deadband_px,
            forward_area_ratio=forward_area_ratio,
            anchor_y_stop_ratio=anchor_y_stop_ratio,
            command_interval_ms=command_interval_ms,
        )

        # 调试状态广播
        self._last_status_broadcast: float = 0.0
        self._last_command: Optional[str] = None
        self._last_decision_reason: Optional[str] = None  # 每帧决策原因
        self._frames_processed: int = 0

        # 跟踪决策日志文件（写入 scripts/ 目录）
        self._decision_log_file: Optional["IO[str]"] = None  # type: ignore[name-defined]
        self._decision_log_path: Optional[Path] = None

        logger.info(
            f"[AutoTrackService] 初始化完成，默认启用={default_enabled}，"
            f"stable_hits={stable_hits}，out_of_zone_frames={out_of_zone_frames}"
        )

    # ─── 公共控制接口 ────────────────────────────────────────────────────────

    def enable(self) -> None:
        """运行时启用自动跟踪。"""
        self._enabled = True
        self._paused = False
        if self._state == AutoTrackState.DISABLED:
            self._state = AutoTrackState.IDLE
        if self._control_arbiter:
            self._control_arbiter.request_control(ControlOwner.AUTO_TRACK)
        logger.info("[AutoTrackService] 自动跟踪已启用")

    def disable(self) -> None:
        """运行时禁用，立即 stop 并进入 DISABLED 状态。"""
        if self._enabled:
            logger.info("[AutoTrackService] 自动跟踪已禁用")
        self._enabled = False
        self._paused = False
        self._do_stop(TrackStopReason.DISABLED, send_stop_command=True)
        self._state = AutoTrackState.DISABLED
        if self._control_arbiter:
            self._control_arbiter.release_control(ControlOwner.AUTO_TRACK)

    def pause(self) -> None:
        """暂停（保留目标状态，停发控制命令）。"""
        if not self._enabled:
            return
        self._paused = True
        self._state = AutoTrackState.PAUSED
        logger.info("[AutoTrackService] 自动跟踪已暂停")

    def resume(self) -> None:
        """恢复到暂停前的状态。"""
        if not self._enabled:
            return
        self._paused = False
        if self._active_target is not None:
            self._state = AutoTrackState.FOLLOWING
        else:
            self._state = AutoTrackState.IDLE
        logger.info("[AutoTrackService] 自动跟踪已恢复")

    def stop(self, reason: TrackStopReason, send_stop_command: bool = True) -> None:
        """外部触发停止（断流、E-STOP、任务结束等）。"""
        self._do_stop(reason, send_stop_command=send_stop_command)

    def get_status(self) -> dict:
        """返回当前跟踪状态快照（用于调试端点和前端展示）。"""
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
            "hit_count": self._hit_count,
            "stable_hits_threshold": self._stable_hits,
            "control_arbiter": arbiter_status,
            "multi_target_mode": self._target_manager is not None,
            "candidate_count": (
                self._target_manager.candidate_count
                if self._target_manager else 0
            ),
        }

    # ─── 核心处理接口 ────────────────────────────────────────────────────────

    async def process_frame(
        self,
        detections: list[DetectionResult],
        frame: bytes,
        frame_index: int,
        current_task_id: Optional[int] = None,
    ) -> None:
        """
        处理单帧的检测结果，推动跟踪状态机。

        由 AIWorker 在每帧推理后调用。
        """
        self._frames_processed += 1

        if not self._enabled or self._paused:
            return

        # 非任务状态禁止跟踪（必须在开启巡检模式后才会激活）
        if not self._is_mission_active(current_task_id):
            if self._state not in (AutoTrackState.DISABLED, AutoTrackState.IDLE):
                self._do_stop(TrackStopReason.MISSION_ENDED, send_stop_command=True)
                self._state = AutoTrackState.IDLE
            return

        # 过滤只要 person 类别
        persons = [d for d in detections if d.class_name == "person"]

        # 阶段 2：如果有 TargetManager，先更新候选池
        if self._target_manager is not None:
            det_tuples = [
                (d.bbox, d.confidence, d.class_name)
                for d in detections
            ]
            self._target_manager.update(
                detections=det_tuples,
                inside_zone_fn=self._zone_service.is_inside_zone,
            )
            self._target_manager.prune_stale(max_age_seconds=2.0)

        if self._active_target is None:
            # 当前无活跃目标，寻找候选
            await self._try_acquire_target(persons, frame, current_task_id)
        else:
            # 已有活跃目标，更新并跟踪
            await self._update_and_follow(persons, frame, current_task_id)

        # 每帧写入检测日志（包含人数、位置；跟踪中还包含决策）
        if not self._active_target:
            self._write_frame_log(persons)

        # 定时广播调试状态
        await self._maybe_broadcast_debug_status()

    # ─── 内部状态机 ─────────────────────────────────────────────────────────

    async def _try_acquire_target(
        self,
        persons: list[DetectionResult],
        frame: bytes,
        task_id: Optional[int],
    ) -> None:
        """尚无活跃目标时，对候选目标进行稳定命中计数。"""
        if not persons:
            # 无检测，重置候选状态
            self._hit_count = 0
            self._miss_count = 0
            self._last_candidate_bbox = None
            if self._state == AutoTrackState.DETECTING:
                self._state = AutoTrackState.IDLE
            return

        # 选择置信度最高的 person（阶段 1 单目标简化）
        best = max(persons, key=lambda d: d.confidence)
        bbox = best.bbox

        # 区域判断
        x1, y1, x2, y2 = bbox
        anchor = ((x1 + x2) // 2, y2)
        inside = self._zone_service.is_inside_zone(anchor)

        if not inside:
            # 不在重点区内，不触发命中
            self._state = AutoTrackState.IDLE
            return

        # 帧间 IOU 匹配（阶段 1 简化：只要置信度最高的那个候选连续命中）
        if self._last_candidate_bbox is not None:
            iou = _calc_iou(bbox, self._last_candidate_bbox)
            if iou < 0.4:
                # IOU 过低视为新目标，重置计数
                self._hit_count = 0
                self._candidate_iou_track_id += 1
                logger.debug(f"[AutoTrackService] 目标切换，新 track_id={self._candidate_iou_track_id}")

        self._last_candidate_bbox = bbox
        self._hit_count += 1
        self._state = AutoTrackState.DETECTING

        if self._hit_count >= self._stable_hits:
            # 稳定命中达标，锁定目标
            ts = time.monotonic()
            self._active_target = ActiveTarget(
                track_id=self._candidate_iou_track_id,
                bbox=bbox,
                anchor_point=anchor,
                inside_zone=inside,
                locked_at=ts,
                last_seen_ts=ts,
            )
            self._hit_count = 0
            self._miss_count = 0
            self._state = AutoTrackState.TARGET_LOCKED
            logger.info(
                f"[AutoTrackService] 目标锁定 track_id={self._candidate_iou_track_id} "
                f"confidence={best.confidence:.2f} anchor={anchor}"
            )
            # 抓拍：目标首次锁定
            await self._take_snapshot_safe(frame, "locked", task_id)
            await self._broadcast_event("STRANGER_TARGET_LOCKED", {
                "track_id": self._candidate_iou_track_id,
                "bbox": list(bbox),
                "confidence": best.confidence,
                "inside_zone": inside,
            })
            # 立即进入跟踪状态
            self._state = AutoTrackState.FOLLOWING
            self._active_target.follow_started_at = time.monotonic()
            await self._broadcast_event("AUTO_TRACK_STARTED", {
                "track_id": self._candidate_iou_track_id,
            })

    async def _update_and_follow(
        self,
        persons: list[DetectionResult],
        frame: bytes,
        task_id: Optional[int],
    ) -> None:
        """已有活跃目标时：更新目标状态，执行跟踪控制命令。"""
        assert self._active_target is not None

        target = self._active_target

        # 用 IOU 在当前帧中找到目标
        matched = _find_matching_detection(persons, target.bbox, iou_threshold=0.3)

        if matched is None:
            # 目标丢失
            target.lost_count += 1
            self._state = AutoTrackState.LOST_SHORT

            if target.lost_count >= self._lost_timeout_frames:
                logger.info(
                    f"[AutoTrackService] 目标 {target.track_id} 丢失超时，停止跟踪"
                )
                await self._stop_with_snapshot(TrackStopReason.TARGET_LOST, frame, task_id)
            else:
                # 短时丢失：保持停止，不前冲
                await self._send_command_safe("stop")
            return

        # 找到目标，更新状态
        target.bbox = matched.bbox
        x1, y1, x2, y2 = matched.bbox
        anchor = ((x1 + x2) // 2, y2)
        target.anchor_point = anchor
        target.last_seen_ts = time.monotonic()
        target.lost_count = 0

        # 区域判断
        inside = self._zone_service.is_inside_zone(anchor)
        target.inside_zone = inside

        if not inside:
            target.out_of_zone_count += 1
            self._state = AutoTrackState.OUT_OF_ZONE_PENDING

            if target.out_of_zone_count >= self._out_of_zone_frames:
                logger.info(
                    f"[AutoTrackService] 目标 {target.track_id} 连续出区 "
                    f"{target.out_of_zone_count} 帧，停止跟踪"
                )
                await self._stop_with_snapshot(TrackStopReason.OUT_OF_ZONE, frame, task_id)
            else:
                await self._send_command_safe("stop")
        else:
            target.out_of_zone_count = 0
            self._state = AutoTrackState.FOLLOWING

            # 生成跟踪控制命令
            decision = self._decision_engine.decide(
                bbox=matched.bbox,
                image_width=self._frame_width,
                image_height=self._frame_height,
            )

            if decision.should_send and decision.command:
                await self._send_command_safe(decision.command)

            # 每帧广播决策结果给前端（用于调试可视化）
            self._last_decision_reason = decision.reason
            await self._broadcast_event("TRACK_DECISION", {
                "command": decision.command,
                "should_send": decision.should_send,
                "reason": decision.reason,
                "bbox": list(matched.bbox),
                "anchor": list(target.anchor_point),
            })

            # 写入跟踪决策日志文件
            self._write_frame_log(
                persons,
                command=decision.command,
                should_send=decision.should_send,
                reason=decision.reason,
                bbox=matched.bbox,
                anchor=target.anchor_point,
            )

    # ─── 内部工具 ────────────────────────────────────────────────────────────


    # --- tracking decision log helpers ------------------------------------------

    def _ensure_decision_log(self) -> None:
        """Lazily create the log file on first write."""
        if self._decision_log_file is not None:
            return
        import io
        from datetime import datetime
        scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = scripts_dir / f"track_decisions_{ts}.log"
        self._decision_log_path = log_path
        self._decision_log_file = io.open(log_path, "w", encoding="utf-8", buffering=1)
        self._decision_log_file.write(
            "# BotDog tracking decision log\n"
            "# cols: timestamp | frame | detected | person_count"
            " | persons_bboxes | track_cmd | sent | reason | active_bbox | anchor\n"
            "# persons_bboxes: x1,y1,x2,y2;... (semicolon-separated, - if none)\n"
        )
        logger.info(f"[AutoTrackService] Decision log created: {log_path}")

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
        """Write one log line per frame. Records detection state and optional decision."""
        try:
            self._ensure_decision_log()
            from datetime import datetime
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            person_count = len(persons)
            detected = "YES" if person_count > 0 else "NO"
            persons_bboxes = ";".join(
                f"{d.bbox[0]},{d.bbox[1]},{d.bbox[2]},{d.bbox[3]}" for d in persons
            ) if person_count > 0 else "-"
            cmd_str = command or "-"
            sent_str = "Y" if should_send else "N"
            reason_str = reason.replace("|", "|") if reason else "-"
            bbox_str = f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}" if bbox else "-"
            anchor_str = f"{anchor[0]},{anchor[1]}" if anchor else "-"
            line = (
                f"{now_str} | {self._frames_processed:06d} | {detected} | {person_count}"
                f" | {persons_bboxes} | {cmd_str} | {sent_str} | {reason_str}"
                f" | {bbox_str} | {anchor_str}\n"
            )
            assert self._decision_log_file is not None
            self._decision_log_file.write(line)
        except Exception as exc:
            logger.warning(f"[AutoTrackService] Failed to write decision log: {exc}")

    def _close_decision_log(self) -> None:
        """Flush and close the log file (call on service stop)."""
        if self._decision_log_file is not None:
            try:
                self._decision_log_file.flush()
                self._decision_log_file.close()
                logger.info(f"[AutoTrackService] Decision log closed: {self._decision_log_path}")
            except Exception:
                pass
            self._decision_log_file = None

    def _is_mission_active(self, task_id: Optional[int]) -> bool:
        from .state_machine import SystemState
        return (
            self._state_machine.state == SystemState.IN_MISSION
            and task_id is not None
        )

    def _do_stop(
        self,
        reason: TrackStopReason,
        send_stop_command: bool = True,
    ) -> None:
        self._stop_reason = reason
        if self._state not in (AutoTrackState.DISABLED, AutoTrackState.IDLE):
            self._state = AutoTrackState.STOPPED
        self._active_target = None
        self._hit_count = 0
        self._miss_count = 0
        self._last_candidate_bbox = None
        self._decision_engine.reset()
        if send_stop_command:
            asyncio.create_task(self._send_command_safe("stop"))
        logger.info(f"[AutoTrackService] 跟踪停止，原因={reason.value}")

    async def _stop_with_snapshot(
        self,
        reason: TrackStopReason,
        frame: bytes,
        task_id: Optional[int],
    ) -> None:
        """停止跟踪，可选补拍一张终止证据图。"""
        if self._stop_snapshot_enabled:
            await self._take_snapshot_safe(frame, "stopped", task_id)

        await self._broadcast_event("AUTO_TRACK_STOPPED", {
            "track_id": self._active_target.track_id if self._active_target else None,
            "reason": reason.value,
        })
        self._do_stop(reason, send_stop_command=True)

        # 停止后等待 IDLE
        if self._enabled:
            self._state = AutoTrackState.IDLE

    async def _send_command_safe(self, cmd: str) -> None:
        """通过 ControlService 发送命令，发前检查 ControlArbiter 权限。"""
        try:
            # stop 命令无需检查控制权（安全命令始终允许）
            if cmd != "stop" and self._control_arbiter is not None:
                if not self._control_arbiter.can_auto_track_send():
                    # 人工控制接管了
                    if self._state not in (
                        AutoTrackState.MANUAL_OVERRIDE,
                        AutoTrackState.DISABLED,
                        AutoTrackState.STOPPED,
                    ):
                        owner = self._control_arbiter.owner
                        logger.info(
                            f"[AutoTrackService] 控制权被 {owner.value} 接管，"
                            f"自动命令已拦截，进入 MANUAL_OVERRIDE"
                        )
                        self._state = AutoTrackState.MANUAL_OVERRIDE
                        await self._broadcast_event("AUTO_TRACK_MANUAL_OVERRIDE", {
                            "control_owner": owner.value,
                        })
                    return
            self._last_command = cmd
            await self._control_service.handle_command(cmd)
        except Exception as exc:
            logger.debug(f"[AutoTrackService] 发送命令 {cmd!r} 失败: {exc}")

    async def _take_snapshot_safe(
        self,
        frame: bytes,
        label: str,
        task_id: Optional[int],
    ) -> None:
        """保存抓拍图并写入证据记录，失败不影响主流程。"""
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
        """广播事件，失败不影响主流程。"""
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
        """每 2 秒广播一次跟踪状态（调试用）。"""
        now = time.monotonic()
        if now - self._last_status_broadcast < 2.0:
            return
        self._last_status_broadcast = now
        await self._broadcast_event("AUTO_TRACK_STATUS", self.get_status())


# ─── 全局单例 ────────────────────────────────────────────────────────────────

_auto_track_service: Optional[AutoTrackService] = None


def get_auto_track_service() -> Optional[AutoTrackService]:
    return _auto_track_service


def set_auto_track_service(service: AutoTrackService) -> None:
    global _auto_track_service
    _auto_track_service = service


# ─── 几何工具 ────────────────────────────────────────────────────────────────

def _calc_iou(
    bbox_a: tuple[int, int, int, int],
    bbox_b: tuple[int, int, int, int],
) -> float:
    """计算两个 bbox 的 IOU（交并比）。"""
    ax1, ay1, ax2, ay2 = bbox_a
    bx1, by1, bx2, by2 = bbox_b

    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)

    inter_w = max(0, ix2 - ix1)
    inter_h = max(0, iy2 - iy1)
    inter = inter_w * inter_h

    if inter == 0:
        return 0.0

    area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    area_b = max(0, bx2 - bx1) * max(0, by2 - by1)
    union = area_a + area_b - inter

    return inter / union if union > 0 else 0.0


def _find_matching_detection(
    persons: list[DetectionResult],
    target_bbox: tuple[int, int, int, int],
    iou_threshold: float = 0.3,
) -> Optional[DetectionResult]:
    """在候选检测中找到与目标 bbox IOU 最高且超过阈值的一个。"""
    best_iou = iou_threshold
    best_det = None
    for det in persons:
        iou = _calc_iou(det.bbox, target_bbox)
        if iou >= best_iou:
            best_iou = iou
            best_det = det
    return best_det


async def _save_snapshot_to_disk(
    *,
    frame: bytes,
    snapshot_dir: Path,
    frame_width: int,
    frame_height: int,
) -> tuple[Path, str]:
    """保存帧数据到磁盘。"""
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
