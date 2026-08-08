"""Visible-camera weather classification with temporal stabilization.

The deployed baseline model predicts eleven visual weather phenomena.  The
product contract only exposes four classes: normal, rain, snow and sandstorm.
Labels outside the three adverse-weather classes are therefore treated as
normal until a site-specific four-class checkpoint replaces the baseline.
"""

from __future__ import annotations

import time
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Mapping, Protocol

from .logging_config import get_logger
from .schemas import utc_now_iso


weather_logger = get_logger("天气识别")

WEATHER_LABELS = ("normal", "rain", "snow", "sandstorm")
WEATHER_LABELS_ZH = {
    "unknown": "未知",
    "normal": "正常",
    "rain": "雨",
    "snow": "雪",
    "sandstorm": "沙尘",
}
RAW_TO_PRODUCT_LABEL = {
    "rain": "rain",
    "snow": "snow",
    "sandstorm": "sandstorm",
}


class WeatherClassifier(Protocol):
    device: str

    def predict(self, frame_bgr: bytes) -> Mapping[str, float]: ...


class HuggingFaceWeatherClassifier:
    """Local-only ViT inference adapter used by the Jetson deployment."""

    def __init__(
        self,
        *,
        model_path: str,
        frame_width: int,
        frame_height: int,
        device: str = "auto",
        use_fp16: bool = True,
    ) -> None:
        model_dir = Path(model_path).expanduser().resolve()
        required = (model_dir / "config.json", model_dir / "model.safetensors")
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"天气模型文件缺失：{', '.join(missing)}")

        try:
            import numpy as np
            import torch
            from PIL import Image
            from transformers import AutoImageProcessor, AutoModelForImageClassification
        except ImportError as exc:
            raise ImportError(
                "天气模型依赖缺失，请安装 transformers、safetensors、Pillow 和 torch"
            ) from exc

        if device == "auto":
            resolved_device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            resolved_device = device
        if resolved_device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError("WEATHER_DEVICE 要求 CUDA，但当前 torch.cuda 不可用")

        self._np = np
        self._torch = torch
        self._image_type = Image
        self._frame_width = max(1, int(frame_width))
        self._frame_height = max(1, int(frame_height))
        self._lock = Lock()
        self.device = resolved_device
        self._fp16 = bool(use_fp16 and resolved_device.startswith("cuda"))
        self._processor = AutoImageProcessor.from_pretrained(
            model_dir,
            local_files_only=True,
            use_fast=False,
        )
        self._model = AutoModelForImageClassification.from_pretrained(
            model_dir,
            local_files_only=True,
        ).to(resolved_device)
        if self._fp16:
            self._model.half()
        self._model.eval()
        self._id2label = {
            int(class_id): str(label).strip().lower()
            for class_id, label in self._model.config.id2label.items()
        }

    def predict(self, frame_bgr: bytes) -> Mapping[str, float]:
        expected_size = self._frame_width * self._frame_height * 3
        if len(frame_bgr) != expected_size:
            raise ValueError(
                f"天气模型帧大小错误：expected={expected_size}, actual={len(frame_bgr)}"
            )

        frame = self._np.frombuffer(frame_bgr, dtype=self._np.uint8).reshape(
            (self._frame_height, self._frame_width, 3)
        )
        # FFmpeg supplies BGR24; the Hugging Face processor expects RGB.
        image = self._image_type.fromarray(frame[:, :, ::-1].copy(), mode="RGB")

        with self._lock:
            inputs = self._processor(images=image, return_tensors="pt")
            prepared: dict[str, Any] = {}
            for key, value in inputs.items():
                tensor = value.to(self.device)
                if self._fp16 and tensor.is_floating_point():
                    tensor = tensor.half()
                prepared[key] = tensor
            with self._torch.inference_mode():
                logits = self._model(**prepared).logits
                probabilities = self._torch.softmax(logits.float(), dim=-1)[0]

        return {
            self._id2label.get(index, str(index)): float(probability)
            for index, probability in enumerate(probabilities.detach().cpu().tolist())
        }


@dataclass(frozen=True)
class _MappedObservation:
    label: str
    confidence: float
    raw_label: str
    raw_confidence: float
    probabilities: dict[str, float]


class WeatherDetectionService:
    """Maps raw model labels and applies a small majority-vote window."""

    def __init__(
        self,
        *,
        enabled: bool,
        classifier: WeatherClassifier | None = None,
        min_confidence: float = 0.55,
        smoothing_window: int = 5,
        stable_votes: int = 3,
        initialization_error: str | None = None,
    ) -> None:
        self.enabled = bool(enabled)
        self._classifier = classifier
        self._min_confidence = min(1.0, max(0.0, float(min_confidence)))
        self._window_size = max(1, int(smoothing_window))
        self._stable_votes = min(self._window_size, max(1, int(stable_votes)))
        self._history: deque[_MappedObservation] = deque(maxlen=self._window_size)
        self._lock = Lock()
        self._state = "disabled" if not self.enabled else "warming_up"
        self._detail = "WEATHER_ENABLED=false" if not self.enabled else "等待首批摄像头画面"
        self._label = "unknown"
        self._confidence = 0.0
        self._raw_label: str | None = None
        self._raw_confidence = 0.0
        self._probabilities = {label: 0.0 for label in WEATHER_LABELS}
        self._observed_at: str | None = None
        self._last_inference_ms = 0.0
        self._frames_processed = 0
        self._errors = 0
        self._last_error: str | None = initialization_error
        if self.enabled and (classifier is None or initialization_error):
            self._state = "failed"
            self._detail = initialization_error or "天气分类器未初始化"

    @classmethod
    def from_settings(cls, settings: Any) -> "WeatherDetectionService":
        if not bool(settings.WEATHER_ENABLED):
            return cls(enabled=False)
        try:
            classifier = HuggingFaceWeatherClassifier(
                model_path=settings.WEATHER_MODEL_PATH,
                frame_width=settings.AI_FRAME_WIDTH,
                frame_height=settings.AI_FRAME_HEIGHT,
                device=settings.WEATHER_DEVICE,
                use_fp16=settings.WEATHER_USE_FP16,
            )
        except Exception as exc:  # noqa: BLE001 - startup must degrade, not crash
            weather_logger.error("天气模型加载失败，天气支路已降级：{}", exc)
            return cls(enabled=True, initialization_error=str(exc))

        weather_logger.info(
            "天气模型已就绪：path={}，device={}，interval={}s，window={}，votes={}",
            settings.WEATHER_MODEL_PATH,
            classifier.device,
            settings.WEATHER_INTERVAL_SECONDS,
            settings.WEATHER_SMOOTHING_WINDOW,
            settings.WEATHER_STABLE_VOTES,
        )
        return cls(
            enabled=True,
            classifier=classifier,
            min_confidence=settings.WEATHER_CONFIDENCE_THRESHOLD,
            smoothing_window=settings.WEATHER_SMOOTHING_WINDOW,
            stable_votes=settings.WEATHER_STABLE_VOTES,
        )

    @property
    def available(self) -> bool:
        return self.enabled and self._classifier is not None and self._state != "failed"

    def process_frame(self, frame_bgr: bytes) -> dict[str, Any]:
        if not self.available or self._classifier is None:
            return self.get_status()

        started = time.perf_counter()
        try:
            raw_probabilities = self._classifier.predict(frame_bgr)
            observation = self._map_probabilities(raw_probabilities)
        except Exception as exc:  # noqa: BLE001 - keep the main AI worker alive
            with self._lock:
                self._errors += 1
                self._last_error = str(exc)
                self._state = "degraded"
                self._detail = f"最近一次天气推理失败：{exc}"
                self._last_inference_ms = round((time.perf_counter() - started) * 1000, 1)
            weather_logger.warning("天气推理失败，本帧已跳过：{}", exc)
            return self.get_status()

        with self._lock:
            self._history.append(observation)
            self._frames_processed += 1
            self._raw_label = observation.raw_label
            self._raw_confidence = observation.raw_confidence
            self._probabilities = observation.probabilities
            self._observed_at = utc_now_iso()
            self._last_inference_ms = round((time.perf_counter() - started) * 1000, 1)
            self._last_error = None

            votes = Counter(item.label for item in self._history)
            voted_label, vote_count = votes.most_common(1)[0]
            if vote_count >= self._stable_votes:
                supporting = [
                    item.confidence for item in self._history if item.label == voted_label
                ]
                self._label = voted_label
                self._confidence = sum(supporting) / max(1, len(supporting))
                self._state = "ready"
                self._detail = (
                    f"连续窗口判定完成：{vote_count}/{len(self._history)}，"
                    "当前仅使用可见光模型"
                )
            elif self._label == "unknown":
                self._state = "warming_up"
                self._detail = (
                    f"天气结果稳定中：已采样 {len(self._history)}，"
                    f"需要同类票数 {self._stable_votes}"
                )
            else:
                self._state = "ready"
                self._detail = "新天气尚未达到稳定票数，保持上一结果"

        return self.get_status()

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self.enabled,
                "state": self._state,
                "detail": self._detail,
                "label": self._label,
                "label_zh": WEATHER_LABELS_ZH.get(self._label, self._label),
                "confidence": round(self._confidence, 4),
                "raw_label": self._raw_label,
                "raw_confidence": round(self._raw_confidence, 4),
                "probabilities": {
                    key: round(value, 4) for key, value in self._probabilities.items()
                },
                "observed_at": self._observed_at,
                "inference_ms": self._last_inference_ms,
                "frames_processed": self._frames_processed,
                "smoothing_window": self._window_size,
                "stable_votes": self._stable_votes,
                "source": "visible_camera",
                "radar_fused": False,
                "last_error": self._last_error,
                "errors": self._errors,
            }

    def _map_probabilities(
        self,
        raw_probabilities: Mapping[str, float],
    ) -> _MappedObservation:
        cleaned = {
            str(label).strip().lower(): max(0.0, float(value))
            for label, value in raw_probabilities.items()
        }
        if not cleaned:
            raise ValueError("天气模型未返回任何类别概率")
        raw_label, raw_confidence = max(cleaned.items(), key=lambda item: item[1])
        mapped = RAW_TO_PRODUCT_LABEL.get(raw_label)
        if mapped is None or raw_confidence < self._min_confidence:
            mapped = "normal"

        target_probabilities = {
            "rain": cleaned.get("rain", 0.0),
            "snow": cleaned.get("snow", 0.0),
            "sandstorm": cleaned.get("sandstorm", 0.0),
        }
        target_sum = min(1.0, sum(target_probabilities.values()))
        product_probabilities = {
            "normal": max(0.0, 1.0 - target_sum),
            **target_probabilities,
        }
        confidence = (
            raw_confidence
            if mapped != "normal"
            else max(product_probabilities["normal"], raw_confidence)
        )
        return _MappedObservation(
            label=mapped,
            confidence=min(1.0, confidence),
            raw_label=raw_label,
            raw_confidence=min(1.0, raw_confidence),
            probabilities=product_probabilities,
        )


_weather_detection_service: WeatherDetectionService | None = None


def get_weather_detection_service() -> WeatherDetectionService | None:
    return _weather_detection_service


def set_weather_detection_service(service: WeatherDetectionService | None) -> None:
    global _weather_detection_service
    _weather_detection_service = service
