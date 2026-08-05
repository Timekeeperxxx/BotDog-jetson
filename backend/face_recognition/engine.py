from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

import numpy as np


class FaceEngineError(RuntimeError):
    """可向 API 转换为明确 4xx/503 的人脸处理错误。"""


@dataclass(frozen=True)
class FaceExtraction:
    embedding: np.ndarray
    bbox: tuple[int, int, int, int]
    detection_score: float
    quality: float


class FaceRecognitionEngine:
    """OpenCV DNN YuNet 检测 + SFace 对齐和特征提取。"""

    model_name = "OpenCV SFace"
    model_version = "2021dec"

    def __init__(
        self,
        detect_model_path: str,
        recognition_model_path: str,
        *,
        detect_threshold: float = 0.85,
        min_face_size: int = 64,
    ) -> None:
        self.detect_model_path = Path(detect_model_path)
        self.recognition_model_path = Path(recognition_model_path)
        self.detect_threshold = float(detect_threshold)
        self.min_face_size = max(1, int(min_face_size))
        self._detector: Any | None = None
        self._recognizer: Any | None = None
        self._cv2: Any | None = None
        self._lock = RLock()

    @property
    def loaded(self) -> bool:
        return self._detector is not None and self._recognizer is not None

    def load(self) -> None:
        with self._lock:
            if self.loaded:
                return
            if not self.detect_model_path.is_file():
                raise FaceEngineError(f"YuNet 模型不存在: {self.detect_model_path}")
            if not self.recognition_model_path.is_file():
                raise FaceEngineError(f"SFace 模型不存在: {self.recognition_model_path}")
            try:
                import cv2
            except ImportError as exc:
                raise FaceEngineError("缺少 OpenCV，无法加载人脸模型") from exc
            if not hasattr(cv2, "FaceDetectorYN_create") or not hasattr(cv2, "FaceRecognizerSF_create"):
                raise FaceEngineError("当前 OpenCV 不包含 YuNet/SFace API")
            try:
                detector = cv2.FaceDetectorYN_create(
                    str(self.detect_model_path),
                    "",
                    (320, 320),
                    self.detect_threshold,
                    0.3,
                    5000,
                )
                recognizer = cv2.FaceRecognizerSF_create(
                    str(self.recognition_model_path),
                    "",
                )
            except Exception as exc:  # OpenCV raises cv2.error
                raise FaceEngineError(f"加载人脸模型失败: {exc}") from exc
            self._cv2 = cv2
            self._detector = detector
            self._recognizer = recognizer

    def decode_image(self, image_bytes: bytes) -> np.ndarray:
        self.load()
        assert self._cv2 is not None
        encoded = np.frombuffer(image_bytes, dtype=np.uint8)
        image = self._cv2.imdecode(encoded, self._cv2.IMREAD_COLOR)
        if image is None or image.ndim != 3 or image.shape[2] != 3:
            raise FaceEngineError("图片无法解码，请上传 JPEG、PNG 或 WebP")
        return image

    def detect(
        self,
        image: np.ndarray,
        *,
        score_threshold: float | None = None,
    ) -> list[np.ndarray]:
        self.load()
        if image.ndim != 3 or image.shape[2] != 3:
            raise FaceEngineError("人脸识别需要 BGR 三通道图像")
        height, width = image.shape[:2]
        if height <= 0 or width <= 0:
            return []
        assert self._detector is not None
        threshold = self.detect_threshold if score_threshold is None else float(score_threshold)
        with self._lock:
            self._detector.setInputSize((width, height))
            self._detector.setScoreThreshold(threshold)
            try:
                _, faces = self._detector.detect(image)
            finally:
                # 同一个 detector 也服务实时视频，注册阶段的宽松阈值不能泄漏过去。
                if threshold != self.detect_threshold:
                    self._detector.setScoreThreshold(self.detect_threshold)
        if faces is None:
            return []
        return [np.asarray(face, dtype=np.float32) for face in faces]

    @staticmethod
    def face_bbox(face: np.ndarray) -> tuple[int, int, int, int]:
        x, y, width, height = (float(value) for value in face[:4])
        return (
            max(0, int(round(x))),
            max(0, int(round(y))),
            max(0, int(round(x + width))),
            max(0, int(round(y + height))),
        )

    def extract_from_face(self, image: np.ndarray, face: np.ndarray) -> FaceExtraction:
        self.load()
        bbox = self.face_bbox(face)
        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]
        if min(width, height) < self.min_face_size:
            raise FaceEngineError(
                f"人脸尺寸过小，最小边长需达到 {self.min_face_size}px"
            )
        assert self._recognizer is not None
        with self._lock:
            try:
                aligned = self._recognizer.alignCrop(image, face)
                feature = self._recognizer.feature(aligned)
            except Exception as exc:
                raise FaceEngineError(f"人脸对齐或特征提取失败: {exc}") from exc
        embedding = np.asarray(feature, dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(embedding))
        if not np.isfinite(norm) or norm <= 1e-8:
            raise FaceEngineError("人脸特征无效")
        embedding = np.ascontiguousarray(embedding / norm, dtype=np.float32)
        score = float(face[-1]) if face.size >= 15 else 0.0
        image_area = max(1, int(image.shape[0]) * int(image.shape[1]))
        face_area_ratio = max(0, width) * max(0, height) / image_area
        quality = min(1.0, max(0.0, score) * min(1.0, face_area_ratio / 0.12))
        return FaceExtraction(
            embedding=embedding,
            bbox=bbox,
            detection_score=score,
            quality=float(quality),
        )

    def extract_exactly_one(
        self,
        image: np.ndarray,
        *,
        detect_threshold: float | None = None,
    ) -> FaceExtraction:
        faces = self.detect(image, score_threshold=detect_threshold)
        if not faces:
            raise FaceEngineError("未检测到人脸")
        if len(faces) != 1:
            raise FaceEngineError(f"注册图片必须且只能包含一张人脸，当前检测到 {len(faces)} 张")
        return self.extract_from_face(image, faces[0])
