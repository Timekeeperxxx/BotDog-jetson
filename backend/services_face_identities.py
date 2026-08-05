from __future__ import annotations

import asyncio
from io import BytesIO
from typing import Any

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .config import settings
from .face_recognition.engine import FaceEngineError, FaceExtraction, FaceRecognitionEngine
from .face_recognition.matcher import FaceMatcher, FaceTemplateRecord
from .face_recognition.runtime import FaceRecognitionRuntime
from .logging_config import get_logger
from .models import FaceIdentity, FaceTemplate
from .schemas import utc_now_iso

face_logger = get_logger("人脸识别")

_ENROLL_MAX_EDGE_PX = 1920


class FaceIdentityService:
    """人员库与实时识别共享服务；模板矩阵更新为进程内原子替换。"""

    def __init__(self) -> None:
        self.engine = FaceRecognitionEngine(
            settings.FACE_DETECT_MODEL_PATH,
            settings.FACE_RECOGNITION_MODEL_PATH,
            detect_threshold=settings.FACE_DETECT_THRESHOLD,
            min_face_size=settings.FACE_MIN_SIZE_PX,
        )
        self.matcher = FaceMatcher(settings.FACE_MATCH_THRESHOLD)
        self.runtime = FaceRecognitionRuntime(
            self.engine,
            self.matcher,
            frame_skip=settings.FACE_FRAME_SKIP,
            confirm_hits=settings.FACE_CONFIRM_HITS,
            track_ttl_seconds=settings.FACE_TRACK_TTL_SECONDS,
            enabled=settings.FACE_RECOGNITION_ENABLED,
        )
        self._initialize_lock = asyncio.Lock()
        self._initialized = False
        self._available = False
        self._error: str | None = None
        self._last_reload_at: str | None = None

    async def ensure_initialized(self, session_factory: Any) -> None:
        if self._initialized:
            return
        async with self._initialize_lock:
            if self._initialized:
                return
            self._initialized = True
            if not settings.FACE_RECOGNITION_ENABLED:
                self._error = "FACE_RECOGNITION_ENABLED=false"
                return
            try:
                await asyncio.to_thread(self.engine.load)
                async with session_factory() as session:
                    await self.reload(session)
            except Exception as exc:  # model absence must not stop AI worker
                self._available = False
                self._error = str(exc)
                face_logger.warning("人脸识别不可用，视频主链路继续运行：{}", exc)
            else:
                self._available = True
                self._error = None
                face_logger.info(
                    "人脸识别已就绪：identities={} templates={} threshold={}",
                    self.matcher.identity_count,
                    self.matcher.template_count,
                    self.matcher.threshold,
                )

    async def reload(self, session: AsyncSession) -> None:
        result = await session.execute(
            select(FaceTemplate, FaceIdentity)
            .join(FaceIdentity, FaceIdentity.id == FaceTemplate.identity_id)
            .where(FaceIdentity.enabled == 1)
            .order_by(FaceTemplate.id)
        )
        records: list[FaceTemplateRecord] = []
        for template, identity in result.all():
            vector = np.frombuffer(template.embedding, dtype=np.float32)
            if vector.size != template.dimension:
                face_logger.warning(
                    "忽略维度异常的人脸模板：template_id={} expected={} actual={}",
                    template.id,
                    template.dimension,
                    vector.size,
                )
                continue
            records.append(
                FaceTemplateRecord(
                    template_id=template.id,
                    identity_id=identity.id,
                    display_name=identity.display_name,
                    embedding=vector.copy(),
                )
            )
        self.matcher.replace(records)
        self.runtime.clear()
        self._last_reload_at = utc_now_iso()

    async def list_identities(self, session: AsyncSession) -> list[FaceIdentity]:
        result = await session.execute(
            select(FaceIdentity)
            .options(selectinload(FaceIdentity.templates))
            .order_by(FaceIdentity.display_name, FaceIdentity.id)
        )
        return list(result.scalars().unique().all())

    async def get_identity(self, session: AsyncSession, identity_id: int) -> FaceIdentity | None:
        result = await session.execute(
            select(FaceIdentity)
            .options(selectinload(FaceIdentity.templates))
            .where(FaceIdentity.id == identity_id)
        )
        return result.scalar_one_or_none()

    def extract_template(self, image_bytes: bytes) -> FaceExtraction:
        if not self.engine.loaded:
            raise FaceEngineError(self._error or "人脸模型尚未加载")
        try:
            with Image.open(BytesIO(image_bytes)) as image:
                width, height = image.size
                image_format = (image.format or "").upper()
                if image_format not in {"JPEG", "PNG", "WEBP"}:
                    raise FaceEngineError("仅支持 JPEG、PNG 或 WebP 图片")
                if width <= 0 or height <= 0 or width * height > settings.FACE_MAX_IMAGE_PIXELS:
                    raise FaceEngineError(
                        f"图片像素数不得超过 {settings.FACE_MAX_IMAGE_PIXELS}"
                    )

                # 浏览器会展示 EXIF 修正后的方向，而 OpenCV imdecode 不会；注册前统一
                # 转正，避免手机自拍肉眼正常、模型实际收到横向像素。
                normalized = ImageOps.exif_transpose(image).convert("RGB")
                if max(normalized.size) > _ENROLL_MAX_EDGE_PX:
                    normalized.thumbnail(
                        (_ENROLL_MAX_EDGE_PX, _ENROLL_MAX_EDGE_PX),
                        Image.Resampling.LANCZOS,
                    )
                image_rgb = np.asarray(normalized, dtype=np.uint8)
        except (UnidentifiedImageError, OSError) as exc:
            raise FaceEngineError("图片无法解码，请上传 JPEG、PNG 或 WebP") from exc
        image_bgr = np.ascontiguousarray(image_rgb[:, :, ::-1])

        # 无/错误 EXIF 的照片也常见。仅在注册阶段尝试四个方向和更宽松阈值，
        # 实时视频仍使用 FACE_DETECT_THRESHOLD，避免增加误检。
        thresholds = [settings.FACE_DETECT_THRESHOLD]
        enroll_threshold = min(
            settings.FACE_DETECT_THRESHOLD,
            settings.FACE_ENROLL_DETECT_THRESHOLD,
        )
        if enroll_threshold != thresholds[0]:
            thresholds.append(enroll_threshold)
        orientations = [
            image_bgr,
            np.ascontiguousarray(np.rot90(image_bgr, 1)),
            np.ascontiguousarray(np.rot90(image_bgr, 2)),
            np.ascontiguousarray(np.rot90(image_bgr, 3)),
        ]
        for threshold in thresholds:
            for candidate in orientations:
                try:
                    return self.engine.extract_exactly_one(
                        candidate,
                        detect_threshold=threshold,
                    )
                except FaceEngineError as exc:
                    if str(exc) != "未检测到人脸":
                        raise
        raise FaceEngineError(
            "未检测到人脸，请使用光线充足、无遮挡、脸部占画面较大的正脸照片"
        )

    async def annotate_frame(
        self,
        frame_bytes: bytes,
        detections: list[Any],
        frame_index: int,
        frame_width: int,
        frame_height: int,
    ) -> None:
        if not settings.FACE_RECOGNITION_ENABLED:
            for detection in detections:
                if getattr(detection, "label", "") == "person":
                    detection.face_status = "unavailable"
            return
        if not self._available:
            for detection in detections:
                if getattr(detection, "label", "") == "person":
                    detection.face_status = "unavailable"
            return
        frame = np.frombuffer(frame_bytes, dtype=np.uint8).reshape(
            (frame_height, frame_width, 3)
        )
        await asyncio.to_thread(self.runtime.process, frame, detections, frame_index)

    def status(self) -> dict[str, Any]:
        return {
            "enabled": bool(settings.FACE_RECOGNITION_ENABLED),
            "available": self._available,
            "engine_loaded": self.engine.loaded,
            "model_name": self.engine.model_name,
            "detect_model_path": str(self.engine.detect_model_path),
            "recognition_model_path": str(self.engine.recognition_model_path),
            "identity_count": self.matcher.identity_count,
            "template_count": self.matcher.template_count,
            "match_threshold": self.matcher.threshold,
            "last_reload_at": self._last_reload_at,
            "error": self._error,
        }


_face_identity_service = FaceIdentityService()


def get_face_identity_service() -> FaceIdentityService:
    return _face_identity_service
