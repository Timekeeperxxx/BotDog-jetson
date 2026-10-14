from __future__ import annotations

from pathlib import Path

import pytest

import backend.workers_ai_processing as processing
from backend.pose_detection import PoseEvent, Posture
from backend.workers_ai_processing import AIWorkerProcessingMixin


class _SessionContext:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *_args: object) -> None:
        return None


class _AlertService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def handle_ai_event(self, **kwargs: object) -> None:
        self.calls.append(kwargs)


class _Worker(AIWorkerProcessingMixin):
    def __init__(self) -> None:
        self._current_task_id = None
        self.saved_frames: list[bytes] = []

    def _session_factory(self) -> _SessionContext:
        return _SessionContext()

    async def _save_snapshot(self, frame: bytes) -> tuple[Path, str]:
        self.saved_frames.append(frame)
        return Path("/snapshots/climbing.jpg"), "/api/v1/static/climbing.jpg"

    def _get_latest_gps(self) -> tuple[None, None]:
        return None, None


@pytest.mark.asyncio
@pytest.mark.parametrize('event_type,event_code,label', [
    ('POSE_CLIMBING_SUSPECTED', 'E_POSE_CLIMBING_SUSPECTED', '检测到人员疑似攀爬'),
    ('POSE_VAULTING_SUSPECTED', 'E_POSE_VAULTING_SUSPECTED', '检测到人员疑似翻越'),
])
async def test_climbing_event_immediately_saves_snapshot_and_evidence(
    monkeypatch: pytest.MonkeyPatch,
    event_type: str, event_code: str, label: str,
) -> None:
    alert_service = _AlertService()
    monkeypatch.setattr(processing, "get_alert_service", lambda: alert_service)
    worker = _Worker()
    event = PoseEvent(
        event_type=event_type,
        track_id=7,
        confidence=0.91,
        bbox=(10, 20, 100, 200),
        posture=Posture.CLIMBING,
        duration_seconds=0.8,
    )

    await worker._process_pose_events([event], b"current-frame")

    assert worker.saved_frames == [b"current-frame"]
    assert len(alert_service.calls) == 1
    assert alert_service.calls[0]["event_type"] == event_type
    assert alert_service.calls[0]["event_code"] == event_code
    assert alert_service.calls[0]["message"].startswith(label + '：')
    assert alert_service.calls[0]["file_path"] == "/snapshots/climbing.jpg"
    assert alert_service.calls[0]["image_url"] == "/api/v1/static/climbing.jpg"
