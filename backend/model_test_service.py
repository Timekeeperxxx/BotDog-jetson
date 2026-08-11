"""Offline image/video inference helpers used by the admin model tester.

Deployed TensorRT engines are preferred for the expensive YOLO/weather paths;
portable ONNX/checkpoint runners remain available as automatic fallbacks.
"""

from __future__ import annotations

import subprocess
import time
import uuid
from collections import Counter, deque
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any, Protocol

import cv2
import numpy as np

from .config import settings


MODEL_TEST_OUTPUT_DIR = Path("data/model-tests")
MODEL_TEST_MAX_UPLOAD_BYTES = 512 * 1024 * 1024
MODEL_TEST_RESULT_TTL_SECONDS = 7 * 24 * 60 * 60

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".m4v", ".webm"}
ALLOWED_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS

COLORS = (
    (56, 182, 255),
    (83, 214, 129),
    (245, 169, 66),
    (232, 99, 120),
)

COCO_SKELETON = (
    (5, 7), (7, 9), (6, 8), (8, 10),
    (5, 6), (5, 11), (6, 12), (11, 12),
    (11, 13), (13, 15), (12, 14), (14, 16),
    (0, 1), (0, 2), (1, 3), (2, 4),
    (3, 5), (4, 6),
)

DISPLAY_LABELS_ZH = {
    "person": "人员",
    "head": "头部",
    "helmet": "安全帽",
    "guns": "枪支",
    "knife": "刀具",
    "face": "人脸",
}


class Runner(Protocol):
    def process(self, frame: np.ndarray, confidence: float) -> tuple[np.ndarray, int]: ...


@dataclass(frozen=True)
class ModelDefinition:
    key: str
    name: str
    description: str
    kind: str
    path: Path
    runtime: str
    labels: tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        if self.kind == "weather_tensorrt":
            return self.path.is_file() and self.path.with_suffix(".json").is_file()
        if self.kind == "weather_vit":
            return (
                self.path.is_dir()
                and (self.path / "config.json").is_file()
                and (self.path / "model.safetensors").is_file()
            )
        return self.path.is_file()


@dataclass(frozen=True)
class ModelTestResult:
    result_id: str
    filename: str
    model_key: str
    model_name: str
    runtime: str
    is_video: bool
    media_type: str
    frames: int
    source_frames: int
    source_fps: float | None
    processing_fps: float | None
    detections: int
    label_counts: dict[str, int]
    elapsed_seconds: float


@dataclass(frozen=True)
class LetterboxInfo:
    scale: float
    pad_x: int
    pad_y: int


@dataclass(frozen=True)
class VideoProcessResult:
    processed_frames: int
    source_frames: int
    detections: int
    source_fps: float
    processing_fps: float


def _onnx_variant(configured_path: str, fallback_name: str) -> Path:
    configured = Path(configured_path).expanduser()
    candidate = configured.with_suffix(".onnx")
    if candidate.is_file():
        return candidate
    fallback = configured.parent / fallback_name
    return fallback if fallback.is_file() else candidate


def _engine_variant(configured_path: str, fallback_name: str) -> Path | None:
    configured = Path(configured_path).expanduser()
    candidates = (
        (
            configured
            if configured.suffix.lower() == ".engine"
            else configured.with_suffix(".engine")
        ),
        configured.parent / fallback_name,
    )
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def _weather_checkpoint(configured_path: str) -> Path:
    configured = Path(configured_path).expanduser()
    if configured.is_dir() and (configured / "config.json").is_file():
        return configured
    preferred = configured.parent / "checkpoint-3000"
    if preferred.is_dir():
        return preferred
    return configured.parent / "checkpoint-1500"


def get_model_definitions() -> dict[str, ModelDefinition]:
    helmet_engine = _engine_variant(settings.AI_MODEL_PATH, "helmet.engine")
    pose_engine = _engine_variant(settings.POSE_MODEL_PATH, "yolo11n-pose.engine")
    weapon_engine = _engine_variant(
        settings.WEAPON_MODEL_PATH,
        "weapon_guns_knife_yolov8n_fp16.engine",
    )
    weather_engine = _engine_variant(
        settings.WEATHER_MODEL_PATH,
        "weather_types_vit_fp16.engine",
    )
    definitions = (
        ModelDefinition(
            key="helmet",
            name="安全帽检测",
            description="识别人、头部和安全帽并绘制目标框",
            kind="ultralytics_detect" if helmet_engine else "yolo_detect",
            path=helmet_engine or _onnx_variant(settings.AI_MODEL_PATH, "helmet.onnx"),
            runtime="TensorRT" if helmet_engine else "ONNX / CPU",
            labels=("person", "head", "helmet"),
        ),
        ModelDefinition(
            key="pose",
            name="人体姿态检测",
            description="识别人并绘制 COCO 17 点人体骨架",
            kind="ultralytics_pose" if pose_engine else "yolo_pose",
            path=pose_engine or _onnx_variant(settings.POSE_MODEL_PATH, "yolo11n-pose.onnx"),
            runtime="TensorRT" if pose_engine else "ONNX / CPU",
            labels=("person",),
        ),
        ModelDefinition(
            key="face",
            name="人脸检测",
            description="使用 YuNet 绘制人脸框和 5 个关键点",
            kind="yunet",
            path=Path(settings.FACE_DETECT_MODEL_PATH).expanduser(),
            runtime="ONNX / CPU",
            labels=("face",),
        ),
        ModelDefinition(
            key="weapon",
            name="刀枪检测",
            description="识别枪支和刀具并绘制目标框",
            kind="ultralytics_detect",
            path=weapon_engine or Path(settings.WEAPON_MODEL_PATH).expanduser(),
            runtime="TensorRT" if weapon_engine else "不可用",
            labels=("guns", "knife"),
        ),
        ModelDefinition(
            key="weather",
            name="天气分类",
            description="使用 ViT 显示天气分类 Top-3 和概率",
            kind="weather_tensorrt" if weather_engine else "weather_vit",
            path=weather_engine or _weather_checkpoint(settings.WEATHER_MODEL_PATH),
            runtime="TensorRT" if weather_engine else "PyTorch",
        ),
    )
    return {definition.key: definition for definition in definitions}


def public_model_definitions() -> list[dict[str, object]]:
    return [
        {
            "key": model.key,
            "name": model.name,
            "description": model.description,
            "available": model.available,
            "runtime": model.runtime,
        }
        for model in get_model_definitions().values()
    ]


def letterbox(frame: np.ndarray, size: int = 640) -> tuple[np.ndarray, LetterboxInfo]:
    height, width = frame.shape[:2]
    scale = min(size / width, size / height)
    resized_width = max(1, round(width * scale))
    resized_height = max(1, round(height * scale))
    resized = cv2.resize(frame, (resized_width, resized_height), interpolation=cv2.INTER_LINEAR)

    pad_x = (size - resized_width) // 2
    pad_y = (size - resized_height) // 2
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    canvas[pad_y:pad_y + resized_height, pad_x:pad_x + resized_width] = resized
    return canvas, LetterboxInfo(scale=scale, pad_x=pad_x, pad_y=pad_y)


def normalize_yolo_output(output: np.ndarray) -> np.ndarray:
    predictions = np.squeeze(output)
    if predictions.ndim != 2:
        raise RuntimeError(f"无法识别 YOLO 输出形状：{output.shape}")
    if predictions.shape[0] < predictions.shape[1]:
        predictions = predictions.T
    return predictions


def restore_box(
    box: np.ndarray,
    info: LetterboxInfo,
    width: int,
    height: int,
) -> list[int]:
    center_x, center_y, box_width, box_height = box[:4]
    x1 = (center_x - box_width / 2 - info.pad_x) / info.scale
    y1 = (center_y - box_height / 2 - info.pad_y) / info.scale
    x2 = (center_x + box_width / 2 - info.pad_x) / info.scale
    y2 = (center_y + box_height / 2 - info.pad_y) / info.scale
    x1 = int(np.clip(x1, 0, width - 1))
    y1 = int(np.clip(y1, 0, height - 1))
    x2 = int(np.clip(x2, 0, width - 1))
    y2 = int(np.clip(y2, 0, height - 1))
    return [x1, y1, max(1, x2 - x1), max(1, y2 - y1)]


def draw_label(
    frame: np.ndarray,
    text: str,
    x: int,
    y: int,
    color: tuple[int, int, int],
) -> None:
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = max(0.45, min(frame.shape[:2]) / 1100)
    thickness = max(1, round(scale * 2))
    (text_width, text_height), baseline = cv2.getTextSize(text, font, scale, thickness)
    top = max(0, y - text_height - baseline - 7)
    cv2.rectangle(frame, (x, top), (x + text_width + 8, y), color, -1)
    cv2.putText(
        frame,
        text,
        (x + 4, y - baseline - 3),
        font,
        scale,
        (20, 24, 31),
        thickness,
        cv2.LINE_AA,
    )


class YoloDetectRunner:
    def __init__(self, model_path: Path, labels: tuple[str, ...]) -> None:
        self.net = cv2.dnn.readNetFromONNX(str(model_path))
        self.labels = labels

    def process(self, frame: np.ndarray, confidence: float) -> tuple[np.ndarray, int]:
        canvas, info = letterbox(frame)
        blob = cv2.dnn.blobFromImage(
            canvas, 1 / 255.0, (640, 640), swapRB=True, crop=False
        )
        self.net.setInput(blob)
        predictions = normalize_yolo_output(self.net.forward())

        boxes: list[list[int]] = []
        scores: list[float] = []
        class_ids: list[int] = []
        height, width = frame.shape[:2]

        for prediction in predictions:
            class_scores = prediction[4:]
            class_id = int(np.argmax(class_scores))
            score = float(class_scores[class_id])
            if score < confidence:
                continue
            boxes.append(restore_box(prediction[:4], info, width, height))
            scores.append(score)
            class_ids.append(class_id)

        indices = cv2.dnn.NMSBoxes(boxes, scores, confidence, 0.45)
        kept = [int(index) for index in np.asarray(indices).reshape(-1)] if len(indices) else []
        result = frame.copy()
        for index in kept:
            x, y, box_width, box_height = boxes[index]
            class_id = class_ids[index]
            color = COLORS[class_id % len(COLORS)]
            label = self.labels[class_id] if class_id < len(self.labels) else f"class_{class_id}"
            cv2.rectangle(result, (x, y), (x + box_width, y + box_height), color, 2)
            draw_label(result, f"{label} {scores[index]:.2f}", x, y, color)
        return result, len(kept)


class YoloPoseRunner:
    def __init__(self, model_path: Path) -> None:
        self.net = cv2.dnn.readNetFromONNX(str(model_path))

    def process(self, frame: np.ndarray, confidence: float) -> tuple[np.ndarray, int]:
        canvas, info = letterbox(frame)
        blob = cv2.dnn.blobFromImage(
            canvas, 1 / 255.0, (640, 640), swapRB=True, crop=False
        )
        self.net.setInput(blob)
        predictions = normalize_yolo_output(self.net.forward())

        boxes: list[list[int]] = []
        scores: list[float] = []
        keypoints: list[np.ndarray] = []
        height, width = frame.shape[:2]

        for prediction in predictions:
            score = float(prediction[4])
            if score < confidence:
                continue
            boxes.append(restore_box(prediction[:4], info, width, height))
            scores.append(score)
            points = prediction[5:].reshape(-1, 3).copy()
            points[:, 0] = (points[:, 0] - info.pad_x) / info.scale
            points[:, 1] = (points[:, 1] - info.pad_y) / info.scale
            keypoints.append(points)

        indices = cv2.dnn.NMSBoxes(boxes, scores, confidence, 0.45)
        kept = [int(index) for index in np.asarray(indices).reshape(-1)] if len(indices) else []
        result = frame.copy()

        for index in kept:
            x, y, box_width, box_height = boxes[index]
            points = keypoints[index]
            cv2.rectangle(result, (x, y), (x + box_width, y + box_height), COLORS[0], 2)
            draw_label(result, f"person {scores[index]:.2f}", x, y, COLORS[0])

            for start, end in COCO_SKELETON:
                if points[start, 2] >= 0.5 and points[end, 2] >= 0.5:
                    start_point = tuple(np.rint(points[start, :2]).astype(int))
                    end_point = tuple(np.rint(points[end, :2]).astype(int))
                    cv2.line(result, start_point, end_point, COLORS[1], 2, cv2.LINE_AA)
            for point_x, point_y, point_score in points:
                if point_score >= 0.5 and 0 <= point_x < width and 0 <= point_y < height:
                    cv2.circle(
                        result,
                        (round(point_x), round(point_y)),
                        3,
                        COLORS[0],
                        -1,
                        cv2.LINE_AA,
                    )

        return result, len(kept)


class UltralyticsTensorRTRunner:
    """Ultralytics adapter for the deployed fixed-shape TensorRT engines."""

    def __init__(self, model_path: Path, task: str) -> None:
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError("TensorRT 模型需要安装 Ultralytics") from exc
        self.model = YOLO(str(model_path), task=task)
        self.label_counts: Counter[str] = Counter()

    def reset(self) -> None:
        self.label_counts.clear()

    def get_label_counts(self) -> dict[str, int]:
        return dict(self.label_counts)

    def process(self, frame: np.ndarray, confidence: float) -> tuple[np.ndarray, int]:
        results = self.model.predict(
            frame,
            conf=confidence,
            imgsz=640,
            verbose=False,
        )
        if not results:
            return frame.copy(), 0
        result = results[0]
        boxes = result.boxes
        translated_names = {
            int(class_id): DISPLAY_LABELS_ZH.get(str(name), str(name))
            for class_id, name in result.names.items()
        }
        labels: list[tuple[tuple[int, int, int, int], str, tuple[int, int, int]]] = []
        if boxes is not None:
            for bbox_values, class_id, score in zip(
                boxes.xyxy.detach().cpu().tolist(),
                boxes.cls.detach().cpu().tolist(),
                boxes.conf.detach().cpu().tolist(),
            ):
                normalized_class_id = int(class_id)
                label = translated_names.get(normalized_class_id, str(normalized_class_id))
                self.label_counts[label] += 1
                bbox = tuple(int(round(value)) for value in bbox_values)
                labels.append(
                    (
                        (bbox[0], bbox[1], bbox[2], bbox[3]),
                        f"{label} {float(score):.2f}",
                        COLORS[normalized_class_id % len(COLORS)],
                    )
                )
        annotated = result.plot(labels=False)
        count = len(boxes) if boxes is not None else 0
        return _draw_unicode_status_labels(annotated, labels), count


class PoseStatusTensorRTRunner:
    """TensorRT pose inference plus tracked posture/action labels."""

    def __init__(self, model_path: Path) -> None:
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError("TensorRT 姿态模型需要安装 Ultralytics") from exc
        self.model = YOLO(str(model_path), task="pose")
        self.frame_time = 0.0
        self.label_counts: Counter[str] = Counter()
        self.wrist_history: dict[tuple[int, int], deque[tuple[float, float, float]]] = {}
        self.event_engine: Any = None
        self.reset()

    def reset(self) -> None:
        from .pose_detection import PoseEventEngine

        self.frame_time = 0.0
        self.label_counts.clear()
        self.wrist_history.clear()
        self.event_engine = PoseEventEngine(
            keypoint_confidence=settings.POSE_KEYPOINT_CONFIDENCE,
            min_visible_keypoints=settings.POSE_MIN_VISIBLE_KEYPOINTS,
            stable_hits=settings.POSE_STABLE_HITS,
            crouch_seconds=settings.POSE_CROUCH_SECONDS,
            loiter_seconds=settings.POSE_LOITER_SECONDS,
            event_cooldown_seconds=settings.POSE_EVENT_COOLDOWN_SECONDS,
            track_ttl_seconds=settings.POSE_TRACK_TTL_SECONDS,
        )

    def set_frame_time(self, frame_time: float) -> None:
        self.frame_time = max(0.0, float(frame_time))

    def get_label_counts(self) -> dict[str, int]:
        return dict(self.label_counts)

    def process(self, frame: np.ndarray, confidence: float) -> tuple[np.ndarray, int]:
        from .pose_detection import PoseKeypoint, RawPose

        results = self.model.predict(
            frame,
            conf=confidence,
            imgsz=640,
            verbose=False,
        )
        if not results:
            return frame.copy(), 0
        result = results[0]
        if result.keypoints is None or result.boxes is None:
            return result.plot(labels=False), 0

        raw_poses: list[RawPose] = []
        for bbox_values, detection_confidence, keypoint_values in zip(
            result.boxes.xyxy.detach().cpu().tolist(),
            result.boxes.conf.detach().cpu().tolist(),
            result.keypoints.data.detach().cpu().tolist(),
        ):
            bbox = tuple(int(round(value)) for value in bbox_values)
            raw_poses.append(
                RawPose(
                    bbox=(bbox[0], bbox[1], bbox[2], bbox[3]),
                    confidence=float(detection_confidence),
                    keypoints=tuple(
                        PoseKeypoint(
                            x=float(values[0]),
                            y=float(values[1]),
                            confidence=float(values[2]) if len(values) >= 3 else 1.0,
                        )
                        for values in keypoint_values
                    ),
                )
            )

        observations, events = self.event_engine.update(raw_poses, now=self.frame_time)
        event_by_track = {event.track_id: event.event_type for event in events}
        labels: list[tuple[tuple[int, int, int, int], str, tuple[int, int, int]]] = []
        for raw_pose, observation in zip(raw_poses, observations):
            label, color = self._status_for_pose(
                raw_pose,
                observation,
                event_by_track.get(observation.track_id),
            )
            self.label_counts[label] += 1
            labels.append((observation.bbox, f"#{observation.track_id} {label}", color))

        annotated = result.plot(labels=False)
        return _draw_unicode_status_labels(annotated, labels), len(observations)

    def _status_for_pose(
        self,
        raw_pose: Any,
        observation: Any,
        event_type: str | None,
    ) -> tuple[str, tuple[int, int, int]]:
        from .pose_detection import Posture

        if event_type == "POSE_CLIMBING_SUSPECTED":
            return "疑似攀爬/翻越", COLORS[3]
        if event_type == "POSE_LYING":
            return "倒地/躺卧", COLORS[3]
        if self._has_repetitive_wrist_motion(observation):
            return "疑似破坏围栏动作", COLORS[3]
        if observation.posture is Posture.CLIMBING:
            return "疑似攀爬/翻越", COLORS[2]
        if observation.posture is Posture.LYING:
            return "倒地/躺卧", COLORS[3]
        if observation.posture is Posture.CROUCHING:
            if _looks_seated(raw_pose, settings.POSE_KEYPOINT_CONFIDENCE):
                return "坐姿", COLORS[2]
            return "蹲姿", COLORS[2]
        if observation.posture is Posture.STANDING:
            return "站立", COLORS[1]
        return "姿态不确定", COLORS[0]

    def _has_repetitive_wrist_motion(self, observation: Any) -> bool:
        x1, y1, x2, y2 = observation.bbox
        height = max(1.0, float(y2 - y1))
        now = self.frame_time
        suspicious = False
        for wrist_index in (9, 10):
            if wrist_index >= len(observation.keypoints):
                continue
            wrist = observation.keypoints[wrist_index]
            if wrist.confidence < settings.POSE_KEYPOINT_CONFIDENCE:
                continue
            key = (observation.track_id, wrist_index)
            history = self.wrist_history.setdefault(key, deque())
            history.append((now, (wrist.x - x1) / height, (wrist.y - y1) / height))
            while history and now - history[0][0] > 1.8:
                history.popleft()
            suspicious = suspicious or _is_repetitive_motion(history)
        return suspicious


def _looks_seated(raw_pose: Any, keypoint_confidence: float) -> bool:
    """Conservative skeleton heuristic separating a seated pose from a squat."""
    height = max(1.0, float(raw_pose.bbox[3] - raw_pose.bbox[1]))
    seated_votes = 0
    visible_legs = 0
    for hip_index, knee_index, ankle_index in ((11, 13, 15), (12, 14, 16)):
        if max(hip_index, knee_index, ankle_index) >= len(raw_pose.keypoints):
            continue
        hip = raw_pose.keypoints[hip_index]
        knee = raw_pose.keypoints[knee_index]
        ankle = raw_pose.keypoints[ankle_index]
        if min(hip.confidence, knee.confidence, ankle.confidence) < keypoint_confidence:
            continue
        visible_legs += 1
        thigh_is_horizontal = (
            abs(knee.y - hip.y) / height <= 0.18
            and abs(knee.x - hip.x) / height >= 0.08
        )
        lower_leg_drops = (ankle.y - knee.y) / height >= 0.10
        if thigh_is_horizontal and lower_leg_drops:
            seated_votes += 1
    return visible_legs > 0 and seated_votes >= max(1, visible_legs // 2)


def _is_repetitive_motion(
    history: deque[tuple[float, float, float]],
) -> bool:
    if len(history) < 5 or history[-1][0] - history[0][0] < 0.8:
        return False
    x_values = [item[1] for item in history]
    y_values = [item[2] for item in history]
    x_travel = sum(abs(right - left) for left, right in zip(x_values, x_values[1:]))
    y_travel = sum(abs(right - left) for left, right in zip(y_values, y_values[1:]))
    values = x_values if x_travel >= y_travel else y_values
    movements = [
        right - left
        for left, right in zip(values, values[1:])
        if abs(right - left) >= 0.025
    ]
    reversals = sum(
        1
        for previous, current in zip(movements, movements[1:])
        if previous * current < 0
    )
    travel = max(x_travel, y_travel)
    span = max(values) - min(values)
    return reversals >= 2 and travel >= 0.35 and span >= 0.12


@lru_cache(maxsize=8)
def _status_font(size: int) -> Any:
    from PIL import ImageFont

    candidates = (
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
        Path("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def _draw_unicode_status_labels(
    frame: np.ndarray,
    labels: list[tuple[tuple[int, int, int, int], str, tuple[int, int, int]]],
) -> np.ndarray:
    if not labels:
        return frame
    from PIL import Image, ImageDraw

    image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(image)
    font_size = max(16, round(min(frame.shape[:2]) / 35))
    font = _status_font(font_size)
    for (x1, y1, _x2, _y2), text, bgr_color in labels:
        text_box = draw.textbbox((0, 0), text, font=font)
        text_width = text_box[2] - text_box[0]
        text_height = text_box[3] - text_box[1]
        top = max(0, y1 - text_height - 10)
        left = max(0, x1)
        right = min(image.width, left + text_width + 12)
        bottom = min(image.height, top + text_height + 10)
        rgb_color = (bgr_color[2], bgr_color[1], bgr_color[0])
        draw.rounded_rectangle((left, top, right, bottom), radius=4, fill=rgb_color)
        draw.text((left + 6, top + 3), text, font=font, fill=(16, 20, 26))
    return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)


class YuNetRunner:
    def __init__(self, model_path: Path) -> None:
        self.detector = cv2.FaceDetectorYN.create(
            str(model_path), "", (320, 320), 0.25, 0.3, 5000
        )

    def process(self, frame: np.ndarray, confidence: float) -> tuple[np.ndarray, int]:
        height, width = frame.shape[:2]
        self.detector.setInputSize((width, height))
        self.detector.setScoreThreshold(confidence)
        _, faces = self.detector.detect(frame)
        result = frame.copy()
        if faces is None:
            return result, 0

        for face in faces:
            x, y, box_width, box_height = np.rint(face[:4]).astype(int)
            score = float(face[-1])
            cv2.rectangle(result, (x, y), (x + box_width, y + box_height), COLORS[1], 2)
            draw_label(result, f"face {score:.2f}", x, y, COLORS[1])
            landmarks = np.rint(face[4:14].reshape(5, 2)).astype(int)
            for point in landmarks:
                cv2.circle(result, tuple(point), 2, COLORS[0], -1, cv2.LINE_AA)
        return result, len(faces)


class WeatherViTRunner:
    def __init__(self, model_path: Path) -> None:
        try:
            import torch
            from transformers import AutoImageProcessor, AutoModelForImageClassification
        except ImportError as exc:
            raise RuntimeError(
                "天气模型依赖缺失，请安装 PyTorch、Transformers 和 Pillow"
            ) from exc

        self.torch = torch
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.processor = AutoImageProcessor.from_pretrained(
            str(model_path), local_files_only=True, use_fast=False
        )
        self.model = AutoModelForImageClassification.from_pretrained(
            str(model_path), local_files_only=True
        ).to(self.device)
        self.model.eval()
        self.labels = {
            int(index): str(label)
            for index, label in self.model.config.id2label.items()
        }

    def process(self, frame: np.ndarray, confidence: float) -> tuple[np.ndarray, int]:
        del confidence  # Classification always reports the Top-3 probabilities.
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        inputs = self.processor(images=rgb_frame, return_tensors="pt")
        inputs = {name: value.to(self.device) for name, value in inputs.items()}
        with self.torch.inference_mode():
            logits = self.model(**inputs).logits[0]
            probabilities = self.torch.softmax(logits, dim=-1)
            scores, indices = self.torch.topk(
                probabilities, k=min(3, probabilities.numel())
            )

        top_results = [
            (self.labels.get(int(index), f"class_{int(index)}"), float(score))
            for score, index in zip(scores.cpu(), indices.cpu())
        ]
        result = frame.copy()
        self._draw_results(result, top_results)
        return result, 1

    @staticmethod
    def _draw_results(
        frame: np.ndarray,
        top_results: list[tuple[str, float]],
    ) -> None:
        height, width = frame.shape[:2]
        scale = max(0.5, min(height, width) / 900)
        thickness = max(1, round(scale * 2))
        line_height = max(24, round(32 * scale))
        panel_width = min(width - 20, max(250, round(355 * scale)))
        panel_height = 20 + line_height * (len(top_results) + 1)
        overlay = frame.copy()
        cv2.rectangle(
            overlay, (10, 10), (10 + panel_width, 10 + panel_height), (12, 18, 27), -1
        )
        cv2.addWeighted(overlay, 0.82, frame, 0.18, 0, frame)
        cv2.putText(
            frame,
            "Weather classification",
            (24, 10 + line_height),
            cv2.FONT_HERSHEY_SIMPLEX,
            scale,
            (230, 237, 243),
            thickness,
            cv2.LINE_AA,
        )
        for rank, (label, score) in enumerate(top_results, start=1):
            text = f"{rank}. {label}: {score * 100:.1f}%"
            cv2.putText(
                frame,
                text,
                (24, 10 + line_height * (rank + 1)),
                cv2.FONT_HERSHEY_SIMPLEX,
                scale,
                COLORS[(rank - 1) % len(COLORS)],
                thickness,
                cv2.LINE_AA,
            )


class WeatherTensorRTRunner:
    """Use the deployed FP16 weather engine for standalone uploaded frames."""

    def __init__(self, model_path: Path) -> None:
        self.model_path = model_path
        self.classifiers: dict[tuple[int, int], object] = {}

    def process(self, frame: np.ndarray, confidence: float) -> tuple[np.ndarray, int]:
        del confidence
        height, width = frame.shape[:2]
        dimensions = (width, height)
        classifier = self.classifiers.get(dimensions)
        if classifier is None:
            from .weather_detection import TensorRTWeatherClassifier

            classifier = TensorRTWeatherClassifier(
                model_path=str(self.model_path),
                frame_width=width,
                frame_height=height,
                device="auto",
            )
            self.classifiers[dimensions] = classifier

        probabilities = classifier.predict(np.ascontiguousarray(frame).tobytes())
        top_results = sorted(
            ((str(label), float(score)) for label, score in probabilities.items()),
            key=lambda item: item[1],
            reverse=True,
        )[:3]
        result = frame.copy()
        WeatherViTRunner._draw_results(result, top_results)
        return result, 1


@lru_cache(maxsize=8)
def _build_runner(kind: str, model_path: str, labels: tuple[str, ...]) -> Runner:
    path = Path(model_path)
    if kind == "ultralytics_detect":
        return UltralyticsTensorRTRunner(path, "detect")
    if kind == "ultralytics_pose":
        return PoseStatusTensorRTRunner(path)
    if kind == "yolo_detect":
        return YoloDetectRunner(path, labels)
    if kind == "yolo_pose":
        return YoloPoseRunner(path)
    if kind == "yunet":
        return YuNetRunner(path)
    if kind == "weather_vit":
        return WeatherViTRunner(path)
    if kind == "weather_tensorrt":
        return WeatherTensorRTRunner(path)
    raise ValueError(f"未知模型类型：{kind}")


def process_image(
    source: Path,
    destination: Path,
    runner: Runner,
    confidence: float,
) -> tuple[int, int]:
    frame = cv2.imread(str(source))
    if frame is None:
        raise ValueError("OpenCV 无法读取这张图片")
    result, count = runner.process(frame, confidence)
    if not cv2.imwrite(str(destination), result):
        raise RuntimeError("结果图片保存失败")
    return 1, count


def process_video(
    source: Path,
    destination: Path,
    runner: Runner,
    confidence: float,
    target_fps: float = 5.0,
) -> VideoProcessResult:
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise ValueError("OpenCV 无法打开这个视频")

    source_fps = capture.get(cv2.CAP_PROP_FPS)
    if not np.isfinite(source_fps) or source_fps <= 0:
        source_fps = 25.0
    processing_fps = min(source_fps, max(1.0, float(target_fps)))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if width <= 0 or height <= 0:
        capture.release()
        raise ValueError("无法获得视频尺寸")

    intermediate = destination.with_name(f".{destination.stem}-intermediate.mp4")
    writer = cv2.VideoWriter(
        str(intermediate),
        cv2.VideoWriter_fourcc(*"mp4v"),
        processing_fps,
        (width, height),
    )
    if not writer.isOpened():
        capture.release()
        intermediate.unlink(missing_ok=True)
        raise RuntimeError("无法创建输出视频，请检查 OpenCV 的视频编码支持")

    source_frame_count = 0
    processed_frame_count = 0
    detection_count = 0
    next_sample_at = 0.0
    try:
        try:
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                frame_time = source_frame_count / source_fps
                source_frame_count += 1
                if frame_time + 1e-9 < next_sample_at:
                    continue
                set_frame_time = getattr(runner, "set_frame_time", None)
                if callable(set_frame_time):
                    set_frame_time(frame_time)
                result, count = runner.process(frame, confidence)
                writer.write(result)
                processed_frame_count += 1
                detection_count += count
                next_sample_at += 1.0 / processing_fps
        finally:
            capture.release()
            writer.release()
    except Exception:
        intermediate.unlink(missing_ok=True)
        raise

    if processed_frame_count == 0:
        intermediate.unlink(missing_ok=True)
        raise ValueError("视频中没有可读取的画面")
    try:
        _transcode_browser_video(intermediate, destination)
    finally:
        intermediate.unlink(missing_ok=True)
    return VideoProcessResult(
        processed_frames=processed_frame_count,
        source_frames=source_frame_count,
        detections=detection_count,
        source_fps=round(source_fps, 3),
        processing_fps=round(processing_fps, 3),
    )


def _transcode_browser_video(source: Path, destination: Path) -> None:
    """Convert OpenCV's intermediate stream to browser-compatible H.264."""
    command = [
        "ffmpeg",
        "-y",
        "-loglevel", "error",
        "-i", str(source),
        "-an",
        "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(destination),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=30 * 60,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("未安装 FFmpeg，无法生成浏览器可播放的视频") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("H.264 视频转码超时") from exc
    if completed.returncode != 0 or not destination.is_file():
        detail = completed.stderr.strip().splitlines()
        message = detail[-1] if detail else f"exit={completed.returncode}"
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"H.264 视频转码失败：{message}")


_PROCESS_LOCK = Lock()


def run_model_test(
    *,
    source: Path,
    original_filename: str,
    model_key: str,
    confidence: float,
    video_fps: float = 5.0,
    output_dir: Path = MODEL_TEST_OUTPUT_DIR,
) -> ModelTestResult:
    models = get_model_definitions()
    model = models.get(model_key)
    if model is None:
        raise ValueError("请选择有效的模型")
    if not model.available:
        raise FileNotFoundError(f"模型文件不可用：{model.name}")
    if not 0.05 <= confidence <= 0.95:
        raise ValueError("置信度必须在 0.05 到 0.95 之间")
    if not 1.0 <= video_fps <= 30.0:
        raise ValueError("视频检测帧率必须在 1 到 30 FPS 之间")

    extension = Path(original_filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError(f"不支持的文件格式：{extension or '未知'}")

    output_dir.mkdir(parents=True, exist_ok=True)
    cleanup_stale_outputs(output_dir)
    is_video = extension in VIDEO_EXTENSIONS
    output_extension = ".mp4" if is_video else ".jpg"
    result_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}-{model_key}"
    filename = f"{result_id}{output_extension}"
    destination = output_dir / filename

    started_at = time.perf_counter()
    try:
        with _PROCESS_LOCK:
            runner = _build_runner(model.kind, str(model.path), model.labels)
            reset_runner = getattr(runner, "reset", None)
            if callable(reset_runner):
                reset_runner()
            if is_video:
                video_result = process_video(
                    source,
                    destination,
                    runner,
                    confidence,
                    target_fps=video_fps,
                )
                frames = video_result.processed_frames
                source_frames = video_result.source_frames
                detections = video_result.detections
                source_fps = video_result.source_fps
                processing_fps = video_result.processing_fps
            else:
                frames, detections = process_image(source, destination, runner, confidence)
                source_frames = frames
                source_fps = None
                processing_fps = None
            get_label_counts = getattr(runner, "get_label_counts", None)
            label_counts = get_label_counts() if callable(get_label_counts) else {}
    except Exception:
        destination.unlink(missing_ok=True)
        raise

    return ModelTestResult(
        result_id=result_id,
        filename=filename,
        model_key=model.key,
        model_name=model.name,
        runtime=model.runtime,
        is_video=is_video,
        media_type="video/mp4" if is_video else "image/jpeg",
        frames=frames,
        source_frames=source_frames,
        source_fps=source_fps,
        processing_fps=processing_fps,
        detections=detections,
        label_counts=label_counts,
        elapsed_seconds=round(time.perf_counter() - started_at, 3),
    )


def cleanup_stale_outputs(
    output_dir: Path = MODEL_TEST_OUTPUT_DIR,
    *,
    now: float | None = None,
) -> None:
    if not output_dir.is_dir():
        return
    cutoff = (time.time() if now is None else now) - MODEL_TEST_RESULT_TTL_SECONDS
    for path in output_dir.iterdir():
        if not path.is_file():
            continue
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
        except OSError:
            continue


def resolve_result_file(
    filename: str,
    output_dir: Path = MODEL_TEST_OUTPUT_DIR,
) -> Path | None:
    if not filename or Path(filename).name != filename:
        return None
    if Path(filename).suffix.lower() not in {".jpg", ".mp4"}:
        return None
    candidate = output_dir / filename
    return candidate if candidate.is_file() else None
