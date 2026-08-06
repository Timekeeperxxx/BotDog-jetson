from __future__ import annotations

import math
from pathlib import Path

import pytest

from backend import fence_detection_service as fence_runtime
from backend.fence_detection_service import (
    FenceBehavior,
    FenceDetectionService,
    FenceDetectionState,
    _SynchronizedSample,
    closest_point_on_segment,
)
from backend.pose_detection import PoseKeypoint, PoseObservation, Posture
from backend.services_nav_fences import (
    create_fence,
    delete_fence,
    list_fences,
    set_fence_enabled,
)
from backend.z2mini_gimbal import Z2MiniStatus


def _scene(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
    scene_id = "Scene01_Fence"
    scene_root = tmp_path / "maps"
    scene_dir = scene_root / scene_id
    scene_dir.mkdir(parents=True)
    (scene_dir / "ground.pcd").write_text("ground", encoding="utf-8")
    monkeypatch.setattr("backend.services_pcd_maps.settings.SCENE_MAP_ROOT", str(scene_root))
    monkeypatch.setattr("backend.services_nav_fences.settings.NAV_FENCE_STORE_DIR", str(tmp_path / "fences"))
    return scene_id


def _status(*, yaw: float = 0.0, pitch: float = 0.0) -> Z2MiniStatus:
    return Z2MiniStatus(
        connected=True,
        timestamp="2026-08-05T00:00:00.000Z",
        mode="angle",
        mode_code=0x10,
        relative_roll_deg=0.0,
        relative_pitch_deg=pitch,
        relative_yaw_deg=yaw,
        absolute_roll_deg=0.0,
        absolute_pitch_deg=pitch,
        absolute_yaw_deg=yaw % 360.0,
        angular_velocity_roll_dps=0.0,
        angular_velocity_pitch_dps=0.0,
        angular_velocity_yaw_dps=0.0,
        zoom_ratio=1.0,
        picture_mode="visible",
        picture_mode_code=4,
        osd_enabled=False,
        night_vision_enabled=False,
        lighting_enabled=False,
        digital_zoom_enabled=False,
        camera_recording=False,
        hardware_version=1,
        firmware_version=1,
        pod_code=1,
        error_code=0,
    )


class _FakeGimbal:
    def __init__(self) -> None:
        self.current = _status()
        self.position_commands: list[tuple[float, float]] = []
        self.jog_commands: list[tuple[float, float]] = []
        self.center_calls = 0

    async def status(self) -> Z2MiniStatus:
        return self.current

    async def set_position(self, *, pitch_deg: float, yaw_deg: float) -> Z2MiniStatus:
        self.position_commands.append((pitch_deg, yaw_deg))
        self.current = _status(yaw=yaw_deg, pitch=pitch_deg)
        return self.current

    async def jog(self, *, pitch_velocity_dps: float, yaw_velocity_dps: float) -> Z2MiniStatus:
        self.jog_commands.append((pitch_velocity_dps, yaw_velocity_dps))
        step_seconds = 1.0 / float(fence_runtime.settings.FENCE_CONTROL_HZ)
        self.current = _status(
            yaw=self.current.relative_yaw_deg + yaw_velocity_dps * step_seconds,
            pitch=self.current.relative_pitch_deg + pitch_velocity_dps * step_seconds,
        )
        return self.current

    async def center(self) -> Z2MiniStatus:
        self.center_calls += 1
        self.current = _status()
        return self.current


def _calibration(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "FENCE_GIMBAL_MOUNT_X_M": 0.0,
        "FENCE_GIMBAL_MOUNT_Y_M": 0.0,
        "FENCE_GIMBAL_MOUNT_Z_M": 1.0,
        "FENCE_GIMBAL_MOUNT_ROLL_DEG": 0.0,
        "FENCE_GIMBAL_MOUNT_PITCH_DEG": 0.0,
        "FENCE_GIMBAL_MOUNT_YAW_DEG": 0.0,
        "FENCE_GIMBAL_YAW_SIGN": 1.0,
        "FENCE_GIMBAL_PITCH_SIGN": 1.0,
        "FENCE_CAMERA_OFFSET_X_M": 0.0,
        "FENCE_CAMERA_OFFSET_Y_M": 0.0,
        "FENCE_CAMERA_OFFSET_Z_M": 0.0,
        "FENCE_CAMERA_ROLL_DEG": 0.0,
        "FENCE_CAMERA_PITCH_DEG": 0.0,
        "FENCE_CAMERA_YAW_DEG": 0.0,
        "FENCE_CAMERA_FX_PX": 400.0,
        "FENCE_CAMERA_FY_PX": 400.0,
        "FENCE_CAMERA_CX_PX": 320.0,
        "FENCE_CAMERA_CY_PX": 180.0,
        "FENCE_CAMERA_CALIBRATED_ZOOM_RATIO": 1.0,
        "FENCE_GIMBAL_SETTLE_SECONDS": 0.0,
        "FENCE_SWITCH_DELAY_SECONDS": 0.0,
        "FENCE_DETECTION_MAX_DISTANCE_M": 20.0,
    }
    for name, value in values.items():
        monkeypatch.setattr(fence_runtime.settings, name, value)


def test_fence_persists_per_scene_and_can_be_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    scene_id = _scene(monkeypatch, tmp_path)
    created = create_fence(
        scene_id,
        {"start": {"x": 0, "y": 1}, "end": {"x": 5, "y": 1}},
    )

    reloaded = list_fences(scene_id)["items"]
    assert reloaded == [created]
    assert reloaded[0]["scene_id"] == scene_id
    assert reloaded[0]["start"] == {"x": 0.0, "y": 1.0}

    disabled = set_fence_enabled(scene_id, created["id"], False)
    assert disabled["enabled"] is False
    assert list_fences(scene_id)["items"][0]["enabled"] is False
    assert delete_fence(scene_id, created["id"]) is True
    assert list_fences(scene_id)["items"] == []


def test_closest_point_uses_finite_segment_not_midpoint() -> None:
    point, distance = closest_point_on_segment(
        3.0,
        2.0,
        {"x": 0.0, "y": 0.0},
        {"x": 10.0, "y": 0.0},
    )
    assert point == pytest.approx({"x": 3.0, "y": 0.0})
    assert distance == pytest.approx(2.0)

    endpoint, endpoint_distance = closest_point_on_segment(
        12.0,
        4.0,
        {"x": 0.0, "y": 0.0},
        {"x": 10.0, "y": 0.0},
    )
    assert endpoint == pytest.approx({"x": 10.0, "y": 0.0})
    assert endpoint_distance == pytest.approx(math.hypot(2.0, 4.0))


@pytest.mark.asyncio
async def test_service_selects_nearest_point_and_keeps_fence_locked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _calibration(monkeypatch)
    gimbal = _FakeGimbal()
    service = FenceDetectionService(gimbal_service=gimbal)  # type: ignore[arg-type]
    pose = {"x": 3.0, "y": 1.0, "z": 0.0, "yaw": -math.pi / 2, "timestamp": 1.0}
    nav_state = {
        "robot_pose": pose,
        "localization_status": {"status": "ok"},
    }
    fences = [
        {"id": "fence_a", "enabled": True, "start": {"x": 0.0, "y": 0.0}, "end": {"x": 10.0, "y": 0.0}},
        {"id": "fence_b", "enabled": True, "start": {"x": 0.0, "y": 3.0}, "end": {"x": 10.0, "y": 3.0}},
    ]
    monkeypatch.setattr(fence_runtime, "get_nav_state", lambda: nav_state)
    monkeypatch.setattr(fence_runtime, "load_current_scene", lambda strict=False: {"scene_id": "scene"})
    monkeypatch.setattr(fence_runtime, "list_fences", lambda scene_id: {"items": fences})

    await service.enable()
    await service._control_step(100.0)
    first = service.get_status()
    assert first["target_fence_id"] == "fence_a"
    assert first["target_point"] == pytest.approx({"x": 3.0, "y": 0.0})
    assert first["distance_m"] == pytest.approx(1.0)
    first_yaw = first["desired_yaw_deg"]

    # fence_b becomes much nearer, but fence_a remains valid and must stay locked.
    pose.update({"y": 2.8, "yaw": 0.0})
    await service._control_step(101.0)
    corrected = service.get_status()
    assert corrected["target_fence_id"] == "fence_a"
    assert corrected["desired_yaw_deg"] != pytest.approx(first_yaw)
    assert abs(gimbal.jog_commands[-1][1]) <= float(
        fence_runtime.settings.FENCE_GIMBAL_MAX_SPEED_DPS
    )
    assert all(pitch_velocity == 0.0 for pitch_velocity, _ in gimbal.jog_commands)
    assert gimbal.position_commands == []


@pytest.mark.asyncio
async def test_gimbal_uses_yaw_velocity_only_and_disable_returns_yaw_to_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _calibration(monkeypatch)
    monkeypatch.setattr(fence_runtime.settings, "FENCE_CONTROL_HZ", 5.0)
    monkeypatch.setattr(fence_runtime.settings, "FENCE_GIMBAL_MAX_SPEED_DPS", 10.0)
    monkeypatch.setattr(fence_runtime.settings, "FENCE_GIMBAL_SMOOTHING_ALPHA", 1.0)
    pose = {"x": 0.0, "y": 0.0, "z": 0.0, "yaw": 0.0, "timestamp": 1.0}
    monkeypatch.setattr(
        fence_runtime,
        "get_nav_state",
        lambda: {"robot_pose": pose, "localization_status": {"status": "ok"}},
    )
    gimbal = _FakeGimbal()
    gimbal.current = _status(pitch=12.0)
    service = FenceDetectionService(gimbal_service=gimbal)  # type: ignore[arg-type]
    service._enabled = True
    service._desired_yaw_deg = 90.0
    service._desired_pitch_deg = None
    service._samples.append(_SynchronizedSample(100.0, pose, gimbal.current))

    await service._apply_gimbal_control(gimbal.current, 100.0)
    assert gimbal.jog_commands[0] == pytest.approx((0.0, 10.0))
    assert gimbal.position_commands == []
    await service.disable(center_gimbal=True)
    assert gimbal.current.relative_yaw_deg == pytest.approx(0.0)
    assert gimbal.current.relative_pitch_deg == pytest.approx(12.0)
    assert all(pitch_velocity == 0.0 for pitch_velocity, _ in gimbal.jog_commands)
    assert gimbal.center_calls == 0
    assert service.get_status()["state"] == FenceDetectionState.DISABLED.value
    command_count = len(gimbal.jog_commands)
    await service._control_step(101.0)
    assert len(gimbal.jog_commands) == command_count


@pytest.mark.asyncio
async def test_missing_localization_and_empty_scene_are_safe_states(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _calibration(monkeypatch)
    nav_state = {"robot_pose": None, "localization_status": {"status": "initializing"}}
    monkeypatch.setattr(fence_runtime, "get_nav_state", lambda: nav_state)
    monkeypatch.setattr(fence_runtime, "load_current_scene", lambda strict=False: {"scene_id": "scene"})
    monkeypatch.setattr(fence_runtime, "list_fences", lambda scene_id: {"items": []})
    service = FenceDetectionService(gimbal_service=_FakeGimbal())  # type: ignore[arg-type]

    await service.enable()
    await service._control_step(100.0)
    assert service.get_status()["state"] == FenceDetectionState.LOCALIZATION_UNAVAILABLE.value

    nav_state.update(
        {
            "robot_pose": {"x": 0.0, "y": 0.0, "z": 0.0, "yaw": 0.0, "timestamp": 1.0},
            "localization_status": {"status": "ok"},
        }
    )
    await service.enable()
    await service._control_step(101.0)
    assert service.get_status()["state"] == FenceDetectionState.NOT_FOUND.value


@pytest.mark.asyncio
async def test_localization_timestamp_reset_releases_fence_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _calibration(monkeypatch)
    pose = {
        "x": 0.0,
        "y": 0.0,
        "z": 0.0,
        "yaw": 0.0,
        "timestamp": 1.0,
        "ros_timestamp": 10.0,
    }
    monkeypatch.setattr(
        fence_runtime,
        "get_nav_state",
        lambda: {"robot_pose": pose, "localization_status": {"status": "ok"}},
    )
    monkeypatch.setattr(fence_runtime, "load_current_scene", lambda strict=False: {"scene_id": "scene"})
    monkeypatch.setattr(
        fence_runtime,
        "list_fences",
        lambda scene_id: {
            "items": [
                {
                    "id": "fence_a",
                    "enabled": True,
                    "start": {"x": 5.0, "y": -1.0},
                    "end": {"x": 5.0, "y": 1.0},
                }
            ]
        },
    )
    service = FenceDetectionService(gimbal_service=_FakeGimbal())  # type: ignore[arg-type]

    await service.enable()
    await service._control_step(100.0)
    assert service.get_status()["target_fence_id"] == "fence_a"

    pose["ros_timestamp"] = 5.0
    await service._control_step(101.0)
    status = service.get_status()
    assert status["target_fence_id"] is None
    assert status["state"] == FenceDetectionState.FINDING.value


@pytest.mark.asyncio
async def test_existing_radar_mount_and_camera_fov_are_used_without_extra_calibration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _calibration(monkeypatch)
    monkeypatch.setattr(fence_runtime.settings, "FENCE_GIMBAL_MOUNT_X_M", None)
    monkeypatch.setattr(fence_runtime.settings, "FENCE_GIMBAL_MOUNT_Y_M", None)
    monkeypatch.setattr(fence_runtime.settings, "FENCE_GIMBAL_MOUNT_Z_M", None)
    monkeypatch.setattr(fence_runtime.settings, "NAV_LIDAR_MOUNT_X_M", 0.0)
    monkeypatch.setattr(fence_runtime.settings, "NAV_LIDAR_MOUNT_Y_M", 0.0)
    monkeypatch.setattr(fence_runtime.settings, "NAV_LIDAR_MOUNT_Z_M", 1.0)
    monkeypatch.setattr(fence_runtime.settings, "FENCE_CAMERA_FX_PX", None)
    monkeypatch.setattr(fence_runtime.settings, "FENCE_CAMERA_FY_PX", None)
    monkeypatch.setattr(fence_runtime.settings, "FENCE_CAMERA_CX_PX", None)
    monkeypatch.setattr(fence_runtime.settings, "FENCE_CAMERA_CY_PX", None)
    monkeypatch.setattr(fence_runtime.settings, "AUTO_TRACK_GIMBAL_HORIZONTAL_FOV_DEG", 60.0)
    monkeypatch.setattr(
        fence_runtime,
        "get_nav_state",
        lambda: {
            "robot_pose": {"x": 0.0, "y": 0.0, "z": 0.0, "yaw": 0.0},
            "localization_status": {"status": "ok"},
        },
    )
    monkeypatch.setattr(fence_runtime, "load_current_scene", lambda strict=False: {"scene_id": "scene"})
    monkeypatch.setattr(
        fence_runtime,
        "list_fences",
        lambda scene_id: {
            "items": [
                {
                    "id": "fence_a",
                    "enabled": True,
                    "start": {"x": 5.0, "y": 1.0},
                    "end": {"x": 5.0, "y": 2.0},
                }
            ]
        },
    )
    gimbal = _FakeGimbal()
    service = FenceDetectionService(gimbal_service=gimbal)  # type: ignore[arg-type]
    await service.enable()
    await service._control_step(100.0)
    status = service.get_status()
    assert status["state"] != FenceDetectionState.CALIBRATION_UNAVAILABLE.value
    assert status["missing_calibration"] == []
    assert status["target_fence_id"] == "fence_a"
    assert gimbal.jog_commands


@pytest.mark.asyncio
async def test_invalid_existing_mount_parameter_never_commands_gimbal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _calibration(monkeypatch)
    monkeypatch.setattr(fence_runtime.settings, "FENCE_GIMBAL_MOUNT_X_M", None)
    monkeypatch.setattr(fence_runtime.settings, "NAV_LIDAR_MOUNT_X_M", math.nan)
    gimbal = _FakeGimbal()
    service = FenceDetectionService(gimbal_service=gimbal)  # type: ignore[arg-type]
    await service.enable()
    await service._control_step(100.0)
    status = service.get_status()
    assert status["state"] == FenceDetectionState.CALIBRATION_UNAVAILABLE.value
    assert "NAV_LIDAR_MOUNT_X_M" in status["missing_calibration"]
    assert gimbal.jog_commands == []
    assert gimbal.position_commands == []


def test_contact_requires_continuous_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _calibration(monkeypatch)
    monkeypatch.setattr(fence_runtime.settings, "FENCE_NEAR_STABLE_FRAMES", 3)
    monkeypatch.setattr(fence_runtime.settings, "FENCE_CONTACT_STABLE_FRAMES", 3)
    monkeypatch.setattr(fence_runtime.settings, "FENCE_WARNING_DISTANCE_M", 1.0)
    gimbal = _FakeGimbal()
    service = FenceDetectionService(gimbal_service=gimbal)  # type: ignore[arg-type]
    service._enabled = True
    service._state = FenceDetectionState.DETECTING
    service._target_fence = {
        "id": "fence_a",
        "start": {"x": 5.0, "y": -2.0},
        "end": {"x": 5.0, "y": 2.0},
    }
    pose = {"x": 0.0, "y": 0.0, "z": 0.0, "yaw": 0.0, "timestamp": 1.0}
    service._samples.append(_SynchronizedSample(100.0, pose, gimbal.current))

    detection = type("Detection", (), {"label": "person", "track_id": 7, "bbox": (280, 80, 360, 260)})()
    keypoints = [PoseKeypoint(0.0, 0.0, 0.0) for _ in range(17)]
    keypoints[9] = PoseKeypoint(300.0, 180.0, 0.9)
    keypoints[10] = PoseKeypoint(340.0, 180.0, 0.9)
    observation = PoseObservation(
        track_id=99,
        bbox=(280, 80, 360, 260),
        confidence=0.9,
        keypoints=tuple(keypoints),
        posture=Posture.STANDING,
        posture_confidence=0.8,
        inside_zone=False,
        dwell_seconds=0.0,
    )

    assert service.process_frame(detections=[detection], poses=[observation], frame_monotonic=100.0) == []
    assert service.process_frame(detections=[detection], poses=[observation], frame_monotonic=100.1) == []
    events = service.process_frame(detections=[detection], poses=[observation], frame_monotonic=100.2)
    assert len(events) == 1
    assert events[0].behavior is FenceBehavior.CONTACT
    assert events[0].track_id == 7


def test_climbing_suspected_requires_continuous_crossing_motion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _calibration(monkeypatch)
    monkeypatch.setattr(fence_runtime.settings, "FENCE_NEAR_STABLE_FRAMES", 3)
    monkeypatch.setattr(fence_runtime.settings, "FENCE_CROSS_STABLE_FRAMES", 3)
    service = FenceDetectionService(gimbal_service=_FakeGimbal())  # type: ignore[arg-type]
    service._enabled = True
    service._state = FenceDetectionState.DETECTING
    service._target_fence = {
        "id": "fence_a",
        "start": {"x": 5.0, "y": -2.0},
        "end": {"x": 5.0, "y": 2.0},
    }
    pose = {"x": 0.0, "y": 0.0, "z": 0.0, "yaw": 0.0, "timestamp": 1.0}
    service._samples.append(_SynchronizedSample(100.0, pose, _status()))

    before_detection = type(
        "Detection",
        (),
        {"label": "person", "track_id": 8, "bbox": (280, 80, 360, 280)},
    )()
    crossed_detection = type(
        "Detection",
        (),
        {"label": "person", "track_id": 8, "bbox": (280, 80, 360, 247)},
    )()
    keypoints = [PoseKeypoint(0.0, 0.0, 0.0) for _ in range(17)]
    for index, x in (
        (5, 300.0),
        (6, 340.0),
        (11, 305.0),
        (12, 335.0),
        (15, 310.0),
        (16, 330.0),
    ):
        keypoints[index] = PoseKeypoint(x, 140.0, 0.9)
    before_observation = PoseObservation(
        track_id=100,
        bbox=(280, 80, 360, 280),
        confidence=0.9,
        keypoints=tuple(keypoints),
        posture=Posture.CLIMBING,
        posture_confidence=0.9,
        inside_zone=False,
        dwell_seconds=0.0,
    )
    crossed_observation = PoseObservation(
        track_id=100,
        bbox=(280, 80, 360, 247),
        confidence=0.9,
        keypoints=tuple(keypoints),
        posture=Posture.CLIMBING,
        posture_confidence=0.9,
        inside_zone=False,
        dwell_seconds=0.0,
    )

    assert service.process_frame(
        detections=[before_detection], poses=[before_observation], frame_monotonic=100.0
    ) == []
    assert service.process_frame(
        detections=[crossed_detection], poses=[crossed_observation], frame_monotonic=100.1
    ) == []
    assert service.process_frame(
        detections=[crossed_detection], poses=[crossed_observation], frame_monotonic=100.2
    ) == []
    events = service.process_frame(
        detections=[crossed_detection], poses=[crossed_observation], frame_monotonic=100.3
    )
    assert len(events) == 1
    assert events[0].behavior is FenceBehavior.CLIMBING_SUSPECTED
    assert events[0].track_id == 8
