import asyncio
import logging
import time
from typing import List, Optional

from .config import Settings, settings
from .control_service import ControlService
from .control_arbiter import ControlArbiter
from .zone_service import ZoneService
from .ws_event_broadcaster import WSEventBroadcaster
from .guard_mission_types import GuardMissionState, GuardStatusDTO
from .motion_script_runner import MotionScriptRunner
from .tracking_types import DetectionResult as TrackDetectionResult, ControlOwner

logger = logging.getLogger("botdog.guard_mission")


class GuardMissionService:
    """驱离任务主服务（编排器）。"""

    def __init__(
        self,
        *,
        zone_service: ZoneService,
        control_service: ControlService,
        control_arbiter: ControlArbiter,
        event_broadcaster: WSEventBroadcaster,
        config: Settings,
        session_factory,
        snapshot_dir,
        frame_width: int,
        frame_height: int,
    ):
        self._zone_service = zone_service
        self._control_service = control_service
        self._control_arbiter = control_arbiter
        self._event_broadcaster = event_broadcaster
        self._config = config
        self._session_factory = session_factory
        self._snapshot_dir = snapshot_dir
        self._frame_width = frame_width
        self._frame_height = frame_height

        self._enabled = config.GUARD_MISSION_ENABLED
        self._state = GuardMissionState.STANDBY

        self._intrusion_counter = 0
        self._clear_counter = 0
        self._guard_start_time = 0.0
        self._guard_total_duration_s = 0.0

        self._last_mission_end_time = 0.0
        self._last_frame_time = time.monotonic()

        # MotionScriptRunner
        self._script_runner = MotionScriptRunner(
            watchdog_timeout_s=config.CONTROL_WATCHDOG_TIMEOUT_MS / 1000.0
        )
        self._cancel_event = asyncio.Event()
        self._script_task: Optional[asyncio.Task] = None
        self._audio_process: Optional[asyncio.subprocess.Process] = None

        # 帧数折算
        self._effective_fps = max(1.0, float(config.AI_FPS))
        self._confirm_time_s = config.GUARD_CONFIRM_TIME_S
        self._clear_time_s = config.GUARD_CLEAR_TIME_S

        # 清空判定过滤门槛
        self._clear_min_conf = config.GUARD_CLEAR_MIN_CONF
        self._clear_min_area = config.GUARD_CLEAR_MIN_AREA

        self._check_health_task = asyncio.create_task(self._health_check_loop())

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        self._enabled = value
        if not value and self._state != GuardMissionState.STANDBY:
            self._abort_mission("主动禁用任务")
            self._state = GuardMissionState.STANDBY

    @property
    def state(self) -> GuardMissionState:
        return self._state

    @property
    def _confirm_frames(self) -> int:
        return int(self._confirm_time_s * self._effective_fps)

    @property
    def _clear_frames(self) -> int:
        return int(self._clear_time_s * self._effective_fps)

    def update_effective_fps(self, fps: float):
        """由 AIWorker 调用，更新实际处理帧率以保持帧数折算准确。"""
        self._effective_fps = max(1.0, fps)

    def get_status(self) -> GuardStatusDTO:
        return GuardStatusDTO(
            enabled=self._enabled,
            state=self._state,
            intrusion_counter=self._intrusion_counter,
            confirm_frames=self._confirm_frames,
            clear_counter=self._clear_counter,
            clear_frames=self._clear_frames,
            guard_duration_s=time.monotonic() - self._guard_start_time if self._state == GuardMissionState.GUARDING else self._guard_total_duration_s,
        )

    # ─── AIWorker 回调入口 ──────────────────────────────────────────

    async def process_frame(self, detections: List[TrackDetectionResult], frame: bytes):
        """每帧调用，驱动状态机。由 AIWorker 调用。"""
        if not self._enabled:
            return

        self._last_frame_time = time.monotonic()

        # 检查人工接管
        if self._control_arbiter and not self._control_arbiter.can_guard_send():
            if self._state not in (GuardMissionState.STANDBY, GuardMissionState.MANUAL_OVERRIDE):
                self._abort_mission("人工接管")
                self._state = GuardMissionState.MANUAL_OVERRIDE
                self._broadcast_event("GUARD_ABORTED")
            
            # 手动释放后，MANUAL_OVERRIDE 应当恢复到 STANDBY，以便重新触发
            if self._state == GuardMissionState.MANUAL_OVERRIDE and not self._control_arbiter.is_manual_override_active():
                 if not self._control_arbiter.is_e_stop_active():
                     self._state = GuardMissionState.STANDBY
                     self._reset_mission_context()
            return

        # 根据当前状态分发处理
        if self._state == GuardMissionState.STANDBY:
            self._on_standby(detections)
        elif self._state == GuardMissionState.GUARDING:
            self._on_guarding(detections)
        # DEPLOYING / RETURNING 由 MotionScriptRunner 异步驱动
        # RETURNING 即使遇到目标，也须先回位

    # ─── 状态机具体逻辑 ──────────────────────────────────────────────

    def _on_standby(self, detections: List[TrackDetectionResult]):
        """待命状态：检查系统就绪条件 + 用 ZoneService polygon 判断是否有入侵。"""
        if not self._check_system_ready():
            self._intrusion_counter = 0
            return

        has_intruder = self._check_zone_intrusion(detections)
        if has_intruder:
            self._intrusion_counter += 1
        else:
            self._intrusion_counter = max(0, self._intrusion_counter - 2)

        if self._intrusion_counter >= self._confirm_frames:
            logger.info("[GuardMission] 目标入侵已确认，准备出出前往驱离点。")
            self._start_deploy(frame)

    def _check_system_ready(self) -> bool:
        """检查系统就绪条件，全部满足才允许触发任务。"""
        if not self._control_arbiter:
            return False
        # 1. 不在 E_STOP
        if self._control_arbiter.is_e_stop_active():
            return False
        # 2. 没有人工接管
        if self._control_arbiter.is_manual_override_active():
            return False
        # 3. 冷却期已过
        if time.monotonic() - self._last_mission_end_time < self._config.GUARD_COOLDOWN_S:
            return False
        return True

    def _check_zone_intrusion(self, detections: List[TrackDetectionResult]) -> bool:
        """【STANDBY 专用】检查是否有 person 在 ZoneService polygon 内。"""
        for det in detections:
            if det.class_name != "person":
                continue
            x1, y1, x2, y2 = det.bbox
            anchor = ((x1 + x2) // 2, y2)
            if self._zone_service.is_inside_zone(anchor):
                return True
        return False

    def _start_deploy(self, frame: bytes):
        """进入 DEPLOYING：开始前往驱离点。"""
        if not self._control_arbiter.request_control(ControlOwner.GUARD_MISSION):
            logger.warning("[GuardMission] 申请控制权失败，无法出动。")
            self._intrusion_counter = 0
            return

        self._state = GuardMissionState.DEPLOYING
        self._intrusion_counter = 0
        self._broadcast_event("GUARD_INTRUSION_CONFIRMED")
        asyncio.create_task(self._take_snapshot_safe(frame, "intrusion_confirmed"))

        deploy_script = [
            ("stand", self._config.GUARD_DEPLOY_SETTLE_S),
            ("forward", self._config.GUARD_DEPLOY_DURATION_S),
            ("stop", 0.5),
        ]
        self._script_task = asyncio.create_task(
            self._run_script_and_transition(deploy_script, GuardMissionState.GUARDING)
        )

    def _on_guarding(self, detections: List[TrackDetectionResult]):
        """驱离状态：用全画面 person 检测判断是否已清空。"""
        has_person_in_view = self._check_any_person_qualified(detections)
        if not has_person_in_view:
            self._clear_counter += 1
        else:
            self._clear_counter = 0

        elapsed = time.monotonic() - self._guard_start_time
        
        # 驱离超时判断
        if elapsed >= self._config.GUARD_MAX_DURATION_S:
            logger.warning("[GuardMission] 驱离已超时强制返回。")
            self._start_return(frame, is_timeout=True)
            return

        # 满足清空判定条件
        if (self._clear_counter >= self._clear_frames and elapsed >= self._config.GUARD_MIN_DURATION_S):
            logger.info("[GuardMission] 目标区域已清空，准备返回起点。")
            self._start_return(frame, is_timeout=False)

    def _check_any_person_qualified(self, detections: List[TrackDetectionResult]) -> bool:
        """【GUARDING 专用】检查全画面中是否还有满足门槛的 person。"""
        for det in detections:
            if det.class_name != "person":
                continue
            if det.confidence < self._clear_min_conf:
                continue
            x1, y1, x2, y2 = det.bbox
            area = (x2 - x1) * (y2 - y1)
            if area < self._clear_min_area:
                continue
            return True
        return False

    def _start_return(self, frame: bytes, is_timeout: bool = False):
        """进入 RETURNING：返回起点。"""
        self._guard_total_duration_s = time.monotonic() - self._guard_start_time
        asyncio.create_task(self._stop_guard_audio())
        self._state = GuardMissionState.RETURNING
        self._clear_counter = 0
        
        if not is_timeout:
            self._broadcast_event("GUARD_ZONE_CLEARED")
            asyncio.create_task(self._take_snapshot_safe(frame, "zone_cleared"))

        return_script = [
            ("backward", self._config.GUARD_RETURN_DURATION_S),
            ("stop", 0.5),
            ("sit", self._config.GUARD_RETURN_SETTLE_S),
        ]
        self._script_task = asyncio.create_task(
            self._run_script_and_transition(return_script, GuardMissionState.STANDBY)
        )

    async def _run_script_and_transition(self, script, next_state: GuardMissionState):
        """执行脚本并在成功后进入下一状态。"""
        success = await self._script_runner.run(
            script, self._control_service, self._cancel_event
        )
        if success:
            self._state = next_state
            if next_state == GuardMissionState.GUARDING:
                self._broadcast_event("GUARD_ARRIVED")
                # 记录抓拍需要用到当时的帧，如果 _run_script 里取不到最新帧，我们这里可以用 None 并在内部使用黑框图或者忽略或者不存原图。
                # 由于这通常是一个长时任务结束触发，我们最好还是在下一帧到达 _on_guarding 或者 _on_standby 时再由 process_frame 接管画面状态比较省力，或者只留文字告警，无图。这里无图记录即可
                asyncio.create_task(self._take_snapshot_safe(b'', "arrived"))
                self._guard_start_time = time.monotonic()
                asyncio.create_task(self._start_guard_audio())
            elif next_state == GuardMissionState.STANDBY:
                self._broadcast_event("GUARD_RETURNED")
                asyncio.create_task(self._take_snapshot_safe(b'', "returned"))
                self._control_arbiter.release_control(ControlOwner.GUARD_MISSION)
                self._reset_mission_context()
        else:
            # 脚本因为异常被终止，如果之前没有设为 MANUAL 或 FAULT
            if self._state not in (GuardMissionState.MANUAL_OVERRIDE, GuardMissionState.FAULT):
                logger.error("[GuardMission] 运动脚本执行失败，进入 FAULT。")
                self._state = GuardMissionState.FAULT
                self._control_arbiter.release_control(ControlOwner.GUARD_MISSION)
                self._broadcast_event("GUARD_FAULT")

    # ─── 异常与状态处理 ─────────────────────────────────────────────

    def _abort_mission(self, reason: str):
        """中止当前任务并重置态。"""
        logger.info(f"[GuardMission] 任务中止: {reason}")
        if self._script_task and not self._script_task.done():
            self._cancel_event.set()
        asyncio.create_task(self._stop_guard_audio())
        asyncio.create_task(self._control_service.handle_command("stop"))
        
        if self._control_arbiter and self._control_arbiter.owner == ControlOwner.GUARD_MISSION:
            self._control_arbiter.release_control(ControlOwner.GUARD_MISSION)
            
        self._reset_mission_context()

    def _reset_mission_context(self):
        """完整清零任务上下文，防止残留状态导致回到 STANDBY 后误触发。"""
        self._intrusion_counter = 0
        self._clear_counter = 0
        self._guard_start_time = 0.0
        self._script_task = None
        self._cancel_event = asyncio.Event()  # 重建，旧的可能已被 set
        self._last_mission_end_time = time.monotonic()  # 进入冷却期

    async def _health_check_loop(self):
        """定期检查视觉链路。"""
        timeout = self._config.GUARD_VISUAL_TIMEOUT_S
        while True:
            await asyncio.sleep(2.0)
            if not self._enabled:
                continue
            
            if self._state in (GuardMissionState.DEPLOYING, GuardMissionState.GUARDING, GuardMissionState.RETURNING):
                if time.monotonic() - self._last_frame_time > timeout:
                    logger.error(f"[GuardMission] 视觉链路超过 {timeout}s 未更新，判定失效！")
                    self._abort_mission("视觉链路失效")
                    self._state = GuardMissionState.FAULT
                    self._broadcast_event("GUARD_FAULT")

    def _broadcast_event(self, msg_type: str):
        """简单的 WS 事件广播方法。"""
        payload = {"status": self._state.value}
        try:
            from .schemas import utc_now_iso
            broadcaster = self._event_broadcaster
            if broadcaster and broadcaster.connection_count > 0:
                msg = {
                    "msg_type": msg_type,
                    "timestamp": utc_now_iso(),
                    "payload": payload,
                }
                asyncio.create_task(self._do_broadcast(msg))
        except Exception as exc:
            logger.debug(f"[GuardMission] 广播 {msg_type} 失败: {exc}")

    async def _do_broadcast(self, msg):
        broadcaster = self._event_broadcaster
        if not broadcaster:
            return
        async with broadcaster._lock:
            failed = []
            for conn in broadcaster._connections:
                try:
                    await conn.send_json(msg)
                except Exception:
                    failed.append(conn)
            for c in failed:
                broadcaster._connections.discard(c)

    async def _take_snapshot_safe(self, frame: bytes, label: str) -> None:
        if not frame:
            logger.info(f"[GuardMission] 纯文字告警/节点记录（无图）: {label}")
            image_path = ""
            image_url = ""
        else:
            try:
                from .auto_track_service import _save_snapshot_to_disk
                image_path, image_url = await _save_snapshot_to_disk(
                    frame=frame,
                    snapshot_dir=self._snapshot_dir,
                    frame_width=self._frame_width,
                    frame_height=self._frame_height,
                )
            except Exception as exc:
                logger.debug(f"[GuardMission] 抓拍磁盘写入失败: {exc}")
                return
            
        try:
            from .alert_service import get_alert_service
            alert_service = get_alert_service()
            if alert_service:
                async with self._session_factory() as session:
                    await alert_service.handle_ai_event(
                        event_type="GUARD_MISSION_SNAPSHOT",
                        event_code=f"E_GUARD_{label.upper()}",
                        severity="INFO",
                        message=f"自动驱离记录节点（{label}）",
                        confidence=1.0,
                        file_path=str(image_path),
                        image_url=image_url,
                        gps_lat=None,
                        gps_lon=None,
                        task_id=None,
                        session=session,
                    )
        except Exception as exc:
            logger.debug(f"[GuardMission] 记录数据库告警失败: {exc}")

    # ─── 音频动作 (Phase 4) ──────────────────────────────────────────

    async def _start_guard_audio(self):
        """启动警告音频循环播放。"""
        path = self._config.GUARD_ALERT_AUDIO_PATH
        logger.info(f"[GuardMission] 开始播放驱离音频: {path}")
        try:
            self._audio_process = await asyncio.create_subprocess_exec(
                "aplay", "-D", "plughw:1,0", "--loop", str(path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except FileNotFoundError:
            # 在没有 aplay 的环境（如 Windows）下模拟
            logger.warning("[GuardMission] 未找到 aplay，采用模拟播放 (Python 版)。")
            self._audio_process = await asyncio.create_subprocess_exec(
                "python", "scripts/mock_audio.py",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )

    async def _stop_guard_audio(self):
        """停止警告音频播放。"""
        if self._audio_process:
            logger.info("[GuardMission] 停止驱离音频。")
            try:
                self._audio_process.terminate()
            except ProcessLookupError:
                pass
            self._audio_process = None


# 全局实例
_guard_mission_service: Optional[GuardMissionService] = None

def get_guard_mission_service() -> Optional[GuardMissionService]:
    return _guard_mission_service

def set_guard_mission_service(service: GuardMissionService):
    global _guard_mission_service
    _guard_mission_service = service
