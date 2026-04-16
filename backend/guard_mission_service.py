"""
基于颜色检测的防区驱离主服务 (v3)。

检测管线已迁移至独立模块 yellow_zone_detector.py（阶段 1）：
  - YellowZoneDetector 负责所有 HSV 分割 + 几何过滤 + 黑边验证
  - 本文件只负责状态机、运动控制、事件广播

不依赖 ZoneService 画框，不依赖 OpenCV MIL Tracker。
"""

import asyncio
import time
import cv2
import numpy as np
from typing import List, Optional, Tuple

from .config import Settings
from .control_service import ControlService
from .control_arbiter import ControlArbiter
from .zone_service import ZoneService
from .ws_event_broadcaster import EventBroadcaster
from .guard_mission_types import GuardMissionState, GuardStatusDTO
from .tracking_types import DetectionResult as TrackDetectionResult, ControlOwner
from .visual_servo_controller import VisualServoController
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
        self._clear_counter = 0       # 人已离开区域的连续帧计数（用于触发返航）
        self._zone_lost_counter = 0   # 区域检测丢失的连续帧计数（用于兜底返航）
        self._guard_start_time = 0.0
        self._guard_total_duration_s = 0.0

        self._last_mission_end_time = 0.0
        self._last_frame_time = time.monotonic()

        self._audio_process: Optional[asyncio.subprocess.Process] = None
        self._audio_task: Optional[asyncio.Task] = None

        # 返航阶段：区域连续丢失的起始时间（0.0 = 当前未丢失）
        self._return_zone_lost_since: float = 0.0

        # 伺服参数
        self._yaw_deadband_px = config.GUARD_YAW_DEADBAND_PX
        self._last_command = "stop"
        self._command_rate_limit_ms = config.GUARD_COMMAND_RATE_LIMIT_MS
        self._last_cmd_send_time = 0.0

        # 驱离专用速度（低于手动遥控速度，提高稳定性）
        self._guard_vx = config.GUARD_VX
        self._guard_vyaw = config.GUARD_VYAW

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

        # ── 阶段 3：视觉伺服控制器 ──────────────────────────────────
        self._servo = VisualServoController(yaw_deadband_px=self._yaw_deadband_px)
        # 前进时记录的起始区域快照（供阶段 4 视觉返航使用）
        self._start_zone: Optional[ZoneDetection] = None
        # 阶段 4：返航稳定计数器（连续 N 帧满足到位条件才确认完成）
        self._return_stable_counter: int = 0
        self._return_stable_threshold: int = config.GUARD_RETURN_STABLE_FRAMES
        # 返航面积判断计数器（连续 N 帧面积 < 10% 才停止，防单帧误判）
        self._return_area_small_counter: int = 0
        self._return_area_small_threshold: int = config.GUARD_RETURN_AREA_STABLE_FRAMES

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
        current_bbox = list(self._current_zone.bbox) if self._current_zone else None
        start_bbox = list(self._start_zone.bbox) if self._start_zone else None
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
            current_zone_bbox=current_bbox,
            start_zone_bbox=start_bbox,
        )

    def _is_foot_in_zone(self, det: TrackDetectionResult) -> bool:
        """
        判断人的底边是否与防区重合。

        检查底边三个采样点（左角、中点、右角），任意一点落在区域内即判定入侵。
        相比只检查底部中心，能覆盖人斜站、区域偏小等边缘情况。
        """
        x1, y1, x2, y2 = det.bbox
        foot_y = int(y2)
        # 底边三个采样点：左角、中点、右角
        check_points = [
            (int(x1), foot_y),
            (int((x1 + x2) / 2), foot_y),
            (int(x2), foot_y),
        ]

        polygon = self._current_zone.polygon if self._current_zone else None
        if polygon is not None:
            try:
                import cv2
                contour = polygon.reshape(-1, 1, 2).astype(np.float32)
                for px, py in check_points:
                    dist = cv2.pointPolygonTest(contour, (float(px), float(py)), False)
                    if dist >= 0:
                        return True
                return False
            except Exception:
                pass

        # 降级：用 bbox 矩形判断
        bbox = self._current_zone.bbox if self._current_zone else None
        if bbox is not None:
            zx, zy, zw, zh = bbox
            for px, py in check_points:
                if zx <= px <= zx + zw and zy <= py <= zy + zh:
                    return True

        return False

    def _compute_foot_status(self, det: TrackDetectionResult):
        """计算脚点坐标及是否在区域内，返回 (foot_x, foot_y, in_zone)。"""
        x1, y1, x2, y2 = det.bbox
        foot_x = int((x1 + x2) / 2)
        foot_y = int(y2)
        return foot_x, foot_y, self._is_foot_in_zone(det)

    # ─── 核心帧处理 ─────────────────────────────────────────────

    async def process_frame(self, detections: List[TrackDetectionResult], frame: bytes):
        if not self._enabled:
            return

        self._last_frame_time = time.monotonic()

        # ── 阶段 1：调用独立检测器（在线程池执行，避免阻塞 event loop）──
        zone = await asyncio.to_thread(self._zone_detector.detect, frame)
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
        now = time.monotonic()
        arbiter = self._control_arbiter

        # E-STOP：清零计数，完全停止
        if arbiter and arbiter.is_e_stop_active():
            self._intrusion_counter = 0
            return

        # 区域未检测到：计数缓慢衰减
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
            # 出动前才检查：E-STOP / 人工接管 / 冷却期
            if arbiter and arbiter.is_manual_override_active():
                logger.info("[GuardMission] 入侵确认，但人工接管中，等待释放")
                return
            cooldown_left = self._config.GUARD_COOLDOWN_S - (now - self._last_mission_end_time)
            if cooldown_left > 0:
                logger.info(f"[GuardMission] 入侵确认，冷却期剩余 {cooldown_left:.1f}s")
                return
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
        self._zone_lost_counter = 0
        self._guard_start_time = time.monotonic()

        # 记录此刻的区域状态作为返航基准（阶段 4 使用）
        self._start_zone = self._current_zone

        self._broadcast_event("GUARD_INTRUSION_CONFIRMED")
        asyncio.create_task(self._take_snapshot_safe(frame, "intrusion_confirmed"))
        asyncio.create_task(self._start_guard_audio())
        await self._control_service.handle_command("stand")

    async def _on_advancing(self, detections: List[TrackDetectionResult], frame: bytes):
        """视觉伺服推进：朝区域中心闭环前进，到位后等待人离开再返航。"""
        elapsed = time.monotonic() - self._guard_start_time
        if elapsed >= self._config.GUARD_MAX_DURATION_S:
            logger.warning("[GuardMission] 超时，返航")
            await self._start_returning()
            return

        # 1. 获取当前区域（由 process_frame 中已检测）
        zone = self._current_zone
        if zone is None:
            self._zone_lost_counter += 1
            if self._zone_lost_counter > 30:
                logger.warning("[GuardMission] 持续丢失区域，返航")
                await self._start_returning()
            else:
                await self._send_command_safe("stop")
            return
        self._zone_lost_counter = 0  # 区域重新检测到，重置丢失计数

        # 2. 调用视觉伺服控制器计算指令
        cmd, is_arrived = self._servo.compute_advancing(
            curr_bbox=zone.bbox,
            frame_width=self._frame_width,
            frame_height=self._frame_height,
            max_view_ratio=self._config.GUARD_MAX_VIEW_RATIO,
            edge_margin_ratio=self._config.GUARD_ZONE_EDGE_MARGIN_RATIO,
        )
        await self._send_command_safe(cmd)

        # 3. 判断人是否已离开区域（脚点不在 zone polygon 内即视为已离开）
        persons_valid = [
            d for d in detections
            if d.class_name == "person"
            and d.confidence >= self._config.GUARD_CLEAR_MIN_CONF
        ]
        still_on_zone = any(self._is_foot_in_zone(p) for p in persons_valid)

        # 近距离保护：机器狗贴近时 YOLO 置信度可能低于阈值，
        # 用极低置信度（0.1）补查一次脚点——只要脚还在区域里就继续驱离，
        # 避免误判为"人已离开"。
        # 注意：这里只检查"脚在区域内"，不阻止屏幕其他位置有人时的判定。
        if not still_on_zone:
            still_on_zone = any(
                self._is_foot_in_zone(p)
                for p in detections
                if p.class_name == "person" and p.confidence >= 0.1
            )

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
        self._zone_lost_counter = 0
        self._return_stable_counter = 0
        self._return_area_small_counter = 0
        self._return_zone_lost_since = 0.0
        asyncio.create_task(self._stop_guard_audio())
        self._broadcast_event("GUARD_ZONE_CLEARED")

    async def _on_returning(self, detections: List[TrackDetectionResult], frame: bytes):
        """视觉闭环返航：朝起始位置后退，面积和中心都回到起点后蹲坐完成任务。"""
        elapsed = time.monotonic() - self._return_start_time

        # 超时保护：超过 GUARD_RETURN_DURATION_S 的 3 倍仍未到位 → 强制结束
        if elapsed >= self._config.GUARD_RETURN_DURATION_S * 3:
            logger.warning("[GuardMission] 返航超时，强制停止")
            await self._send_command_safe("stop")
            self._finish_mission_and_reset(frame)
            return

        zone = self._current_zone

        # 区域丢失：计时，超过 2 秒视为已退回起点
        if zone is None:
            now = time.monotonic()
            if self._return_zone_lost_since == 0.0:
                self._return_zone_lost_since = now
                await self._send_command_safe("backward")
            elif now - self._return_zone_lost_since >= 2.0:
                logger.info("[GuardMission] 返航中区域丢失超过 2 秒，视为已到起点")
                await self._send_command_safe("stop")
                self._finish_mission_and_reset(frame)
            else:
                await self._send_command_safe("backward")
            return

        # 区域重新出现，重置丢失计时
        self._return_zone_lost_since = 0.0

        # 面积判断：区域面积 < GUARD_RETURN_AREA_STOP_RATIO 时视为已退回足够远，停止
        _, _, zw, zh = zone.bbox
        zone_area = zw * zh
        screen_area = self._frame_width * self._frame_height
        if zone_area < screen_area * self._config.GUARD_RETURN_AREA_STOP_RATIO:
            self._return_area_small_counter += 1
            logger.debug(
                f"[GuardMission] 面积 {zone_area}px²（{zone_area/screen_area*100:.1f}%）"
                f"< {self._config.GUARD_RETURN_AREA_STOP_RATIO*100:.0f}%，"
                f"稳定帧 {self._return_area_small_counter}/{self._return_area_small_threshold}"
            )
            if self._return_area_small_counter >= self._return_area_small_threshold:
                logger.info(
                    f"[GuardMission] 区域面积持续 {self._return_area_small_threshold} 帧 "
                    f"< {self._config.GUARD_RETURN_AREA_STOP_RATIO*100:.0f}%，视为到位"
                )
                await self._send_command_safe("stop")
                self._finish_mission_and_reset(frame)
                return
            # 未达到阈值：继续后退
            await self._send_command_safe("backward")
            return
        else:
            # 面积恢复正常，重置计数
            self._return_area_small_counter = 0

        # 面积未达到停止阈值：计算转向修正指令（纠偏，不判断到位）
        cmd, _ = self._servo.compute_returning(
            curr_bbox=zone.bbox,
            start_bbox=self._start_zone.bbox,
            frame_width=self._frame_width,
            pos_tolerance_px=self._config.GUARD_RETURN_POS_TOLERANCE_PX,
            area_tolerance_ratio=self._config.GUARD_RETURN_AREA_TOLERANCE_RATIO,
        )
        # 只使用方向指令（backward/left/right），到位判断完全由面积条件负责
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
            # 计算脚点（只对置信度 >= 0.4 的 person）
            persons = [d for d in detections if d.class_name == "person" and d.confidence >= 0.4]
            foot_points = [
                {"x": foot_x, "y": foot_y, "in_zone": in_zone}
                for d in persons
                for foot_x, foot_y, in_zone in [self._compute_foot_status(d)]
            ]
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
                    "foot_points": foot_points,
                    "intrusion_confirmed": self._intrusion_counter >= self._confirm_frames,
                    "tracker_bbox": None,
                    "command": self._last_command if active_bbox else None,
                    "reason": f"Guard: {self._state.value}",
                    "state": self._state.value,
                    "frame_w": self._frame_width,
                    "frame_h": self._frame_height,
                    "deadband_px": self._yaw_deadband_px,
                    "anchor_y_stop_ratio": 0.0,
                    "forward_area_ratio": 0.0,
                    "edge_margin_ratio": self._config.GUARD_ZONE_EDGE_MARGIN_RATIO,
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
            # 驱离模式使用专用低速，防止速度过快导致不稳定
            await self._control_service.handle_command(
                cmd, vx=self._guard_vx, vyaw=self._guard_vyaw
            )
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

    @property
    def is_audio_playing(self) -> bool:
        """返回当前是否正在播放驱离音频（用 Task 状态判断，比 returncode 可靠）。"""
        return self._audio_task is not None and not self._audio_task.done()

    async def start_audio(self):
        """公开：启动驱离音频循环播放（供 API 手动触发）。"""
        if self.is_audio_playing:
            return
        await self._start_guard_audio()

    async def stop_audio(self):
        """公开：停止驱离音频（供 API 手动触发）。"""
        await self._stop_guard_audio()

    async def _audio_loop(self, path: str):
        """asyncio 任务：每次等 aplay 完整播完后再循环，被 cancel 时干净退出。"""
        while True:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "aplay", "-D", "plughw:3,0", path,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                self._audio_process = proc
                await proc.wait()          # 等待本轮播放完整结束
                self._audio_process = None
                await asyncio.sleep(0.05)  # 给设备短暂释放时间再重启
            except asyncio.CancelledError:
                # 任务被取消：终止当前 aplay 子进程后退出
                if self._audio_process:
                    try:
                        self._audio_process.terminate()
                    except ProcessLookupError:
                        pass
                    self._audio_process = None
                raise  # 让 Task 正常以 CancelledError 结束

    async def _start_guard_audio(self):
        from pathlib import Path as _Path
        path = _Path(self._config.GUARD_ALERT_AUDIO_PATH)
        if not path.is_absolute():
            path = _Path(__file__).resolve().parent.parent / path
        if not path.exists():
            logger.warning("[GuardMission] 音频文件不存在：{}，跳过播放", path)
            return
        self._audio_task = asyncio.create_task(self._audio_loop(str(path)))
        logger.info("[GuardMission] 音频循环任务已启动：{}", path)

    async def _stop_guard_audio(self):
        if self._audio_task and not self._audio_task.done():
            self._audio_task.cancel()
            try:
                await self._audio_task
            except asyncio.CancelledError:
                pass
        self._audio_task = None
        # 兜底：若 aplay 子进程仍在，强制终止
        if self._audio_process:
            try:
                self._audio_process.terminate()
            except ProcessLookupError:
                pass
            self._audio_process = None
        logger.info("[GuardMission] 音频已停止")


_guard_mission_service: Optional[GuardMissionService] = None

def get_guard_mission_service() -> Optional[GuardMissionService]:
    return _guard_mission_service

def set_guard_mission_service(service: GuardMissionService):
    global _guard_mission_service
    _guard_mission_service = service
