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

        # 缓存模型类别名映射
        self._class_names: dict[int, str] = self._model.names
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

        if not results or len(results[0].boxes) == 0:
            return []

        detections = []
        for box in results[0].boxes:
            cls_id = int(box.cls[0])
            cls_name = "person" if cls_id == 0 else self._class_names.get(cls_id, str(cls_id))
            conf = float(box.conf[0])

            if cls_name not in self._target_classes:
                continue

            # 提取 bbox (x1,y1,x2,y2)
            xyxy = box.xyxy[0].tolist()
            bbox = (int(xyxy[0]), int(xyxy[1]), int(xyxy[2]), int(xyxy[3]))

            # 提取 YOLO 分配的稳定 track_id（无则 -1）
            track_id = int(box.id[0]) if box.id is not None else -1

            detections.append(DetectionResult(
                label=cls_name,
                confidence=conf,
                bbox=bbox,
                track_id=track_id,
            ))

        return detections


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

        # 兼容路径状态（仅当 auto_track_service 未启用时使用）
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
        self._frame_process_timeout_s = max(1.0, float(settings.AI_FRAME_PROCESS_TIMEOUT_SECONDS))
        self._max_frame_age_s = max(0.05, float(settings.AI_MAX_FRAME_AGE_SECONDS))
        self._event_send_timeout_s = max(0.005, float(settings.AI_EVENT_SEND_TIMEOUT_SECONDS))
        self._last_frame_started_at = 0.0
        self._last_frame_completed_at = 0.0
        self._last_frame_timeout_reason: str | None = None
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
        self._last_pose_overlay_broadcast = 0.0
        self._pose_status = "disabled"
        self._pose_detector: UltralyticsPoseDetector | None = None
        self._pose_event_engine: PoseEventEngine | None = None
        # 姿态模型同时提供可靠的人体框。当安全帽检测模型漏掉 person 时，
        # 缓存最近一批姿态框，供两次姿态推理之间的检测帧兜底使用。
        self._latest_pose_observations: list[PoseObservation] = []
        self._latest_pose_observations_at: float = 0.0
        self._pose_person_grace_seconds: float = 0.8
        self._parallel_inference_enabled = bool(settings.AI_PARALLEL_INFERENCE_ENABLED)
        self._detector_warmed_up = False
        self._pose_warmed_up = False
        self._startup_status = "waiting"
        self._startup_detail = (
            f"等待 RTSP 连接：rtsp={self._current_rtsp_url}，fps={settings.AI_FPS}，"
            f"分辨率={self._frame_width}x{self._frame_height}"
        )

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
        return {
            "status": self._startup_status,
            "detail": f"{self._startup_detail}，pose={self._pose_status}",
        }

    async def start(self, stop_event: asyncio.Event) -> None:
        ai_logger.info(
            "AI Worker 已启动：fps={}，分辨率={}x{}，rtsp_sources={}，pose={}，"
            "patrol_skip={}，pose_skip={}，parallel_inference={}",
            settings.AI_FPS,
            self._frame_width,
            self._frame_height,
            self._rtsp_urls,
            self._pose_status,
            self._patrol_skip,
            settings.POSE_FRAME_SKIP,
            self._parallel_inference_enabled,
        )
        retry_delay = max(0.5, settings.AI_FFMPEG_RETRY_MIN_SECONDS)
        max_retry_delay = max(retry_delay, settings.AI_FFMPEG_RETRY_MAX_SECONDS)
        reset_threshold = 10.0

        while not stop_event.is_set():
            await self._update_current_task_id()
            if not self._is_mission_active():
                self._reset_detection_state()
                await asyncio.sleep(0.5)
                continue

            loop_start = asyncio.get_event_loop().time()
            try:
                await self._run_ffmpeg_loop(stop_event)
            except asyncio.CancelledError:
                break
            except AIWorkerFrameTimeout as exc:
                ai_logger.critical("AI 单帧处理超时：{}", exc)
                if settings.AI_EXIT_ON_FRAME_TIMEOUT:
                    ai_logger.critical(
                        "AI 推理线程可能已卡死，后端将退出并交给 systemd 自动重启"
                    )
                    os._exit(75)
            except Exception as exc:  # noqa: BLE001
                ai_logger.exception("AI Worker 运行异常：{}", exc)

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

    async def _run_ffmpeg_loop(self, stop_event: asyncio.Event) -> None:
        process = await self._start_ffmpeg()
        if process.stdout is None:
            raise AIWorkerError("FFmpeg stdout 未初始化")
        stderr_task = asyncio.create_task(self._drain_stderr(process))

        frame_queue: asyncio.Queue[_AIFrame] = asyncio.Queue(maxsize=1)

        async def reader_task() -> None:
            frame_index = 0
            try:
                while not stop_event.is_set():
                    frame = await process.stdout.readexactly(self._frame_size)
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
                        _AIFrame(data=frame, index=frame_index, read_at=time.monotonic()),
                    )
            except asyncio.IncompleteReadError:
                if self._ffmpeg_last_exit_reason == "unknown":
                    self._ffmpeg_last_exit_reason = "stdout_closed"

        reader = asyncio.create_task(reader_task())
        mission_watchdog = asyncio.create_task(
            self._stop_ffmpeg_when_mission_inactive(process, stop_event)
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

                frame_age_s = time.monotonic() - ai_frame.read_at
                self._last_frame_age_ms = round(frame_age_s * 1000, 1)
                if frame_age_s > self._max_frame_age_s:
                    self._stale_frames_dropped += 1
                    self._queued_frames_dropped += 1
                    continue

                skip = self._get_frame_skip()
                if skip > 1 and (ai_frame.index % skip) != 0:
                    continue

                await self._process_frame_with_timeout(
                    ai_frame.data,
                    ai_frame.index,
                    frame_read_at=ai_frame.read_at,
                )
        finally:
            mission_watchdog.cancel()
            stderr_task.cancel()
            reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await mission_watchdog
            with contextlib.suppress(asyncio.CancelledError):
                await reader
            with contextlib.suppress(asyncio.CancelledError):  # CancelledError 不是 Exception，须单独捕获
                await stderr_task

            await self._terminate_ffmpeg_process(process, reason="loop_stopped")
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
                self._detect_and_process_frame(frame, frame_index),
                timeout=self._frame_process_timeout_s,
            )
        except asyncio.TimeoutError as exc:
            reason = (
                f"frame_index={frame_index} timeout={self._frame_process_timeout_s:.1f}s "
                f"frames_processed={self._frames_processed}"
            )
            self._last_frame_timeout_reason = reason
            self._ffmpeg_last_exit_reason = f"AI_Frame_Process_Timeout({reason})"
            await self._notify_auto_track_video_lost(self._ffmpeg_last_exit_reason)
            video_logger.error(
                "AI 单帧处理超时，准备恢复：{}。"
                "若卡在 YOLO/TensorRT/CUDA 推理线程，当前进程需要重启才能释放底层状态。",
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

    async def _detect_and_process_frame(self, frame: bytes, frame_index: int) -> None:
        pose_due = (
            self._pose_detector is not None
            and self._pose_event_engine is not None
            and frame_index % max(1, int(settings.POSE_FRAME_SKIP)) == 0
        )
        # TensorRT engine 的第一次 predict() 会惰性创建执行上下文。先分别顺序预热，
        # 后续才允许两个独立 engine 并发，避免 CUDA 初始化竞争。
        run_parallel = (
            pose_due
            and self._parallel_inference_enabled
            and self._detector_warmed_up
            and self._pose_warmed_up
        )
        pose_task: asyncio.Task[tuple[list, float, float]] | None = None
        pose_task_consumed = False
        if run_parallel:
            pose_task = asyncio.create_task(self._infer_pose(frame))

        # 调用 detect_many 返回所有候选结果。
        t_start = time.monotonic()
        try:
            if hasattr(self._detector, 'detect_many'):
                detections = await asyncio.to_thread(self._detector.detect_many, frame)
            else:
                # _SimulatedDetector/_NullDetector 回退到 detect() 兼容
                single = await asyncio.to_thread(self._detector.detect, frame)
                detections = [single] if single else []
            t_detect_end = time.monotonic()
            self._last_detect_ms = round((t_detect_end - t_start) * 1000, 1)
            self._detector_warmed_up = True

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
                    now=pose_started_at,
                )
                if observations:
                    self._latest_pose_observations = observations
                    self._latest_pose_observations_at = time.monotonic()
                elif (
                    time.monotonic() - self._latest_pose_observations_at
                    > self._pose_person_grace_seconds
                ):
                    self._latest_pose_observations = []
                self._pose_frames_processed += 1
                self._pose_events_count += len(pose_events)
                await self._process_pose_events(pose_events, frame)
                await self._broadcast_pose_overlay(observations, detections)
            else:
                self._last_pose_ms = 0.0

            detections = self._merge_pose_person_fallback(
                detections,
                self._latest_pose_observations,
            )
            await self._process_detection(detections, frame, t_start, t_detect_end)

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
                )
                for observation in observations
            ],
        ]

    async def _infer_pose(self, frame: bytes) -> tuple[list, float, float]:
        if self._pose_detector is None:
            return [], time.monotonic(), 0.0
        pose_started_at = time.monotonic()
        raw_poses = await asyncio.to_thread(self._pose_detector.detect, frame)
        pose_ms = round((time.monotonic() - pose_started_at) * 1000, 1)
        return raw_poses, pose_started_at, pose_ms

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
            "-use_wallclock_as_timestamps", "1",
            "-stimeout", "5000000",
            "-hwaccel", "auto",
            "-i", self._current_rtsp_url,
            "-an",
            "-sn",
            "-dn",
            "-vf", f"fps={settings.AI_FPS},scale={self._frame_width}:{self._frame_height}:flags=fast_bilinear",
            "-f", "image2pipe",
            "-vcodec", "rawvideo",
            "-pix_fmt", "bgr24",
            "-",
        ]

        self._ffmpeg_last_exit_reason = "unknown"
        self._stream_restored_logged = False

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

                reason = self._classify_ffmpeg_failure_reason(text)
                if reason is None:
                    continue

                self._ffmpeg_last_exit_reason = reason
                if not self._ffmpeg_stream_unavailable:
                    self._ffmpeg_stream_unavailable = True
                    self._ffmpeg_unavailable_reason = reason
                    await self._notify_auto_track_video_lost(reason)
                    video_logger.warning(
                        "RTSP 流不可用，AI 识别暂时降级：rtsp={}，原因={}，3.0 秒后重试",
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
    def _classify_ffmpeg_failure_reason(text: str) -> Optional[str]:
        lowered = text.lower()
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
