import asyncio
import logging
import time
from typing import List, Optional

from .config import Settings, settings
from .control_service import ControlService
from .control_arbiter import ControlArbiter
from .zone_service import ZoneService
from .ws_event_broadcaster import EventBroadcaster
from .guard_mission_types import GuardMissionState, GuardStatusDTO, AnchorStatusDTO
from .tracking_types import DetectionResult as TrackDetectionResult, ControlOwner

from .visual_anchor_tracker import VisualAnchorTracker
from .visual_servo_controller import VisualServoController

logger = logging.getLogger("botdog.guard_mission")

def _calc_intersection_ratio(boxA, boxB):
    # box: (x, y, w, h)
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[0] + boxA[2], boxB[0] + boxB[2])
    yB = min(boxA[1] + boxA[3], boxB[1] + boxB[3])

    interArea = max(0, xB - xA) * max(0, yB - yA)
    if interArea == 0:
        return 0.0
    boxAArea = boxA[2] * boxA[3]
    return interArea / float(boxAArea) if boxAArea > 0 else 0.0

class GuardMissionService:
    """视觉锚点防区驱离主服务（基于视觉伺服）。"""

    def __init__(
        self,
        *,
        zone_service: ZoneService,
        control_service: ControlService,
        control_arbiter: ControlArbiter,
        event_broadcaster: EventBroadcaster,
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
        
        self._audio_process: Optional[asyncio.subprocess.Process] = None

        # ==== 视觉伺服组件 ====
        self._anchor_tracker = VisualAnchorTracker()
        self._servo_controller = VisualServoController(yaw_deadband_px=40)
        self._start_bbox: Optional[tuple] = None
        self._curr_bbox: Optional[tuple] = None
        self._lost_anchor_counter = 0
        self._last_command = "stop"
        self._command_rate_limit_ms = 100
        self._last_cmd_send_time = 0.0

        # 帧数折算
        self._effective_fps = max(1.0, float(config.AI_FPS))

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
        return int(self._config.GUARD_CONFIRM_TIME_S * self._effective_fps)

    @property
    def _clear_frames(self) -> int:
        return int(self._config.GUARD_CLEAR_TIME_S * self._effective_fps)

    @property
    def _lost_anchor_frames(self) -> int:
        return int(self._config.GUARD_ANCHOR_LOST_TIMEOUT_S * self._effective_fps)

    def update_effective_fps(self, fps: float):
        self._effective_fps = max(1.0, fps)

    def get_status(self) -> GuardStatusDTO:
        return GuardStatusDTO(
            enabled=self._enabled,
            state=self._state,
            intrusion_counter=self._intrusion_counter,
            confirm_frames=self._confirm_frames,
            clear_counter=self._clear_counter,
            clear_frames=self._clear_frames,
            guard_duration_s=time.monotonic() - self._guard_start_time if self._state == GuardMissionState.ADVANCING else self._guard_total_duration_s,
        )

    # ─── 核心帧处理流 ──────────────────────────────────────────

    async def process_frame(self, detections: List[TrackDetectionResult], frame: bytes):
        if not self._enabled:
            return

        self._last_frame_time = time.monotonic()

        # ── 人工接管校验（仅在已获取控制权的活跃运动状态下检查） ──
        if self._state in (GuardMissionState.ADVANCING, GuardMissionState.RETURNING):
            if self._control_arbiter and not self._control_arbiter.can_guard_send():
                self._abort_mission("人工接管")
                self._state = GuardMissionState.MANUAL_OVERRIDE
                self._broadcast_event("GUARD_ABORTED")

        # ── 手动接管恢复检测 ──
        if self._state == GuardMissionState.MANUAL_OVERRIDE:
            if self._control_arbiter:
                if not self._control_arbiter.is_manual_override_active() and not self._control_arbiter.is_e_stop_active():
                    self._state = GuardMissionState.STANDBY
                    self._reset_mission_context()
            # 手动接管中不执行状态机，但仍然广播 overlay
        elif self._state == GuardMissionState.STANDBY:
            await self._on_standby(detections, frame)
        elif self._state == GuardMissionState.ADVANCING:
            await self._on_advancing(detections, frame)
        elif self._state == GuardMissionState.RETURNING:
            await self._on_returning(detections, frame)

        # ── 始终广播 overlay（无论什么状态前端都能看到框） ──
        active_bbox = None
        if self._state in (GuardMissionState.ADVANCING, GuardMissionState.RETURNING) and self._curr_bbox:
            x, y, w, h = self._curr_bbox
            active_bbox = [x, y, x + w, y + h]
        else:
            # 待机/故障等状态：画出防区原始范围
            z_box = self._get_zone_bounding_box()
            if z_box:
                x, y, w, h = z_box
                active_bbox = [x, y, x + w, y + h]
            
        await self._broadcast_overlay(detections, active_bbox)

    async def _broadcast_overlay(self, detections: List[TrackDetectionResult], active_bbox: Optional[list]):
        try:
            from .schemas import utc_now_iso
            broadcaster = self._event_broadcaster
            if broadcaster and broadcaster.connection_count > 0:
                msg = {
                    "msg_type": "TRACK_OVERLAY",
                    "timestamp": utc_now_iso(),
                    "payload": {
                        "persons": [
                            {
                                "bbox": list(d.bbox),
                                "conf": round(d.confidence, 2),
                                "track_id": d.track_id
                            }
                            for d in detections
                        ],
                        "active_bbox": active_bbox,
                        "command": self._last_command if active_bbox else None,
                        "reason": f"Guard: {self._state.value}",
                        "state": self._state.value,
                        "frame_w": self._frame_width,
                        "frame_h": self._frame_height,
                        "deadband_px": self._servo_controller._yaw_deadband_px,
                        "anchor_y_stop_ratio": 0.0,
                        "forward_area_ratio": 0.0,
                    }
                }
                asyncio.create_task(self._do_broadcast(msg))
        except Exception:
            pass

    # ─── 状态流转逻辑 ──────────────────────────────────────────────

    async def _on_standby(self, detections: List[TrackDetectionResult], frame: bytes):
        if not self._check_system_ready():
            self._intrusion_counter = 0
            return

        has_intruder = self._check_zone_intrusion(detections)
        if has_intruder:
            self._intrusion_counter += 1
        else:
            self._intrusion_counter = max(0, self._intrusion_counter - 2)

        if self._intrusion_counter >= self._confirm_frames:
            logger.info("[GuardMission] 目标入侵已确认，准备锁定视觉锚点！")
            await self._lock_anchor_and_start(frame)

    def _check_system_ready(self) -> bool:
        if not self._control_arbiter:
            return False
        if self._control_arbiter.is_e_stop_active():
            return False
        if self._control_arbiter.is_manual_override_active():
            return False
        if time.monotonic() - self._last_mission_end_time < self._config.GUARD_COOLDOWN_S:
            return False
        return True

    def _check_zone_intrusion(self, detections: List[TrackDetectionResult]) -> bool:
        zone_bbox = self._get_zone_bounding_box()
        if not zone_bbox:
            return False
            
        # 只要有一点重叠（复用重叠检测逻辑），就认为发起了入侵
        has_overlap = self._check_person_overlap(detections, zone_bbox)
        return has_overlap

    def _get_zone_bounding_box(self) -> Optional[tuple]:
        """将绘制的 polygon 转化为 opencv 的 bbox: (x, y, w, h)"""
        polygon = self._zone_service.polygon
        if not polygon or len(polygon) < 3:
            return None
        min_x = min(p[0] for p in polygon)
        max_x = max(p[0] for p in polygon)
        min_y = min(p[1] for p in polygon)
        max_y = max(p[1] for p in polygon)
        w = max_x - min_x
        h = max_y - min_y
        return (min_x, min_y, w, h)

    async def _lock_anchor_and_start(self, frame: bytes):
        """进入 LOCK_ANCHOR -> ADVANCING"""
        if not self._control_arbiter.request_control(ControlOwner.GUARD_MISSION):
            logger.warning("[GuardMission] 申请控制权失败，无法出动。")
            self._intrusion_counter = 0
            return

        zone_bbox = self._get_zone_bounding_box()
        if not zone_bbox:
            logger.error("[GuardMission] 尚无有效的防区形状，无法截取视觉锚点。")
            self._intrusion_counter = 0
            self._control_arbiter.release_control(ControlOwner.GUARD_MISSION)
            return

        # 锁定底层特征
        ok = self._anchor_tracker.init_anchor(frame, self._frame_width, self._frame_height, zone_bbox)
        if not ok:
            logger.error("[GuardMission] OpenCV 特征捕捉初始化失败！可能由于防区形状不合法或依赖未安装。")
            self._intrusion_counter = 0
            self._control_arbiter.release_control(ControlOwner.GUARD_MISSION)
            return

        self._start_bbox = zone_bbox
        self._curr_bbox = zone_bbox
        
        self._state = GuardMissionState.ADVANCING
        self._intrusion_counter = 0
        self._lost_anchor_counter = 0
        
        self._guard_start_time = time.monotonic()
        self._broadcast_event("GUARD_INTRUSION_CONFIRMED")
        asyncio.create_task(self._take_snapshot_safe(frame, "intrusion_confirmed"))
        
        # 播音频、起立
        asyncio.create_task(self._start_guard_audio())
        await self._control_service.handle_command("stand")

    async def _on_advancing(self, detections: List[TrackDetectionResult], frame: bytes):
        # 1. 更新视觉跟踪
        ok, curr_bbox = self._anchor_tracker.update_anchor(frame, self._frame_width, self._frame_height)
        if not ok or curr_bbox is None:
            self._lost_anchor_counter += 1
            if self._lost_anchor_counter > self._lost_anchor_frames:
                logger.error("[GuardMission] 追击途中完全丢失视觉锚点！进入 LOST_ANCHOR")
                await self._handle_lost_anchor()
            else:
                # 暂时丢失，发 stop 等待一两帧
                await self._send_command_safe("stop")
            return
            
        self._lost_anchor_counter = 0
        self._curr_bbox = curr_bbox
        
        # 2. 驱离超时（防止一直卡着报错）
        elapsed = time.monotonic() - self._guard_start_time
        if elapsed >= self._config.GUARD_MAX_DURATION_S:
            logger.warning("[GuardMission] 驱离已超时限制，中止前进进入返航！")
            await self._start_returning(frame, is_timeout=True)
            return

        # 3. 伺服控制：计算命令
        cmd, is_edge = self._servo_controller.compute_advancing(curr_bbox, self._frame_width, self._frame_height, self._config.GUARD_MAX_VIEW_RATIO)
        
        if is_edge:
            # 已经贴在目标脸上了，不再前进，只维持对质方向
            cmd = "stop" if cmd == "forward" else cmd 
        
        await self._send_command_safe(cmd)

        # 4. 判断人是否还在防区（重叠分析）
        has_overlap = self._check_person_overlap(detections, curr_bbox)
        
        if not has_overlap:
            self._clear_counter += 1
        else:
            self._clear_counter = 0
            
        if self._clear_counter >= self._clear_frames and elapsed >= self._config.GUARD_MIN_DURATION_S:
            logger.info("[GuardMission] 视觉判定人员已不占有锚点区域，开始执行视觉闭环返航！")
            await self._start_returning(frame, is_timeout=False)

    async def _on_returning(self, detections: List[TrackDetectionResult], frame: bytes):
        ok, curr_bbox = self._anchor_tracker.update_anchor(frame, self._frame_width, self._frame_height)
        if not ok or curr_bbox is None:
            self._lost_anchor_counter += 1
            if self._lost_anchor_counter > self._lost_anchor_frames:
                logger.error("[GuardMission] 返航途中丢失锚点！放弃返航")
                await self._handle_lost_anchor()
            else:
                await self._send_command_safe("stop")
            return
            
        self._lost_anchor_counter = 0
        self._curr_bbox = curr_bbox
        
        cmd, is_returned = self._servo_controller.compute_returning(
            curr_bbox=curr_bbox, 
            start_bbox=self._start_bbox, 
            frame_width=self._frame_width, 
            pos_tolerance_px=self._config.GUARD_RETURN_POS_TOLERANCE_PX,
            area_tolerance_ratio=self._config.GUARD_RETURN_AREA_TOLERANCE_RATIO
        )
        
        if is_returned:
            logger.info("[GuardMission] 返航伺服判定归位！完成任务。")
            await self._send_command_safe("stop")
            await asyncio.sleep(0.5)
            await self._send_command_safe("sit")
            self._finish_mission_and_reset(frame)
        else:
            await self._send_command_safe(cmd)

    def _check_person_overlap(self, detections: List[TrackDetectionResult], anchor_bbox: tuple) -> bool:
        """检查有没有人框和当前的物理锚点重叠达到一定危险门槛"""
        for det in detections:
            if det.class_name != "person":
                continue
            if det.confidence < self._config.GUARD_CLEAR_MIN_CONF:
                continue
            # det.bbox: (x1, y1, x2, y2)
            person_w = det.bbox[2] - det.bbox[0]
            person_h = det.bbox[3] - det.bbox[1]
            if person_w * person_h < self._config.GUARD_CLEAR_MIN_AREA:
                continue
                
            # opencv tracker bbox: (x, y, w, h)
            p_box = (det.bbox[0], det.bbox[1], person_w, person_h)
            
            overlap_ratio = _calc_intersection_ratio(p_box, anchor_bbox)
            if overlap_ratio >= self._config.GUARD_OVERLAP_CLEAR_RATIO:
                return True
        return False

    async def _start_returning(self, frame: bytes, is_timeout: bool = False):
        self._state = GuardMissionState.RETURNING
        self._clear_counter = 0
        self._guard_total_duration_s = time.monotonic() - self._guard_start_time
        asyncio.create_task(self._stop_guard_audio())
        
        if not is_timeout:
            self._broadcast_event("GUARD_ZONE_CLEARED")
            asyncio.create_task(self._take_snapshot_safe(frame, "zone_cleared"))

    async def _handle_lost_anchor(self):
        """由于视觉完全失效而兜底保护"""
        self._state = GuardMissionState.LOST_ANCHOR
        self._broadcast_event("GUARD_LOST_ANCHOR")
        logger.error("[GuardMission] 执行紧急刹车保护！")
        await self._send_command_safe("stop")
        asyncio.create_task(self._stop_guard_audio())
        # 在真实场地，可能需要接管发送一个硬盲退或者坐下
        await asyncio.sleep(1.0)
        await self._send_command_safe("sit")
        
        if self._control_arbiter:
            self._control_arbiter.release_control(ControlOwner.GUARD_MISSION)
        self._reset_mission_context()

    def _finish_mission_and_reset(self, frame: bytes):
        """正常成功回位后清理上下文"""
        self._state = GuardMissionState.STANDBY
        self._broadcast_event("GUARD_RETURNED")
        asyncio.create_task(self._take_snapshot_safe(frame, "returned"))
        asyncio.create_task(self._stop_guard_audio())
        if self._control_arbiter:
            self._control_arbiter.release_control(ControlOwner.GUARD_MISSION)
        self._reset_mission_context()

    async def _send_command_safe(self, cmd: str):
        """带限频和拦截发送到底层 ControlService"""
        now = time.monotonic()
        if cmd == self._last_command and cmd != "stop":
            # 持续一样的状态，避免把信道塞满，按 100ms 频率发即可
            if (now - self._last_cmd_send_time) * 1000 < self._command_rate_limit_ms:
                return
                
        self._last_cmd_send_time = now
        self._last_command = cmd
        try:
            await self._control_service.handle_command(cmd)
        except Exception as e:
            logger.debug(f"[GuardMission] 伺服发送命令 {cmd} 异常: {e}")

    # ─── 异常与状态处理 ─────────────────────────────────────────────

    def _abort_mission(self, reason: str):
        logger.info(f"[GuardMission] 任务中止: {reason}")
        asyncio.create_task(self._stop_guard_audio())
        asyncio.create_task(self._control_service.handle_command("stop"))
        
        if self._control_arbiter and self._control_arbiter.owner == ControlOwner.GUARD_MISSION:
            self._control_arbiter.release_control(ControlOwner.GUARD_MISSION)
            
        self._reset_mission_context()

    def _reset_mission_context(self):
        self._intrusion_counter = 0
        self._clear_counter = 0
        self._guard_start_time = 0.0
        self._last_mission_end_time = time.monotonic()
        self._anchor_tracker.reset()
        self._start_bbox = None
        self._curr_bbox = None

    def _broadcast_event(self, msg_type: str):
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
            pass

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
            return
        try:
            from .auto_track_service import _save_snapshot_to_disk
            image_path, image_url = await _save_snapshot_to_disk(
                frame=frame,
                snapshot_dir=self._snapshot_dir,
                frame_width=self._frame_width,
                frame_height=self._frame_height,
            )
        except Exception as exc:
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
                        message=f"视觉拦截锚点定位抓拍（{label}）",
                        confidence=1.0,
                        file_path=str(image_path),
                        image_url=image_url,
                        gps_lat=None,
                        gps_lon=None,
                        task_id=None,
                        session=session,
                    )
        except Exception as exc:
            pass

    async def _start_guard_audio(self):
        path = self._config.GUARD_ALERT_AUDIO_PATH
        try:
            self._audio_process = await asyncio.create_subprocess_exec(
                "aplay", "-D", "plughw:1,0", "--loop", str(path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except FileNotFoundError:
            self._audio_process = await asyncio.create_subprocess_exec(
                "python", "scripts/mock_audio.py",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )

    async def _stop_guard_audio(self):
        if self._audio_process:
            try:
                self._audio_process.terminate()
            except ProcessLookupError:
                pass
            self._audio_process = None

_guard_mission_service: Optional[GuardMissionService] = None

def get_guard_mission_service() -> Optional[GuardMissionService]:
    return _guard_mission_service

def set_guard_mission_service(service: GuardMissionService):
    global _guard_mission_service
    _guard_mission_service = service
