"""
视觉颜色检测防区驱离主服务。

核心原理（v2 颜色检测版）：
- 每帧通过 HSV 色彩空间检测地面上的黄色标记区域作为"防区"
- STANDBY：检测到人的脚底（bbox 底部）踩在黄色区域上 → 入侵判定
- ADVANCING：朝黄色区域的中心走（每帧实时检测，不依赖任何追踪器）
- RETURNING：倒退固定时间后坐下

不依赖 ZoneService 画框、不依赖 OpenCV MIL Tracker。
"""

import asyncio
import time
import numpy as np
from typing import List, Optional, Tuple

from .config import Settings, settings
from .control_service import ControlService
from .control_arbiter import ControlArbiter
from .zone_service import ZoneService
from .ws_event_broadcaster import EventBroadcaster
from .guard_mission_types import GuardMissionState, GuardStatusDTO
from .tracking_types import DetectionResult as TrackDetectionResult, ControlOwner

from .logging_config import logger

# ─── HSV 黄色检测参数（可根据实际地面颜色微调） ────────────────────────
# 宽松的黄色范围（覆盖浅黄到深黄/橙黄）
YELLOW_HSV_LOW  = np.array([15, 80, 80], dtype=np.uint8)
YELLOW_HSV_HIGH = np.array([35, 255, 255], dtype=np.uint8)
# 最小有效黄色区域面积（像素），过小的噪点忽略
YELLOW_MIN_AREA = 500


class GuardMissionService:
    """基于地面颜色检测的防区驱离主服务。"""

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

        # 伺服参数
        self._yaw_deadband_px = 40
        self._last_command = "stop"
        self._command_rate_limit_ms = 100
        self._last_cmd_send_time = 0.0

        # 返航计时
        self._return_start_time = 0.0
        self._return_duration_s = 5.0  # 倒退 5 秒

        # 当前帧检测到的黄色区域 bbox (x, y, w, h)，用于 overlay 广播
        self._detected_zone_bbox: Optional[Tuple[int, int, int, int]] = None

        # 帧数折算
        self._effective_fps = max(1.0, float(config.AI_FPS))

        # 诊断计数器
        self._dbg_frame_counter = 0
        self._overlay_call_counter = 0

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

    # ─── 颜色检测核心 ──────────────────────────────────────────────

    def _detect_yellow_zone(self, frame: bytes) -> Optional[Tuple[int, int, int, int]]:
        """
        用 HSV 色彩空间检测画面中最大的黄色区域。
        :param frame: BGR24 原始字节
        :return: (x, y, w, h) 或 None
        """
        try:
            import cv2
            frame_np = np.frombuffer(frame, dtype=np.uint8).reshape(
                (self._frame_height, self._frame_width, 3)
            )
            hsv = cv2.cvtColor(frame_np, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, YELLOW_HSV_LOW, YELLOW_HSV_HIGH)

            # 形态学操作去噪
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not contours:
                return None

            # 取面积最大的轮廓
            largest = max(contours, key=cv2.contourArea)
            area = cv2.contourArea(largest)
            if area < YELLOW_MIN_AREA:
                return None

            x, y, w, h = cv2.boundingRect(largest)
            return (x, y, w, h)
        except ImportError:
            logger.error("[GuardMission] cv2 未安装，无法进行颜色检测")
            return None
        except Exception as e:
            logger.debug(f"[GuardMission] 黄色检测异常: {e}")
            return None

    def _is_foot_in_zone(
        self, det: TrackDetectionResult, zone_bbox: Tuple[int, int, int, int]
    ) -> bool:
        """
        检查人的"脚底"（bbox 底部中心点）是否落在黄色区域内。
        """
        x1, y1, x2, y2 = det.bbox
        foot_x = (x1 + x2) // 2
        foot_y = y2  # bbox 底边 = 脚底

        zx, zy, zw, zh = zone_bbox
        return zx <= foot_x <= zx + zw and zy <= foot_y <= zy + zh

    # ─── 核心帧处理流 ──────────────────────────────────────────

    async def process_frame(self, detections: List[TrackDetectionResult], frame: bytes):
        if not self._enabled:
            return

        self._last_frame_time = time.monotonic()

        # 每帧检测黄色区域
        self._detected_zone_bbox = self._detect_yellow_zone(frame)

        # 诊断日志（每 60 帧一次）
        self._dbg_frame_counter += 1
        dbg = (self._dbg_frame_counter % 60 == 1)
        if dbg:
            b = self._event_broadcaster
            logger.info(
                f"[GuardMission] frame #{self._dbg_frame_counter}: "
                f"state={self._state.value}, zone_detected={'YES' if self._detected_zone_bbox else 'NO'}, "
                f"zone_bbox={self._detected_zone_bbox}, "
                f"persons={len(detections)}, intrusion={self._intrusion_counter}, "
                f"broadcaster={'ok' if b else 'None'}, conns={getattr(b, 'connection_count', '?')}"
            )

        # ── 人工接管校验 ──
        if self._state in (GuardMissionState.ADVANCING, GuardMissionState.RETURNING):
            if self._control_arbiter and not self._control_arbiter.can_guard_send():
                self._abort_mission("人工接管")
                self._state = GuardMissionState.MANUAL_OVERRIDE
                self._broadcast_event("GUARD_ABORTED")

        # ── 手动接管恢复 ──
        if self._state == GuardMissionState.MANUAL_OVERRIDE:
            if self._control_arbiter:
                if not self._control_arbiter.is_manual_override_active() and not self._control_arbiter.is_e_stop_active():
                    self._state = GuardMissionState.STANDBY
                    self._reset_mission_context()
        elif self._state == GuardMissionState.STANDBY:
            await self._on_standby(detections, frame)
        elif self._state == GuardMissionState.ADVANCING:
            await self._on_advancing(detections, frame)
        elif self._state == GuardMissionState.RETURNING:
            await self._on_returning(detections, frame)

        # ── 始终广播 overlay ──
        zone_bbox_xyxy = None
        if self._detected_zone_bbox:
            zx, zy, zw, zh = self._detected_zone_bbox
            zone_bbox_xyxy = [zx, zy, zx + zw, zy + zh]

        # active_bbox = 当前系统正在导航的目标
        active_bbox = zone_bbox_xyxy  # 始终显示黄色区域

        if dbg:
            logger.info(
                f"[GuardMission] overlay: zone={zone_bbox_xyxy}, persons={len(detections)}"
            )

        await self._broadcast_overlay(detections, active_bbox, zone_bbox_xyxy)

    # ─── 状态流转逻辑 ──────────────────────────────────────────────

    async def _on_standby(self, detections: List[TrackDetectionResult], frame: bytes):
        ready = self._check_system_ready()
        if not ready:
            self._intrusion_counter = 0
            return

        zone = self._detected_zone_bbox
        if zone is None:
            # 没检测到黄色区域，没有防区可守
            if self._intrusion_counter > 0:
                self._intrusion_counter = max(0, self._intrusion_counter - 2)
            return

        # 检查有没有人的脚踩在黄区上
        persons = [d for d in detections if d.class_name == "person" and d.confidence >= 0.4]
        has_intruder = any(self._is_foot_in_zone(p, zone) for p in persons)

        if has_intruder:
            self._intrusion_counter += 1
            logger.info(
                f"[GuardMission] 入侵检出! counter={self._intrusion_counter}/{self._confirm_frames}, "
                f"zone={zone}"
            )
        else:
            if self._intrusion_counter > 0:
                self._intrusion_counter = max(0, self._intrusion_counter - 2)

        if self._intrusion_counter >= self._confirm_frames:
            logger.info("[GuardMission] 入侵已确认！起立，朝黄区前进！")
            await self._start_advancing(frame)

    async def _start_advancing(self, frame: bytes):
        """申请控制权 → 起立 → ADVANCING"""
        if not self._control_arbiter.request_control(ControlOwner.GUARD_MISSION):
            logger.warning("[GuardMission] 申请控制权失败，无法出动。")
            self._intrusion_counter = 0
            return

        self._state = GuardMissionState.ADVANCING
        self._intrusion_counter = 0
        self._clear_counter = 0
        self._guard_start_time = time.monotonic()

        self._broadcast_event("GUARD_INTRUSION_CONFIRMED")
        asyncio.create_task(self._take_snapshot_safe(frame, "intrusion_confirmed"))
        asyncio.create_task(self._start_guard_audio())
        await self._control_service.handle_command("stand")

    async def _on_advancing(self, detections: List[TrackDetectionResult], frame: bytes):
        """
        ADVANCING：朝黄色区域的中心走。
        每帧实时检测黄色，不用追踪器。
        """
        zone = self._detected_zone_bbox

        # 1. 超时保护
        elapsed = time.monotonic() - self._guard_start_time
        if elapsed >= self._config.GUARD_MAX_DURATION_S:
            logger.warning("[GuardMission] 驱离超时，开始返航！")
            await self._start_returning()
            return

        # 2. 如果这一帧没检测到黄色，暂停等下一帧
        if zone is None:
            self._clear_counter += 1
            if self._clear_counter > 30:  # 连续 30 帧找不到黄色区域 → 返航
                logger.warning("[GuardMission] 持续找不到黄色区域，开始返航")
                await self._start_returning()
            else:
                await self._send_command_safe("stop")
            return
        self._clear_counter = 0

        zx, zy, zw, zh = zone
        zone_center_x = zx + zw // 2
        zone_area_ratio = (zw * zh) / (self._frame_width * self._frame_height)

        # 3. 计算导航命令
        error_x = zone_center_x - (self._frame_width // 2)

        if zone_area_ratio >= self._config.GUARD_MAX_VIEW_RATIO:
            # 黄色区域占满了整个屏幕 → 已经贴脸了
            cmd = "stop"
            logger.info("[GuardMission] 已到达黄区正前方（占满视野），停止前进")
        elif abs(error_x) > self._yaw_deadband_px:
            cmd = "left" if error_x < 0 else "right"
        else:
            cmd = "forward"

        await self._send_command_safe(cmd)

        # 4. 检测人是否已经离开黄区
        persons = [d for d in detections if d.class_name == "person" and d.confidence >= 0.4]
        person_on_zone = any(self._is_foot_in_zone(p, zone) for p in persons)

        if not person_on_zone and elapsed >= self._config.GUARD_MIN_DURATION_S:
            # 人走了，可以开始数帧
            self._clear_counter += 1
            if self._clear_counter >= self._clear_frames:
                logger.info("[GuardMission] 人已离开黄区，开始返航")
                await self._start_returning()
        else:
            self._clear_counter = 0

    async def _start_returning(self):
        """开始倒退返航"""
        self._state = GuardMissionState.RETURNING
        self._return_start_time = time.monotonic()
        self._guard_total_duration_s = time.monotonic() - self._guard_start_time
        self._clear_counter = 0
        asyncio.create_task(self._stop_guard_audio())
        self._broadcast_event("GUARD_ZONE_CLEARED")

    async def _on_returning(self, detections: List[TrackDetectionResult], frame: bytes):
        """
        RETURNING：直接倒退固定秒数然后坐下。
        如果能检测到黄色区域，可以做简单的居中修正。
        """
        elapsed = time.monotonic() - self._return_start_time

        if elapsed >= self._return_duration_s:
            logger.info("[GuardMission] 返航完成，坐下。")
            await self._send_command_safe("stop")
            await asyncio.sleep(0.5)
            await self._send_command_safe("sit")
            self._finish_mission_and_reset(frame)
            return

        # 基本策略：往后退，如果看到黄区偏了就微调方向
        zone = self._detected_zone_bbox
        if zone is not None:
            zx, zy, zw, zh = zone
            zone_center_x = zx + zw // 2
            error_x = zone_center_x - (self._frame_width // 2)
            if abs(error_x) > self._yaw_deadband_px:
                cmd = "left" if error_x < 0 else "right"
            else:
                cmd = "backward"
        else:
            cmd = "backward"

        await self._send_command_safe(cmd)

    # ─── 系统检查 ─────────────────────────────────────────────

    def _check_system_ready(self) -> bool:
        if not self._control_arbiter:
            logger.debug("[GuardMission] system_ready=False: no arbiter")
            return False
        if self._control_arbiter.is_e_stop_active():
            logger.debug("[GuardMission] system_ready=False: e_stop")
            return False
        if self._control_arbiter.is_manual_override_active():
            logger.debug("[GuardMission] system_ready=False: manual_override")
            return False
        cooldown_remaining = self._config.GUARD_COOLDOWN_S - (time.monotonic() - self._last_mission_end_time)
        if cooldown_remaining > 0:
            logger.debug(f"[GuardMission] system_ready=False: cooldown {cooldown_remaining:.1f}s")
            return False
        return True

    # ─── overlay 广播 ─────────────────────────────────────────────

    async def _broadcast_overlay(
        self,
        detections: List[TrackDetectionResult],
        active_bbox: Optional[list],
        zone_bbox: Optional[list] = None,
    ):
        broadcaster = self._event_broadcaster
        if broadcaster is None:
            logger.warning("[GuardMission] broadcaster is None!")
            return

        self._overlay_call_counter += 1
        if self._overlay_call_counter % 60 == 1:
            logger.info(
                f"[GuardMission] overlay #{self._overlay_call_counter}: "
                f"connections={broadcaster.connection_count}, "
                f"zone={zone_bbox}, active={active_bbox}"
            )

        if broadcaster.connection_count == 0:
            return

        try:
            from .schemas import utc_now_iso
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
                    "zone_bbox": zone_bbox,
                    "tracker_bbox": None,
                    "command": self._last_command if active_bbox else None,
                    "reason": f"Guard: {self._state.value}",
                    "state": self._state.value,
                    "frame_w": self._frame_width,
                    "frame_h": self._frame_height,
                    "deadband_px": self._yaw_deadband_px,
                    "anchor_y_stop_ratio": 0.0,
                    "forward_area_ratio": 0.0,
                }
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
        except Exception as e:
            logger.warning(f"[GuardMission] overlay broadcast error: {e}")

    # ─── 指令发送 ─────────────────────────────────────────────

    async def _send_command_safe(self, cmd: str):
        now = time.monotonic()
        if cmd == self._last_command and cmd != "stop":
            if (now - self._last_cmd_send_time) * 1000 < self._command_rate_limit_ms:
                return

        self._last_cmd_send_time = now
        self._last_command = cmd
        try:
            await self._control_service.handle_command(cmd)
        except Exception as e:
            logger.debug(f"[GuardMission] 发送命令 {cmd} 异常: {e}")

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
        self._detected_zone_bbox = None

    def _finish_mission_and_reset(self, frame: bytes):
        self._state = GuardMissionState.STANDBY
        self._broadcast_event("GUARD_RETURNED")
        asyncio.create_task(self._take_snapshot_safe(frame, "returned"))
        asyncio.create_task(self._stop_guard_audio())
        if self._control_arbiter:
            self._control_arbiter.release_control(ControlOwner.GUARD_MISSION)
        self._reset_mission_context()

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
        except Exception:
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
        except Exception:
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
                        message=f"驱离抓拍（{label}）",
                        confidence=1.0,
                        file_path=str(image_path),
                        image_url=image_url,
                        gps_lat=None,
                        gps_lon=None,
                        task_id=None,
                        session=session,
                    )
        except Exception:
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
