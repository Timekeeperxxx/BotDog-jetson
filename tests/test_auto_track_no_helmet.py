from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from backend.auto_track_service import AutoTrackService
from backend.tracking_types import AutoTrackState, DetectionResult, TrackStopReason


class _ZoneAlwaysInside:
    def is_inside_zone(self, anchor: tuple[int, int]) -> bool:
        return True


class _ControlService:
    def __init__(self) -> None:
        self.commands: list[tuple[str, dict[str, Any]]] = []

    async def handle_command(self, cmd: str, **kwargs: Any) -> None:
        self.commands.append((cmd, kwargs))
        return SimpleNamespace(result="ACCEPTED")


class _Broadcaster:
    connection_count = 0


class _StateMachine:
    pass


def _service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    default_enabled: bool = True,
    gimbal_enabled: bool = False,
    gimbal_service: Any = None,
    gimbal_body_deadband_deg: float = 8.0,
    gimbal_realign_frames: int = 3,
) -> AutoTrackService:
    service = AutoTrackService(
        zone_service=_ZoneAlwaysInside(),
        control_service=_ControlService(),
        event_broadcaster=_Broadcaster(),
        state_machine=_StateMachine(),
        session_factory=None,
        snapshot_dir=tmp_path,
        frame_width=640,
        frame_height=480,
        stable_hits=1,
        lost_timeout_frames=5,
        command_interval_ms=0,
        forward_area_ratio=0.30,
        stop_snapshot_enabled=False,
        default_enabled=default_enabled,
        gimbal_enabled=gimbal_enabled,
        gimbal_body_deadband_deg=gimbal_body_deadband_deg,
        gimbal_forward_deadband_deg=5.0,
        gimbal_realign_frames=gimbal_realign_frames,
        gimbal_horizontal_fov_deg=60.0,
        gimbal_servo_gain=0.75,
        gimbal_pixel_deadband_px=20,
        gimbal_command_interval_ms=0,
        gimbal_service=gimbal_service,
    )

    async def noop(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(service, "_take_snapshot_safe", noop)
    monkeypatch.setattr(service, "_pause_navigation_for_tracking", noop)
    monkeypatch.setattr(service, "_resume_navigation_after_tracking", noop)
    return service


class _Gimbal:
    def __init__(self, yaw_deg: float = 0.0, *, fail: bool = False) -> None:
        self.yaw_deg = yaw_deg
        self.fail = fail
        self.positions: list[tuple[float, float]] = []
        self.velocities: list[tuple[float, float]] = []
        self.modes: list[str] = []

    async def status(self):
        if self.fail:
            raise OSError("camera offline")
        return SimpleNamespace(
            connected=True,
            relative_pitch_deg=0.0,
            relative_yaw_deg=self.yaw_deg,
            zoom_ratio=1.0,
        )

    async def set_position(self, *, pitch_deg: float, yaw_deg: float):
        self.positions.append((pitch_deg, yaw_deg))
        self.yaw_deg = yaw_deg
        return await self.status()

    async def jog(self, *, pitch_velocity_dps: float, yaw_velocity_dps: float):
        self.velocities.append((pitch_velocity_dps, yaw_velocity_dps))
        return await self.status()

    async def set_mode(self, mode: str):
        self.modes.append(mode)
        return await self.status()


def _person(track_id: int = -1, bbox: tuple[int, int, int, int] = (100, 80, 300, 460)) -> DetectionResult:
    return DetectionResult(bbox=bbox, confidence=0.92, class_name="person", track_id=track_id)


def _head() -> DetectionResult:
    return DetectionResult(bbox=(150, 105, 245, 195), confidence=0.88, class_name="head")


def _helmet() -> DetectionResult:
    return DetectionResult(bbox=(148, 92, 247, 162), confidence=0.86, class_name="helmet")


async def _establish_centered_gimbal_follow(
    service: AutoTrackService,
) -> DetectionResult:
    centered = _person(bbox=(220, 80, 420, 460))
    centered_head = DetectionResult(
        bbox=(275, 105, 365, 195),
        confidence=0.88,
        class_name="head",
    )
    for frame_index in range(1, 6):
        await service.process_frame(
            [centered, centered_head],
            b"",
            frame_index=frame_index,
            current_task_id="task",
        )
    for frame_index in range(6, 10):
        await service.process_frame(
            [centered],
            b"",
            frame_index=frame_index,
            current_task_id="task",
        )
    return centered


async def _feed_head_person_frames(
    service: AutoTrackService,
    *,
    start_frame: int,
    count: int,
    task_id: str | None = "task",
) -> None:
    for frame_index in range(start_frame, start_frame + count):
        await service.process_frame(
            [_person(), _head()],
            b"",
            frame_index=frame_index,
            current_task_id=task_id,
        )


@pytest.mark.asyncio
async def test_auto_track_locks_only_person_with_head_without_helmet(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path, monkeypatch)
    events: list[tuple[str, dict[str, Any]]] = []

    async def capture_event(msg_type: str, payload: dict[str, Any]) -> None:
        events.append((msg_type, payload))

    monkeypatch.setattr(service, "_broadcast_event", capture_event)

    await _feed_head_person_frames(service, start_frame=1, count=4)
    assert service.get_status()["state"] == AutoTrackState.DETECTING.value

    await _feed_head_person_frames(service, start_frame=5, count=1)
    status = service.get_status()
    assert status["state"] == AutoTrackState.FOLLOWING.value
    assert status["active_target"]["bbox"] == (100, 80, 300, 460)

    overlays = [payload for msg_type, payload in events if msg_type == "TRACK_OVERLAY"]
    assert overlays
    assert any(
        det["class_name"] == "person" and det["safety_status"] == "no_helmet"
        for det in overlays[-1]["detections"]
    )


@pytest.mark.asyncio
async def test_auto_track_uses_identity_instead_of_head_or_helmet(tmp_path, monkeypatch):
    service = _service(tmp_path, monkeypatch)
    for i in range(1, 6):
        await service.process_frame([_person(), _helmet()], b"", frame_index=i, current_task_id="task")
    assert service._state == AutoTrackState.FOLLOWING

    service = _service(tmp_path, monkeypatch)
    person = _person()
    person.face_status = "recognized"
    person.identity_id = 1
    for i in range(1, 7):
        await service.process_frame([person], b"", frame_index=i, current_task_id="task")
    assert service._state == AutoTrackState.IDLE


@pytest.mark.asyncio
async def test_locked_target_keeps_following_when_head_disappears(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path, monkeypatch)

    await _feed_head_person_frames(service, start_frame=1, count=5)
    assert service.get_status()["state"] == AutoTrackState.FOLLOWING.value

    moved_person = _person(bbox=(112, 84, 312, 464))
    await service.process_frame([moved_person], b"", frame_index=6, current_task_id="task")

    status = service.get_status()
    assert status["state"] == AutoTrackState.FOLLOWING.value
    assert status["active_target"]["bbox"] == (112, 84, 312, 464)


@pytest.mark.asyncio
async def test_transient_lost_stops_body_immediately(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path, monkeypatch)

    await _feed_head_person_frames(service, start_frame=1, count=5)
    assert service.get_status()["state"] == AutoTrackState.FOLLOWING.value

    await service.process_frame([], b"", frame_index=6, current_task_id="task")
    status = service.get_status()
    assert status["state"] == AutoTrackState.LOST.value
    assert any(cmd == "stop" for cmd, _ in service._control_service.commands)

    for frame_index in range(7, 11):
        await service.process_frame([], b"", frame_index=frame_index, current_task_id="task")
    await asyncio.sleep(0)

    assert any(cmd == "stop" for cmd, _ in service._control_service.commands)


@pytest.mark.asyncio
async def test_video_lost_freezes_target_without_releasing_tracking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path, monkeypatch)

    await _feed_head_person_frames(service, start_frame=1, count=5)
    assert service.get_status()["state"] == AutoTrackState.FOLLOWING.value

    await service.notify_video_lost("publisher_disconnected")
    status = service.get_status()
    assert status["state"] == AutoTrackState.LOST.value
    assert status["active_target"]["bbox"] == (100, 80, 300, 460)
    assert status["video_lost"] is True
    assert not any(msg == TrackStopReason.VIDEO_LOST.value for msg, _ in service._control_service.commands)
    assert any(cmd == "stop" for cmd, _ in service._control_service.commands)

    await service.process_frame([_person(bbox=(110, 80, 310, 460))], b"", frame_index=6, current_task_id="task")
    status = service.get_status()
    assert status["state"] == AutoTrackState.FOLLOWING.value
    assert status["video_lost"] is False
    assert status["active_target"]["bbox"] == (110, 80, 310, 460)


@pytest.mark.asyncio
async def test_manual_auto_track_enable_works_without_running_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path, monkeypatch, default_enabled=False)
    service.enable()

    await _feed_head_person_frames(service, start_frame=1, count=5, task_id=None)

    status = service.get_status()
    assert status["standalone_enabled"] is True
    assert status["state"] == AutoTrackState.FOLLOWING.value
    assert status["active_target"]["bbox"] == (100, 80, 300, 460)


@pytest.mark.asyncio
async def test_navigation_auto_track_enable_still_requires_task_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path, monkeypatch, default_enabled=False)
    service.enable_for_navigation()

    await _feed_head_person_frames(service, start_frame=1, count=5, task_id=None)

    status = service.get_status()
    assert status["standalone_enabled"] is False
    assert status["state"] == AutoTrackState.IDLE.value
    assert status["active_target"] is None

    await _feed_head_person_frames(service, start_frame=6, count=5, task_id="nav-task")

    status = service.get_status()
    assert status["state"] == AutoTrackState.FOLLOWING.value


@pytest.mark.asyncio
async def test_tracking_ignores_helmet_and_stops_on_confirmed_identity(tmp_path, monkeypatch):
    service = _service(tmp_path, monkeypatch)
    await _feed_head_person_frames(service, start_frame=1, count=5)
    for i in range(6, 11):
        await service.process_frame([_person(), _head(), _helmet()], b"", frame_index=i, current_task_id="task")
    assert service._state == AutoTrackState.FOLLOWING
    person = _person()
    person.face_status = "recognized"
    person.identity_id = 1
    await service.process_frame([person], b"", frame_index=11, current_task_id="task")
    await asyncio.sleep(0)
    assert service._state == AutoTrackState.STOPPED
    assert service._stop_reason == TrackStopReason.IDENTITY_CONFIRMED
    assert any(cmd == "stop" for cmd, _ in service._control_service.commands)


@pytest.mark.asyncio
async def test_gimbal_yaw_turns_body_before_allowing_forward(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gimbal = _Gimbal(yaw_deg=30.0)
    service = _service(
        tmp_path,
        monkeypatch,
        gimbal_enabled=True,
        gimbal_service=gimbal,
    )
    centered = _person(bbox=(220, 80, 420, 460))
    centered_head = DetectionResult(
        bbox=(275, 105, 365, 195),
        confidence=0.88,
        class_name="head",
    )

    for frame_index in range(1, 6):
        await service.process_frame(
            [centered, centered_head],
            b"",
            frame_index=frame_index,
            current_task_id="task",
        )
    await service.process_frame([centered], b"", frame_index=6, current_task_id="task")

    assert service._control_service.commands[-1][0] == "right"
    assert service._control_service.commands[-1][1]["vyaw"] == pytest.approx(0.35)
    assert not any(cmd == "forward" for cmd, _ in service._control_service.commands)
    assert gimbal.modes == ["head_lock"]
    assert not any(yaw_velocity != 0.0 for _, yaw_velocity in gimbal.velocities)

    gimbal.yaw_deg = 2.0
    await service.process_frame([centered], b"", frame_index=7, current_task_id="task")
    await service.process_frame([centered], b"", frame_index=8, current_task_id="task")
    assert service._control_service.commands[-1][0] == "stop"
    await service.process_frame([centered], b"", frame_index=9, current_task_id="task")
    assert service._control_service.commands[-1][0] == "stop"
    assert gimbal.modes == ["head_lock", "head_follow"]

    await service.process_frame([centered], b"", frame_index=10, current_task_id="task")
    assert service._control_service.commands[-1][0] == "forward"


@pytest.mark.asyncio
async def test_alignment_escalates_when_b2_reports_no_yaw_motion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gimbal = _Gimbal(yaw_deg=30.0)
    service = _service(
        tmp_path,
        monkeypatch,
        gimbal_enabled=True,
        gimbal_service=gimbal,
    )
    centered = _person(bbox=(220, 80, 420, 460))
    centered_head = DetectionResult(
        bbox=(275, 105, 365, 195),
        confidence=0.88,
        class_name="head",
    )
    monkeypatch.setattr(service, "_read_body_yaw_speed_dps", lambda: 0.0)

    for frame_index in range(1, 6):
        await service.process_frame(
            [centered, centered_head],
            b"",
            frame_index=frame_index,
            current_task_id="task",
        )
    await service.process_frame([centered], b"", frame_index=6, current_task_id="task")
    service._alignment_turn_started_at -= 1.1
    await service.process_frame([centered], b"", frame_index=7, current_task_id="task")

    assert service._control_service.commands[-1] == (
        "right",
        {"vyaw": pytest.approx(0.5)},
    )
    assert service.get_status()["alignment_motion_confirmed"] is False


@pytest.mark.asyncio
async def test_after_alignment_turns_body_without_moving_gimbal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gimbal = _Gimbal(yaw_deg=0.0)
    service = _service(
        tmp_path,
        monkeypatch,
        gimbal_enabled=True,
        gimbal_service=gimbal,
    )
    right_person = _person(bbox=(360, 80, 560, 460))
    right_head = DetectionResult(
        bbox=(415, 105, 505, 195),
        confidence=0.88,
        class_name="head",
    )

    for frame_index in range(1, 6):
        await service.process_frame(
            [right_person, right_head],
            b"",
            frame_index=frame_index,
            current_task_id="task",
        )
    # 初始三帧确认机身与摄像头同向；下一帧人在右侧时只转机身。
    for frame_index in range(6, 10):
        await service.process_frame(
            [right_person],
            b"",
            frame_index=frame_index,
            current_task_id="task",
        )

    assert gimbal.velocities
    assert all(pitch == 0.0 and yaw == 0.0 for pitch, yaw in gimbal.velocities)
    assert gimbal.modes == ["head_lock", "head_follow"]
    assert service._control_service.commands[-1][0] == "right"
    assert service._control_service.commands[-1][1]["vyaw"] == pytest.approx(0.35)


@pytest.mark.asyncio
async def test_gimbal_yaw_jitter_inside_tracking_deadband_keeps_following(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gimbal = _Gimbal(yaw_deg=0.0)
    service = _service(
        tmp_path,
        monkeypatch,
        gimbal_enabled=True,
        gimbal_service=gimbal,
    )
    centered = await _establish_centered_gimbal_follow(service)

    assert service._control_service.commands[-1][0] == "forward"
    assert gimbal.modes == ["head_lock", "head_follow"]

    for frame_index, yaw_deg in enumerate(
        (-5.4, -6.8, -5.9, -7.1, -6.2),
        start=10,
    ):
        gimbal.yaw_deg = yaw_deg
        await service.process_frame(
            [centered],
            b"",
            frame_index=frame_index,
            current_task_id="task",
        )
        assert service.get_status()["tracking_phase"] == "FOLLOWING"
        assert service._initial_alignment_complete is True
        assert service._control_service.commands[-1][0] == "forward"

    assert service.get_status()["camera_realign_deadband_deg"] == pytest.approx(8.0)
    assert service.get_status()["gimbal_realign_hits"] == 0
    assert gimbal.modes == ["head_lock", "head_follow"]


@pytest.mark.asyncio
async def test_persistent_moderate_gimbal_offset_realigns_after_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gimbal = _Gimbal(yaw_deg=0.0)
    service = _service(
        tmp_path,
        monkeypatch,
        gimbal_enabled=True,
        gimbal_service=gimbal,
    )
    centered = await _establish_centered_gimbal_follow(service)

    gimbal.yaw_deg = 9.0
    for frame_index in (10, 11):
        await service.process_frame(
            [centered],
            b"",
            frame_index=frame_index,
            current_task_id="task",
        )
        assert service.get_status()["tracking_phase"] == "FOLLOWING"
        assert service._initial_alignment_complete is True

    assert service.get_status()["gimbal_realign_hits"] == 2
    assert service._control_service.commands[-1][0] == "right"

    await service.process_frame(
        [centered],
        b"",
        frame_index=12,
        current_task_id="task",
    )

    assert service._control_service.commands[-1][0] == "stop"
    assert service.get_status()["tracking_phase"] == "ALIGNING"
    assert service._initial_alignment_complete is False
    assert gimbal.modes == ["head_lock", "head_follow", "head_lock"]


@pytest.mark.asyncio
async def test_manual_gimbal_turn_stops_and_realigns_body_again(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gimbal = _Gimbal(yaw_deg=0.0)
    service = _service(
        tmp_path,
        monkeypatch,
        gimbal_enabled=True,
        gimbal_service=gimbal,
    )
    centered = _person(bbox=(220, 80, 420, 460))
    centered_head = DetectionResult(
        bbox=(275, 105, 365, 195),
        confidence=0.88,
        class_name="head",
    )

    for frame_index in range(1, 6):
        await service.process_frame(
            [centered, centered_head],
            b"",
            frame_index=frame_index,
            current_task_id="task",
        )
    for frame_index in range(6, 10):
        await service.process_frame(
            [centered],
            b"",
            frame_index=frame_index,
            current_task_id="task",
        )

    assert service._control_service.commands[-1][0] == "forward"
    assert gimbal.modes == ["head_lock", "head_follow"]

    # 跟踪期间人为把相机向右转 25°：本帧必须先停车并重新锁住相机，
    # 下一帧只能让机器狗向右追到相机方向。
    gimbal.yaw_deg = 25.0
    await service.process_frame(
        [centered],
        b"",
        frame_index=10,
        current_task_id="task",
    )

    assert service._control_service.commands[-1][0] == "stop"
    assert service.get_status()["tracking_phase"] == "ALIGNING"
    assert service._initial_alignment_complete is False
    assert gimbal.modes == ["head_lock", "head_follow", "head_lock"]

    await service.process_frame(
        [centered],
        b"",
        frame_index=11,
        current_task_id="task",
    )

    assert service._control_service.commands[-1][0] == "right"
    assert service._control_service.commands[-1][1]["vyaw"] == pytest.approx(0.35)
    assert all(pitch == 0.0 and yaw == 0.0 for pitch, yaw in gimbal.velocities)


@pytest.mark.asyncio
async def test_gimbal_failure_stops_instead_of_blind_forward(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gimbal = _Gimbal(fail=True)
    service = _service(
        tmp_path,
        monkeypatch,
        gimbal_enabled=True,
        gimbal_service=gimbal,
    )
    centered = _person(bbox=(220, 80, 420, 460))
    centered_head = DetectionResult(
        bbox=(275, 105, 365, 195),
        confidence=0.88,
        class_name="head",
    )

    for frame_index in range(1, 6):
        await service.process_frame(
            [centered, centered_head],
            b"",
            frame_index=frame_index,
            current_task_id="task",
        )
    await service.process_frame([centered], b"", frame_index=6, current_task_id="task")

    assert service._control_service.commands[-1][0] == "stop"
    assert not any(cmd == "forward" for cmd, _ in service._control_service.commands)
    assert service.get_status()["gimbal_connected"] is False


@pytest.mark.asyncio
async def test_tracking_toggle_preserves_fence_and_resumes_after_stop(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock
    from backend import auto_track_service, fence_detection_service

    gimbal = _Gimbal()
    auto_track = _service(tmp_path, monkeypatch, default_enabled=False,
                          gimbal_enabled=True, gimbal_service=gimbal)
    fence = fence_detection_service.FenceDetectionService(gimbal_service=gimbal)
    monkeypatch.setattr(auto_track_service, "get_auto_track_service", lambda: auto_track)
    monkeypatch.setattr(fence_detection_service, "get_fence_detection_service", lambda: fence)
    fence._return_yaw_to_default = AsyncMock()
    fence._control_step_locked = AsyncMock()
    await fence.enable()
    fence._target_fence = {"id": "fence-a"}
    await fence_detection_service.enable_auto_tracking(for_navigation=True)
    assert fence.enabled and auto_track.get_status()["enabled"]
    assert fence.tracking_override and fence.get_status()["state"] == "tracking"
    assert auto_track._is_mission_active(None)  # 围栏提供上下文，无导航任务也能跟踪。
    assert not auto_track._standalone_enabled
    assert gimbal.velocities == [(0.0, 0.0)]
    await fence._control_step(100.0)
    fence._control_step_locked.assert_not_awaited()
    assert fence.process_frame(detections=[], poses=[], frame_monotonic=100.0) == []

    # 必须等待旧跟踪帧退出并完成停车，才能恢复围栏控制。
    async with auto_track._frame_lock:
        switching = asyncio.create_task(fence_detection_service.disable_auto_tracking())
        await asyncio.sleep(0)
        assert not switching.done()
        assert fence.tracking_override
    await switching
    assert fence.enabled and not auto_track.get_status()["enabled"]
    assert not fence.tracking_override
    assert fence.get_status()["state"] == "finding"
    assert fence.get_status()["target_fence_id"] == "fence-a"
    assert auto_track._control_service.commands[-1][0] == "stop"
    await fence._control_step(101.0)
    fence._control_step_locked.assert_awaited_once_with(101.0)
    fence._return_yaw_to_default.assert_not_awaited()


@pytest.mark.asyncio
async def test_disabling_fence_during_tracking_does_not_move_camera(tmp_path, monkeypatch):
    from backend import auto_track_service, fence_detection_service

    gimbal = _Gimbal()
    auto_track = _service(tmp_path, monkeypatch)
    fence = fence_detection_service.FenceDetectionService(gimbal_service=gimbal)
    monkeypatch.setattr(auto_track_service, "get_auto_track_service", lambda: auto_track)
    monkeypatch.setattr(fence_detection_service, "get_fence_detection_service", lambda: fence)
    await fence.enable()  # 先开跟踪再开围栏，也保留跟踪。
    assert auto_track.get_status()["enabled"] and fence.tracking_override
    await fence.disable()
    assert not fence.enabled and auto_track.get_status()["enabled"]
    assert gimbal.velocities == []


@pytest.mark.asyncio
async def test_failed_fence_stop_does_not_enable_tracking(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock
    from backend import auto_track_service, fence_detection_service

    auto_track = _service(tmp_path, monkeypatch, default_enabled=False)
    gimbal = SimpleNamespace(jog=AsyncMock(side_effect=OSError("stop failed")))
    fence = fence_detection_service.FenceDetectionService(gimbal_service=gimbal)
    monkeypatch.setattr(auto_track_service, "get_auto_track_service", lambda: auto_track)
    monkeypatch.setattr(fence_detection_service, "get_fence_detection_service", lambda: fence)
    await fence.enable()
    with pytest.raises(OSError, match="stop failed"):
        await fence_detection_service.enable_auto_tracking()
    assert fence.enabled and not fence.tracking_override
    assert not auto_track.get_status()["enabled"]


@pytest.mark.asyncio
async def test_failed_tracking_stop_keeps_fence_suspended_until_retry(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock
    from backend import auto_track_service, fence_detection_service

    auto_track = _service(tmp_path, monkeypatch)
    fence = fence_detection_service.FenceDetectionService(gimbal_service=_Gimbal())
    monkeypatch.setattr(auto_track_service, "get_auto_track_service", lambda: auto_track)
    monkeypatch.setattr(fence_detection_service, "get_fence_detection_service", lambda: fence)
    await fence.enable()
    auto_track._control_service.handle_command = AsyncMock(
        return_value=SimpleNamespace(result="REJECTED_ADAPTER_ERROR"),
    )
    for _ in range(2):
        with pytest.raises(RuntimeError, match="REJECTED_ADAPTER_ERROR"):
            await fence_detection_service.disable_auto_tracking()
        assert fence.enabled and fence.tracking_override
    auto_track._control_service.handle_command.return_value = SimpleNamespace(result="ACCEPTED")
    await fence_detection_service.disable_auto_tracking()
    assert fence.enabled and not fence.tracking_override


@pytest.mark.asyncio
async def test_confirmed_identity_clears_candidate_and_stops_lost_target(tmp_path, monkeypatch):
    service = _service(tmp_path, monkeypatch)
    await _feed_head_person_frames(service, start_frame=1, count=3)
    known = _person()
    known.face_status = "recognized"
    known.identity_id = 7
    await service.process_frame([known], b"", frame_index=4, current_task_id="task")
    assert not service._candidates
    assert service._state == AutoTrackState.IDLE
    await _feed_head_person_frames(service, start_frame=5, count=5)
    assert service._state == AutoTrackState.FOLLOWING
    await service.process_frame([], b"", frame_index=10, current_task_id="task")
    assert service._state == AutoTrackState.LOST
    await service.process_frame([known], b"", frame_index=11, current_task_id="task")
    await asyncio.sleep(0)
    assert service._state == AutoTrackState.STOPPED
    assert service._stop_reason == TrackStopReason.IDENTITY_CONFIRMED
