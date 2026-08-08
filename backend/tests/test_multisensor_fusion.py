from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.multisensor_fusion import MultiSensorFusionService


def _calibration() -> dict:
    return {
        "version": "test-v1",
        "calibrated_at": "2026-08-06T00:00:00Z",
        "visible_frame_id": "visible_camera",
        "thermal_frame_id": "thermal_camera",
        "lidar_frame_id": "livox_frame",
        "visible_intrinsics": {
            "width": 100,
            "height": 100,
            "fx": 100.0,
            "fy": 100.0,
            "cx": 50.0,
            "cy": 50.0,
        },
        "thermal_resolution": {"width": 100, "height": 100},
        "lidar_to_visible": {
            "rotation": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            "translation_m": [0.0, 0.0, 0.0],
        },
        "thermal_to_visible_homography": [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ],
        "gimbal_reference": {
            "yaw_deg": 0.0,
            "pitch_deg": 0.0,
            "zoom_ratio": 1.0,
        },
    }


def _service(path: Path) -> MultiSensorFusionService:
    service = MultiSensorFusionService(
        enabled=True,
        calibration_path=path,
        sync_tolerance_seconds=0.08,
        sample_max_age_seconds=2.0,
        queue_size=10,
        min_target_points=5,
        cluster_gap_m=0.35,
        gimbal_tolerance_deg=1.0,
        zoom_tolerance_ratio=0.02,
    )
    service.update_calibration(_calibration())
    return service


def _visible(service: MultiSensorFusionService, timestamp: float, now: float):
    return service.ingest_visible(
        timestamp=timestamp,
        monotonic_at=now,
        detections=[
            SimpleNamespace(
                label="person",
                confidence=0.91,
                track_id=7,
                bbox=(45, 45, 55, 55),
            )
        ],
        width=100,
        height=100,
        gimbal={"yaw_deg": 0.0, "pitch_deg": 0.0, "zoom_ratio": 1.0},
    )


def _points() -> list[tuple[float, float, float]]:
    foreground = [
        (-0.12, -0.08, 5.00),
        (-0.08, 0.06, 5.02),
        (0.00, 0.00, 5.01),
        (0.07, -0.04, 4.99),
        (0.12, 0.08, 5.03),
        (0.04, 0.02, 5.00),
    ]
    background = [
        (-0.1, 0.0, 8.0),
        (0.0, 0.0, 8.1),
        (0.1, 0.0, 8.05),
        (0.0, 0.1, 8.0),
        (0.0, -0.1, 8.1),
    ]
    return foreground + background + [(10.0, 10.0, 2.0)]


def test_three_sources_sync_and_emit_nearest_3d_target(tmp_path: Path) -> None:
    service = _service(tmp_path / "calibration.json")
    now = time.monotonic()

    assert _visible(service, 100.00, now) is None
    assert service.ingest_thermal(
        timestamp=100.03,
        monotonic_at=now + 0.01,
        width=100,
        height=100,
    ) is None
    bundle = service.ingest_lidar(
        timestamp=100.01,
        monotonic_at=now + 0.02,
        points=_points(),
        frame_id="livox_frame",
    )

    assert bundle is not None
    assert bundle.delta_seconds == pytest.approx(0.03)
    targets = service.get_targets()
    assert len(targets) == 1
    assert targets[0]["track_id"] == 7
    assert targets[0]["lidar_xyz_m"][2] == pytest.approx(5.005, abs=0.02)
    assert targets[0]["point_count"] == 6
    assert targets[0]["thermal_bbox"] == [45.0, 45.0, 55.0, 55.0]
    status = service.get_status()
    assert status["state"] == "ready"
    assert status["synchronization"]["bundles"] == 1
    assert status["synchronization"]["last_delta_ms"] == pytest.approx(30.0)
    assert status["acceptance"]["coordinate_accuracy_verified"] is False


def test_samples_outside_sync_window_are_not_paired(tmp_path: Path) -> None:
    service = _service(tmp_path / "calibration.json")
    now = time.monotonic()

    _visible(service, 100.0, now)
    service.ingest_thermal(
        timestamp=100.2,
        monotonic_at=now + 0.01,
        width=100,
        height=100,
    )
    bundle = service.ingest_lidar(
        timestamp=100.4,
        monotonic_at=now + 0.02,
        points=_points(),
        frame_id="livox_frame",
    )

    assert bundle is None
    assert service.get_status()["state"] == "synchronizing"
    assert service.get_targets() == []


def test_gimbal_pose_mismatch_blocks_coordinate_output(tmp_path: Path) -> None:
    service = _service(tmp_path / "calibration.json")
    now = time.monotonic()
    service.ingest_visible(
        timestamp=200.0,
        monotonic_at=now,
        detections=[
            SimpleNamespace(
                label="person",
                confidence=0.9,
                track_id=1,
                bbox=(45, 45, 55, 55),
            )
        ],
        width=100,
        height=100,
        gimbal={"yaw_deg": 5.0, "pitch_deg": 0.0, "zoom_ratio": 1.0},
    )
    service.ingest_thermal(
        timestamp=200.0,
        monotonic_at=now + 0.01,
        width=100,
        height=100,
    )
    service.ingest_lidar(
        timestamp=200.0,
        monotonic_at=now + 0.02,
        points=_points(),
        frame_id="livox_frame",
    )

    assert service.get_targets() == []
    assert "偏航角偏离标定姿态" in service.get_status()["fusion"]["reason"]


def test_invalid_rotation_is_rejected_without_overwriting_file(tmp_path: Path) -> None:
    path = tmp_path / "calibration.json"
    service = _service(path)
    original = path.read_text(encoding="utf-8")
    invalid = _calibration()
    invalid["lidar_to_visible"]["rotation"] = [
        [2.0, 0.0, 0.0],
        [0.0, 2.0, 0.0],
        [0.0, 0.0, 2.0],
    ]

    with pytest.raises(ValueError, match="不是有效旋转矩阵"):
        service.update_calibration(invalid)

    assert path.read_text(encoding="utf-8") == original


def test_missing_calibration_is_reported_without_fake_targets(tmp_path: Path) -> None:
    service = MultiSensorFusionService(
        enabled=True,
        calibration_path=tmp_path / "missing.json",
        sync_tolerance_seconds=0.08,
        sample_max_age_seconds=2.0,
        queue_size=10,
        min_target_points=5,
        cluster_gap_m=0.35,
        gimbal_tolerance_deg=1.0,
        zoom_tolerance_ratio=0.02,
    )

    status = service.get_status()
    assert status["state"] == "calibration_required"
    assert status["calibration"]["ready"] is False
    assert "标定文件不存在" in status["detail"]


def test_coordinate_acceptance_requires_recorded_rmse_and_max_error(tmp_path: Path) -> None:
    service = _service(tmp_path / "calibration.json")
    calibration = _calibration()
    calibration["coordinate_validation"] = {
        "sample_count": 20,
        "rmse_m": 0.04,
        "max_error_m": 0.05,
        "validated_at": "2026-08-06T12:00:00Z",
    }

    service.update_calibration(calibration)

    acceptance = service.get_status()["acceptance"]
    assert acceptance["coordinate_accuracy_verified"] is True
    assert acceptance["sample_count"] == 20
