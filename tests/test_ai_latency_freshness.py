import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from backend import workers_ai
from test_workers_ai_timeout import _worker, _FastDetector


@pytest.mark.asyncio
async def test_inference_uses_frame_arriving_during_task_check(tmp_path, monkeypatch):
    worker = _worker(tmp_path, monkeypatch)
    stop, release, queued = asyncio.Event(), asyncio.Event(), asyncio.Event()
    reads = 0

    async def readexactly(_):
        nonlocal reads
        reads += 1
        if reads == 1:
            return b'old'
        if reads == 2:
            await release.wait()
            return b'latest'
        await asyncio.Event().wait()

    process = SimpleNamespace(stdout=SimpleNamespace(readexactly=readexactly), communicate=AsyncMock(return_value=(b'', b'')))
    monkeypatch.setattr(worker, '_start_ffmpeg', AsyncMock(return_value=process))
    for name in ('_drain_stderr', '_stop_ffmpeg_when_mission_inactive', '_stop_ffmpeg_on_memory_limit', '_terminate_ffmpeg_process', '_notify_auto_track_video_lost'):
        monkeypatch.setattr(worker, name, AsyncMock())
    monkeypatch.setattr(worker, '_is_mission_active', lambda: True)
    monkeypatch.setattr(worker, '_get_frame_skip', lambda: 1)
    put_latest = worker._put_latest_frame

    async def put(queue, frame):
        result = await put_latest(queue, frame)
        if frame.data == b'latest':
            queued.set()
        return result

    async def task_check():
        release.set()
        await queued.wait()

    consumed = []
    async def consume(frame, *args, **kwargs):
        consumed.append(frame)
        stop.set()

    monkeypatch.setattr(worker, '_put_latest_frame', put)
    monkeypatch.setattr(worker, '_update_current_task_id', task_check)
    monkeypatch.setattr(worker, '_process_frame_with_timeout', consume)
    await asyncio.wait_for(worker._run_ffmpeg_loop(stop), 1)
    assert consumed == [b'latest']


@pytest.mark.asyncio
async def test_empty_pose_clears_cached_person_and_overlay_precedes_evidence(tmp_path, monkeypatch):
    worker = _worker(tmp_path, monkeypatch)
    worker._detector = _FastDetector()
    worker._pose_detector = object()
    worker._pose_event_engine = Mock()
    worker._pose_event_engine.update.return_value = ([], ['pose_event'])
    worker._latest_pose_observations = [object()]
    worker._latest_pose_observations_at = time.monotonic()
    monkeypatch.setattr(workers_ai.settings, 'POSE_FRAME_SKIP', 1)
    monkeypatch.setattr(worker, '_infer_pose', AsyncMock(return_value=([], time.monotonic(), 1)))
    monkeypatch.setattr(worker, '_process_detection', AsyncMock())
    monkeypatch.setattr(worker, '_report_face_service_fault', AsyncMock())
    monkeypatch.setattr(worker, '_maybe_process_weather', AsyncMock())
    calls = []
    async def overlay(poses, detections, **kwargs):
        assert poses == [] and detections == []
        calls.append(kwargs.get('stage', 'complete'))
    async def evidence(events, frame):
        assert events == ['pose_event']
        calls.append('evidence')
    monkeypatch.setattr(worker, '_broadcast_pose_overlay', overlay)
    monkeypatch.setattr(worker, '_process_pose_events', evidence)
    await worker._detect_and_process_frame(b'frame', 1)
    assert worker._latest_pose_observations == []
    assert calls == ['pose_location', 'complete', 'evidence']
