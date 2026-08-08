"""雷达、可见光和热成像的近似时间同步与目标坐标融合。"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from .config import settings


class SensorSource(str, Enum):
    LIDAR = "lidar"
    VISIBLE = "visible"
    THERMAL = "thermal"


@dataclass(frozen=True)
class TimedSensorSample:
    source: SensorSource
    timestamp: float
    monotonic_at: float
    sequence: int
    frame_id: str
    payload: Any


@dataclass(frozen=True)
class SynchronizedBundle:
    bundle_id: int
    lidar: TimedSensorSample
    visible: TimedSensorSample
    thermal: TimedSensorSample
    delta_seconds: float


@dataclass(frozen=True)
class CameraIntrinsics:
    width: int
    height: int
    fx: float
    fy: float
    cx: float
    cy: float


@dataclass(frozen=True)
class GimbalReference:
    yaw_deg: float
    pitch_deg: float
    zoom_ratio: float


@dataclass(frozen=True)
class CoordinateValidation:
    sample_count: int
    rmse_m: float
    max_error_m: float
    validated_at: str


@dataclass(frozen=True)
class MultisensorCalibration:
    version: str
    calibrated_at: str
    visible_frame_id: str
    thermal_frame_id: str
    lidar_frame_id: str
    visible_intrinsics: CameraIntrinsics
    thermal_width: int
    thermal_height: int
    lidar_to_visible_rotation: np.ndarray
    lidar_to_visible_translation_m: np.ndarray
    thermal_to_visible_homography: np.ndarray
    gimbal_reference: GimbalReference
    coordinate_validation: CoordinateValidation | None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MultisensorCalibration":
        if not isinstance(value, dict):
            raise ValueError("标定文件根节点必须是对象")

        intrinsics_raw = _required_dict(value, "visible_intrinsics")
        transform_raw = _required_dict(value, "lidar_to_visible")
        gimbal_raw = _required_dict(value, "gimbal_reference")
        thermal_resolution_raw = _required_dict(value, "thermal_resolution")
        intrinsics = CameraIntrinsics(
            width=_positive_int(intrinsics_raw, "width"),
            height=_positive_int(intrinsics_raw, "height"),
            fx=_positive_float(intrinsics_raw, "fx"),
            fy=_positive_float(intrinsics_raw, "fy"),
            cx=_finite_float(intrinsics_raw, "cx"),
            cy=_finite_float(intrinsics_raw, "cy"),
        )
        rotation = _matrix(transform_raw.get("rotation"), 3, 3, "lidar_to_visible.rotation")
        translation = _vector(
            transform_raw.get("translation_m"),
            3,
            "lidar_to_visible.translation_m",
        )
        homography = _matrix(
            value.get("thermal_to_visible_homography"),
            3,
            3,
            "thermal_to_visible_homography",
        )
        determinant = float(np.linalg.det(rotation))
        orthonormal = np.allclose(
            rotation.T @ rotation,
            np.eye(3, dtype=np.float64),
            atol=0.05,
        )
        if abs(determinant - 1.0) > 0.05 or not orthonormal:
            raise ValueError("lidar_to_visible.rotation 不是有效旋转矩阵")
        if abs(float(np.linalg.det(homography))) <= 1e-9:
            raise ValueError("thermal_to_visible_homography 不可逆")

        validation_raw = value.get("coordinate_validation")
        coordinate_validation = None
        if validation_raw is not None:
            if not isinstance(validation_raw, dict):
                raise ValueError("coordinate_validation 必须是对象或 null")
            coordinate_validation = CoordinateValidation(
                sample_count=_positive_int(validation_raw, "sample_count"),
                rmse_m=_nonnegative_float(validation_raw, "rmse_m"),
                max_error_m=_nonnegative_float(validation_raw, "max_error_m"),
                validated_at=_required_text(validation_raw, "validated_at"),
            )

        return cls(
            version=_required_text(value, "version"),
            calibrated_at=_required_text(value, "calibrated_at"),
            visible_frame_id=_required_text(value, "visible_frame_id"),
            thermal_frame_id=_required_text(value, "thermal_frame_id"),
            lidar_frame_id=_required_text(value, "lidar_frame_id"),
            visible_intrinsics=intrinsics,
            thermal_width=_positive_int(thermal_resolution_raw, "width"),
            thermal_height=_positive_int(thermal_resolution_raw, "height"),
            lidar_to_visible_rotation=rotation,
            lidar_to_visible_translation_m=translation,
            thermal_to_visible_homography=homography,
            gimbal_reference=GimbalReference(
                yaw_deg=_finite_float(gimbal_raw, "yaw_deg"),
                pitch_deg=_finite_float(gimbal_raw, "pitch_deg"),
                zoom_ratio=_positive_float(gimbal_raw, "zoom_ratio"),
            ),
            coordinate_validation=coordinate_validation,
        )

    def as_dict(self) -> dict[str, Any]:
        result = {
            "version": self.version,
            "calibrated_at": self.calibrated_at,
            "visible_frame_id": self.visible_frame_id,
            "thermal_frame_id": self.thermal_frame_id,
            "lidar_frame_id": self.lidar_frame_id,
            "visible_intrinsics": {
                "width": self.visible_intrinsics.width,
                "height": self.visible_intrinsics.height,
                "fx": self.visible_intrinsics.fx,
                "fy": self.visible_intrinsics.fy,
                "cx": self.visible_intrinsics.cx,
                "cy": self.visible_intrinsics.cy,
            },
            "thermal_resolution": {
                "width": self.thermal_width,
                "height": self.thermal_height,
            },
            "lidar_to_visible": {
                "rotation": self.lidar_to_visible_rotation.tolist(),
                "translation_m": self.lidar_to_visible_translation_m.tolist(),
            },
            "thermal_to_visible_homography": (
                self.thermal_to_visible_homography.tolist()
            ),
            "gimbal_reference": {
                "yaw_deg": self.gimbal_reference.yaw_deg,
                "pitch_deg": self.gimbal_reference.pitch_deg,
                "zoom_ratio": self.gimbal_reference.zoom_ratio,
            },
        }
        result["coordinate_validation"] = (
            {
                "sample_count": self.coordinate_validation.sample_count,
                "rmse_m": self.coordinate_validation.rmse_m,
                "max_error_m": self.coordinate_validation.max_error_m,
                "validated_at": self.coordinate_validation.validated_at,
            }
            if self.coordinate_validation is not None
            else None
        )
        return result


@dataclass(frozen=True)
class FusedTarget:
    bundle_id: int
    track_id: int
    label: str
    confidence: float
    visible_bbox: tuple[int, int, int, int]
    thermal_bbox: tuple[float, float, float, float] | None
    lidar_xyz_m: tuple[float, float, float]
    camera_xyz_m: tuple[float, float, float]
    distance_m: float
    point_count: int
    depth_spread_m: float
    lidar_frame_id: str
    visible_frame_id: str
    timestamp: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "track_id": self.track_id,
            "label": self.label,
            "confidence": round(self.confidence, 4),
            "visible_bbox": list(self.visible_bbox),
            "thermal_bbox": (
                [round(value, 2) for value in self.thermal_bbox]
                if self.thermal_bbox is not None
                else None
            ),
            "lidar_xyz_m": [round(value, 4) for value in self.lidar_xyz_m],
            "camera_xyz_m": [round(value, 4) for value in self.camera_xyz_m],
            "distance_m": round(self.distance_m, 4),
            "point_count": self.point_count,
            "depth_spread_m": round(self.depth_spread_m, 4),
            "lidar_frame_id": self.lidar_frame_id,
            "visible_frame_id": self.visible_frame_id,
            "timestamp": self.timestamp,
        }


class ApproximateTimeSynchronizer:
    """使用设备时间戳配对三路样本；同一样本最多消费一次。"""

    def __init__(
        self,
        *,
        tolerance_seconds: float,
        max_age_seconds: float,
        queue_size: int,
    ) -> None:
        self.tolerance_seconds = max(0.001, float(tolerance_seconds))
        self.max_age_seconds = max(self.tolerance_seconds, float(max_age_seconds))
        self._queues = {
            source: deque(maxlen=max(3, int(queue_size))) for source in SensorSource
        }
        self._next_bundle_id = 1

    def add(self, sample: TimedSensorSample) -> SynchronizedBundle | None:
        self._queues[sample.source].append(sample)
        self._prune(sample.monotonic_at)
        if any(not queue for queue in self._queues.values()):
            return None

        matches: dict[SensorSource, tuple[int, TimedSensorSample]] = {
            sample.source: (len(self._queues[sample.source]) - 1, sample)
        }
        for source, queue in self._queues.items():
            if source is sample.source:
                continue
            index, candidate = min(
                enumerate(queue),
                key=lambda item: abs(item[1].timestamp - sample.timestamp),
            )
            matches[source] = (index, candidate)

        timestamps = [item.timestamp for _, item in matches.values()]
        delta_seconds = max(timestamps) - min(timestamps)
        if delta_seconds > self.tolerance_seconds:
            return None

        selected = {source: item for source, (_, item) in matches.items()}
        for source, (index, _) in matches.items():
            queue = self._queues[source]
            for _ in range(index + 1):
                queue.popleft()

        bundle = SynchronizedBundle(
            bundle_id=self._next_bundle_id,
            lidar=selected[SensorSource.LIDAR],
            visible=selected[SensorSource.VISIBLE],
            thermal=selected[SensorSource.THERMAL],
            delta_seconds=delta_seconds,
        )
        self._next_bundle_id += 1
        return bundle

    def queue_depths(self) -> dict[str, int]:
        return {source.value: len(queue) for source, queue in self._queues.items()}

    def _prune(self, now_monotonic: float) -> None:
        for queue in self._queues.values():
            while queue and now_monotonic - queue[0].monotonic_at > self.max_age_seconds:
                queue.popleft()


class MultiSensorFusionService:
    def __init__(
        self,
        *,
        enabled: bool,
        calibration_path: Path,
        sync_tolerance_seconds: float,
        sample_max_age_seconds: float,
        queue_size: int,
        min_target_points: int,
        cluster_gap_m: float,
        gimbal_tolerance_deg: float,
        zoom_tolerance_ratio: float,
    ) -> None:
        self.enabled = bool(enabled)
        self.calibration_path = Path(calibration_path)
        self.sample_max_age_seconds = max(0.1, float(sample_max_age_seconds))
        self.min_target_points = max(1, int(min_target_points))
        self.cluster_gap_m = max(0.01, float(cluster_gap_m))
        self.gimbal_tolerance_deg = max(0.0, float(gimbal_tolerance_deg))
        self.zoom_tolerance_ratio = max(0.0, float(zoom_tolerance_ratio))
        self._synchronizer = ApproximateTimeSynchronizer(
            tolerance_seconds=sync_tolerance_seconds,
            max_age_seconds=sample_max_age_seconds,
            queue_size=queue_size,
        )
        self._lock = threading.RLock()
        self._sequence = 0
        self._received = {source: 0 for source in SensorSource}
        self._last_received: dict[SensorSource, TimedSensorSample] = {}
        self._bundle_count = 0
        self._last_bundle: SynchronizedBundle | None = None
        self._latest_targets: list[FusedTarget] = []
        self._last_fusion_reason = "尚未收到同步数据"
        self._calibration: MultisensorCalibration | None = None
        self._calibration_error: str | None = None
        self.reload_calibration()

    @classmethod
    def from_settings(cls) -> "MultiSensorFusionService":
        return cls(
            enabled=settings.MULTISENSOR_ENABLED,
            calibration_path=Path(settings.MULTISENSOR_CALIBRATION_PATH),
            sync_tolerance_seconds=settings.MULTISENSOR_SYNC_TOLERANCE_MS / 1000.0,
            sample_max_age_seconds=settings.MULTISENSOR_SAMPLE_MAX_AGE_SECONDS,
            queue_size=settings.MULTISENSOR_QUEUE_SIZE,
            min_target_points=settings.MULTISENSOR_MIN_TARGET_POINTS,
            cluster_gap_m=settings.MULTISENSOR_CLUSTER_GAP_M,
            gimbal_tolerance_deg=settings.MULTISENSOR_GIMBAL_TOLERANCE_DEG,
            zoom_tolerance_ratio=settings.MULTISENSOR_ZOOM_TOLERANCE_RATIO,
        )

    def reload_calibration(self) -> None:
        with self._lock:
            if not self.calibration_path.is_file():
                self._calibration = None
                self._calibration_error = f"标定文件不存在：{self.calibration_path}"
                return
            try:
                raw = json.loads(self.calibration_path.read_text(encoding="utf-8"))
                self._calibration = MultisensorCalibration.from_dict(raw)
                self._calibration_error = None
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                self._calibration = None
                self._calibration_error = f"标定文件无效：{exc}"

    def update_calibration(self, value: dict[str, Any]) -> dict[str, Any]:
        calibration = MultisensorCalibration.from_dict(value)
        serialized = json.dumps(
            calibration.as_dict(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        self.calibration_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.calibration_path.with_suffix(
            self.calibration_path.suffix + f".tmp-{os.getpid()}"
        )
        try:
            temporary.write_text(serialized + "\n", encoding="utf-8")
            temporary.replace(self.calibration_path)
        finally:
            temporary.unlink(missing_ok=True)
        with self._lock:
            self._calibration = calibration
            self._calibration_error = None
        return calibration.as_dict()

    def get_calibration(self) -> dict[str, Any] | None:
        with self._lock:
            return self._calibration.as_dict() if self._calibration is not None else None

    def ingest_visible(
        self,
        *,
        timestamp: float,
        monotonic_at: float,
        detections: Iterable[Any],
        width: int,
        height: int,
        frame_id: str = "visible_camera",
        gimbal: dict[str, float | None] | None = None,
    ) -> SynchronizedBundle | None:
        normalized_detections = []
        for item in detections:
            bbox = getattr(item, "bbox", None)
            if bbox is None:
                continue
            normalized_detections.append(
                {
                    "label": str(getattr(item, "label", getattr(item, "class_name", ""))),
                    "confidence": float(getattr(item, "confidence", 0.0)),
                    "track_id": int(getattr(item, "track_id", -1)),
                    "bbox": tuple(int(value) for value in bbox),
                }
            )
        return self._ingest(
            SensorSource.VISIBLE,
            timestamp=timestamp,
            monotonic_at=monotonic_at,
            frame_id=frame_id,
            payload={
                "width": int(width),
                "height": int(height),
                "detections": tuple(normalized_detections),
                "gimbal": dict(gimbal) if gimbal is not None else None,
            },
        )

    def ingest_thermal(
        self,
        *,
        timestamp: float,
        monotonic_at: float | None = None,
        width: int,
        height: int,
        frame_id: str = "thermal_camera",
        sequence: int | None = None,
    ) -> SynchronizedBundle | None:
        return self._ingest(
            SensorSource.THERMAL,
            timestamp=timestamp,
            monotonic_at=time.monotonic() if monotonic_at is None else monotonic_at,
            frame_id=frame_id,
            payload={"width": int(width), "height": int(height), "sequence": sequence},
        )

    def ingest_lidar(
        self,
        *,
        timestamp: float,
        monotonic_at: float | None = None,
        points: Iterable[Iterable[float]],
        frame_id: str,
    ) -> SynchronizedBundle | None:
        normalized_points = (
            points
            if isinstance(points, (list, tuple, np.ndarray))
            else list(points)
        )
        point_array = np.asarray(normalized_points, dtype=np.float32)
        if point_array.size == 0:
            point_array = np.empty((0, 3), dtype=np.float32)
        if point_array.ndim != 2 or point_array.shape[1] < 3:
            raise ValueError("雷达点必须是 N×3 数组")
        point_array = point_array[:, :3]
        point_array = point_array[np.isfinite(point_array).all(axis=1)]
        return self._ingest(
            SensorSource.LIDAR,
            timestamp=timestamp,
            monotonic_at=time.monotonic() if monotonic_at is None else monotonic_at,
            frame_id=frame_id,
            payload=point_array,
        )

    def _ingest(
        self,
        source: SensorSource,
        *,
        timestamp: float,
        monotonic_at: float,
        frame_id: str,
        payload: Any,
    ) -> SynchronizedBundle | None:
        if not self.enabled:
            return None
        timestamp = float(timestamp)
        monotonic_at = float(monotonic_at)
        if not math.isfinite(timestamp) or timestamp <= 0:
            raise ValueError("传感器时间戳必须是正的有限秒数")
        if not math.isfinite(monotonic_at):
            raise ValueError("monotonic_at 必须是有限秒数")
        with self._lock:
            self._sequence += 1
            sample = TimedSensorSample(
                source=source,
                timestamp=timestamp,
                monotonic_at=monotonic_at,
                sequence=self._sequence,
                frame_id=str(frame_id).strip() or source.value,
                payload=payload,
            )
            self._received[source] += 1
            self._last_received[source] = sample
            bundle = self._synchronizer.add(sample)
            if bundle is None:
                return None
            self._bundle_count += 1
            self._last_bundle = bundle
            self._latest_targets = self._fuse_targets(bundle)
            return bundle

    def _fuse_targets(self, bundle: SynchronizedBundle) -> list[FusedTarget]:
        calibration = self._calibration
        if calibration is None:
            self._last_fusion_reason = self._calibration_error or "缺少标定"
            return []
        if bundle.lidar.frame_id != calibration.lidar_frame_id:
            self._last_fusion_reason = (
                "雷达坐标系不匹配："
                f"sample={bundle.lidar.frame_id} calibration={calibration.lidar_frame_id}"
            )
            return []
        if bundle.visible.frame_id != calibration.visible_frame_id:
            self._last_fusion_reason = (
                "可见光坐标系不匹配："
                f"sample={bundle.visible.frame_id} calibration={calibration.visible_frame_id}"
            )
            return []
        if bundle.thermal.frame_id != calibration.thermal_frame_id:
            self._last_fusion_reason = (
                "热成像坐标系不匹配："
                f"sample={bundle.thermal.frame_id} calibration={calibration.thermal_frame_id}"
            )
            return []

        intrinsics = calibration.visible_intrinsics
        visible_payload = bundle.visible.payload
        if (
            int(visible_payload.get("width", 0)) != intrinsics.width
            or int(visible_payload.get("height", 0)) != intrinsics.height
        ):
            self._last_fusion_reason = "可见光分辨率与标定内参不一致，拒绝输出三维坐标"
            return []
        thermal_payload = bundle.thermal.payload
        if (
            int(thermal_payload.get("width", 0)) != calibration.thermal_width
            or int(thermal_payload.get("height", 0)) != calibration.thermal_height
        ):
            self._last_fusion_reason = "热成像分辨率与标定单应矩阵不一致，拒绝融合"
            return []

        gimbal = bundle.visible.payload.get("gimbal")
        gimbal_reason = self._validate_gimbal(gimbal, calibration.gimbal_reference)
        if gimbal_reason is not None:
            self._last_fusion_reason = gimbal_reason
            return []

        points_lidar = bundle.lidar.payload
        if len(points_lidar) == 0:
            self._last_fusion_reason = "同步雷达帧没有有效点"
            return []
        rotation = calibration.lidar_to_visible_rotation
        translation = calibration.lidar_to_visible_translation_m
        points_camera = points_lidar @ rotation.T + translation
        positive_depth = points_camera[:, 2] > 0.05
        if not positive_depth.any():
            self._last_fusion_reason = "雷达点均不在相机前方"
            return []

        u = np.full(len(points_camera), np.nan, dtype=np.float64)
        v = np.full(len(points_camera), np.nan, dtype=np.float64)
        u[positive_depth] = (
            intrinsics.fx * points_camera[positive_depth, 0]
            / points_camera[positive_depth, 2]
            + intrinsics.cx
        )
        v[positive_depth] = (
            intrinsics.fy * points_camera[positive_depth, 1]
            / points_camera[positive_depth, 2]
            + intrinsics.cy
        )

        targets: list[FusedTarget] = []
        for detection in bundle.visible.payload.get("detections", ()):
            x1, y1, x2, y2 = detection["bbox"]
            mask = positive_depth & (u >= x1) & (u <= x2) & (v >= y1) & (v <= y2)
            indexes = np.flatnonzero(mask)
            selected = self._nearest_depth_cluster(indexes, points_camera[:, 2])
            if len(selected) < self.min_target_points:
                continue
            lidar_center = np.median(points_lidar[selected], axis=0)
            camera_center = np.median(points_camera[selected], axis=0)
            depths = points_camera[selected, 2]
            targets.append(
                FusedTarget(
                    bundle_id=bundle.bundle_id,
                    track_id=int(detection["track_id"]),
                    label=str(detection["label"]),
                    confidence=float(detection["confidence"]),
                    visible_bbox=tuple(int(value) for value in detection["bbox"]),
                    thermal_bbox=self._visible_to_thermal_bbox(
                        detection["bbox"], calibration.thermal_to_visible_homography
                    ),
                    lidar_xyz_m=tuple(float(value) for value in lidar_center),
                    camera_xyz_m=tuple(float(value) for value in camera_center),
                    distance_m=float(np.linalg.norm(lidar_center)),
                    point_count=int(len(selected)),
                    depth_spread_m=float(np.percentile(depths, 90) - np.percentile(depths, 10)),
                    lidar_frame_id=bundle.lidar.frame_id,
                    visible_frame_id=calibration.visible_frame_id,
                    timestamp=bundle.visible.timestamp,
                )
            )
        self._last_fusion_reason = (
            f"已输出 {len(targets)} 个三维目标"
            if targets
            else "同步成功，但目标框内有效雷达点不足"
        )
        return targets

    def _nearest_depth_cluster(self, indexes: np.ndarray, depths: np.ndarray) -> np.ndarray:
        if len(indexes) < self.min_target_points:
            return np.empty(0, dtype=np.int64)
        ordered = indexes[np.argsort(depths[indexes])]
        clusters: list[np.ndarray] = []
        start = 0
        ordered_depths = depths[ordered]
        for index in range(1, len(ordered)):
            if ordered_depths[index] - ordered_depths[index - 1] > self.cluster_gap_m:
                clusters.append(ordered[start:index])
                start = index
        clusters.append(ordered[start:])
        for cluster in clusters:
            if len(cluster) >= self.min_target_points:
                return cluster
        return np.empty(0, dtype=np.int64)

    def _validate_gimbal(
        self,
        gimbal: dict[str, float | None] | None,
        reference: GimbalReference,
    ) -> str | None:
        if gimbal is None:
            return "没有可见光帧对应的云台姿态，拒绝输出三维坐标"
        try:
            yaw = float(gimbal["yaw_deg"])
            pitch = float(gimbal["pitch_deg"])
            zoom = float(gimbal["zoom_ratio"])
        except (KeyError, TypeError, ValueError):
            return "云台姿态或变焦数据不完整，拒绝输出三维坐标"
        if abs(yaw - reference.yaw_deg) > self.gimbal_tolerance_deg:
            return "云台偏航角偏离标定姿态，拒绝输出三维坐标"
        if abs(pitch - reference.pitch_deg) > self.gimbal_tolerance_deg:
            return "云台俯仰角偏离标定姿态，拒绝输出三维坐标"
        zoom_error = abs(zoom - reference.zoom_ratio) / reference.zoom_ratio
        if zoom_error > self.zoom_tolerance_ratio:
            return "相机变焦偏离标定倍率，拒绝输出三维坐标"
        return None

    def _visible_to_thermal_bbox(
        self,
        bbox: Iterable[int],
        thermal_to_visible: np.ndarray,
    ) -> tuple[float, float, float, float] | None:
        try:
            visible_to_thermal = np.linalg.inv(thermal_to_visible)
        except np.linalg.LinAlgError:
            return None
        x1, y1, x2, y2 = (float(value) for value in bbox)
        corners = np.asarray(
            [[x1, y1, 1.0], [x2, y1, 1.0], [x1, y2, 1.0], [x2, y2, 1.0]],
            dtype=np.float64,
        )
        mapped = corners @ visible_to_thermal.T
        valid = np.abs(mapped[:, 2]) > 1e-9
        if not valid.all():
            return None
        mapped_xy = mapped[:, :2] / mapped[:, 2:3]
        return (
            float(mapped_xy[:, 0].min()),
            float(mapped_xy[:, 1].min()),
            float(mapped_xy[:, 0].max()),
            float(mapped_xy[:, 1].max()),
        )

    def get_targets(self) -> list[dict[str, Any]]:
        with self._lock:
            return [target.as_dict() for target in self._latest_targets]

    def get_status(self) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            sources: dict[str, Any] = {}
            fresh_sources = 0
            for source in SensorSource:
                sample = self._last_received.get(source)
                age = now - sample.monotonic_at if sample is not None else None
                fresh = age is not None and age <= self.sample_max_age_seconds
                fresh_sources += int(fresh)
                sources[source.value] = {
                    "received": self._received[source],
                    "last_timestamp": sample.timestamp if sample is not None else None,
                    "last_age_seconds": round(age, 3) if age is not None else None,
                    "fresh": fresh,
                    "frame_id": sample.frame_id if sample is not None else None,
                }

            if not self.enabled:
                state = "disabled"
                detail = "MULTISENSOR_ENABLED=false"
            elif self._calibration is None:
                state = "calibration_required"
                detail = self._calibration_error or "缺少多源标定"
            elif fresh_sources < len(SensorSource):
                state = "waiting_sources"
                missing = [name for name, item in sources.items() if not item["fresh"]]
                detail = f"等待新鲜数据源：{', '.join(missing)}"
            elif self._last_bundle is None:
                state = "synchronizing"
                detail = "三路数据已到达，尚未配对到同步时间窗"
            else:
                state = "ready"
                detail = self._last_fusion_reason

            return {
                "enabled": self.enabled,
                "state": state,
                "detail": detail,
                "sources": sources,
                "calibration": {
                    "ready": self._calibration is not None,
                    "path": str(self.calibration_path),
                    "version": (
                        self._calibration.version if self._calibration is not None else None
                    ),
                    "error": self._calibration_error,
                },
                "synchronization": {
                    "tolerance_ms": round(
                        self._synchronizer.tolerance_seconds * 1000.0, 3
                    ),
                    "bundles": self._bundle_count,
                    "last_delta_ms": (
                        round(self._last_bundle.delta_seconds * 1000.0, 3)
                        if self._last_bundle is not None
                        else None
                    ),
                    "queue_depths": self._synchronizer.queue_depths(),
                },
                "fusion": {
                    "target_count": len(self._latest_targets),
                    "reason": self._last_fusion_reason,
                },
                "acceptance": self._acceptance_status(),
            }

    def _acceptance_status(self) -> dict[str, Any]:
        limit_m = 0.05
        validation = (
            self._calibration.coordinate_validation
            if self._calibration is not None
            else None
        )
        verified = (
            validation is not None
            and validation.rmse_m <= limit_m
            and validation.max_error_m <= limit_m
        )
        return {
            "coordinate_error_limit_m": limit_m,
            "coordinate_accuracy_verified": verified,
            "sample_count": validation.sample_count if validation is not None else 0,
            "rmse_m": validation.rmse_m if validation is not None else None,
            "max_error_m": validation.max_error_m if validation is not None else None,
            "validated_at": validation.validated_at if validation is not None else None,
            "detail": (
                "现场独立测量结果满足 RMSE 和最大误差均不超过 5 cm"
                if verified
                else "尚无满足 RMSE 和最大误差均不超过 5 cm 的现场验证记录"
            ),
        }


def _required_dict(value: dict[str, Any], key: str) -> dict[str, Any]:
    result = value.get(key)
    if not isinstance(result, dict):
        raise ValueError(f"{key} 必须是对象")
    return result


def _required_text(value: dict[str, Any], key: str) -> str:
    result = str(value.get(key, "")).strip()
    if not result:
        raise ValueError(f"{key} 不能为空")
    return result


def _finite_float(value: dict[str, Any], key: str) -> float:
    try:
        result = float(value[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{key} 必须是数字") from exc
    if not math.isfinite(result):
        raise ValueError(f"{key} 必须是有限数字")
    return result


def _positive_float(value: dict[str, Any], key: str) -> float:
    result = _finite_float(value, key)
    if result <= 0:
        raise ValueError(f"{key} 必须大于 0")
    return result


def _nonnegative_float(value: dict[str, Any], key: str) -> float:
    result = _finite_float(value, key)
    if result < 0:
        raise ValueError(f"{key} 不能小于 0")
    return result


def _positive_int(value: dict[str, Any], key: str) -> int:
    try:
        result = int(value[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{key} 必须是整数") from exc
    if result <= 0:
        raise ValueError(f"{key} 必须大于 0")
    return result


def _matrix(value: Any, rows: int, columns: int, label: str) -> np.ndarray:
    try:
        result = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} 必须是 {rows}×{columns} 数字矩阵") from exc
    if result.shape != (rows, columns) or not np.isfinite(result).all():
        raise ValueError(f"{label} 必须是 {rows}×{columns} 有限数字矩阵")
    return result


def _vector(value: Any, length: int, label: str) -> np.ndarray:
    try:
        result = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} 必须是长度 {length} 的数字数组") from exc
    if result.shape != (length,) or not np.isfinite(result).all():
        raise ValueError(f"{label} 必须是长度 {length} 的有限数字数组")
    return result


_multisensor_fusion_service: MultiSensorFusionService | None = None


def get_multisensor_fusion_service() -> MultiSensorFusionService | None:
    return _multisensor_fusion_service


def set_multisensor_fusion_service(service: MultiSensorFusionService | None) -> None:
    global _multisensor_fusion_service
    _multisensor_fusion_service = service
