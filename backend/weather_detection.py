"""Visible-camera weather classification with temporal stabilization.

The deployed baseline model predicts eleven visual weather phenomena.  The
product contract only exposes four classes: normal, rain, snow and sandstorm.
Rime is grouped with snow. Low-confidence or unsupported observations remain
unknown. Results require time-spaced frames; changes require two valid rounds.
"""

from __future__ import annotations

import json
import math
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
    "unknown": "待确认",
    "normal": "正常",
    "rain": "雨",
    "snow": "雪",
    "sandstorm": "沙尘",
}
RAW_TO_PRODUCT_LABEL = {
    "normal": "normal",
    "rain": "rain",
    "snow": "snow",
    "rime": "snow",
    "sandstorm": "sandstorm",
}


class WeatherClassifier(Protocol):
    device: str

    def predict(self, frame_bgr: bytes) -> Mapping[str, float]: ...


class HuggingFaceWeatherClassifier:
    """Local-only ViT inference adapter used by the Jetson deployment."""

    runtime = "pytorch"

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


class TensorRTWeatherClassifier:
    """Fixed-shape TensorRT adapter for the deployed weather checkpoint."""

    runtime = "tensorrt_fp16"

    def __init__(
        self,
        *,
        model_path: str,
        frame_width: int,
        frame_height: int,
        device: str = "auto",
    ) -> None:
        engine_path = Path(model_path).expanduser().resolve()
        metadata_path = engine_path.with_suffix(".json")
        missing = [
            str(path) for path in (engine_path, metadata_path) if not path.is_file()
        ]
        if missing:
            raise FileNotFoundError(f"天气 TensorRT 文件缺失：{', '.join(missing)}")

        try:
            import numpy as np
            import tensorrt as trt
            import torch
            from PIL import Image
        except ImportError as exc:
            raise ImportError(
                "TensorRT 天气模型依赖缺失，请安装 Pillow、TensorRT 和 torch"
            ) from exc

        if device not in {"auto", "cuda", "cuda:0"}:
            raise RuntimeError("TensorRT 天气模型仅支持 WEATHER_DEVICE=auto/cuda/cuda:0")
        if not torch.cuda.is_available():
            raise RuntimeError("TensorRT 天气模型要求 CUDA，但当前 torch.cuda 不可用")

        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        labels = metadata.get("labels")
        input_shape = tuple(int(value) for value in metadata.get("input_shape", ()))
        resize = tuple(int(value) for value in metadata.get("resize", ()))
        mean = tuple(float(value) for value in metadata.get("image_mean", ()))
        std = tuple(float(value) for value in metadata.get("image_std", ()))
        resample = str(metadata.get("resample", "bilinear")).lower()
        if (
            not isinstance(labels, list)
            or input_shape != (1, 3, 224, 224)
            or resize != (224, 224)
            or len(mean) != 3
            or len(std) != 3
            or resample != "bilinear"
        ):
            raise ValueError(f"天气 TensorRT 元数据格式不正确：{metadata_path}")

        self._np = np
        self._torch = torch
        self._trt = trt
        self._image_type = Image
        self._frame_width = max(1, int(frame_width))
        self._frame_height = max(1, int(frame_height))
        self._resize = (resize[1], resize[0])
        self._resample = Image.Resampling.BILINEAR
        self._mean = np.asarray(mean, dtype=np.float32).reshape((1, 1, 3))
        self._std = np.asarray(std, dtype=np.float32).reshape((1, 1, 3))
        self._labels = [str(label).strip().lower() for label in labels]
        self._input_name = str(metadata.get("input_name", "pixel_values"))
        self._output_name = str(metadata.get("output_name", "logits"))
        self._lock = Lock()
        self.device = "cuda:0"

        self._logger = trt.Logger(trt.Logger.ERROR)
        self._runtime = trt.Runtime(self._logger)
        self._engine = self._runtime.deserialize_cuda_engine(engine_path.read_bytes())
        if self._engine is None:
            raise RuntimeError(f"天气 TensorRT 引擎反序列化失败：{engine_path}")
        self._context = self._engine.create_execution_context()
        if self._context is None:
            raise RuntimeError("天气 TensorRT 执行上下文创建失败")

        engine_input_shape = tuple(self._engine.get_tensor_shape(self._input_name))
        engine_output_shape = tuple(self._engine.get_tensor_shape(self._output_name))
        if engine_input_shape != input_shape:
            raise ValueError(
                "天气 TensorRT 输入形状不匹配："
                f"engine={engine_input_shape}, metadata={input_shape}"
            )
        if engine_output_shape != (1, len(self._labels)):
            raise ValueError(
                "天气 TensorRT 输出形状与类别数不匹配："
                f"shape={engine_output_shape}, labels={len(self._labels)}"
            )

        input_dtype = self._torch_dtype(self._engine.get_tensor_dtype(self._input_name))
        output_dtype = self._torch_dtype(self._engine.get_tensor_dtype(self._output_name))
        self._input_tensor = torch.empty(input_shape, dtype=input_dtype, device=self.device)
        self._output_tensor = torch.empty(
            engine_output_shape,
            dtype=output_dtype,
            device=self.device,
        )
        if not self._context.set_tensor_address(
            self._input_name, self._input_tensor.data_ptr()
        ):
            raise RuntimeError("天气 TensorRT 输入地址绑定失败")
        if not self._context.set_tensor_address(
            self._output_name, self._output_tensor.data_ptr()
        ):
            raise RuntimeError("天气 TensorRT 输出地址绑定失败")

    def _torch_dtype(self, dtype: Any) -> Any:
        mapping = {
            self._trt.float16: self._torch.float16,
            self._trt.float32: self._torch.float32,
            self._trt.int32: self._torch.int32,
            self._trt.int64: self._torch.int64,
        }
        if dtype not in mapping:
            raise TypeError(f"天气 TensorRT 不支持的数据类型：{dtype}")
        return mapping[dtype]

    def predict(self, frame_bgr: bytes) -> Mapping[str, float]:
        expected_size = self._frame_width * self._frame_height * 3
        if len(frame_bgr) != expected_size:
            raise ValueError(
                f"天气模型帧大小错误：expected={expected_size}, actual={len(frame_bgr)}"
            )

        frame = self._np.frombuffer(frame_bgr, dtype=self._np.uint8).reshape(
            (self._frame_height, self._frame_width, 3)
        )
        image = self._image_type.fromarray(frame[:, :, ::-1].copy(), mode="RGB")
        image = self._np.asarray(
            image.resize(self._resize, resample=self._resample),
            dtype=self._np.float32,
        )
        image = (image / 255.0 - self._mean) / self._std
        image = self._np.ascontiguousarray(image.transpose((2, 0, 1))[None, ...])

        with self._lock, self._torch.inference_mode():
            self._input_tensor.copy_(self._torch.from_numpy(image))
            stream = self._torch.cuda.current_stream(device=self.device)
            if not self._context.execute_async_v3(stream_handle=stream.cuda_stream):
                raise RuntimeError("天气 TensorRT 推理执行失败")
            probabilities = self._torch.softmax(self._output_tensor.float(), dim=-1)[0]
            values = probabilities.cpu().tolist()

        return {
            label: float(values[index]) for index, label in enumerate(self._labels)
        }


@dataclass(frozen=True)
class _MappedObservation:
    label: str
    confidence: float
    raw_label: str
    raw_confidence: float
    probabilities: dict[str, float]


class WeatherDetectionService:
    """Confirm weather across time-spaced frames, never from one observation."""

    def __init__(
        self,
        *,
        enabled: bool,
        classifier: WeatherClassifier | None = None,
        min_confidence: float = 0.55,
        smoothing_window: int = 6,
        stable_votes: int = 5,
        initialization_error: str | None = None,
        round_interval_seconds: float = 300.0,
        sample_interval_seconds: float = 2.0,
        min_observation_seconds: float = 10.0,
    ) -> None:
        self.next_sample_at = 0.0
        self._refresh_pending = False
        self._round_interval_seconds = max(0.5, float(round_interval_seconds))
        self._previous_round_label: str | None = None
        self._rounds_processed = 0
        self.enabled = bool(enabled)
        self._classifier = classifier
        self._runtime = getattr(classifier, "runtime", "unknown") if classifier else None
        self._min_confidence = min(1.0, max(0.0, float(min_confidence)))
        # Persisted 1/3-frame settings cannot re-enable instant decisions.
        self._window_size = max(6, int(smoothing_window))
        self._stable_votes = min(self._window_size, max(math.ceil(self._window_size * 0.8), int(stable_votes)))
        self._min_observation_seconds = max(10.0, float(min_observation_seconds))
        self._sample_interval_seconds = max(2.0, float(sample_interval_seconds),
                                            self._min_observation_seconds / (self._window_size - 1))
        self._max_sample_gap_seconds = self._sample_interval_seconds * 3
        self._round_started_at: float | None = None
        self._last_sample_at: float | None = None
        self._round_generation = 0
        self._candidate_label: str | None = None
        self._candidate_rounds = 0
        self._candidate_at: float | None = None
        self._last_confirmed_at: float | None = None
        self._last_confirmed_observed_at: str | None = None
        self._result_status = "collecting"
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
            if Path(settings.WEATHER_MODEL_PATH).suffix.lower() == ".engine":
                classifier = TensorRTWeatherClassifier(
                    model_path=settings.WEATHER_MODEL_PATH,
                    frame_width=settings.AI_FRAME_WIDTH,
                    frame_height=settings.AI_FRAME_HEIGHT,
                    device=settings.WEATHER_DEVICE,
                )
            else:
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
            "天气模型已就绪：path={}，runtime={}，device={}，"
            "interval={}s，window={}，votes={}",
            settings.WEATHER_MODEL_PATH,
            classifier.runtime,
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
            round_interval_seconds=settings.WEATHER_INTERVAL_SECONDS,
            sample_interval_seconds=getattr(settings, "WEATHER_SAMPLE_INTERVAL_SECONDS", 2.0),
            min_observation_seconds=getattr(settings, "WEATHER_MIN_OBSERVATION_SECONDS", 10.0),
        )

    @property
    def available(self) -> bool:
        return self.enabled and self._classifier is not None and self._state != "failed"

    @property
    def refresh_pending(self) -> bool:
        with self._lock:
            return self._refresh_pending

    @property
    def round_in_progress(self) -> bool:
        with self._lock:
            return bool(self._history)

    def _clear_round(self) -> None:
        """Caller holds the lock; votes never cross a gap or refresh boundary."""
        self._history.clear()
        self._round_started_at = None
        self._last_sample_at = None

    def _clear_candidate(self) -> None:
        self._candidate_label = None
        self._candidate_rounds = 0
        self._candidate_at = None

    def _set_uncertain(self, status: str) -> None:
        self._label = "unknown"
        self._confidence = 0.0
        self._probabilities = {label: 0.0 for label in WEATHER_LABELS}
        self._state = "warming_up"
        self._result_status = status

    def request_refresh(self) -> bool:
        """A refresh starts a full observation round, never a single-frame result."""
        if not self.available:
            return False
        with self._lock:
            if self._refresh_pending:
                return False
            self._refresh_pending = True
            self._round_generation += 1
            self._clear_round()
            self._clear_candidate()
            self.next_sample_at = 0.0
            self._result_status = "collecting"
            self._detail = f"等待本轮{self._window_size}次间隔采样，至少观察{self._min_observation_seconds:g}秒"
        return True

    def cancel_refresh(self, detail: str) -> None:
        with self._lock:
            self._round_generation += 1
            self._clear_round()
            self._clear_candidate()
            self._refresh_pending = False
            self._set_uncertain("uncertain")
            self._detail = detail
            self.next_sample_at = time.monotonic() + 10.0

    def process_frame(self, frame_bgr: bytes) -> dict[str, Any]:
        if not self.available or self._classifier is None:
            return self.get_status()
        sampled_at = time.monotonic()
        with self._lock:
            due = sampled_at >= self.next_sample_at
            generation = self._round_generation
            if due and self._last_sample_at is not None and sampled_at - self._last_sample_at > self._max_sample_gap_seconds:
                self._clear_round()
                self._clear_candidate()
                self._set_uncertain("collecting")
        if not due:
            return self.get_status()
        started = time.perf_counter()
        try:
            observation = self._map_probabilities(self._classifier.predict(frame_bgr))
        except Exception as exc:  # noqa: BLE001 - isolate weather failures
            with self._lock:
                if generation == self._round_generation:
                    self._clear_round()
                    self._clear_candidate()
                    self.next_sample_at = time.monotonic() + 10.0
                    self._errors += 1
                    self._last_error = str(exc)
                    self._refresh_pending = False
                    self._set_uncertain("uncertain")
                    self._state = "degraded"
                    self._detail = f"天气采样失败，待重新确认：{exc}"
                    self._last_inference_ms = round((time.perf_counter() - started) * 1000, 1)
            weather_logger.warning("天气推理失败，本帧已跳过：{}", exc)
            return self.get_status()
        with self._lock:
            # A refresh during GPU work invalidates that old frame.
            if generation == self._round_generation:
                self._record_observation(observation, sampled_at, started)
        return self.get_status()

    def _record_observation(self, observation: _MappedObservation, now: float, started: float) -> None:
        if self._round_started_at is None:
            self._round_started_at = now
        self._last_sample_at = now
        self._history.append(observation)
        self._frames_processed += 1
        self._raw_label = observation.raw_label
        self._raw_confidence = observation.raw_confidence
        self._last_inference_ms = round((time.perf_counter() - started) * 1000, 1)
        self._last_error = None
        elapsed = now - self._round_started_at
        if len(self._history) < self._window_size or elapsed + 1e-9 < self._min_observation_seconds:
            self._state = "warming_up" if self._label == "unknown" else "ready"
            self._result_status = "collecting"
            self._detail = f"多帧确认中：{len(self._history)}/{self._window_size}张，已观察{elapsed:.1f}/{self._min_observation_seconds:g}秒"
            self.next_sample_at = now + self._sample_interval_seconds
            return
        votes = Counter(item.label for item in self._history if item.label != "unknown")
        voted_label, vote_count = votes.most_common(1)[0] if votes else ("unknown", 0)
        valid = vote_count >= self._stable_votes
        changed = valid and self._previous_round_label not in (None, voted_label)
        confirmed = valid
        if changed:
            fresh = (self._candidate_at is not None and now - self._candidate_at
                     <= max(30.0, 2 * self._min_observation_seconds + 10.0))
            if self._candidate_label == voted_label and fresh:
                self._candidate_rounds += 1
            else:
                self._candidate_label = voted_label
                self._candidate_rounds = 1
            self._candidate_at = now
            confirmed = self._candidate_rounds >= 2
        else:
            self._clear_candidate()
        if confirmed:
            self._label = voted_label
            supporting = [item.confidence for item in self._history if item.label == voted_label]
            self._confidence = sum(supporting) / len(supporting)
            self._probabilities = {
                label: sum(item.probabilities[label] for item in self._history) / self._window_size
                for label in WEATHER_LABELS
            }
            self._previous_round_label = voted_label
            self._observed_at = utc_now_iso()
            self._last_confirmed_observed_at = self._observed_at
            self._last_confirmed_at = now
            self._state = "ready"
            self._result_status = "confirmed"
            self._clear_candidate()
            reason = "跨两轮确认变化" if changed else "多帧确认"
        else:
            self._set_uncertain("pending_change" if changed else "uncertain")
            reason = "疑似天气变化，等待第二轮复核" if changed else "证据不足，待确认"
        delay = 10.0 if changed or not valid else self._round_interval_seconds
        self._detail = f"本轮{vote_count}/{self._window_size}张一致，观察{elapsed:.1f}秒，{reason}；{delay:g}秒后复测"
        self._rounds_processed += 1
        self._refresh_pending = False
        self._clear_round()
        self.next_sample_at = now + delay

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            now = time.monotonic()
            stale = (self._label != "unknown" and self._last_confirmed_at is not None
                     and now - self._last_confirmed_at > self._round_interval_seconds + self._min_observation_seconds + 30.0)
            label = "unknown" if stale else self._label
            return {
                "enabled": self.enabled,
                "state": "warming_up" if stale else self._state,
                "detail": "天气结果已过期，等待新的多帧确认" if stale else self._detail,
                "label": label,
                "label_zh": WEATHER_LABELS_ZH.get(label, label),
                "confidence": 0.0 if label == "unknown" else round(self._confidence, 4),
                "raw_label": self._raw_label,
                "raw_confidence": round(self._raw_confidence, 4),
                "probabilities": {
                    key: 0.0 if label == "unknown" else round(value, 4) for key, value in self._probabilities.items()
                },
                "observed_at": None if label == "unknown" else self._observed_at,
                "inference_ms": self._last_inference_ms,
                "frames_processed": self._frames_processed,
                "smoothing_window": self._window_size,
                "stable_votes": self._stable_votes,
                "rounds_processed": self._rounds_processed,
                "round_samples": len(self._history),
                "sample_interval_seconds": self._sample_interval_seconds,
                "min_observation_seconds": self._min_observation_seconds,
                "round_observation_seconds": round(max(0.0, (self._last_sample_at or 0.0) - (self._round_started_at or 0.0)), 1),
                "result_status": "stale" if stale else self._result_status,
                "change_confirm_rounds": 2,
                "candidate_label": self._candidate_label,
                "candidate_rounds": self._candidate_rounds,
                "last_confirmed_label": self._previous_round_label,
                "last_confirmed_at": self._last_confirmed_observed_at,
                "next_sample_in_seconds": round(max(0.0, self.next_sample_at - time.monotonic()), 1),
                "source": "visible_camera",
                "runtime": self._runtime,
                "radar_fused": False,
                "last_error": self._last_error,
                "errors": self._errors,
            }

    def _map_probabilities(
        self,
        raw_probabilities: Mapping[str, float],
    ) -> _MappedObservation:
        cleaned = {str(label).strip().lower(): float(value) for label, value in raw_probabilities.items()}
        if not cleaned or any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in cleaned.values()):
            raise ValueError("天气模型未返回有效类别概率")
        raw_label, raw_confidence = max(cleaned.items(), key=lambda item: item[1])
        mapped = RAW_TO_PRODUCT_LABEL.get(raw_label, "unknown")
        if raw_confidence < self._min_confidence:
            mapped = "unknown"
        product_probabilities = {
            "normal": cleaned.get("normal", 0.0),
            "rain": cleaned.get("rain", 0.0),
            "snow": min(1.0, cleaned.get("snow", 0.0) + cleaned.get("rime", 0.0)),
            "sandstorm": cleaned.get("sandstorm", 0.0),
        }
        return _MappedObservation(
            label=mapped,
            confidence=raw_confidence,
            raw_label=raw_label,
            raw_confidence=raw_confidence,
            probabilities=product_probabilities,
        )



_weather_detection_service: WeatherDetectionService | None = None


def get_weather_detection_service() -> WeatherDetectionService | None:
    return _weather_detection_service


def set_weather_detection_service(service: WeatherDetectionService | None) -> None:
    global _weather_detection_service
    _weather_detection_service = service
