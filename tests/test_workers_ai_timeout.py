from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import pytest

from backend import workers_ai
from backend.workers_ai import AIWorker, AIWorkerFrameTimeout, DetectionResult, _AIFrame


class _SessionFactory:
    def __call__(self) -> "_SessionFactory":
        return self

    async def __aenter__(self) -> "_SessionFactory":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None


class _MavlinkGateway:
    def get_latest_position(self) -> None:
        return None


class _HangingDetector:
    def detect_many(self, frame: bytes) -> list[DetectionResult]:
        time.sleep(0.2)
        return []


class _FastDetector:
    def detect_many(self, frame: bytes) -> list[DetectionResult]:
        return []


class _FakeAutoTrack:
    def __init__(
        self,
        *,
        enabled: bool,
        paused: bool = False,
        active_target: object | None = None,
        candidates: dict[int, object] | None = None,
    ) -> None:
        self._enabled = enabled
        self._paused = paused
        self._active_target = active_target
        self._candidates = candidates or {}


class _FakeProcess:
    def __init__(self, *, wait_never_finishes: bool = False) -> None:
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False
        self.wait_never_finishes = wait_never_finishes

    def terminate(self) -> None:
        self.terminated = True
        if not self.wait_never_finishes:
            self.returncode = -15

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    async def wait(self) -> int:
        if self.wait_never_finishes and not self.killed:
            await asyncio.Future()
        return self.returncode or 0


def _worker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AIWorker:
    monkeypatch.setattr(workers_ai.settings, "AI_SIMULATE_DETECTION", True)
    monkeypatch.setattr(workers_ai.settings, "AI_FRAME_PROCESS_TIMEOUT_SECONDS", 1.0)
    monkeypatch.setattr(workers_ai.settings, "AI_EXIT_ON_FRAME_TIMEOUT", False)
    monkeypatch.setattr(workers_ai.settings, "AI_MAX_FRAME_AGE_SECONDS", 0.35)
    monkeypatch.setattr(workers_ai.settings, "AI_EVENT_SEND_TIMEOUT_SECONDS", 0.03)
    monkeypatch.setattr(workers_ai.settings, "AI_PATROL_SKIP", 2)
    monkeypatch.setattr(workers_ai.settings, "AI_AUTO_TRACK_SKIP", 1)
    monkeypatch.setattr(workers_ai.settings, "AI_SUSPECT_SKIP", 1)
    worker = AIWorker(
        session_factory=_SessionFactory(),
        state_machine=object(),
        mavlink_gateway=_MavlinkGateway(),
        snapshot_dir=tmp_path,
    )
    worker._frame_process_timeout_s = 0.01
    return worker


@pytest.mark.asyncio
async def test_ai_frame_processing_timeout_detects_stuck_detector(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)
    worker._detector = _HangingDetector()

    async def noop_video_lost(reason: str) -> None:
        return None

    monkeypatch.setattr(worker, "_notify_auto_track_video_lost", noop_video_lost)

    with pytest.raises(AIWorkerFrameTimeout):
        await worker._process_frame_with_timeout(b"\0", frame_index=542)

    assert worker._frames_processed == 0
    assert worker._last_frame_timeout_reason is not None
    assert "frame_index=542" in worker._last_frame_timeout_reason
    assert worker._ffmpeg_last_exit_reason.startswith("AI_Frame_Process_Timeout")


@pytest.mark.asyncio
async def test_ai_frame_processing_timeout_detects_stuck_post_processing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)
    worker._detector = _FastDetector()

    async def slow_process_detection(*args: Any, **kwargs: Any) -> None:
        await asyncio.sleep(0.2)

    async def noop_video_lost(reason: str) -> None:
        return None

    monkeypatch.setattr(worker, "_process_detection", slow_process_detection)
    monkeypatch.setattr(worker, "_notify_auto_track_video_lost", noop_video_lost)

    with pytest.raises(AIWorkerFrameTimeout):
        await worker._process_frame_with_timeout(b"\0", frame_index=543)

    assert worker._frames_processed == 0
    assert worker._last_frame_timeout_reason is not None
    assert "frame_index=543" in worker._last_frame_timeout_reason


@pytest.mark.asyncio
async def test_ai_frame_processing_clears_timeout_after_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)
    worker._detector = _FastDetector()
    worker._last_frame_timeout_reason = "previous"

    async def noop_process_detection(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(worker, "_process_detection", noop_process_detection)

    await worker._process_frame_with_timeout(b"\0", frame_index=544)

    assert worker._frames_processed == 1
    assert worker._last_frame_timeout_reason is None
    assert worker._last_frame_completed_at >= worker._last_frame_started_at


@pytest.mark.asyncio
async def test_ai_frame_queue_keeps_only_latest_frame() -> None:
    queue: asyncio.Queue[_AIFrame] = asyncio.Queue(maxsize=1)
    old_frame = _AIFrame(data=b"old", index=1, read_at=1.0)
    latest_frame = _AIFrame(data=b"latest", index=2, read_at=2.0)

    assert await AIWorker._put_latest_frame(queue, old_frame) == 0
    assert await AIWorker._put_latest_frame(queue, latest_frame) == 1

    queued = queue.get_nowait()
    assert queued.data == b"latest"
    assert queued.index == 2


def test_ai_frame_skip_uses_patrol_skip_without_tracking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)

    import backend.auto_track_service as auto_track_service
    import backend.guard_mission_service as guard_mission_service

    monkeypatch.setattr(auto_track_service, "get_auto_track_service", lambda: None)
    monkeypatch.setattr(guard_mission_service, "get_guard_mission_service", lambda: None)

    assert worker._get_frame_skip() == 2


def test_ai_frame_skip_uses_auto_track_skip_while_finding_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)

    import backend.auto_track_service as auto_track_service
    import backend.guard_mission_service as guard_mission_service

    monkeypatch.setattr(
        auto_track_service,
        "get_auto_track_service",
        lambda: _FakeAutoTrack(enabled=True, active_target=None, candidates={}),
    )
    monkeypatch.setattr(guard_mission_service, "get_guard_mission_service", lambda: None)

    assert worker._get_frame_skip() == 1


def test_ai_frame_skip_falls_back_to_patrol_when_auto_track_paused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)

    import backend.auto_track_service as auto_track_service
    import backend.guard_mission_service as guard_mission_service

    monkeypatch.setattr(
        auto_track_service,
        "get_auto_track_service",
        lambda: _FakeAutoTrack(enabled=True, paused=True),
    )
    monkeypatch.setattr(guard_mission_service, "get_guard_mission_service", lambda: None)

    assert worker._get_frame_skip() == 2


@pytest.mark.asyncio
async def test_ai_frame_processing_records_latency_metrics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)
    worker._detector = _FastDetector()

    async def noop_process_detection(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(worker, "_process_detection", noop_process_detection)
    broadcast_metrics: list[tuple[int, float, float]] = []

    async def capture_status() -> None:
        broadcast_metrics.append(
            (
                worker._last_processed_frame_index,
                worker._last_processing_ms,
                worker._last_end_to_end_ms,
            )
        )

    monkeypatch.setattr(worker, "_maybe_broadcast_status", capture_status)

    frame_read_at = time.monotonic() - 0.05
    await worker._process_frame_with_timeout(
        b"\0",
        frame_index=545,
        frame_read_at=frame_read_at,
    )

    assert worker._last_processed_frame_index == 545
    assert worker._last_frame_age_ms >= 0
    assert worker._last_processing_ms >= 0
    assert worker._last_end_to_end_ms >= worker._last_processing_ms
    assert broadcast_metrics == [
        (545, worker._last_processing_ms, worker._last_end_to_end_ms)
    ]


@pytest.mark.asyncio
async def test_ai_ffmpeg_termination_kills_after_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)
    process = _FakeProcess(wait_never_finishes=True)

    await worker._terminate_ffmpeg_process(
        process,  # type: ignore[arg-type]
        reason="mission_inactive",
        terminate_timeout_s=0.01,
    )

    assert process.terminated is True
    assert process.killed is True
    assert process.returncode == -9
    assert worker._ffmpeg_last_exit_reason == "mission_inactive"
