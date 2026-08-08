from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .alert_service import get_alert_service
from .config import settings
from .lightweight_tracker import calc_iou
from .logging_config import get_logger
from .models import InspectionTask
from .pose_detection import PoseEvent, PoseObservation
from .schemas import utc_now_iso
from .tracking_types import DetectionResult as TrackDetectionResult
from .ws_event_broadcaster import get_event_broadcaster

video_logger = get_logger("AI视频")
ai_logger = get_logger("AI识别")
pose_logger = get_logger("姿态识别")


class AIWorkerProcessingMixin:
    async def _notify_auto_track_video_lost(self, reason: str) -> None:
        try:
            from .auto_track_service import get_auto_track_service

            auto_track = get_auto_track_service()
            if auto_track is not None:
                await auto_track.notify_video_lost(reason)
        except Exception as exc:  # noqa: BLE001
            video_logger.debug("通知自动跟踪视频断流失败：{}", exc)

    async def _notify_auto_track_video_restored(self) -> None:
        try:
            from .auto_track_service import get_auto_track_service

            auto_track = get_auto_track_service()
            if auto_track is not None:
                await auto_track.notify_video_restored()
        except Exception as exc:  # noqa: BLE001
            video_logger.debug("通知自动跟踪视频恢复失败：{}", exc)

    async def _update_current_task_id(self) -> None:
        current_time = asyncio.get_event_loop().time()
        if current_time - self._last_task_check_time < 1.0:
            return

        self._last_task_check_time = current_time

        async with self._session_factory() as session:
            task = await _get_latest_running_task(session)
            self._current_task_id = task.task_id if task else self._get_active_navigation_task_id()

    def _get_active_navigation_task_id(self) -> str | None:
        try:
            from .nav_auto_track_coordinator import get_nav_auto_track_coordinator

            coordinator = get_nav_auto_track_coordinator()
            if coordinator is not None:
                interrupted_task_id = coordinator.get_status().get("interrupted_task_id")
                if interrupted_task_id:
                    return str(interrupted_task_id)
        except Exception:
            pass

        try:
            from .services_nav_state import get_nav_state

            nav_status = get_nav_state().get("navigation_status") or {}
            status = str(nav_status.get("status") or "").strip().lower()
            task_id = str(nav_status.get("task_id") or "").strip()
            if task_id and status in {"navigating", "paused"}:
                return task_id
        except Exception:
            pass
        return None

    def _is_mission_active(self) -> bool:
        # 持续分析仅保持视频推理支路运行，不会启用 AutoTrackService，
        # 因此不会向机器人下发任何运动命令。
        if settings.AI_CONTINUOUS_DETECTION_ENABLED:
            return True
        try:
            from .fence_detection_service import get_fence_detection_service

            fence_detection = get_fence_detection_service()
            if fence_detection is not None and fence_detection.enabled:
                return True
        except Exception:
            pass
        # 移除对 self._state_machine.state == SystemState.IN_MISSION 的强依赖。
        # 只要存在运行中的任务，且 RTSP 摄像头推流正常，AI 就会开始分析画面。
        if self._current_task_id is not None and settings.AI_PASSIVE_SESSION_DETECTION_ENABLED:
            return True
        try:
            from .auto_track_service import get_auto_track_service

            auto_track = get_auto_track_service()
            if auto_track is not None and auto_track._enabled:
                return True
        except Exception:
            pass
        from .guard_mission_service import get_guard_mission_service

        guard_mission = get_guard_mission_service()
        return guard_mission is not None and guard_mission.enabled

    def _is_suspect_mode(self) -> bool:
        if self._hits > 0 or self._in_alert:
            return True

        from .auto_track_service import get_auto_track_service
        from .guard_mission_service import get_guard_mission_service

        auto_track = get_auto_track_service()
        guard_mission = get_guard_mission_service()

        if guard_mission is not None and guard_mission.enabled:
            return True

        if auto_track is not None and auto_track._enabled:
            return auto_track._active_target is not None or len(auto_track._candidates) > 0
        return False

    def _get_frame_skip(self) -> int:
        """
        Decide how aggressively to sample frames for inference.

        Patrol can skip frames to save load. Once automatic tracking is enabled,
        even before a candidate is locked, keep a higher cadence so no-helmet
        confirmation and target reacquisition do not miss every other frame.
        """
        from .guard_mission_service import get_guard_mission_service

        try:
            from .fence_detection_service import get_fence_detection_service

            fence_detection = get_fence_detection_service()
            if fence_detection is not None and fence_detection.enabled:
                return self._suspect_skip
        except Exception:
            pass

        guard_mission = get_guard_mission_service()
        if guard_mission is not None and guard_mission.enabled:
            return self._suspect_skip

        try:
            from .auto_track_service import get_auto_track_service

            auto_track = get_auto_track_service()
            if auto_track is not None and auto_track._enabled and not auto_track._paused:
                return self._auto_track_skip
        except Exception:
            pass

        return self._suspect_skip if self._is_suspect_mode() else self._patrol_skip

    def _reset_detection_state(self) -> None:
        self._hits = 0
        self._misses = 0
        self._in_alert = False
        self._weapon_active_until = 0.0
        for class_name in self._weapon_hits:
            self._weapon_hits[class_name] = 0
            self._weapon_last_bbox[class_name] = None

    def _filter_weapon_detections(
        self,
        detections: list[DetectionResult],
        persons: list[DetectionResult],
    ) -> list[DetectionResult]:
        """过滤与人员无关的低置信度武器框，抑制椅子扶手等静态误报。"""
        if not bool(settings.WEAPON_REQUIRE_PERSON_ASSOCIATION):
            return list(detections)

        expand_ratio = max(
            0.0,
            min(2.0, float(settings.WEAPON_PERSON_EXPAND_RATIO)),
        )
        unattended_threshold = max(
            0.0,
            min(1.0, float(settings.WEAPON_UNATTENDED_CONFIDENCE_THRESHOLD)),
        )
        person_bboxes = [person.bbox for person in persons if person.bbox is not None]
        eligible: list[DetectionResult] = []
        for detection in detections:
            if detection.confidence >= unattended_threshold:
                eligible.append(detection)
                continue
            if detection.bbox is None:
                continue
            if any(
                _bbox_center_inside_expanded_bbox(
                    detection.bbox,
                    person_bbox,
                    expand_ratio,
                )
                for person_bbox in person_bboxes
            ):
                eligible.append(detection)
        return eligible

    async def _process_weapon_detections(
        self,
        detections: list[DetectionResult],
        frame: bytes,
    ) -> None:
        """独立处理枪械/刀具命中，不受自动跟踪或驱离状态机短路影响。"""
        now = asyncio.get_running_loop().time()
        detections_by_class: dict[str, list[DetectionResult]] = {}
        for detection in detections:
            detections_by_class.setdefault(detection.label, []).append(detection)

        if detections_by_class:
            self._weapon_active_until = max(
                self._weapon_active_until,
                now + max(0.0, float(settings.WEAPON_ACTIVE_SECONDS)),
            )

        stable_hits = max(1, int(settings.WEAPON_STABLE_HITS))
        confirm_iou_threshold = max(
            0.0,
            min(1.0, float(settings.WEAPON_CONFIRM_IOU_THRESHOLD)),
        )
        cooldown_seconds = max(
            0.0,
            float(settings.WEAPON_ALERT_COOLDOWN_SECONDS),
        )
        for class_name in self._weapon_hits:
            class_detections = detections_by_class.get(class_name, [])
            previous_bbox = self._weapon_last_bbox[class_name]
            if not class_detections:
                self._weapon_hits[class_name] = 0
                self._weapon_last_bbox[class_name] = None
                continue

            if previous_bbox is None:
                detection = max(class_detections, key=lambda item: item.confidence)
                spatially_consistent = False
            else:
                detection = max(
                    class_detections,
                    key=lambda item: (
                        calc_iou(item.bbox, previous_bbox)
                        if item.bbox is not None
                        else 0.0
                    ),
                )
                spatially_consistent = (
                    detection.bbox is not None
                    and calc_iou(detection.bbox, previous_bbox) >= confirm_iou_threshold
                )

            if previous_bbox is None or not spatially_consistent:
                self._weapon_hits[class_name] = 1
            else:
                self._weapon_hits[class_name] = min(
                    stable_hits,
                    self._weapon_hits[class_name] + 1,
                )
            self._weapon_last_bbox[class_name] = detection.bbox
            if self._weapon_hits[class_name] < stable_hits:
                continue
            if now - self._weapon_last_alert_at[class_name] < cooldown_seconds:
                continue

            await self._raise_alert(detection, frame)
            self._weapon_last_alert_at[class_name] = now
            self._weapon_hits[class_name] = 0
            self._weapon_alerts_count += 1

    async def _process_detection(
        self,
        detections: list[DetectionResult],
        frame: bytes,
        t_start: float = 0.0,
        t_detect_end: float = 0.0,
        *,
        allow_motion_services: bool = True,
    ) -> None:
        """
        处理检测结果。

        优先路径：将结果交给 AutoTrackService 处理（包含状态机、控制命令、抓拍）。
        兼容路径：若 AutoTrackService 未启用，回退到原有「检测即告警」逻辑。
        """
        from .auto_track_service import get_auto_track_service
        from .guard_mission_service import get_guard_mission_service

        auto_track = get_auto_track_service()
        guard_mission = get_guard_mission_service()

        skip = self._get_frame_skip()
        effective_fps = settings.AI_FPS / skip if skip > 0 else settings.AI_FPS

        track_detections = [
            TrackDetectionResult(
                bbox=d.bbox or (0, 0, 1, 1),
                confidence=d.confidence,
                class_name=d.label,
                track_id=getattr(d, "track_id", -1),
                identity_id=getattr(d, "identity_id", None),
                display_name=getattr(d, "display_name", None),
                face_status=getattr(d, "face_status", None),
                face_score=getattr(d, "face_score", None),
            )
            for d in detections
            if d.bbox is not None
        ]

        if allow_motion_services and guard_mission is not None and guard_mission.enabled:
            guard_mission.update_effective_fps(effective_fps)
            await guard_mission.process_frame(track_detections, frame)
            return

        if allow_motion_services and auto_track is not None:
            await auto_track.process_frame(
                detections=track_detections,
                frame=frame,
                frame_index=self._frames_processed,
                current_task_id=self._current_task_id,
                t_start=t_start,
                t_detect_end=t_detect_end,
            )
            if auto_track._enabled:
                return

        # 多类别模型上线后，head/helmet 只作为前端叠框信息；旧告警路径仍只对
        # 主目标检测器确认的 person 抓拍。姿态模型补齐的人体框置信度阈值更低，
        # 其用途是叠层/跟踪辅助，不能单独触发“陌生人”告警。
        alert_detections = [
            d
            for d in detections
            if d.label == "person" and not getattr(d, "is_pose_fallback", False)
        ]
        detection = alert_detections[0] if alert_detections else None

        if detection:
            self._hits += 1
            self._misses = 0
        else:
            self._misses += 1
            self._hits = 0

        if self._in_alert and self._misses >= self._reset_misses:
            self._in_alert = False

        if detection is None:
            return

        if self._in_alert:
            return

        now = asyncio.get_event_loop().time()
        if now - self._last_alert_time < self._cooldown_seconds:
            return

        if self._hits < self._stable_hits:
            return

        await self._raise_alert(detection, frame)
        self._in_alert = True
        self._last_alert_time = now
        self._hits = 0
        self._misses = 0

    async def _raise_alert(self, detection: DetectionResult, frame: bytes) -> None:
        image_path, image_url = await self._save_snapshot(frame)
        gps = self._get_latest_gps()

        label_zh: dict[str, str] = {
            "person": "陌生人",
            "car": "车辆",
            "dog": "动物",
            "cat": "动物",
            "fire": "火焰",
            "guns": "枪械",
            "knife": "刀具",
        }
        label_zh_value = label_zh.get(detection.label, detection.label)

        alert_service = get_alert_service()

        async with self._session_factory() as session:
            await alert_service.handle_ai_event(
                event_type="AI_DETECTION",
                event_code=f"E_AI_{detection.label.upper()}",
                severity="CRITICAL",
                message=f"检测到目标: {label_zh_value}",
                confidence=detection.confidence,
                file_path=str(image_path),
                image_url=image_url,
                gps_lat=gps[0],
                gps_lon=gps[1],
                task_id=self._current_task_id if isinstance(self._current_task_id, int) else None,
                session=session,
            )

    async def _process_pose_events(
        self,
        events: list[PoseEvent],
        frame: bytes,
    ) -> None:
        if not events:
            return

        event_meta = {
            "POSE_CLIMBING_SUSPECTED": (
                "E_POSE_CLIMBING_SUSPECTED",
                "CRITICAL",
                "检测到人员疑似攀爬",
            ),
            "POSE_LYING": (
                "E_POSE_LYING",
                "CRITICAL",
                "检测到人员疑似倒地",
            ),
            "POSE_CROUCHING": (
                "E_POSE_CROUCHING",
                "WARNING",
                "检测到重点区域人员持续蹲伏",
            ),
            "POSE_LOITERING": (
                "E_POSE_LOITERING",
                "WARNING",
                "检测到重点区域人员长时间停留",
            ),
        }
        gps = self._get_latest_gps()
        alert_service = get_alert_service()

        for event in events:
            code, severity, label = event_meta.get(
                event.event_type,
                (f"E_{event.event_type}", "WARNING", "检测到异常人体姿态"),
            )
            image_path, image_url = await self._save_snapshot(frame)
            pose_logger.info(
                "异常姿态已自动抓拍：event={}，track_id={}，path={}",
                event.event_type,
                event.track_id,
                image_path,
            )
            duration = max(0.0, event.duration_seconds)
            message = (
                f"{label}：track_id={event.track_id}，"
                f"持续={duration:.1f}s"
            )
            async with self._session_factory() as session:
                await alert_service.handle_ai_event(
                    event_type=event.event_type,
                    event_code=code,
                    severity=severity,
                    message=message,
                    confidence=event.confidence,
                    file_path=str(image_path),
                    image_url=image_url,
                    gps_lat=gps[0],
                    gps_lon=gps[1],
                    task_id=self._current_task_id
                    if isinstance(self._current_task_id, int)
                    else None,
                    session=session,
                )

    async def _process_fence_events(self, events, frame: bytes) -> None:
        if not events:
            return

        from .fence_detection_service import FenceBehavior

        event_meta = {
            FenceBehavior.DWELLING: (
                "FENCE_DWELL",
                "E_FENCE_DWELL",
                "WARNING",
                "检测到人员在围栏附近停留",
            ),
            FenceBehavior.CONTACT: (
                "FENCE_CONTACT",
                "E_FENCE_CONTACT",
                "WARNING",
                "检测到人员接触围栏",
            ),
            FenceBehavior.CLIMBING_SUSPECTED: (
                "FENCE_CLIMBING_SUSPECTED",
                "E_FENCE_CLIMBING_SUSPECTED",
                "CRITICAL",
                "检测到人员疑似翻越围栏",
            ),
        }
        gps = self._get_latest_gps()
        alert_service = get_alert_service()
        for event in events:
            meta = event_meta.get(event.behavior)
            if meta is None:
                continue
            event_type, event_code, severity, label = meta
            image_path, image_url = await self._save_snapshot(frame)
            message = (
                f"{label}：fence_id={event.fence_id}，track_id={event.track_id}，"
                f"持续={event.duration_seconds:.1f}s"
            )
            async with self._session_factory() as session:
                await alert_service.handle_ai_event(
                    event_type=event_type,
                    event_code=event_code,
                    severity=severity,
                    message=message,
                    confidence=event.confidence,
                    file_path=str(image_path),
                    image_url=image_url,
                    gps_lat=gps[0],
                    gps_lon=gps[1],
                    task_id=self._current_task_id if isinstance(self._current_task_id, int) else None,
                    session=session,
                )

    async def _broadcast_pose_overlay(
        self,
        observations: list[PoseObservation],
        detections: list[DetectionResult],
    ) -> None:
        now = asyncio.get_event_loop().time()
        interval = max(0.05, float(settings.POSE_OVERLAY_INTERVAL_SECONDS))
        if now - self._last_pose_overlay_broadcast < interval:
            return
        self._last_pose_overlay_broadcast = now

        broadcaster = get_event_broadcaster()
        if broadcaster.connection_count == 0:
            return

        message = {
            "msg_type": "POSE_OVERLAY",
            "timestamp": utc_now_iso(),
            "payload": {
                "frame_w": self._frame_width,
                "frame_h": self._frame_height,
                "keypoint_confidence": settings.POSE_KEYPOINT_CONFIDENCE,
                "detections": [
                    {
                        "bbox": list(detection.bbox)
                        if detection.bbox is not None
                        else [],
                        "conf": round(detection.confidence, 4),
                        "class_name": detection.label,
                        "track_id": getattr(detection, "track_id", -1),
                        "identity_id": getattr(detection, "identity_id", None),
                        "display_name": getattr(detection, "display_name", None),
                        "face_status": getattr(detection, "face_status", None),
                        "face_score": getattr(detection, "face_score", None),
                    }
                    for detection in detections
                    if detection.bbox is not None
                ],
                "poses": [observation.as_overlay() for observation in observations],
            },
        }

        async with broadcaster._lock:
            failed = []
            for connection in broadcaster._connections:
                try:
                    await asyncio.wait_for(
                        connection.send_json(message),
                        timeout=self._event_send_timeout_s,
                    )
                except Exception:
                    failed.append(connection)
            for connection in failed:
                broadcaster._connections.discard(connection)

    async def _save_snapshot(self, frame: bytes) -> tuple[Path, str]:
        return await asyncio.to_thread(self._save_snapshot_sync, frame)

    def _save_snapshot_sync(self, frame: bytes) -> tuple[Path, str]:
        try:
            import numpy as np
            from PIL import Image
        except ImportError as exc:  # noqa: BLE001
            ai_logger.error("缺少图像依赖，无法抓拍：{}", exc)
            raise

        now = datetime.utcnow()
        date_dir = now.strftime("%Y-%m-%d")
        filename = now.strftime("%H-%M-%S-%f") + ".jpg"

        target_dir = self._snapshot_dir / date_dir
        target_dir.mkdir(parents=True, exist_ok=True)

        image_path = target_dir / filename
        image_url = f"/api/v1/static/{date_dir}/{filename}"

        frame_array = np.frombuffer(frame, dtype=np.uint8)
        frame_array = frame_array.reshape((self._frame_height, self._frame_width, 3))
        frame_array = frame_array[:, :, ::-1]
        image = Image.fromarray(frame_array)
        image.save(image_path, format="JPEG", quality=90)

        return image_path, image_url

    def _get_latest_gps(self) -> tuple[Optional[float], Optional[float]]:
        position = self._mavlink_gateway.get_latest_position()
        if position is None:
            return None, None
        return position.lat, position.lon

    def _get_mode(self) -> str:
        if not self._is_mission_active():
            return "idle"
        if self._in_alert:
            return "alert"
        if self._is_suspect_mode():
            return "suspect"
        return "patrol"

    async def _maybe_broadcast_status(self) -> None:
        now = asyncio.get_event_loop().time()
        if now - self._last_status_broadcast < self._status_interval:
            return
        self._last_status_broadcast = now

        try:
            broadcaster = get_event_broadcaster()
            if broadcaster.connection_count == 0:
                return

            msg = {
                "msg_type": "AI_STATUS",
                "timestamp": utc_now_iso(),
                "payload": {
                    "frames_processed": self._frames_processed,
                    "detections_count": self._detections_count,
                    "mode": self._get_mode(),
                    "hits": self._hits,
                    "stable_hits": self._stable_hits,
                    "latest_frame_index": self._latest_frame_index,
                    "last_processed_frame_index": self._last_processed_frame_index,
                    "queued_frames_dropped": self._queued_frames_dropped,
                    "stale_frames_dropped": self._stale_frames_dropped,
                    "frame_age_ms": self._last_frame_age_ms,
                    "processing_ms": self._last_processing_ms,
                    "detect_ms": self._last_detect_ms,
                    "weapon_ms": self._last_weapon_ms,
                    "weather_ms": self._last_weather_ms,
                    "pose_ms": self._last_pose_ms,
                    "postprocess_ms": self._last_postprocess_ms,
                    "end_to_end_ms": self._last_end_to_end_ms,
                    "frame_timeout_reason": self._last_frame_timeout_reason,
                    "pose_status": self._pose_status,
                    "pose_frames_processed": self._pose_frames_processed,
                    "pose_events_count": self._pose_events_count,
                    "weapon_status": self._weapon_status,
                    "weapon_active": (
                        asyncio.get_running_loop().time()
                        < self._weapon_active_until
                    ),
                    "weapon_frames_processed": self._weapon_frames_processed,
                    "weapon_detections_count": self._weapon_detections_count,
                    "weapon_filtered_detections_count": self._weapon_filtered_detections_count,
                    "weapon_alerts_count": self._weapon_alerts_count,
                    "weather": self._weather_service.get_status(),
                    "parallel_inference_enabled": self._parallel_inference_enabled,
                    "inference_warmed_up": (
                        self._detector_warmed_up
                        and (self._pose_detector is None or self._pose_warmed_up)
                        and (
                            self._weapon_detector is None
                            or self._weapon_warmed_up
                        )
                        and (
                            not self._weather_service.available
                            or self._weather_warmed_up
                        )
                    ),
                },
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
                for conn in failed:
                    broadcaster._connections.discard(conn)
        except Exception as exc:
            ai_logger.debug("AI 状态广播失败：{}", exc)


def _bbox_center_inside_expanded_bbox(
    target_bbox: tuple[int, int, int, int],
    reference_bbox: tuple[int, int, int, int],
    expand_ratio: float,
) -> bool:
    """判断目标框中心是否落在按比例外扩后的参考框内。"""
    target_cx = (target_bbox[0] + target_bbox[2]) / 2.0
    target_cy = (target_bbox[1] + target_bbox[3]) / 2.0
    reference_width = max(1.0, float(reference_bbox[2] - reference_bbox[0]))
    reference_height = max(1.0, float(reference_bbox[3] - reference_bbox[1]))
    expand_x = reference_width * max(0.0, expand_ratio)
    expand_y = reference_height * max(0.0, expand_ratio)
    return (
        reference_bbox[0] - expand_x <= target_cx <= reference_bbox[2] + expand_x
        and reference_bbox[1] - expand_y <= target_cy <= reference_bbox[3] + expand_y
    )


async def _get_latest_running_task(session: AsyncSession) -> Optional[InspectionTask]:
    stmt = (
        select(InspectionTask)
        .where(InspectionTask.status == "running")
        .order_by(InspectionTask.started_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()
