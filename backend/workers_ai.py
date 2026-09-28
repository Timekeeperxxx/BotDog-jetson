"""
旁路 AI 识别与抓拍 Worker。

职责（阶段 1 改造后）：
- 通过 FFmpeg 子进程读取 RTSP 原始帧（BGR24）
- 调用检测器 detect_many() 获取所有 person 检测结果
- 将检测结果交给 AutoTrackService.process_frame() 处理
- 广播基础 AI 状态（AI_STATUS）

注意：目标稳定命中、锁定、出区判断、跟踪控制命令均由 AutoTrackService 负责。
若 auto_track_service 未启用，回退到原有「检测即告警」兼容路径。
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import settings
from .logging_config import get_logger
from .pose_detection import PoseEventEngine, PoseObservation, UltralyticsPoseDetector
from .workers_ai_processing import AIWorkerProcessingMixin

model_logger = get_logger("AI模型")
video_logger = get_logger("AI视频")
ai_logger = get_logger("AI识别")
pose_logger = get_logger("姿态识别")
weapon_logger = get_logger("武器识别")
weather_logger = get_logger("天气识别")
ffmpeg_logger = get_logger("AI视频").bind(raw_ffmpeg=True)


class AIWorkerError(RuntimeError):
    """AI Worker 运行时错误。"""


class AIWorkerFrameTimeout(AIWorkerError):
    """单帧 AI 处理超时。"""


@dataclass
class DetectionResult:
    """AIWorker 内部检测结果（兼容老路径用）。"""
    label: str
    confidence: float
    bbox: Optional[tuple[int, int, int, int]] = None
    track_id: int = -1  # YOLO ByteTrack 分配的跨帧 ID
    identity_id: int | None = None
    display_name: str | None = None
    face_status: str | None = None
    face_score: float | None = None
    # 姿态模型的人体框只用于补齐叠层和跟踪输入，不能单独作为“陌生人”
    # 被动告警的证据。否则姿态模型对背景的低置信度误检会绕过主检测器阈值。
    is_pose_fallback: bool = False


@dataclass(frozen=True)
class _AIFrame:
    data: bytes
    index: int
    read_at: float


class _BaseDetector:
    def detect(self, frame_bytes: bytes) -> Optional[DetectionResult]:
        raise NotImplementedError


class _SimulatedDetector(_BaseDetector):
    def __init__(self, prob: float) -> None:
        self._prob = prob

    def detect(self, frame_bytes: bytes) -> Optional[DetectionResult]:
        if random.random() < self._prob:
            confidence = random.uniform(0.6, 0.95)
            return DetectionResult(label="person", confidence=confidence)
        return None


class _NullDetector(_BaseDetector):
    def __init__(self) -> None:
        self._warned = False

    def detect(self, frame_bytes: bytes) -> Optional[DetectionResult]:
        if not self._warned:
            model_logger.warning("AI 模型未加载，当前仅支持模拟检测：AI_SIMULATE_DETECTION=true")
            self._warned = True
        return None


class _YoloDetector(_BaseDetector):
    """基于 YOLOv8 的真实目标检测器。"""

    def __init__(
        self,
        model_path: str,
        device: str,
        confidence: float,
        target_classes: list[str],
        frame_width: int,
        frame_height: int,
        inference_imgsz: int,
        use_bytetrack: bool,
        class_aliases: dict[str, str] | None = None,
    ) -> None:
        import numpy as np  # noqa: F811
        self._np = np
        self._frame_width = frame_width
        self._frame_height = frame_height
        self._inference_imgsz = max(32, int(inference_imgsz))
        self._confidence = confidence
        self._target_classes = set(target_classes)
        self._use_bytetrack = use_bytetrack

        try:
            from ultralytics import YOLO
        except ImportError:
            raise ImportError("请安装 ultralytics: pip install ultralytics")

        # 解析设备
        if device == "auto":
            try:
                import torch
                resolved_device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                resolved_device = "cpu"
        else:
            resolved_device = device

        model_logger.info("YOLO 加载模型：path={}，device={}", model_path, resolved_device)
        self._model = YOLO(model_path, task='detect')
        # self._model.to(resolved_device)
        self._device = resolved_device

        # 缓存模型类别名映射。不得把 cls=0 写死为 person：独立武器模型的
        # cls=0 是 guns，类别应始终以模型元数据为准。
        raw_names = self._model.names
        aliases = class_aliases or {}
        if isinstance(raw_names, dict):
            self._class_names = {
                int(class_id): aliases.get(str(class_name), str(class_name))
                for class_id, class_name in raw_names.items()
            }
        else:
            self._class_names = {
                class_id: aliases.get(str(class_name), str(class_name))
                for class_id, class_name in enumerate(raw_names)
            }
        missing_classes = self._target_classes.difference(self._class_names.values())
        if missing_classes:
            raise ValueError(
                f"模型类别缺失：expected={sorted(self._target_classes)}，"
                f"actual={sorted(self._class_names.values())}"
            )
        model_logger.info(
            "YOLO 模型已就绪：类别数={}，检测目标={}，bytetrack={}",
            len(self._class_names),
            target_classes,
            use_bytetrack,
        )

    def detect(self, frame_bytes: bytes) -> Optional[DetectionResult]:
        """返回置信度最高的单个目标（兼容老路径）。"""
        results = self.detect_many(frame_bytes)
        return results[0] if results else None

    def _result_to_detections(
        self,
        result,
        *,
        offset_x: int = 0,
        offset_y: int = 0,
    ) -> list[DetectionResult]:
        if result is None or result.boxes is None or len(result.boxes) == 0:
            return []
        detections: list[DetectionResult] = []
        for box in result.boxes:
            cls_id = int(box.cls[0])
            cls_name = self._class_names.get(cls_id, str(cls_id))
            if cls_name not in self._target_classes:
                continue
            xyxy = box.xyxy[0].tolist()
            detections.append(
                DetectionResult(
                    label=cls_name,
                    confidence=float(box.conf[0]),
                    bbox=(
                        int(xyxy[0]) + offset_x,
                        int(xyxy[1]) + offset_y,
                        int(xyxy[2]) + offset_x,
                        int(xyxy[3]) + offset_y,
                    ),
                    track_id=int(box.id[0]) if box.id is not None else -1,
                )
            )
        return detections

    def detect_many(self, frame_bytes: bytes) -> list[DetectionResult]:
        """返回所有目标类别的检测结果列表，使用 ByteTrack 提供稳定 track_id。"""
        frame = self._np.frombuffer(frame_bytes, dtype=self._np.uint8)
        frame = frame.reshape((self._frame_height, self._frame_width, 3))

        if self._use_bytetrack:
            # 使用 YOLO 内置 ByteTrack，persist=True 保证跨帧 ID 稳定。
            try:
                results = self._model.track(
                    frame,
                    conf=self._confidence,
                    imgsz=self._inference_imgsz,
                    persist=True,
                    tracker="bytetrack.yaml",
                    verbose=False,
                )
            except Exception as exc:
                # tracker 不可用时降级到 predict
                model_logger.warning("YOLO track() 调用失败，已降级到 predict()：{}", exc)
                results = self._model.predict(
                    frame,
                    conf=self._confidence,
                    imgsz=self._inference_imgsz,
                    verbose=False,
                )
        else:
            results = self._model.predict(
                frame,
                conf=self._confidence,
                imgsz=self._inference_imgsz,
                verbose=False,
            )

        if not results:
            return []
        return self._result_to_detections(results[0])

    def detect_many_regions(
        self,
        frame_bytes: bytes,
        regions: list[tuple[int, int, int, int]],
        *,
        expand_ratio: float,
        max_regions: int,
        nms_iou: float,
    ) -> list[DetectionResult]:
        """在人员区域内放大检测，并把武器框映射回完整画面坐标。"""
        frame = self._np.frombuffer(frame_bytes, dtype=self._np.uint8)
        frame = frame.reshape((self._frame_height, self._frame_width, 3))
        ordered_regions = sorted(
            regions,
            key=lambda item: max(0, item[2] - item[0]) * max(0, item[3] - item[1]),
            reverse=True,
        )[: max(1, int(max_regions))]
        detections: list[DetectionResult] = []
        for region in ordered_regions:
            x1, y1, x2, y2 = region
            width = max(1, x2 - x1)
            height = max(1, y2 - y1)
            crop_x1 = max(0, int(x1 - width * expand_ratio))
            crop_y1 = max(0, int(y1 - height * expand_ratio))
            crop_x2 = min(self._frame_width, int(x2 + width * expand_ratio))
            crop_y2 = min(self._frame_height, int(y2 + height * expand_ratio))
            if crop_x2 <= crop_x1 or crop_y2 <= crop_y1:
                continue
            crop = frame[crop_y1:crop_y2, crop_x1:crop_x2]
            results = self._model.predict(
                crop,
                conf=self._confidence,
                imgsz=self._inference_imgsz,
                verbose=False,
            )
            if results:
                detections.extend(
                    self._result_to_detections(
                        results[0],
                        offset_x=crop_x1,
                        offset_y=crop_y1,
                    )
                )

        kept: list[DetectionResult] = []
        for detection in sorted(
            detections, key=lambda item: item.confidence, reverse=True
        ):
            if detection.bbox is None:
                continue
            if any(
                previous.label == detection.label
                and previous.bbox is not None
                and self._bbox_iou(previous.bbox, detection.bbox) >= nms_iou
                for previous in kept
            ):
                continue
            kept.append(detection)
        return kept

    @staticmethod
    def _bbox_iou(
        first: tuple[int, int, int, int],
        second: tuple[int, int, int, int],
    ) -> float:
        x1 = max(first[0], second[0])
        y1 = max(first[1], second[1])
        x2 = min(first[2], second[2])
        y2 = min(first[3], second[3])
        intersection = max(0, x2 - x1) * max(0, y2 - y1)
        first_area = max(0, first[2] - first[0]) * max(0, first[3] - first[1])
        second_area = max(0, second[2] - second[0]) * max(0, second[3] - second[1])
        union = first_area + second_area - intersection
        return intersection / union if union > 0 else 0.0


class AIWorker(AIWorkerProcessingMixin):
    def __init__(
        self,
        *,
        session_factory,
        state_machine,
        mavlink_gateway,
        snapshot_dir: Path,
    ) -> None:
        self._session_factory = session_factory
        self._state_machine = state_machine
        self._mavlink_gateway = mavlink_gateway
        self._snapshot_dir = snapshot_dir

        from .lightweight_tracker import LightweightIouTracker

        self._lightweight_tracker = LightweightIouTracker(
            frame_width=settings.AI_FRAME_WIDTH,
            max_age_frames=max(15, settings.AI_FPS * 3),
        )

        self._frame_width = settings.AI_FRAME_WIDTH
        self._frame_height = settings.AI_FRAME_HEIGHT
        self._frame_size = self._frame_width * self._frame_height * 3

        self._patrol_skip = max(1, settings.AI_PATROL_SKIP)
        self._auto_track_skip = max(1, settings.AI_AUTO_TRACK_SKIP)
        self._suspect_skip = max(1, settings.AI_SUSPECT_SKIP)
        self._stable_hits = max(1, settings.AI_STABLE_HITS)
        self._reset_misses = max(1, settings.AI_RESET_MISSES)
        self._cooldown_seconds = max(0.0, settings.AI_COOLDOWN_SECONDS)

        self._current_task_id: Optional[int | str] = None
        self._last_task_check_time: float = 0.0

        # 按轨迹去重；身份恢复不删除历史报警，避免同一人员反复告警。
        self._person_alert_last_seen: dict[int, int] = {}
        self._person_pose_hits: dict[int, int] = {}
        self._person_alert_frame = 0
        self._face_fault_reported = False

        # 兼容状态（状态接口保留）
        self._hits = 0
        self._misses = 0
        self._in_alert = False
        self._last_alert_time = 0.0

        # 状态广播计数
        self._frames_processed = 0
        self._detections_count = 0
        self._last_status_broadcast = 0.0
        self._status_interval = 5.0  # 每 5 秒广播一次
        self._ffmpeg_stream_unavailable = False
        self._ffmpeg_unavailable_reason = "unknown"
        self._ffmpeg_last_exit_reason = "unknown"
        self._ffmpeg_banner_logged = False
        self._stream_restored_logged = False
        self._last_ffmpeg_start_log_at = 0.0
        self._last_retry_log_at = 0.0
        self._rtsp_urls = self._build_rtsp_urls()
        self._rtsp_url_index = 0
        self._ffmpeg_max_rss_bytes = max(
            128, int(settings.AI_FFMPEG_MAX_RSS_MB)
        ) * 1024 * 1024
        self._ffmpeg_memory_check_interval_s = max(
            0.2, float(settings.AI_FFMPEG_MEMORY_CHECK_INTERVAL_SECONDS)
        )
        self._ffmpeg_peak_rss_bytes = 0
        self._ffmpeg_frame_timeout_s = max(1.0, float(settings.AI_FFMPEG_FRAME_TIMEOUT_SECONDS))
        self._frame_process_timeout_s = max(1.0, float(settings.AI_FRAME_PROCESS_TIMEOUT_SECONDS))
        self._max_frame_age_s = max(0.05, float(settings.AI_MAX_FRAME_AGE_SECONDS))
        self._event_send_timeout_s = max(0.005, float(settings.AI_EVENT_SEND_TIMEOUT_SECONDS))
        self._last_frame_started_at = 0.0
        self._last_frame_completed_at = 0.0
        self._last_frame_timeout_reason: str | None = None
        self._pending_inferences: dict[asyncio.Task, str] = {}
        self._latest_frame_index = 0
        self._last_processed_frame_index = 0
        self._queued_frames_dropped = 0
        self._stale_frames_dropped = 0
        self._last_frame_age_ms = 0.0
        self._last_processing_ms = 0.0
        self._last_detect_ms = 0.0
        self._last_pose_ms = 0.0
        self._last_postprocess_ms = 0.0
        self._last_end_to_end_ms = 0.0
        self._pose_frames_processed = 0
        self._pose_events_count = 0
        self._pose_inference_deferred = False
        self._last_pose_overlay_broadcast = 0.0
        self._pose_status = "disabled"
        self._pose_detector: UltralyticsPoseDetector | None = None
        self._pose_event_engine: PoseEventEngine | None = None
        self._weapon_status = "disabled"
        self._weapon_detector: _YoloDetector | None = None
        self._weapon_frame_skip = max(1, int(settings.WEAPON_FRAME_SKIP))
        self._weapon_active_until = 0.0
        self._weapon_hits = {
            class_name: 0 for class_name in settings.WEAPON_TARGET_CLASSES
        }
        self._weapon_first_seen: dict[str, float | None] = {}
        self._weapon_last_bbox = {
            class_name: None for class_name in settings.WEAPON_TARGET_CLASSES
        }
        self._weapon_last_alert_at = {
            class_name: 0.0 for class_name in settings.WEAPON_TARGET_CLASSES
        }
        self._weapon_frames_processed = 0
        self._weapon_detections_count = 0
        self._weapon_filtered_detections_count = 0
        self._weapon_alerts_count = 0
        self._last_weapon_ms = 0.0
        self._last_weather_inference_at = 0.0
        self._last_weather_ms = 0.0
        self._weather_warmed_up = False
        # 姿态模型同时提供可靠的人体框。当安全帽检测模型漏掉 person 时，
        # 缓存最近一批姿态框，供两次姿态推理之间的检测帧兜底使用。
        self._latest_pose_observations: list[PoseObservation] = []
        self._latest_pose_observations_at: float = 0.0
        self._pose_person_grace_seconds: float = 0.8
        self._parallel_inference_enabled = bool(settings.AI_PARALLEL_INFERENCE_ENABLED)
        self._detector_warmed_up = False
        self._pose_warmed_up = False
        self._weapon_warmed_up = False
        self._startup_status = "waiting"
        self._startup_detail = (
            f"等待 RTSP 连接：rtsp={self._current_rtsp_url}，fps={settings.AI_FPS}，"
            f"分辨率={self._frame_width}x{self._frame_height}"
        )

        from .weather_detection import (
            WeatherDetectionService,
            set_weather_detection_service,
        )

        self._weather_service = WeatherDetectionService.from_settings(settings)
        set_weather_detection_service(self._weather_service)

        if settings.AI_SIMULATE_DETECTION:
            self._detector: _BaseDetector = _SimulatedDetector(settings.AI_SIMULATE_PROB)
            self._startup_status = "ready"
            self._startup_detail = f"模拟检测已启用：prob={settings.AI_SIMULATE_PROB}"
        else:
            try:
                self._detector = _YoloDetector(
                    model_path=settings.AI_MODEL_PATH,
                    device=settings.AI_DEVICE,
                    confidence=settings.AI_CONFIDENCE_THRESHOLD,
                    target_classes=settings.AI_TARGET_CLASSES,
                    frame_width=self._frame_width,
                    frame_height=self._frame_height,
                    inference_imgsz=settings.AI_INFERENCE_IMGSZ,
                    use_bytetrack=settings.AI_USE_BYTETRACK,
                )
                self._startup_status = "waiting"
                self._startup_detail = (
                    f"模型已加载，等待 RTSP 连接：rtsp={self._current_rtsp_url}，"
                    f"device={settings.AI_DEVICE}"
                )
            except Exception as exc:
                import traceback
                model_logger.error("YOLO 模型加载失败，AI 识别已降级：{}", exc)
                model_logger.debug("YOLO 模型加载堆栈：\n{}", traceback.format_exc())
                self._detector = _NullDetector()
                self._startup_status = "failed"
                self._startup_detail = f"YOLO 模型加载失败：{exc}"

        if settings.WEAPON_ENABLED and not settings.AI_SIMULATE_DETECTION:
            try:
                self._weapon_detector = _YoloDetector(
                    model_path=settings.WEAPON_MODEL_PATH,
                    device=settings.WEAPON_DEVICE,
                    confidence=settings.WEAPON_CONFIDENCE_THRESHOLD,
                    target_classes=settings.WEAPON_TARGET_CLASSES,
                    frame_width=self._frame_width,
                    frame_height=self._frame_height,
                    inference_imgsz=settings.WEAPON_INFERENCE_IMGSZ,
                    use_bytetrack=False,
                    class_aliases={
                        "Firearm": "guns",
                        "Melee_Weapon": "knife",
                    },
                )
                self._weapon_status = "ready"
                weapon_logger.info(
                    "武器模型已就绪：path={}，device={}，imgsz={}，classes={}，frame_skip={}",
                    settings.WEAPON_MODEL_PATH,
                    settings.WEAPON_DEVICE,
                    settings.WEAPON_INFERENCE_IMGSZ,
                    settings.WEAPON_TARGET_CLASSES,
                    self._weapon_frame_skip,
                )
            except Exception as exc:
                import traceback

                self._weapon_status = "failed"
                self._weapon_detector = None
                weapon_logger.error("武器模型加载失败，武器支路已降级：{}", exc)
                weapon_logger.debug("武器模型加载堆栈：\n{}", traceback.format_exc())

        if settings.POSE_ENABLED:
            try:
                self._pose_detector = UltralyticsPoseDetector(
                    model_path=settings.POSE_MODEL_PATH,
                    device=settings.POSE_DEVICE,
                    confidence=settings.POSE_CONFIDENCE_THRESHOLD,
                    inference_imgsz=settings.POSE_INFERENCE_IMGSZ,
                    frame_width=self._frame_width,
                    frame_height=self._frame_height,
                )
                self._pose_event_engine = PoseEventEngine(
                    keypoint_confidence=settings.POSE_KEYPOINT_CONFIDENCE,
                    min_visible_keypoints=settings.POSE_MIN_VISIBLE_KEYPOINTS,
                    stable_hits=settings.POSE_STABLE_HITS,
                    chest_motion_seconds=settings.POSE_CHEST_MOTION_SECONDS,
                    chest_motion_span=settings.POSE_CHEST_MOTION_SPAN,
                    crouch_seconds=settings.POSE_CROUCH_SECONDS,
                    loiter_seconds=settings.POSE_LOITER_SECONDS,
                    event_cooldown_seconds=settings.POSE_EVENT_COOLDOWN_SECONDS,
                    track_ttl_seconds=settings.POSE_TRACK_TTL_SECONDS,
                )
                self._pose_status = "ready"
                pose_logger.info(
                    "姿态模型已就绪：path={}，device={}，imgsz={}，stable_hits={}",
                    settings.POSE_MODEL_PATH,
                    self._pose_detector.device,
                    settings.POSE_INFERENCE_IMGSZ,
                    settings.POSE_STABLE_HITS,
                )
            except Exception as exc:
                import traceback

                self._pose_status = "failed"
                pose_logger.error("姿态模型加载失败，姿态支路已降级：{}", exc)
                pose_logger.debug("姿态模型加载堆栈：\n{}", traceback.format_exc())

    def get_startup_status(self) -> dict[str, str]:
        weather_status = self._weather_service.get_status()
        return {
            "status": self._startup_status,
            "detail": (
                f"{self._startup_detail}，pose={self._pose_status}，"
                f"weapon={self._weapon_status}，weather={weather_status['state']}"
            ),
        }

    async def _await_inference(self, stage: str, awaitable):
        task = asyncio.create_task(awaitable)
        self._pending_inferences[task] = stage

        def completed(done):
            self._pending_inferences.pop(done, None)
            if not done.cancelled():
                done.exception()  # 外层超时后仍回收底层异常，避免遗留 Task 警告。

        task.add_done_callback(completed)
        return await asyncio.shield(task)

    async def _run_inference(self, stage: str, function, *args, **kwargs):
        return await self._await_inference(stage, asyncio.to_thread(function, *args, **kwargs))

    async def _wait_for_pending_inferences(self, stop_event: asyncio.Event) -> None:
        stopped = asyncio.create_task(stop_event.wait())
        try:
            # ponytail: 线程真正挂死时只能等待；强制恢复需将推理隔离到可终止的子进程。
            while self._pending_inferences and not stop_event.is_set():
                await asyncio.wait(
                    [*self._pending_inferences, stopped],
                    return_when=asyncio.FIRST_COMPLETED,
                )
        finally:
            stopped.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await stopped

    async def _warmup_models(self) -> None:
        frame = bytes(self._frame_size)
        models = [
            ("主检测预热", self._detector, "_detector_warmed_up", "detect_many"),
            ("姿态预热", self._pose_detector, "_pose_warmed_up", "detect"),
            ("刀枪预热", self._weapon_detector, "_weapon_warmed_up", "detect_many"),
        ]
        for stage, detector, flag, method in models:
            if detector is None or getattr(self, flag):
                continue
            started = time.monotonic()
            self._startup_status = "warming_up"
            self._startup_detail = stage
            ai_logger.info("{}开始", stage)
            infer = getattr(detector, method, None) or detector.detect
            try:
                await asyncio.wait_for(
                    self._run_inference(stage, infer, frame),
                    timeout=max(1.0, float(settings.AI_MODEL_WARMUP_TIMEOUT_SECONDS)),
                )
            except asyncio.TimeoutError as exc:
                raise AIWorkerFrameTimeout(f"{stage}超时，等待初始化结束") from exc
            setattr(self, flag, True)
            ai_logger.info("{}完成：{:.1f}ms", stage, (time.monotonic() - started) * 1000)
        self._startup_status = "ready"
        self._startup_detail = "模型预热完成，等待最新视频帧"

    async def start(self, stop_event: asyncio.Event) -> None:
        ai_logger.info(
            "AI Worker 已启动：fps={}，分辨率={}x{}，rtsp_sources={}，pose={}，"
            "weapon={}，weather={}，patrol_skip={}，pose_skip={}，weapon_skip={}，"
            "parallel_inference={}",
            settings.AI_FPS,
            self._frame_width,
            self._frame_height,
            self._rtsp_urls,
            self._pose_status,
            self._weapon_status,
            self._weather_service.get_status()["state"],
            self._patrol_skip,
            settings.POSE_FRAME_SKIP,
            self._weapon_frame_skip,
            self._parallel_inference_enabled,
        )
        retry_delay = max(0.5, settings.AI_FFMPEG_RETRY_MIN_SECONDS)
        max_retry_delay = max(retry_delay, settings.AI_FFMPEG_RETRY_MAX_SECONDS)
        reset_threshold = 10.0

        while not stop_event.is_set():
            await self._update_current_task_id()
            if not self._is_mission_active():
                self._reset_detection_state()
                if self._weather_service.available and time.monotonic() >= self._weather_service.next_sample_at:
                    await self._sample_weather_round_idle()
                    continue
                await asyncio.sleep(0.5)
                continue

            loop_start = asyncio.get_event_loop().time()
            try:
                # 独立预热，不把 TensorRT/NMS 首次初始化塞进实时帧的 15 秒预算。
                await self._warmup_models()
                await self._run_ffmpeg_loop(stop_event)
            except asyncio.CancelledError:
                break
            except AIWorkerFrameTimeout as exc:
                self._startup_status = "waiting"
                self._startup_detail = f"丢弃超时帧，等待在途推理完成后自动恢复：{exc}"
                self._last_frame_timeout_reason = str(exc)
                ai_logger.error("{}", self._startup_detail)
                self._last_status_broadcast = 0.0
                await self._maybe_broadcast_status()
                await self._wait_for_pending_inferences(stop_event)
                if stop_event.is_set():
                    return
                self._startup_status = "ready"
                self._startup_detail = "在途推理已结束，重新拉取最新画面"
                ai_logger.info("{}", self._startup_detail)
            except Exception as exc:  # noqa: BLE001
                ai_logger.exception("AI Worker 运行异常：{}", exc)
                await self._wait_for_pending_inferences(stop_event)

            if stop_event.is_set():
                break

            await self._update_current_task_id()
            if not self._is_mission_active():
                retry_delay = max(0.5, settings.AI_FFMPEG_RETRY_MIN_SECONDS)
                continue

            ran_seconds = asyncio.get_event_loop().time() - loop_start
            if ran_seconds >= reset_threshold:
                retry_delay = 1.0
            else:
                retry_delay = min(retry_delay * 2, max_retry_delay)

            self._rotate_rtsp_url_after_failure()
            self._log_retry_scheduled(retry_delay)
            await asyncio.sleep(retry_delay)

        ai_logger.info("AI Worker 已停止")

    async def _sample_weather_round_idle(self) -> None:
        """Take a scheduled weather round without starting robot control."""
        process = None
        stderr_task = None
        try:
            process = await self._start_ffmpeg()
            if process.stdout is None:
                raise AIWorkerError("天气刷新拉流失败")
            stderr_task = asyncio.create_task(self._drain_stderr(process))
            while time.monotonic() >= self._weather_service.next_sample_at:
                frame = await asyncio.wait_for(
                    process.stdout.readexactly(self._frame_size),
                    timeout=self._ffmpeg_frame_timeout_s,
                )
                await self._maybe_process_weather(frame)
        except (AIWorkerError, asyncio.TimeoutError, asyncio.IncompleteReadError, OSError) as exc:
            self._weather_service.cancel_refresh(f"天气刷新未取得视频帧：{exc}")
            ai_logger.warning("空闲天气采样未完成：{}", exc)
        finally:
            if process is not None:
                await self._terminate_ffmpeg_process(process, reason="weather_refresh")
            if stderr_task is not None:
                stderr_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await stderr_task
            self._last_status_broadcast = 0.0
            await self._maybe_broadcast_status()

    async def _run_ffmpeg_loop(self, stop_event: asyncio.Event) -> None:
        process = await self._start_ffmpeg()
        if process.stdout is None:
            raise AIWorkerError("FFmpeg stdout 未初始化")
        stderr_task = asyncio.create_task(self._drain_stderr(process))

        frame_queue: asyncio.Queue[_AIFrame] = asyncio.Queue(maxsize=1)
        from .frame_rate_limiter import FrameRateLimiter
        limiter = FrameRateLimiter(settings.AI_FPS)
        sampled_index = 0

        async def reader_task() -> None:
            frame_index = 0
            last_read_at = time.monotonic()
            try:
                while not stop_event.is_set():
                    frame = await asyncio.wait_for(
                        process.stdout.readexactly(self._frame_size),
                        timeout=self._ffmpeg_frame_timeout_s,
                    )
                    read_at = time.monotonic()
                    read_gap = read_at - last_read_at
                    last_read_at = read_at
                    if settings.AI_STREAM_READER == "gstreamer" and read_gap > self._max_frame_age_s:
                        # 原生 queue 会丢旧帧，但管道里已开始写的那一帧不能撤回。
                        self._queued_frames_dropped += 1
                        continue
                    # 每个解码帧都覆盖旧帧；限频放在消费端，不能先丢掉更新的画面。
                    if self._ffmpeg_stream_unavailable and not self._stream_restored_logged:
                        self._stream_restored_logged = True
                        self._ffmpeg_stream_unavailable = False
                        self._ffmpeg_last_exit_reason = "stream_restored"
                        await self._notify_auto_track_video_restored()
                        video_logger.info(
                            "RTSP 流已恢复，AI 识别恢复运行：rtsp={}",
                            self._current_rtsp_url,
                        )
                    frame_index += 1
                    self._latest_frame_index = frame_index
                    self._queued_frames_dropped += await self._put_latest_frame(
                        frame_queue,
                        _AIFrame(data=frame, index=frame_index, read_at=read_at),
                    )
            except asyncio.TimeoutError:
                self._ffmpeg_last_exit_reason = "frame_read_timeout"
                self._ffmpeg_stream_unavailable = True
                self._ffmpeg_unavailable_reason = "frame_read_timeout"
                video_logger.warning(
                    "AI 拉流连续 {:.1f}s 无完整帧，停止并重连", self._ffmpeg_frame_timeout_s
                )
                await self._terminate_ffmpeg_process(process, reason="frame_read_timeout")
            except asyncio.IncompleteReadError:
                if self._ffmpeg_last_exit_reason == "unknown":
                    self._ffmpeg_last_exit_reason = "stdout_closed"

        reader = asyncio.create_task(reader_task())
        mission_watchdog = asyncio.create_task(
            self._stop_ffmpeg_when_mission_inactive(process, stop_event)
        )
        memory_watchdog = asyncio.create_task(
            self._stop_ffmpeg_on_memory_limit(process, stop_event)
        )

        try:
            while not stop_event.is_set():
                try:
                    # 使用 timeout 定期唤醒检测 stop_event
                    ai_frame = await asyncio.wait_for(frame_queue.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    if reader.done():
                        if self._ffmpeg_last_exit_reason == "unknown":
                            self._ffmpeg_last_exit_reason = "process_exited"
                        break
                    continue

                await self._update_current_task_id()

                if not self._is_mission_active():
                    self._reset_detection_state()
                    break

                # 数据库/任务状态检查期间也可能到达新帧，推理前再取最新的一帧。
                while not frame_queue.empty():
                    ai_frame = frame_queue.get_nowait()
                    self._queued_frames_dropped += 1
                frame_age_s = time.monotonic() - ai_frame.read_at
                self._last_frame_age_ms = round(frame_age_s * 1000, 1)
                if frame_age_s > self._max_frame_age_s:
                    self._stale_frames_dropped += 1
                    self._queued_frames_dropped += 1
                    continue

                if not limiter.allow(time.monotonic()):
                    self._queued_frames_dropped += 1
                    continue
                sampled_index += 1
                skip = self._get_frame_skip()
                if skip > 1 and (sampled_index % skip) != 0:
                    continue

                await self._process_frame_with_timeout(
                    ai_frame.data,
                    ai_frame.index,
                    frame_read_at=ai_frame.read_at,
                )
        finally:
            mission_watchdog.cancel()
            memory_watchdog.cancel()
            stderr_task.cancel()
            reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await mission_watchdog
            with contextlib.suppress(asyncio.CancelledError):
                await memory_watchdog
            with contextlib.suppress(asyncio.CancelledError):
                await reader
            with contextlib.suppress(asyncio.CancelledError):  # CancelledError 不是 Exception，须单独捕获
                await stderr_task

            # 读任务已退出，收空管道以释放 subprocess transport；否则重连时会残留管道。
            drain = asyncio.create_task(process.communicate())
            try:
                await self._terminate_ffmpeg_process(process, reason="loop_stopped")
            finally:
                await drain
            if (
                not stop_event.is_set()
                and self._ffmpeg_last_exit_reason != "stream_restored"
                and self._is_mission_active()
            ):
                await self._notify_auto_track_video_lost(self._ffmpeg_last_exit_reason)

    async def _stop_ffmpeg_when_mission_inactive(
        self,
        process: asyncio.subprocess.Process,
        stop_event: asyncio.Event,
    ) -> None:
        while not stop_event.is_set():
            await asyncio.sleep(0.2)
            await self._update_current_task_id()
            if self._is_mission_active():
                continue
            await self._terminate_ffmpeg_process(process, reason="mission_inactive")
            return

    async def _stop_ffmpeg_on_memory_limit(
        self,
        process: asyncio.subprocess.Process,
        stop_event: asyncio.Event,
    ) -> None:
        while not stop_event.is_set() and process.returncode is None:
            await asyncio.sleep(self._ffmpeg_memory_check_interval_s)
            if stop_event.is_set() or process.returncode is not None:
                return

            rss_bytes = self._read_process_rss_bytes(process.pid)
            if rss_bytes is None:
                continue
            self._ffmpeg_peak_rss_bytes = max(self._ffmpeg_peak_rss_bytes, rss_bytes)
            if rss_bytes <= self._ffmpeg_max_rss_bytes:
                continue

            rss_mb = rss_bytes / (1024 * 1024)
            limit_mb = self._ffmpeg_max_rss_bytes / (1024 * 1024)
            reason = f"memory_limit_exceeded(rss={rss_mb:.1f}MiB,limit={limit_mb:.0f}MiB)"
            self._ffmpeg_last_exit_reason = reason
            self._ffmpeg_stream_unavailable = True
            self._ffmpeg_unavailable_reason = reason
            video_logger.error(
                "FFmpeg 内存异常，停止并重拉流：pid={}，rss={:.1f} MiB，上限={:.0f} MiB",
                process.pid,
                rss_mb,
                limit_mb,
            )
            await self._terminate_ffmpeg_process(process, reason=reason)
            return

    @staticmethod
    def _read_process_rss_bytes(
        pid: int,
        proc_root: Path = Path("/proc"),
    ) -> int | None:
        try:
            status = (proc_root / str(pid) / "status").read_text(
                encoding="utf-8", errors="replace"
            )
        except (FileNotFoundError, PermissionError, OSError):
            return None

        for line in status.splitlines():
            if not line.startswith("VmRSS:"):
                continue
            fields = line.split()
            if len(fields) < 2:
                return None
            try:
                return int(fields[1]) * 1024
            except ValueError:
                return None
        return None

    async def _terminate_ffmpeg_process(
        self,
        process: asyncio.subprocess.Process,
        *,
        reason: str,
        terminate_timeout_s: float = 0.8,
    ) -> None:
        if process.returncode is not None:
            return

        if self._ffmpeg_last_exit_reason == "unknown":
            self._ffmpeg_last_exit_reason = reason

        with contextlib.suppress(ProcessLookupError, OSError):
            process.terminate()

        try:
            await asyncio.wait_for(process.wait(), timeout=terminate_timeout_s)
            return
        except asyncio.TimeoutError:
            pass
        except ProcessLookupError:
            return

        with contextlib.suppress(ProcessLookupError, OSError):
            process.kill()
        with contextlib.suppress(Exception):
            await process.wait()

    @staticmethod
    async def _put_latest_frame(
        frame_queue: asyncio.Queue[_AIFrame],
        frame: _AIFrame,
    ) -> int:
        dropped = 0
        while frame_queue.full():
            try:
                frame_queue.get_nowait()
                dropped += 1
            except asyncio.QueueEmpty:
                break
        await frame_queue.put(frame)
        return dropped

    async def _process_frame_with_timeout(
        self,
        frame: bytes,
        frame_index: int,
        frame_read_at: float | None = None,
    ) -> None:
        self._last_frame_started_at = time.monotonic()
        if frame_read_at is not None:
            self._last_frame_age_ms = round(
                (self._last_frame_started_at - frame_read_at) * 1000,
                1,
            )
        try:
            await asyncio.wait_for(
                self._detect_and_process_frame(
                    frame,
                    frame_index,
                    frame_read_at=frame_read_at,
                ),
                # read_at 与围栏控制循环的位姿/云台样本同为 monotonic 时钟，
                # 用于选择图像对应时刻的样本，避免运动中拿“现在”投影旧帧。
                # 关键字传参也保持测试替身易于兼容。
                timeout=self._frame_process_timeout_s,
            )
        except asyncio.TimeoutError as exc:
            reason = (
                f"frame_index={frame_index} timeout={self._frame_process_timeout_s:.1f}s "
                f"frames_processed={self._frames_processed} "
                f"pending_stages={list(self._pending_inferences.values())}"
            )
            self._last_frame_timeout_reason = reason
            self._ffmpeg_last_exit_reason = f"AI_Frame_Process_Timeout({reason})"
            await self._notify_auto_track_video_lost(self._ffmpeg_last_exit_reason)
            video_logger.error(
                "AI 单帧处理超时：{}。丢弃旧帧，等待在途推理后自动恢复；不退出后端。",
                reason,
            )
            raise AIWorkerFrameTimeout(reason) from exc
        else:
            self._last_frame_completed_at = time.monotonic()
            self._last_processing_ms = round(
                (self._last_frame_completed_at - self._last_frame_started_at) * 1000,
                1,
            )
            if frame_read_at is not None:
                self._last_end_to_end_ms = round(
                    (self._last_frame_completed_at - frame_read_at) * 1000,
                    1,
                )
            self._last_processed_frame_index = frame_index
            self._last_frame_timeout_reason = None
            await self._maybe_broadcast_status()

    async def _detect_and_process_frame(
        self,
        frame: bytes,
        frame_index: int,
        frame_read_at: float | None = None,
    ) -> None:
        self._current_frame_received_at = frame_read_at
        from .fence_detection_service import get_fence_detection_service

        fence_detection = get_fence_detection_service()
        fence_enabled = fence_detection is not None and fence_detection.enabled
        # 刀枪支路不再跟随围栏开关：围栏是区域判定，刀枪是独立告警。
        # 这里以前会在围栏关闭时清空刀枪的命中计数与冷却状态，等于让整条
        # 支路停摆，现已移除；刀枪状态由 _process_weapon_detections 自行维护。
        pose_observations_for_overlay: list[PoseObservation] | None = None
        fresh_pose_observations: list[PoseObservation] = []
        pose_events = []
        fence_events = []
        # 摄像头通常以 20~25 FPS 输入，而 Worker 只消费最新帧。原始 frame_index
        # 会一次跳过数帧，拿它做取模可能导致 skip=2 仍然帧帧命中。各 AI 支路
        # 必须按实际进入推理的帧计数调度，才能得到稳定的 1/N 采样频率。
        inference_cycle_index = self._frames_processed + 1
        pose_scheduled = (
            self._pose_detector is not None
            and self._pose_event_engine is not None
            and (
                self._pose_inference_deferred
                or inference_cycle_index % max(1, int(settings.POSE_FRAME_SKIP)) == 0
            )
        )
        now = time.monotonic()
        weapon_active = now < self._weapon_active_until
        weapon_due = self._is_weapon_due(inference_cycle_index, now=now)
        # 巡逻态下避免主检测、姿态、武器三个 TensorRT engine 同时争抢 GPU：
        # 与刀枪同轮冲突的姿态帧，本轮直接跳过，等下一个姿态周期再来。
        # 这里以前会把「下一轮必跑」标记置真，那次顺延之后姿态就变成帧帧推理，
        # 实测耗时与主检测同量级，把吞吐砍半；该标记已停用。
        defer_pose_for_weapon = pose_scheduled and weapon_due and not weapon_active
        pose_due = pose_scheduled and not defer_pose_for_weapon
        self._pose_inference_deferred = False
        # TensorRT engine 的第一次 predict() 会惰性创建执行上下文。每个支路先
        # 顺序预热，后续才允许独立 engine 并发，避免 CUDA 初始化竞争。
        run_pose_parallel = (
            pose_due
            and self._parallel_inference_enabled
            and self._detector_warmed_up
            and self._pose_warmed_up
        )
        run_weapon_parallel = (
            weapon_due
            and not bool(settings.WEAPON_PERSON_CROP_ENABLED)
            and self._parallel_inference_enabled
            and self._detector_warmed_up
            and self._weapon_warmed_up
        )
        pose_task: asyncio.Task[tuple[list, float, float]] | None = None
        pose_task_consumed = False
        weapon_task: asyncio.Task[tuple[list[DetectionResult], float]] | None = None
        weapon_task_consumed = False
        if run_pose_parallel:
            pose_task = asyncio.create_task(self._infer_pose(frame))
        if run_weapon_parallel:
            weapon_task = asyncio.create_task(self._infer_weapon(frame))

        # 调用 detect_many 返回所有候选结果。
        t_start = time.monotonic()
        try:
            if hasattr(self._detector, 'detect_many'):
                detections = await self._run_inference("主检测", self._detector.detect_many, frame)
            else:
                # _SimulatedDetector/_NullDetector 回退到 detect() 兼容
                single = await self._run_inference("主检测", self._detector.detect, frame)
                detections = [single] if single else []
            t_detect_end = time.monotonic()
            self._last_detect_ms = round((t_detect_end - t_start) * 1000, 1)
            self._detector_warmed_up = True

            # 位置先到：不等姿态、刀枪和人脸，不把旧身份用于本帧。
            if any(item.label == "person" for item in detections):
                await self._broadcast_pose_overlay([], detections, stage="location", force=True)

            # Person crops need a current-frame person even when the helmet
            # detector misses it. Run pose now instead of deferring it, and do
            # not use cached display boxes to trigger weapon inference.
            if (weapon_due and settings.WEAPON_PERSON_CROP_ENABLED
                    and not any(d.label == "person" for d in detections)
                    and self._pose_detector is not None
                    and self._pose_event_engine is not None):
                pose_due = True
                self._pose_inference_deferred = False

            if pose_due:
                if pose_task is None:
                    raw_poses, pose_started_at, pose_ms = await self._infer_pose(frame)
                else:
                    raw_poses, pose_started_at, pose_ms = await pose_task
                    pose_task_consumed = True
                self._pose_warmed_up = True
                self._last_pose_ms = pose_ms

                from .zone_service import get_zone_service

                observations, pose_events = self._pose_event_engine.update(
                    raw_poses,
                    zone_gate=get_zone_service(),
                    events_enabled=fence_enabled,
                    now=frame_read_at if frame_read_at is not None else pose_started_at,
                )
                # 仅统计新推理的连续命中；用于显示的缓存人体框不增加确认次数。
                self._person_pose_hits = {
                    observation.track_id: self._person_pose_hits.get(observation.track_id, 0) + 1
                    for observation in observations
                }
                # 新推理已确认无人时立即清除，不能再把旧人体框包装成当前结果。
                self._latest_pose_observations = observations
                self._latest_pose_observations_at = time.monotonic()
                self._pose_frames_processed += 1
                self._pose_events_count += len(pose_events)
                pose_observations_for_overlay = observations
                fresh_pose_observations = observations
                await self._broadcast_pose_overlay(
                    observations,
                    self._merge_pose_person_fallback(detections, observations),
                    stage="pose_location", force=True,
                )
            else:
                self._last_pose_ms = 0.0

            if weapon_due:
                person_detections = [
                    detection for detection in self._merge_pose_person_fallback(detections, fresh_pose_observations)
                    if detection.label == "person"
                ]
                if weapon_task is None:
                    weapon_detections, weapon_ms = await self._infer_weapon(
                        frame,
                        person_detections,
                    )
                else:
                    weapon_detections, weapon_ms = await weapon_task
                    weapon_task_consumed = True
                self._weapon_warmed_up = True
                self._last_weapon_ms = weapon_ms
                self._weapon_frames_processed += 1
                self._weapon_detections_count += len(weapon_detections)
                eligible_weapon_detections = self._filter_weapon_detections(
                    weapon_detections,
                    person_detections,
                )
                self._weapon_filtered_detections_count += (
                    len(weapon_detections) - len(eligible_weapon_detections)
                )
                detections.extend(eligible_weapon_detections)

            else:
                self._last_weapon_ms = 0.0

            # 天气只需低频分类。若本帧已有姿态/武器 GPU 任务，顺延到下一空闲
            # 周期，避免天气的 30~50 ms 再叠加到延迟尖峰上。
            await self._maybe_process_weather(
                frame,
                defer=pose_due or weapon_due,
            )

            preview_detections = list(detections)
            detections = self._merge_pose_person_fallback(
                detections,
                self._latest_pose_observations,
            )
            persons = [item for item in detections if item.label == "person"]
            self._lightweight_tracker.update(persons, frame_index)

            # 复用已经解码并完成跟踪的可见光帧，仅向多源服务传递时间戳、
            # 检测框和缓存云台姿态，不复制整帧图像。纯热成像模式则只登记
            # 热成像时间戳；画中画模式不是独立双路原始图，不能用于精确标定。
            try:
                from .multisensor_fusion import get_multisensor_fusion_service
                from .z2mini_gimbal import get_z2mini_gimbal

                multisensor = get_multisensor_fusion_service()
                if multisensor is not None and multisensor.enabled:
                    observed_monotonic = (
                        frame_read_at if frame_read_at is not None else time.monotonic()
                    )
                    source_timestamp = time.time() - max(
                        0.0,
                        time.monotonic() - observed_monotonic,
                    )
                    gimbal_status = get_z2mini_gimbal().get_cached_status(
                        max_age_seconds=settings.MULTISENSOR_SAMPLE_MAX_AGE_SECONDS
                    )
                    picture_mode = (
                        gimbal_status.picture_mode if gimbal_status is not None else "unknown"
                    )
                    if picture_mode in {"visible", "unknown"}:
                        gimbal_sample = (
                            {
                                "yaw_deg": gimbal_status.relative_yaw_deg,
                                "pitch_deg": gimbal_status.relative_pitch_deg,
                                "zoom_ratio": gimbal_status.zoom_ratio,
                            }
                            if gimbal_status is not None
                            else None
                        )
                        multisensor.ingest_visible(
                            timestamp=source_timestamp,
                            monotonic_at=observed_monotonic,
                            detections=detections,
                            width=self._frame_width,
                            height=self._frame_height,
                            gimbal=gimbal_sample,
                        )
                    elif picture_mode == "thermal":
                        multisensor.ingest_thermal(
                            timestamp=source_timestamp,
                            monotonic_at=observed_monotonic,
                            width=self._frame_width,
                            height=self._frame_height,
                        )
            except Exception as exc:  # noqa: BLE001
                ai_logger.warning("多源融合采样失败，本帧已跳过：{}", exc)

            if fence_detection is not None and fence_enabled:
                fence_events = fence_detection.process_frame(
                    detections=detections,
                    poses=fresh_pose_observations,
                    frame_bgr=frame,
                    frame_monotonic=(
                        frame_read_at if frame_read_at is not None else time.monotonic()
                    ),
                )

            from .services_face_identities import get_face_identity_service

            face_stage_started = time.monotonic()
            face_error = None
            try:
                face_service = get_face_identity_service()
                await self._await_inference("人脸初始化", face_service.ensure_initialized(self._session_factory))
                await self._await_inference("人脸", face_service.annotate_frame(
                    frame, detections, inference_cycle_index,
                    self._frame_width, self._frame_height,
                ))
                health = face_service.status()
                if not health["available"] or not health["enabled"]:
                    face_error = health.get("error") or "人脸识别服务不可用或已禁用"
                elif any(d.face_status == "unavailable" for d in persons):
                    face_error = "人脸推理失败"
            except Exception as exc:
                face_error = str(exc)
                # 识别故障不能中断人员告警链。
                ai_logger.error("人脸识别服务故障：{}", exc)
                for detection in persons:
                    detection.face_status = "unavailable"
                    detection.identity_id = None
                    detection.display_name = None
            await self._report_face_service_fault(face_error)
            self._last_face_stage_ms = round((time.monotonic() - face_stage_started) * 1000, 1)
            overlay_stage_started = time.monotonic()
            await self._broadcast_pose_overlay(
                pose_observations_for_overlay
                if pose_observations_for_overlay is not None
                else self._latest_pose_observations,
                detections,
                force=True,
            )
            self._last_overlay_stage_ms = round((time.monotonic() - overlay_stage_started) * 1000, 1)
            # Preview keeps only this frame's results; never reuse held overlays.
            from .ai_sync_preview import publish as publish_preview
            publish_preview(
                frame, self._frame_width, self._frame_height,
                frame_read_at if frame_read_at is not None else t_start,
                preview_detections, fresh_pose_observations, pose_due, weapon_due,
            )

            events_stage_started = time.monotonic()
            # 先发布画框，再保存证据和广播告警；这些 I/O 不应拖住当前画面。
            if weapon_due:
                await self._process_weapon_detections(eligible_weapon_detections, frame)
            if pose_due:
                await self._process_pose_events(pose_events, frame)
            if fence_enabled:
                await self._process_fence_events(fence_events, frame)
            # 围栏保留开启状态；显式跟踪联动接管时只放行 AutoTrack，
            # Guard 仍不可争抢控制，围栏几何判定等待恢复观察后继续。
            await self._process_detection(
                detections,
                frame,
                t_start,
                t_detect_end,
                allow_motion_services=not fence_enabled,
                allow_auto_track=not fence_enabled or fence_detection.tracking_override,
            )

            self._last_events_stage_ms = round((time.monotonic() - events_stage_started) * 1000, 1)

            t_done = time.monotonic()
            self._last_postprocess_ms = round((t_done - t_detect_end) * 1000, 1)
            self._frames_processed += 1
            if detections:
                self._detections_count += 1
        finally:
            # 检测支路异常或外层超时取消时，也要取走姿态 Task 的结果/异常，
            # 防止后台留下未回收 Task。to_thread 底层调用不可强杀，但不会入队旧帧。
            if pose_task is not None and not pose_task_consumed:
                if not pose_task.done():
                    pose_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await pose_task

            if weapon_task is not None and not weapon_task_consumed:
                if not weapon_task.done():
                    weapon_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await weapon_task

    @staticmethod
    def _merge_pose_person_fallback(
        detections: list[DetectionResult],
        observations: list[PoseObservation],
    ) -> list[DetectionResult]:
        """普通检测漏掉 person 时，用姿态模型的人体框补齐。

        head/helmet 仍来自安全帽模型，因此自动跟踪的“有头且无安全帽”
        规则保持不变。只在整帧没有 person 时兜底，避免双模型产生重复人体框。
        """
        if any(detection.label == "person" for detection in detections):
            return detections
        if not observations:
            return detections

        return [
            *detections,
            *[
                DetectionResult(
                    label="person",
                    confidence=observation.confidence,
                    bbox=observation.bbox,
                    track_id=observation.track_id,
                    is_pose_fallback=True,
                )
                for observation in observations
            ],
        ]

    async def _infer_pose(self, frame: bytes) -> tuple[list, float, float]:
        if self._pose_detector is None:
            return [], time.monotonic(), 0.0
        pose_started_at = time.monotonic()
        raw_poses = await self._run_inference("姿态", self._pose_detector.detect, frame)
        pose_ms = round((time.monotonic() - pose_started_at) * 1000, 1)
        return raw_poses, pose_started_at, pose_ms

    def _is_weapon_due(self, cycle_index: int, *, now: float | None = None) -> bool:
        if self._weapon_detector is None:
            return False
        current_time = time.monotonic() if now is None else now
        if current_time < self._weapon_active_until:
            return True
        return cycle_index % self._weapon_frame_skip == 0

    async def _infer_weapon(
        self,
        frame: bytes,
        persons: list[DetectionResult] | None = None,
    ) -> tuple[list[DetectionResult], float]:
        if self._weapon_detector is None:
            return [], 0.0
        weapon_started_at = time.monotonic()
        if bool(settings.WEAPON_PERSON_CROP_ENABLED):
            regions = [
                person.bbox
                for person in (persons or [])
                if person.bbox is not None
            ]
            if not regions:
                return [], round((time.monotonic() - weapon_started_at) * 1000, 1)
            detections = await self._run_inference("刀枪裁剪",
                self._weapon_detector.detect_many_regions,
                frame,
                regions,
                expand_ratio=max(
                    0.0,
                    min(2.0, float(settings.WEAPON_PERSON_CROP_EXPAND_RATIO)),
                ),
                max_regions=max(1, int(settings.WEAPON_PERSON_CROP_MAX_REGIONS)),
                nms_iou=max(
                    0.0,
                    min(1.0, float(settings.WEAPON_PERSON_CROP_NMS_IOU)),
                ),
            )
        else:
            detections = await self._run_inference("刀枪", self._weapon_detector.detect_many, frame)
        weapon_ms = round((time.monotonic() - weapon_started_at) * 1000, 1)
        return detections, weapon_ms

    async def _maybe_process_weather(self, frame: bytes, *, defer: bool = False) -> None:
        if not self._weather_service.available:
            self._last_weather_ms = 0.0
            return
        now = time.monotonic()
        # 轮间由天气服务安排 300/10 秒；轮内连续取三张新帧。
        if now < self._weather_service.next_sample_at or now - self._last_weather_inference_at < 0.5:
            self._last_weather_ms = 0.0
            return
        if defer:
            self._last_weather_ms = 0.0
            return

        # Reserve the slot before entering the thread so a cancelled outer task
        # cannot enqueue duplicate GPU work for the immediately following frame.
        self._last_weather_inference_at = now
        started = time.monotonic()
        status = await self._run_inference("天气", self._weather_service.process_frame, frame)
        self._last_weather_ms = round((time.monotonic() - started) * 1000, 1)
        self._weather_warmed_up = status["state"] in {"ready", "warming_up"}
        weather_logger.debug(
            "天气采样：state={}，label={}，confidence={}，raw={}，cost={}ms",
            status["state"],
            status["label"],
            status["confidence"],
            status["raw_label"],
            self._last_weather_ms,
        )

    async def _start_ffmpeg(self) -> asyncio.subprocess.Process:
        command = [
            "nice",
            "-n", "10",
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-loglevel", "warning",
            "-fflags", "nobuffer+discardcorrupt",
            "-avioflags", "direct",
            "-flags", "low_delay",
            "-probesize", "32",
            "-analyzeduration", "0",
            "-rtsp_transport", "tcp",       # 用 TCP 代替 UDP，避免丢包导致 H.264 解码花屏
            "-rtsp_flags", "prefer_tcp",
            "-reorder_queue_size", "0",
            "-max_delay", "0",
            "-stimeout", "5000000",
            # 实机相机的 H.264 VUI 偶发给出 0/0 时间基。不要使用 hwaccel=auto
            # 和 FFmpeg fps 滤镜：两者组合曾令输出队列在几十秒内积压上万帧。
            "-threads", "2",
            "-filter_threads", "1",
            "-i", self._current_rtsp_url,
            "-an",
            "-sn",
            "-dn",
            "-vf", f"scale={self._frame_width}:{self._frame_height}:flags=fast_bilinear",
            "-vsync", "0",
            "-f", "image2pipe",
            "-vcodec", "rawvideo",
            "-pix_fmt", "bgr24",
            "-",
        ]

        if settings.AI_STREAM_READER == "gstreamer":
            if self._frame_width % 4:
                raise AIWorkerError("GStreamer BGR 输出要求 AI_FRAME_WIDTH 为 4 的倍数")
            # 原生线程持续解码；Python 暂停读管道时，只保留一个最新完整帧。
            # NVIDIA 插件可能向 stdout 打印启动信息，原始图像独占 fd 3。
            command = [
                "bash", "-c", 'exec "$@" 3>&1 1>/dev/null', "ai-reader",
                "nice", "-n", "10", "gst-launch-1.0", "-q",
                "rtspsrc", f"location={self._current_rtsp_url}", "protocols=tcp",
                "latency=30", "drop-on-latency=true", "do-retransmission=false",
                "tcp-timeout=5000000", "!", "rtph264depay", "!",
                "video/x-h264,stream-format=byte-stream,alignment=au", "!",
                "nvv4l2decoder", "enable-max-performance=true", "!", "nvvidconv", "!",
                f"video/x-raw,format=BGRx,width={self._frame_width},height={self._frame_height}",
                "!", "videoconvert", "!", "video/x-raw,format=BGR", "!",
                "queue", "max-size-buffers=1", "max-size-bytes=0", "max-size-time=0",
                "leaky=downstream", "!", "fdsink", "fd=3", "sync=false", "async=false",
            ]
            video_logger.info("AI 硬件解码启用：原生队列仅保留最新帧")

        self._ffmpeg_last_exit_reason = "unknown"
        self._stream_restored_logged = False
        self._ffmpeg_peak_rss_bytes = 0

        self._log_ffmpeg_start()

        return await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._ffmpeg_env_without_proxy(),
        )

    def _log_ffmpeg_start(self) -> None:
        now = time.monotonic()
        if self._last_ffmpeg_start_log_at and now - self._last_ffmpeg_start_log_at < 30.0:
            video_logger.debug(
                "启动 FFmpeg 拉流：rtsp={}，fps={}，分辨率={}x{}",
                self._current_rtsp_url,
                settings.AI_FPS,
                self._frame_width,
                self._frame_height,
            )
            return

        self._last_ffmpeg_start_log_at = now
        video_logger.info(
            "启动 FFmpeg 拉流：rtsp={}，fps={}，分辨率={}x{}",
            self._current_rtsp_url,
            settings.AI_FPS,
            self._frame_width,
            self._frame_height,
        )

    def _log_retry_scheduled(self, retry_delay: float) -> None:
        now = time.monotonic()
        should_warn = (
            not self._last_retry_log_at
            or now - self._last_retry_log_at >= 30.0
            or not self._ffmpeg_stream_unavailable
        )
        if should_warn:
            self._last_retry_log_at = now
            video_logger.warning(
                "FFmpeg 已退出，准备重连：原因={}，{:.1f} 秒后重试",
                self._ffmpeg_last_exit_reason,
                retry_delay,
            )
        else:
            video_logger.debug(
                "FFmpeg 已退出，准备重连：原因={}，{:.1f} 秒后重试",
                self._ffmpeg_last_exit_reason,
                retry_delay,
            )

    async def _drain_stderr(self, process: asyncio.subprocess.Process) -> None:
        if process.stderr is None:
            return

        buffer = b""
        while True:
            chunk = await process.stderr.read(4096)
            if not chunk:
                break
            buffer += chunk
            # 按行输出，FFmpeg 进度用 \r，错误用 \n
            lines = buffer.replace(b"\r", b"\n").split(b"\n")
            buffer = lines[-1]  # 保留未完成的行
            for line in lines[:-1]:
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                ffmpeg_logger.debug("{}", text)

                if text.startswith("frame=") or text.startswith("size="):
                    continue

                if self._is_ffmpeg_banner_line(text):
                    if not self._ffmpeg_banner_logged:
                        self._ffmpeg_banner_logged = True
                        video_logger.debug("FFmpeg 版本信息已写入 logs/ffmpeg.log")
                    continue

                if self._is_ffmpeg_output_backlog(text):
                    reason = "output_buffer_backlog"
                    self._ffmpeg_last_exit_reason = reason
                    self._ffmpeg_stream_unavailable = True
                    self._ffmpeg_unavailable_reason = reason
                    video_logger.error(
                        "FFmpeg 输出队列发生异常积压，立即停止并重拉流：pid={}，detail={}",
                        process.pid,
                        text[:160],
                    )
                    await self._terminate_ffmpeg_process(process, reason=reason)
                    return

                reason = self._classify_ffmpeg_failure_reason(text)
                if reason is None:
                    continue

                self._ffmpeg_last_exit_reason = reason
                if reason == "RTSP_Protocol_Error":
                    self._ffmpeg_stream_unavailable = True
                    self._ffmpeg_unavailable_reason = reason
                    video_logger.warning("AI RTSP 协议失步，停止并重连：{}", text[:160])
                    await self._terminate_ffmpeg_process(process, reason=reason)
                    return
                if not self._ffmpeg_stream_unavailable:
                    self._ffmpeg_stream_unavailable = True
                    self._ffmpeg_unavailable_reason = reason
                    await self._notify_auto_track_video_lost(reason)
                    video_logger.warning(
                        "RTSP 流异常，等待下一完整帧；持续无帧将重连：rtsp={}，原因={}",
                        self._current_rtsp_url,
                        reason,
                    )

    @property
    def _current_rtsp_url(self) -> str:
        return self._rtsp_urls[self._rtsp_url_index]

    @staticmethod
    def _split_rtsp_urls(raw: str) -> list[str]:
        return [part.strip() for part in raw.split(",") if part.strip()]

    def _build_rtsp_urls(self) -> list[str]:
        urls: list[str] = []
        for url in [settings.AI_RTSP_URL] + self._split_rtsp_urls(settings.AI_RTSP_FALLBACK_URLS):
            if url and url not in urls:
                urls.append(url)
        return urls or [settings.AI_RTSP_URL]

    def _rotate_rtsp_url_after_failure(self) -> None:
        if len(self._rtsp_urls) <= 1:
            return
        previous = self._current_rtsp_url
        self._rtsp_url_index = (self._rtsp_url_index + 1) % len(self._rtsp_urls)
        video_logger.warning(
            "切换 AI RTSP 拉流地址：{} -> {}",
            previous,
            self._current_rtsp_url,
        )

    @staticmethod
    def _ffmpeg_env_without_proxy() -> dict[str, str]:
        env = os.environ.copy()
        for key in (
            "http_proxy",
            "https_proxy",
            "ftp_proxy",
            "all_proxy",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "FTP_PROXY",
            "ALL_PROXY",
        ):
            env.pop(key, None)
        return env

    @staticmethod
    def _is_ffmpeg_banner_line(text: str) -> bool:
        prefixes = (
            "ffmpeg version",
            "built with",
            "configuration:",
            "libavutil",
            "libavcodec",
            "libavformat",
            "libavdevice",
            "libavfilter",
            "libswscale",
            "libswresample",
            "libpostproc",
        )
        lowered = text.lower()
        return lowered.startswith(prefixes)

    @staticmethod
    def _is_ffmpeg_output_backlog(text: str) -> bool:
        lowered = text.lower()
        return "buffers queued in out_" in lowered and "something may be wrong" in lowered

    @staticmethod
    def _classify_ffmpeg_failure_reason(text: str) -> Optional[str]:
        lowered = text.lower()
        if "cseq" in lowered and "expected" in lowered and "received" in lowered:
            return "RTSP_Protocol_Error"
        if "404 not found" in lowered:
            return "404_Not_Found"
        if "401 unauthorized" in lowered:
            return "401_Unauthorized"
        if "connection refused" in lowered:
            return "Connection_Refused"
        if "connection timed out" in lowered or "timed out" in lowered:
            return "Connection_Timed_Out"
        if "no route to host" in lowered:
            return "No_Route_To_Host"
        if "server returned" in lowered:
            return text.replace(" ", "_")
        if "error" in lowered or "failed" in lowered:
            return text[:120]
        return None
