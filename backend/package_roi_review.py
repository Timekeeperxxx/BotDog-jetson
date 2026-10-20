"""Optional current-frame bag/nonbag review; no person or motion inference."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

import cv2
import numpy as np

from .abandoned_package import PACKAGE_LABELS

_REVIEW_MEAN = [.485, .456, .406]
_REVIEW_STD = [.229, .224, .225]


def review_patch(image, box):
    values = np.asarray(box, dtype=float)
    if values.shape != (4,) or not np.isfinite(values).all():
        raise ValueError("包复核框无效")
    height, width = image.shape[:2]
    x1, y1, x2, y2 = values
    if x2 <= x1 or y2 <= y1:
        return None
    cx, cy = (x1+x2)/2, (y1+y2)/2
    left, right = max(0, round(cx-(x2-x1)*.55)), min(width, round(cx+(x2-x1)*.55))
    top, bottom = max(0, round(cy-(y2-y1)*.55)), min(height, round(cy+(y2-y1)*.55))
    if right-left < 12 or bottom-top < 12:
        return None
    crop = image[top:bottom, left:right]
    scale = min(224/crop.shape[1], 224/crop.shape[0])
    crop = cv2.resize(crop, (max(1, round(crop.shape[1]*scale)), max(1, round(crop.shape[0]*scale))))
    canvas = np.full((224, 224, 3), 114, np.uint8)
    x, y = (224-crop.shape[1])//2, (224-crop.shape[0])//2
    canvas[y:y+crop.shape[0], x:x+crop.shape[1]] = crop
    return canvas


def long_axis_views(box):
    x1, y1, x2, y2 = box
    w, h = x2-x1, y2-y1
    if min(w, h) <= 0:
        return []
    if h >= 1.5*w:
        return [(x1, y1, x2, y1+h*2/3), (x1, y2-h*2/3, x2, y2)]
    if w >= 1.5*h:
        return [(x1, y1, x1+w*2/3, y2), (x2-w*2/3, y1, x2, y2)]
    return []


class PackageRoiReviewer:
    def __init__(self, model_path, metadata_path, device="auto"):
        model_path, metadata_path = Path(model_path), Path(metadata_path)
        if not model_path.is_file() or not metadata_path.is_file():
            raise FileNotFoundError("包复核模型及其校准元数据必须已存在")
        metadata = json.loads(metadata_path.read_text())
        output = metadata.get("output")
        quality_output = ["reject_candidate", "valid_package_candidate"]
        if output not in (["not_bag", "bag"], quality_output):
            raise ValueError("包复核模型类别顺序不匹配")
        self.review_policy = metadata.get("review_policy", "legacy_multiview")
        if self.review_policy not in {"legacy_multiview", "full_box"}:
            raise ValueError("包复核策略无效")
        if output == quality_output and self.review_policy != "full_box":
            raise ValueError("完整候选框质量模型必须使用 full_box 复核策略")
        runtime = metadata.get("runtime", {})
        if not isinstance(runtime, dict):
            raise ValueError("包复核运行策略无效")
        self.batch_policy = runtime.get("batch_policy", "calibrated")
        if self.batch_policy not in {"calibrated", "guarded_fp32"}:
            raise ValueError("包复核批次策略无效")
        if self.batch_policy == "guarded_fp32":
            point = metadata.get("operating_point", {})
            if (point.get("physical_batch") != 16 or point.get("calibration_precision") != "float32"
                    or runtime.get("reference_physical_batch") != 16
                    or runtime.get("guard_band") != .02 or runtime.get("compact_max_batch") != 8):
                raise ValueError("快速复核必须保留 FP32/16 校准基线和固定回退策略")
        specification = metadata.get("input", {})
        if (specification.get("size") != [224, 224] or specification.get("context") != 1.1
                or specification.get("color") != "RGB"
                or specification.get("mean") != _REVIEW_MEAN
                or specification.get("std") != _REVIEW_STD):
            raise ValueError("包复核预处理元数据不匹配")
        self.threshold = float(metadata["operating_point"]["threshold"])
        if not np.isfinite(self.threshold) or not 0 < self.threshold <= 1:
            raise ValueError("包复核阈值无效")
        digest = hashlib.sha256()
        with model_path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024*1024), b""):
                digest.update(block)
        actual_hash = digest.hexdigest()
        if actual_hash != metadata.get("sha256"):
            raise ValueError("包复核模型校验失败")
        import torch
        self.torch = torch
        if device == "auto":
            device = "cuda:0" if torch.cuda.is_available() else "cpu"
        elif str(device).isdigit():
            device = "cuda:"+str(device)
        self.device = device
        if self.batch_policy == "guarded_fp32" and not str(device).startswith("cuda"):
            raise ValueError("快速复核运行策略只适用于已验证的 CUDA 环境")
        self.model = torch.jit.load(str(model_path), map_location=device).eval()
        self.mean = torch.tensor(_REVIEW_MEAN, device=device).view(1, 3, 1, 1)
        self.std = torch.tensor(_REVIEW_STD, device=device).view(1, 3, 1, 1)
        self.last_status = {}
        self.warmup_status = {"completed": False, "elapsed_ms": 0.0}
        if str(device).startswith("cuda"):
            self.warmup()

    def _predict_batch(self, tensor):
        with self.torch.inference_mode(), self.torch.autocast(str(self.device).split(":")[0], enabled=False):
            output = self.model(tensor).cpu().numpy()
        if (output.shape != (len(tensor), 2) or not np.isfinite(output).all()
                or np.any(output < 0) or np.any(output > 1)
                or not np.allclose(output.sum(axis=1), 1, atol=1e-4)):
            raise ValueError("包复核模型输出无效")
        return output

    def warmup(self):
        if getattr(self, "warmup_status", {}).get("completed"):
            return
        started = time.monotonic()
        tensor = self.mean.new_zeros((16, 3, 224, 224))
        batches = [tensor, tensor.contiguous(memory_format=self.torch.channels_last)]
        if getattr(self, "batch_policy", "calibrated") == "guarded_fp32":
            batches.extend(tensor[:count] for count in range(1, 9))
        for batch in batches:
            for _ in range(3):
                self._predict_batch(batch)
        self.warmup_status = {"completed": True,
                              "elapsed_ms": round((time.monotonic()-started)*1000, 1)}

    def _score_batch(self, tensor):
        if not hasattr(self, "_batch_counts"):
            self._batch_counts = {"compact": 0, "reference": 0, "fallback": 0}
        if getattr(self, "batch_policy", "calibrated") == "guarded_fp32" and len(tensor) <= 8:
            output = self._predict_batch(tensor.contiguous())
            self._batch_counts["compact"] += 1
            lower, upper = np.float32(self.threshold-.02), np.float32(self.threshold+.02)
            if not np.any((output[:, 1] >= lower) & (output[:, 1] <= upper)):
                return output
            self._batch_counts["fallback"] += 1
        # The calibration reference is physical batch16 in the original padded layout.
        if len(tensor) < 16:
            tensor = self.torch.cat((tensor, tensor.new_zeros((16-len(tensor), 3, 224, 224))))
        output = self._predict_batch(tensor)
        self._batch_counts["reference"] += 1
        return output

    def _score_boxes(self, image, boxes):
        scores = [None]*len(boxes)
        crops, indices = [], []
        for index, box in enumerate(boxes):
            crop = review_patch(image, box)
            if crop is not None:
                crops.append(crop[:, :, ::-1].copy())
                indices.append(index)
        torch = self.torch
        for start in range(0, len(crops), 16):
            tensor = torch.from_numpy(np.stack(crops[start:start+16]).transpose(0, 3, 1, 2))
            tensor = (tensor.to(self.device, dtype=torch.float32)/255.-self.mean)/self.std
            output = self._score_batch(tensor)
            for index, probability in zip(indices[start:start+16], output[:, 1]):
                scores[index] = float(probability)
        return scores

    def filter(self, image, detections):
        if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
            raise ValueError("包复核需要当前帧 uint8 BGR 图像")
        self._batch_counts = {"compact": 0, "reference": 0, "fallback": 0}
        packages = [d for d in detections if d.label in PACKAGE_LABELS]
        scores = self._score_boxes(image, [d.bbox for d in packages])
        original_scores = list(scores)
        views, indices = [], []
        policy = getattr(self, "review_policy", "legacy_multiview")
        if policy == "legacy_multiview":
            for index, (detection, score) in enumerate(zip(packages, scores)):
                if score is None or score >= self.threshold:
                    continue
                for box in long_axis_views(detection.bbox):
                    views.append(box)
                    indices.append(index)
            for index, score in zip(indices, self._score_boxes(image, views)):
                if score is not None:
                    scores[index] = max(scores[index], score)
        accepted = {id(d) for d, p in zip(packages, scores) if p is not None and p >= self.threshold}
        self.last_status = {
            "review_policy": policy,
            "batch_policy": getattr(self, "batch_policy", "calibrated"),
            "batch_counts": dict(self._batch_counts),
            "threshold": self.threshold, "candidates": len(packages),
            "rejected": len(packages)-len(accepted), "extra_views": len(views),
            "rescued": sum(p is not None and old is not None and old < self.threshold <= p
                           for p, old in zip(scores, original_scores)),
        }
        return [d for d in detections if d.label not in PACKAGE_LABELS or id(d) in accepted]
