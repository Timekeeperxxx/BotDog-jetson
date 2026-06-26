from __future__ import annotations

import asyncio
from pathlib import Path
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


class _Broadcaster:
    connection_count = 0


class _StateMachine:
    pass


def _service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    default_enabled: bool = True,
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
        stop_snapshot_enabled=False,
        default_enabled=default_enabled,
    )

    async def noop(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(service, "_take_snapshot_safe", noop)
    monkeypatch.setattr(service, "_pause_navigation_for_tracking", noop)
    monkeypatch.setattr(service, "_resume_navigation_after_tracking", noop)
    return service


def _person(track_id: int = -1, bbox: tuple[int, int, int, int] = (100, 80, 300, 460)) -> DetectionResult:
    return DetectionResult(bbox=bbox, confidence=0.92, class_name="person", track_id=track_id)


def _head() -> DetectionResult:
    return DetectionResult(bbox=(150, 105, 245, 195), confidence=0.88, class_name="head")


def _helmet() -> DetectionResult:
    return DetectionResult(bbox=(148, 92, 247, 162), confidence=0.86, class_name="helmet")


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
async def test_auto_track_ignores_person_without_head_or_with_helmet(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path, monkeypatch)

    await service.process_frame([_person()], b"", frame_index=1, current_task_id="task")
    await service.process_frame([_person()], b"", frame_index=2, current_task_id="task")
    assert service.get_status()["state"] == AutoTrackState.IDLE.value
    assert service.get_status()["active_target"] is None

    await service.process_frame([_person(), _head(), _helmet()], b"", frame_index=3, current_task_id="task")
    await service.process_frame([_person(), _head(), _helmet()], b"", frame_index=4, current_task_id="task")
    assert service.get_status()["state"] == AutoTrackState.IDLE.value
    assert service.get_status()["active_target"] is None


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
async def test_transient_lost_does_not_send_stop_until_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path, monkeypatch)

    await _feed_head_person_frames(service, start_frame=1, count=5)
    assert service.get_status()["state"] == AutoTrackState.FOLLOWING.value

    await service.process_frame([], b"", frame_index=6, current_task_id="task")
    status = service.get_status()
    assert status["state"] == AutoTrackState.LOST.value
    assert not any(cmd == "stop" for cmd, _ in service._control_service.commands)

    for frame_index in range(7, 11):
        await service.process_frame([], b"", frame_index=frame_index, current_task_id="task")
    await asyncio.sleep(0)

    assert any(cmd == "stop" for cmd, _ in service._control_service.commands)


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
async def test_tracking_stops_when_target_has_helmet_for_five_frames(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path, monkeypatch)

    await _feed_head_person_frames(service, start_frame=1, count=5)
    assert service.get_status()["state"] == AutoTrackState.FOLLOWING.value

    for frame_index in range(6, 10):
        await service.process_frame([_person(), _head(), _helmet()], b"", frame_index=frame_index, current_task_id="task")
        status = service.get_status()
        assert status["state"] == AutoTrackState.FOLLOWING.value
        assert status["active_target"]["helmet_hits"] == frame_index - 5

    await service.process_frame([_person(), _head(), _helmet()], b"", frame_index=10, current_task_id="task")
    await asyncio.sleep(0)

    status = service.get_status()
    assert status["state"] == AutoTrackState.STOPPED.value
    assert status["stop_reason"] == TrackStopReason.HELMET_CONFIRMED.value
    assert any(cmd == "stop" for cmd, _ in service._control_service.commands)
