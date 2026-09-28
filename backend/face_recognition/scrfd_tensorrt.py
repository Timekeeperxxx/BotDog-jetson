from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Any, Mapping

import numpy as np


def _letterbox_blob(image: np.ndarray, input_size: int) -> tuple[np.ndarray, float]:
    """Build the top-left padded RGB blob used by InsightFace SCRFD."""
    import cv2

    image_height, image_width = image.shape[:2]
    image_ratio = float(image_height) / float(image_width)
    model_ratio = 1.0
    if image_ratio > model_ratio:
        resized_height = input_size
        resized_width = max(1, int(resized_height / image_ratio))
    else:
        resized_width = input_size
        resized_height = max(1, int(resized_width * image_ratio))

    scale = float(resized_height) / float(image_height)
    resized = cv2.resize(image, (resized_width, resized_height))
    padded = np.zeros((input_size, input_size, 3), dtype=np.uint8)
    padded[:resized_height, :resized_width] = resized
    rgb = padded[:, :, ::-1].astype(np.float32)
    blob = (rgb - 127.5) / 128.0
    return np.ascontiguousarray(blob.transpose(2, 0, 1)[None]), scale


def _anchor_centers(input_size: int, stride: int) -> np.ndarray:
    height = input_size // stride
    width = input_size // stride
    centers = np.stack(np.mgrid[:height, :width][::-1], axis=-1).astype(np.float32)
    centers = (centers * stride).reshape((-1, 2))
    return np.stack([centers, centers], axis=1).reshape((-1, 2))


def _nms(boxes: np.ndarray, scores: np.ndarray, threshold: float) -> list[int]:
    if boxes.size == 0:
        return []
    x1, y1, x2, y2 = (boxes[:, index] for index in range(4))
    areas = np.maximum(0.0, x2 - x1 + 1.0) * np.maximum(0.0, y2 - y1 + 1.0)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size:
        index = int(order[0])
        keep.append(index)
        if order.size == 1:
            break
        remaining = order[1:]
        xx1 = np.maximum(x1[index], x1[remaining])
        yy1 = np.maximum(y1[index], y1[remaining])
        xx2 = np.minimum(x2[index], x2[remaining])
        yy2 = np.minimum(y2[index], y2[remaining])
        width = np.maximum(0.0, xx2 - xx1 + 1.0)
        height = np.maximum(0.0, yy2 - yy1 + 1.0)
        intersection = width * height
        union = areas[index] + areas[remaining] - intersection
        overlap = np.divide(
            intersection,
            union,
            out=np.zeros_like(intersection),
            where=union > 0,
        )
        order = remaining[np.where(overlap <= threshold)[0]]
    return keep


def decode_scrfd_predictions(
    predictions: Mapping[int, tuple[np.ndarray, np.ndarray, np.ndarray]],
    *,
    input_size: int,
    image_shape: tuple[int, int],
    scale: float,
    score_threshold: float,
    nms_threshold: float,
) -> list[np.ndarray]:
    """Decode SCRFD heads into rows accepted by OpenCV FaceRecognizerSF."""
    candidate_boxes: list[np.ndarray] = []
    candidate_scores: list[np.ndarray] = []
    candidate_keypoints: list[np.ndarray] = []

    for stride in sorted(predictions):
        scores, box_distances, keypoint_distances = predictions[stride]
        scores = np.asarray(scores, dtype=np.float32).reshape(-1)
        selected = np.flatnonzero(scores >= float(score_threshold))
        if selected.size == 0:
            continue

        centers = _anchor_centers(input_size, stride)[selected]
        box_distances = np.asarray(box_distances, dtype=np.float32).reshape((-1, 4))
        box_distances = box_distances[selected] * stride
        boxes = np.stack(
            (
                centers[:, 0] - box_distances[:, 0],
                centers[:, 1] - box_distances[:, 1],
                centers[:, 0] + box_distances[:, 2],
                centers[:, 1] + box_distances[:, 3],
            ),
            axis=1,
        )

        keypoint_distances = np.asarray(
            keypoint_distances, dtype=np.float32
        ).reshape((-1, 5, 2))
        keypoints = centers[:, None, :] + keypoint_distances[selected] * stride
        candidate_boxes.append(boxes)
        candidate_scores.append(scores[selected])
        candidate_keypoints.append(keypoints)

    if not candidate_boxes:
        return []

    boxes = np.vstack(candidate_boxes) / scale
    scores = np.concatenate(candidate_scores)
    keypoints = np.vstack(candidate_keypoints) / scale
    order = scores.argsort()[::-1]
    boxes = boxes[order]
    scores = scores[order]
    keypoints = keypoints[order]

    image_height, image_width = image_shape
    boxes[:, (0, 2)] = np.clip(boxes[:, (0, 2)], 0, image_width - 1)
    boxes[:, (1, 3)] = np.clip(boxes[:, (1, 3)], 0, image_height - 1)
    keypoints[:, :, 0] = np.clip(keypoints[:, :, 0], 0, image_width - 1)
    keypoints[:, :, 1] = np.clip(keypoints[:, :, 1], 0, image_height - 1)

    kept = _nms(boxes, scores, float(nms_threshold))
    faces: list[np.ndarray] = []
    for index in kept:
        x1, y1, x2, y2 = boxes[index]
        if x2 <= x1 or y2 <= y1:
            continue
        face = np.zeros(15, dtype=np.float32)
        face[:4] = (x1, y1, x2 - x1, y2 - y1)
        # SCRFD and FaceRecognizerSF both consume the five points from image-left
        # to image-right: eye, eye, nose, mouth corner, mouth corner.
        face[4:14] = keypoints[index].reshape(-1)
        face[14] = scores[index]
        faces.append(face)
    return faces


class SCRFDTensorRTDetector:
    """Fixed 640x640 SCRFD TensorRT detector for Jetson."""

    def __init__(
        self,
        model_path: str | Path,
        *,
        input_size: int = 640,
        nms_threshold: float = 0.4,
    ) -> None:
        engine_path = Path(model_path).expanduser().resolve()
        if not engine_path.is_file():
            raise FileNotFoundError(f"SCRFD TensorRT 模型不存在: {engine_path}")
        try:
            import tensorrt as trt
            import torch
        except ImportError as exc:
            raise ImportError("SCRFD TensorRT 需要 TensorRT 和 CUDA 版 PyTorch") from exc
        if not torch.cuda.is_available():
            raise RuntimeError("SCRFD TensorRT 需要 CUDA，但当前 torch.cuda 不可用")

        self._trt = trt
        self._torch = torch
        self._input_size = max(1, int(input_size))
        self._nms_threshold = min(1.0, max(0.0, float(nms_threshold)))
        self._device = "cuda:0"
        self._lock = Lock()
        self._logger = trt.Logger(trt.Logger.ERROR)
        self._runtime = trt.Runtime(self._logger)
        self._engine = self._runtime.deserialize_cuda_engine(engine_path.read_bytes())
        if self._engine is None:
            raise RuntimeError(f"SCRFD TensorRT 引擎反序列化失败: {engine_path}")
        self._context = self._engine.create_execution_context()
        if self._context is None:
            raise RuntimeError("SCRFD TensorRT 执行上下文创建失败")

        input_names: list[str] = []
        output_names: list[str] = []
        for index in range(self._engine.num_io_tensors):
            name = self._engine.get_tensor_name(index)
            mode = self._engine.get_tensor_mode(name)
            if mode == trt.TensorIOMode.INPUT:
                input_names.append(name)
            else:
                output_names.append(name)
        if len(input_names) != 1 or len(output_names) != 9:
            raise ValueError(
                "SCRFD TensorRT I/O 数量不匹配: "
                f"inputs={len(input_names)}, outputs={len(output_names)}"
            )
        self._input_name = input_names[0]
        input_shape = tuple(self._engine.get_tensor_shape(self._input_name))
        expected_input_shape = (1, 3, self._input_size, self._input_size)
        if input_shape != expected_input_shape:
            raise ValueError(
                f"SCRFD TensorRT 输入形状不匹配: engine={input_shape}, expected={expected_input_shape}"
            )

        grouped: dict[int, list[tuple[int, str]]] = {1: [], 4: [], 10: []}
        self._output_tensors: dict[str, Any] = {}
        for name in output_names:
            shape = tuple(int(value) for value in self._engine.get_tensor_shape(name))
            if len(shape) != 2 or shape[1] not in grouped:
                raise ValueError(f"SCRFD TensorRT 输出形状不支持: name={name}, shape={shape}")
            grouped[shape[1]].append((shape[0], name))
            dtype = self._torch_dtype(self._engine.get_tensor_dtype(name))
            self._output_tensors[name] = torch.empty(shape, dtype=dtype, device=self._device)

        for values in grouped.values():
            values.sort(reverse=True)
        if any(len(values) != 3 for values in grouped.values()):
            raise ValueError(f"SCRFD TensorRT 输出分组不完整: {grouped}")
        self._prediction_names: dict[int, tuple[str, str, str]] = {}
        for level, stride in enumerate((8, 16, 32)):
            expected_rows = 2 * (self._input_size // stride) ** 2
            rows = {grouped[width][level][0] for width in (1, 4, 10)}
            if rows != {expected_rows}:
                raise ValueError(
                    f"SCRFD TensorRT stride={stride} 输出行数不匹配: {sorted(rows)}"
                )
            self._prediction_names[stride] = (
                grouped[1][level][1],
                grouped[4][level][1],
                grouped[10][level][1],
            )

        input_dtype = self._torch_dtype(self._engine.get_tensor_dtype(self._input_name))
        self._input_tensor = torch.empty(
            expected_input_shape, dtype=input_dtype, device=self._device
        )
        if not self._context.set_tensor_address(
            self._input_name, self._input_tensor.data_ptr()
        ):
            raise RuntimeError("SCRFD TensorRT 输入地址绑定失败")
        for name, tensor in self._output_tensors.items():
            if not self._context.set_tensor_address(name, tensor.data_ptr()):
                raise RuntimeError(f"SCRFD TensorRT 输出地址绑定失败: {name}")

    def _torch_dtype(self, dtype: Any) -> Any:
        mapping = {
            self._trt.float16: self._torch.float16,
            self._trt.float32: self._torch.float32,
            self._trt.int32: self._torch.int32,
            self._trt.int64: self._torch.int64,
        }
        if dtype not in mapping:
            raise TypeError(f"SCRFD TensorRT 不支持的数据类型: {dtype}")
        return mapping[dtype]

    def detect(self, image: np.ndarray, *, score_threshold: float) -> list[np.ndarray]:
        if image.ndim != 3 or image.shape[2] != 3:
            raise ValueError("SCRFD 需要 BGR 三通道图像")
        blob, scale = _letterbox_blob(image, self._input_size)
        with self._lock, self._torch.inference_mode():
            self._input_tensor.copy_(self._torch.from_numpy(blob))
            stream = self._torch.cuda.current_stream(device=self._device)
            if not self._context.execute_async_v3(stream_handle=stream.cuda_stream):
                raise RuntimeError("SCRFD TensorRT 推理执行失败")
            predictions: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
            for stride, names in self._prediction_names.items():
                predictions[stride] = tuple(
                    self._output_tensors[name].float().cpu().numpy() for name in names
                )  # type: ignore[assignment]

        return decode_scrfd_predictions(
            predictions,
            input_size=self._input_size,
            image_shape=image.shape[:2],
            scale=scale,
            score_threshold=score_threshold,
            nms_threshold=self._nms_threshold,
        )
