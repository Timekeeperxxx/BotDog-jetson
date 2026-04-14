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
import random
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .logging_config import logger
from .models import InspectionTask
from .alert_service import get_alert_service
from .state_machine import SystemState
from .ws_event_broadcaster import get_event_broadcaster
from .schemas import utc_now_iso
from .tracking_types import DetectionResult as TrackDetectionResult


class AIWorkerError(RuntimeError):
    """AI Worker 运行时错误。"""


@dataclass
class DetectionResult:
    """AIWorker 内部检测结果（兼容老路径用）。"""
    label: str
    confidence: float
    bbox: Optional[tuple[int, int, int, int]] = None
    track_id: int = -1  # YOLO ByteTrack 分配的跨帧 ID


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
            logger.warning("AI 模型未加载，当前仅支持模拟检测 (AI_SIMULATE_DETECTION)")
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
    ) -> None:
        import numpy as np  # noqa: F811
        self._np = np
        self._frame_width = frame_width
        self._frame_height = frame_height
        self._confidence = confidence
        self._target_classes = set(target_classes)

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

        logger.info("YOLO 加载模型: %s, 设备: %s", model_path, resolved_device)
        self._model = YOLO(model_path, task='detect')
        # self._model.to(resolved_device)
        self._device = resolved_device

        # 缓存模型类别名映射
        self._class_names: dict[int, str] = self._model.names
        logger.info("YOLO 模型已就绪，类别数: %d, 目标: %s", len(self._class_names), target_classes)

    def detect(self, frame_bytes: bytes) -> Optional[DetectionResult]:
        """返回置信度最高的单个目标（兼容老路径）。"""
        results = self.detect_many(frame_bytes)
        return results[0] if results else None

    def detect_many(self, frame_bytes: bytes) -> list[DetectionResult]:
        """返回所有目标类别的检测结果列表，使用 ByteTrack 提供稳定 track_id。"""
        frame = self._np.frombuffer(frame_bytes, dtype=self._np.uint8)
        frame = frame.reshape((self._frame_height, self._frame_width, 3))

        # 使用 YOLO 内置 ByteTrack，persist=True 保证跨帧 ID 稳定
        try:
            results = self._model.track(
                frame,
                conf=self._confidence,
                persist=True,
                tracker="bytetrack.yaml",
                verbose=False,
            )
        except Exception as exc:
            # tracker 不可用时降级到 predict
            logger.warning("[YoloDetector] track() 失败，降级到 predict(): %s", exc)
            results = self._model.predict(frame, conf=self._confidence, verbose=False)

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


class AIWorker:
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
        self._suspect_skip = max(1, settings.AI_SUSPECT_SKIP)
        self._stable_hits = max(1, settings.AI_STABLE_HITS)
        self._reset_misses = max(1, settings.AI_RESET_MISSES)
        self._cooldown_seconds = max(0.0, settings.AI_COOLDOWN_SECONDS)

        self._current_task_id: Optional[int] = None
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

        if settings.AI_SIMULATE_DETECTION:
            self._detector: _BaseDetector = _SimulatedDetector(settings.AI_SIMULATE_PROB)
        else:
            try:
                self._detector = _YoloDetector(
                    model_path=settings.AI_MODEL_PATH,
                    device=settings.AI_DEVICE,
                    confidence=settings.AI_CONFIDENCE_THRESHOLD,
                    target_classes=settings.AI_TARGET_CLASSES,
                    frame_width=self._frame_width,
                    frame_height=self._frame_height,
                )
            except Exception as exc:
                import traceback
                logger.warning(f"YOLO 模型加载失败，回退到 NullDetector: {exc}\n{traceback.format_exc()}")
                self._detector = _NullDetector()

    async def start(self, stop_event: asyncio.Event) -> None:
        logger.info("AI Worker 已启动")
        retry_delay = 1.0
        max_retry_delay = 3.0   # 缩短最大重试间隔，RTSP 流恢复后最多 3 秒内重连
        reset_threshold = 10.0

        while not stop_event.is_set():
            loop_start = asyncio.get_event_loop().time()
            try:
                await self._run_ffmpeg_loop(stop_event)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.exception("AI Worker 异常: %s", exc)

            if stop_event.is_set():
                break

            ran_seconds = asyncio.get_event_loop().time() - loop_start
            if ran_seconds >= reset_threshold:
                retry_delay = 1.0
            else:
                retry_delay = min(retry_delay * 2, max_retry_delay)

            logger.warning("AI Worker 重连等待 {:.1f}s", retry_delay)
            await asyncio.sleep(retry_delay)

        logger.info("AI Worker 已停止")

    async def _run_ffmpeg_loop(self, stop_event: asyncio.Event) -> None:
        process = await self._start_ffmpeg()
        if process.stdout is None:
            raise AIWorkerError("FFmpeg stdout 未初始化")
        stderr_task = asyncio.create_task(self._drain_stderr(process))

        frame_queue = asyncio.Queue(maxsize=1)

        async def reader_task() -> None:
            frame_index = 0
            try:
                while not stop_event.is_set():
                    frame = await process.stdout.readexactly(self._frame_size)
                    frame_index += 1
                    # 保持队列里始终只有一帧最新鲜的首帧，丢弃堆积的旧帧避免延迟累加
                    if frame_queue.full():
                        try:
                            frame_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                    await frame_queue.put((frame, frame_index))
            except asyncio.IncompleteReadError:
                logger.warning("AI Worker: FFmpeg 输出中断，准备重启")
                # stop_event.set()
        
        reader = asyncio.create_task(reader_task())

        try:
            while not stop_event.is_set():
                try:
                    # 使用 timeout 定期唤醒检测 stop_event
                    frame, frame_index = await asyncio.wait_for(frame_queue.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    if reader.done():
                        logger.warning("AI Worker: FFmpeg 进程已中断，跳出读取循环准备重连...")
                        break
                    continue

                await self._update_current_task_id()

                if not self._is_mission_active():
                    self._reset_detection_state()
                    continue

                skip = self._suspect_skip if self._is_suspect_mode() else self._patrol_skip
                if skip > 1 and (frame_index % skip) != 0:
                    continue

                # 调用 detect_many 返回所有候选结果
                t_start = time.monotonic()
                if hasattr(self._detector, 'detect_many'):
                    detections = await asyncio.to_thread(self._detector.detect_many, frame)
                else:
                    # _SimulatedDetector/_NullDetector 回退到 detect() 兼容
                    single = await asyncio.to_thread(self._detector.detect, frame)
                    detections = [single] if single else []
                t_detect_end = time.monotonic()

                await self._process_detection(detections, frame, t_start, t_detect_end)
                self._frames_processed += 1
                if detections:
                    self._detections_count += 1
                await self._maybe_broadcast_status()
        finally:
            stderr_task.cancel()
            reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):  # CancelledError 不是 Exception，须单独捕获
                await stderr_task
                await reader

            with contextlib.suppress(ProcessLookupError, OSError):
                process.terminate()
            with contextlib.suppress(Exception):
                await process.wait()

    async def _start_ffmpeg(self) -> asyncio.subprocess.Process:
        command = [
            "ffmpeg",
            "-rtsp_transport", "tcp",       # 用 TCP 代替 UDP，避免丢包导致 H.264 解码花屏
            "-hwaccel", "auto",
            "-i", settings.AI_RTSP_URL,
            "-fflags", "+discardcorrupt",   # 解码失败的帧直接丢弃，不输出马赛克帧
            "-vf", f"scale={self._frame_width}:{self._frame_height}",
            "-f", "image2pipe",
            "-vcodec", "rawvideo",
            "-pix_fmt", "bgr24",
            "-r", str(settings.AI_FPS),
            "-",
        ]

        logger.info(
            "AI Worker 启动 FFmpeg: rtsp={} fps={} size={}x{}",
            settings.AI_RTSP_URL,
            settings.AI_FPS,
            self._frame_width,
            self._frame_height,
        )

        return await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
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
                # 过滤掉高频进度行（frame= fps= 开头的），只保留有意义的信息
                if text.startswith("frame=") or text.startswith("size="):
                    continue
                # 错误和警告优先输出
                if "error" in text.lower() or "failed" in text.lower() or "connection" in text.lower():
                    logger.warning("[FFmpeg] {}", text)
                else:
                    logger.debug("[FFmpeg] {}", text)

    async def _update_current_task_id(self) -> None:
        current_time = asyncio.get_event_loop().time()
        if current_time - self._last_task_check_time < 1.0:
            return

        self._last_task_check_time = current_time

        async with self._session_factory() as session:
            task = await _get_latest_running_task(session)
            self._current_task_id = task.task_id if task else None

    def _is_mission_active(self) -> bool:
        # 移除对 self._state_machine.state == SystemState.IN_MISSION 的强依赖
        # 只要存在运行中的任务，且 RTSP 摄像头推流正常，AI 就会开始分析画面（即使底盘由于离线处于 DISCONNECTED）
        # 底盘失联时的移动指令丢弃由 ControlService 的 can_accept_control 代理把关。
        return self._current_task_id is not None

    def _is_suspect_mode(self) -> bool:
        # 兼容路径：旧状态判断
        if self._hits > 0 or self._in_alert:
            return True
        # AutoTrackService 路径：有活跃目标或候选目标时切高帧率
        from .auto_track_service import get_auto_track_service
        auto_track = get_auto_track_service()
        
        from .guard_mission_service import get_guard_mission_service
        guard_mission = get_guard_mission_service()
        
        if guard_mission is not None and guard_mission.enabled:
            # 如果驱离模式启用了，且目前并不是 STANDBY 或者处于刚确认入侵，这期间不应该是 patrol 降频，应提供更多的帧以稳定验证
            from .guard_mission_types import GuardMissionState
            if guard_mission.state != GuardMissionState.STANDBY or guard_mission._intrusion_counter > 0:
                return True
                
        if auto_track is not None and auto_track._enabled:
            return (
                auto_track._active_target is not None
                or len(auto_track._candidates) > 0
            )
        return False

    def _reset_detection_state(self) -> None:
        self._hits = 0
        self._misses = 0
        self._in_alert = False

    async def _process_detection(
        self,
        detections: list[DetectionResult],
        frame: bytes,
        t_start: float = 0.0,
        t_detect_end: float = 0.0,
    ) -> None:
        """
        处理检测结果。

        优先路径：将结果交给 AutoTrackService 处理（包含状态机、控制命令、抓拍）。
        兼容路径：若 AutoTrackService 未启用，回退到原有「检测即告警」逻辑。
        """
        from .auto_track_service import get_auto_track_service
        auto_track = get_auto_track_service()
        
        from .guard_mission_service import get_guard_mission_service
        guard_mission = get_guard_mission_service()

        # 计算实际的等效帧率
        skip = self._suspect_skip if self._is_suspect_mode() else self._patrol_skip
        effective_fps = settings.AI_FPS / skip if skip > 0 else settings.AI_FPS

        if guard_mission is not None and guard_mission.enabled:
            # ── 新增路径：交给 GuardMissionService ─────────────
            track_detections = [
                TrackDetectionResult(
                    bbox=d.bbox or (0, 0, 1, 1),
                    confidence=d.confidence,
                    class_name=d.label,
                    track_id=getattr(d, 'track_id', -1),
                )
                for d in detections
                if d.bbox is not None
            ]
            guard_mission.update_effective_fps(effective_fps)
            await guard_mission.process_frame(track_detections, frame)
            return
            
        elif auto_track is not None and auto_track._enabled:
            # ── 优先路径：交给 AutoTrackService，传递 YOLO track_id + 计时 ─
            track_detections = [
                TrackDetectionResult(
                    bbox=d.bbox or (0, 0, 1, 1),
                    confidence=d.confidence,
                    class_name=d.label,
                    track_id=getattr(d, 'track_id', -1),
                )
                for d in detections
                if d.bbox is not None
            ]
            await auto_track.process_frame(
                detections=track_detections,
                frame=frame,
                frame_index=self._frames_processed,
                current_task_id=self._current_task_id,
                t_start=t_start,
                t_detect_end=t_detect_end,
            )
            return

        # ── 兼容路径：原有「检测即告警」逻辑 ──────────────────────────────
        detection = detections[0] if detections else None

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

        # YOLO 类别 → 中文显示名映射
        _label_zh: dict[str, str] = {
            "person": "陌生人",
            "car": "车辆",
            "dog": "动物",
            "cat": "动物",
            "fire": "火焰",
        }
        label_zh = _label_zh.get(detection.label, detection.label)

        alert_service = get_alert_service()

        async with self._session_factory() as session:
            await alert_service.handle_ai_event(
                event_type="AI_DETECTION",
                event_code=f"E_AI_{detection.label.upper()}",
                severity="CRITICAL",
                message=f"检测到目标: {label_zh}",
                confidence=detection.confidence,
                file_path=str(image_path),
                image_url=image_url,
                gps_lat=gps[0],
                gps_lon=gps[1],
                task_id=self._current_task_id,
                session=session,
            )

    async def _save_snapshot(self, frame: bytes) -> tuple[Path, str]:
        try:
            import numpy as np
            from PIL import Image
        except ImportError as exc:  # noqa: BLE001
            logger.error("缺少图像依赖，无法抓拍: %s", exc)
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
                },
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
            logger.debug("AI 状态广播失败: %s", exc)


async def _get_latest_running_task(session: AsyncSession) -> Optional[InspectionTask]:
    stmt = (
        select(InspectionTask)
        .where(InspectionTask.status == "running")
        .order_by(InspectionTask.started_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()
