"""
基于颜色检测的防区驱离主服务 (v3)。

检测管线已迁移至独立模块 yellow_zone_detector.py（阶段 1）：
  - YellowZoneDetector 负责所有 HSV 分割 + 几何过滤 + 黑边验证
  - 本文件只负责状态机、运动控制、事件广播

不依赖 ZoneService 画框，不依赖 OpenCV MIL Tracker。
"""

import asyncio
import time
import numpy as np
from typing import List, Optional, Tuple

from .config import Settings
from .control_service import ControlService
from .control_arbiter import ControlArbiter
from .zone_service import ZoneService
from .ws_event_broadcaster import EventBroadcaster
from .guard_mission_types import GuardMissionState, GuardStatusDTO
from .tracking_types import DetectionResult as TrackDetectionResult, ControlOwner
from .yellow_zone_detector import YellowZoneDetector, ZoneDetection

from .logging_config import logger


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
        self._return_duration_s = 5.0

        # ── 阶段 1：独立区域检测器 ──────────────────────────────────
        self._zone_detector = YellowZoneDetector(
            frame_width=frame_width,
            frame_height=frame_height,
        )
        # 当前帧最新检测结果（ZoneDetection 或 None）
        self._current_zone: Optional[ZoneDetection] = None
        # 保留旧字段兼容下游（从 _current_zone 派生，不再独立维护）
        self._detected_zone_bbox: Optional[Tuple[int, int, int, int]] = None
        self._detected_zone_polygon: Optional[np.ndarray] = None

        # 帧数折算
        self._effective_fps = max(1.0, float(config.AI_FPS))

        # 诊断计数器
        self._dbg_frame_counter = 0
        self._overlay_call_counter = 0

    # ─── 属性 ─────────────────────────────────────────────────────

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
        zone_q = self._current_zone.quality if self._current_zone else 0.0
        zone_lost = getattr(self._zone_detector, '_lost_frames_count', 0)
        return GuardStatusDTO(
            enabled=self._enabled,
            state=self._state,
            intrusion_counter=self._intrusion_counter,
            confirm_frames=self._confirm_frames,
            clear_counter=self._clear_counter,
            clear_frames=self._clear_frames,
            guard_duration_s=time.monotonic() - self._guard_start_time if self._state == GuardMissionState.ADVANCING else self._guard_total_duration_s,
            zone_quality=round(zone_q, 3),
            zone_lost_frames=zone_lost,
        )

    def _is_foot_in_zone(self, det: TrackDetectionResult) -> bool:
        """人的脚底 (bbox 底部中心) 是否在检测到的多边形内。"""
        x1, y1, x2, y2 = det.bbox
        foot_x = int((x1 + x2) / 2)
        foot_y = int(y2)

        if self._detected_zone_polygon is not None:
            try:
                import cv2
                contour = self._detected_zone_polygon.reshape(-1, 1, 2).astype(np.float32)
                dist = cv2.pointPolygonTest(contour, (float(foot_x), float(foot_y)), False)
                return dist >= 0
            except Exception:
                pass

        if self._detected_zone_bbox is not None:
            zx, zy, zw, zh = self._detected_zone_bbox
            return zx <= foot_x <= zx + zw and zy <= foot_y <= zy + zh

        return False

    # ─── 核心帧处理 ─────────────────────────────────────────────

    async def process_frame(self, detections: List[TrackDetectionResult], frame: bytes):
        if not self._enabled:
            return

        self._last_frame_time = time.monotonic()

        # ── 阶段 1：调用独立检测器，替代原来的 _detect_zone() ──
        zone = self._zone_detector.detect(frame)
        self._current_zone = zone
        # 保持旧字段兼容性（_on_standby / _on_advancing / _is_foot_in_zone 仍在用）
        if zone is not None:
            self._detected_zone_bbox    = zone.bbox
            self._detected_zone_polygon = zone.polygon
        else:
            self._detected_zone_bbox    = None
            self._detected_zone_polygon = None

        # 诊断（每 60 帧）
        self._dbg_frame_counter += 1
        dbg = (self._dbg_frame_counter % 60 == 1)
        if dbg:
            b = self._event_broadcaster
            has_zone = self._detected_zone_bbox is not None
            has_poly = self._detected_zone_polygon is not None
            logger.info(
                f"[GuardMission] frame #{self._dbg_frame_counter}: "
                f"state={self._state.value}, "
                f"zone={'YES' if has_zone else 'NO'} bbox={self._detected_zone_bbox}, "
                f"poly={'YES' if has_poly else 'NO'}, "
                f"persons={len(detections)}, intrusion={self._intrusion_counter}, "
                f"conns={getattr(b, 'connection_count', '?')}"
            )

        # 人工接管校验
        if self._state in (GuardMissionState.ADVANCING, GuardMissionState.RETURNING):
            if self._control_arbiter and not self._control_arbiter.can_guard_send():
                self._abort_mission("人工接管")
                self._state = GuardMissionState.MANUAL_OVERRIDE
                self._broadcast_event("GUARD_ABORTED")

        # 状态机
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

        # overlay 广播
        zone_xyxy = None
        zone_poly_list = None
        zone_quality = 0.0
        if self._current_zone is not None:
            zx, zy, zw, zh = self._current_zone.bbox
            zone_xyxy = [zx, zy, zx + zw, zy + zh]
            zone_poly_list = self._current_zone.polygon.tolist()
            zone_quality = round(self._current_zone.quality, 3)

        if dbg:
            logger.info(
                f"[GuardMission] overlay: zone={zone_xyxy}, "
                f"poly_pts={len(zone_poly_list) if zone_poly_list else 0}, "
                f"quality={zone_quality:.2f}"
            )

        await self._broadcast_overlay(detections, zone_xyxy, zone_xyxy, zone_poly_list, zone_quality)

    # ─── 状态流转 ───────────────────────────────────────────────

    async def _on_standby(self, detections: List[TrackDetectionResult], frame: bytes):
        ready = self._check_system_ready()
        if not ready:
            self._intrusion_counter = 0
            return

        if self._detected_zone_bbox is None:
            if self._intrusion_counter > 0:
                self._intrusion_counter = max(0, self._intrusion_counter - 2)
            return

        persons = [d for d in detections if d.class_name == "person" and d.confidence >= 0.4]
        has_intruder = any(self._is_foot_in_zone(p) for p in persons)

        if has_intruder:
            self._intrusion_counter += 1
            logger.info(
                f"[GuardMission] 入侵! counter={self._intrusion_counter}/{self._confirm_frames}"
            )
        else:
            if self._intrusion_counter > 0:
                self._intrusion_counter = max(0, self._intrusion_counter - 2)

        if self._intrusion_counter >= self._confirm_frames:
            logger.info("[GuardMission] 入侵已确认！起立前进！")
            await self._start_advancing(frame)

    async def _start_advancing(self, frame: bytes):
        if not self._control_arbiter.request_control(ControlOwner.GUARD_MISSION):
            logger.warning("[GuardMission] 申请控制权失败")
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
        """朝检测到的区域中心走。"""
        elapsed = time.monotonic() - self._guard_start_time
        if elapsed >= self._config.GUARD_MAX_DURATION_S:
            logger.warning("[GuardMission] 超时，返航")
            await self._start_returning()
            return

        zone = self._detected_zone_bbox
        if zone is None:
            self._clear_counter += 1
            if self._clear_counter > 30:
                logger.warning("[GuardMission] 持续丢失区域，返航")
                await self._start_returning()
            else:
                await self._send_command_safe("stop")
            return
        self._clear_counter = 0

        zx, zy, zw, zh = zone
        zone_cx = zx + zw // 2
        zone_area_ratio = (zw * zh) / (self._frame_width * self._frame_height)

        error_x = zone_cx - (self._frame_width // 2)

        if zone_area_ratio >= self._config.GUARD_MAX_VIEW_RATIO:
            cmd = "stop"
        elif abs(error_x) > self._yaw_deadband_px:
            cmd = "left" if error_x < 0 else "right"
        else:
            cmd = "forward"

        await self._send_command_safe(cmd)

        # 人是否已离开
        persons = [d for d in detections if d.class_name == "person" and d.confidence >= 0.4]
        still_on_zone = any(self._is_foot_in_zone(p) for p in persons)

        if not still_on_zone and elapsed >= self._config.GUARD_MIN_DURATION_S:
            self._clear_counter += 1
            if self._clear_counter >= self._clear_frames:
                logger.info("[GuardMission] 人已离开，返航")
                await self._start_returning()
        else:
            self._clear_counter = 0

    async def _start_returning(self):
        self._state = GuardMissionState.RETURNING
        self._return_start_time = time.monotonic()
        self._guard_total_duration_s = time.monotonic() - self._guard_start_time
        self._clear_counter = 0
        asyncio.create_task(self._stop_guard_audio())
        self._broadcast_event("GUARD_ZONE_CLEARED")

    async def _on_returning(self, detections: List[TrackDetectionResult], frame: bytes):
        elapsed = time.monotonic() - self._return_start_time
        if elapsed >= self._return_duration_s:
            logger.info("[GuardMission] 返航完成")
            await self._send_command_safe("stop")
            await asyncio.sleep(0.5)
            await self._send_command_safe("sit")
            self._finish_mission_and_reset(frame)
            return

        zone = self._detected_zone_bbox
        if zone is not None:
            zx, zy, zw, zh = zone
            zone_cx = zx + zw // 2
            error_x = zone_cx - (self._frame_width // 2)
            if abs(error_x) > self._yaw_deadband_px:
                cmd = "left" if error_x < 0 else "right"
            else:
                cmd = "backward"
        else:
            cmd = "backward"

        await self._send_command_safe(cmd)

    # ─── 系统检查 ───────────────────────────────────────────────

    def _check_system_ready(self) -> bool:
        if not self._control_arbiter:
            return False
        if self._control_arbiter.is_e_stop_active():
            return False
        if self._control_arbiter.is_manual_override_active():
            return False
        cooldown = self._config.GUARD_COOLDOWN_S - (time.monotonic() - self._last_mission_end_time)
        if cooldown > 0:
            return False
        return True

    # ─── overlay 广播 ───────────────────────────────────────────

    async def _broadcast_overlay(
        self,
        detections: List[TrackDetectionResult],
        active_bbox: Optional[list],
        zone_bbox: Optional[list] = None,
        zone_polygon: Optional[list] = None,
        zone_quality: float = 0.0,
    ):
        broadcaster = self._event_broadcaster
        if broadcaster is None:
            return

        self._overlay_call_counter += 1
        if self._overlay_call_counter % 60 == 1:
            logger.info(
                f"[GuardMission] overlay #{self._overlay_call_counter}: "
                f"conns={broadcaster.connection_count}, "
                f"zone={zone_bbox}, poly_pts={len(zone_polygon) if zone_polygon else 0}"
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
                    "zone_polygon": zone_polygon,
                    "zone_quality": zone_quality,
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
            logger.warning(f"[GuardMission] overlay error: {e}")

    # ─── 指令发送 ───────────────────────────────────────────────

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
            logger.debug(f"[GuardMission] cmd {cmd} err: {e}")

    # ─── 异常与状态 ─────────────────────────────────────────────

    def _abort_mission(self, reason: str):
        logger.info(f"[GuardMission] 中止: {reason}")
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
        self._detected_zone_polygon = None

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
