import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from backend import workers_ai
from backend.workers_ai import DetectionResult
from backend.pose_detection import PoseObservation, Posture
from test_workers_ai_timeout import _worker


@pytest.mark.asyncio
@pytest.mark.parametrize('main_person', [True, False])
async def test_location_precedes_slow_models_but_decisions_wait_for_current_identity(tmp_path, monkeypatch, main_person):
    worker = _worker(tmp_path, monkeypatch)
    person = DetectionResult(label='person', confidence=.9, bbox=(10, 10, 100, 200))
    worker._detector = SimpleNamespace(detect_many=lambda _: [person] if main_person else [])
    worker._pose_detector = object()
    observation = PoseObservation(track_id=3, bbox=(10,10,100,200), confidence=.9, keypoints=(), posture=Posture.UNKNOWN, posture_confidence=0, inside_zone=False, dwell_seconds=0)
    worker._pose_event_engine = Mock()
    worker._pose_event_engine.update.return_value = ([observation], [])
    fence = SimpleNamespace(enabled=True, tracking_override=False, process_frame=Mock(return_value=[]))
    monkeypatch.setattr('backend.fence_detection_service.get_fence_detection_service', lambda: fence)
    monkeypatch.setattr(workers_ai.settings, 'POSE_FRAME_SKIP', 1)
    monkeypatch.setattr(worker, '_is_weapon_due', lambda *args, **kwargs: True)
    monkeypatch.setattr(workers_ai.settings, 'WEAPON_PERSON_CROP_ENABLED', True, raising=False)
    worker._weapon_active_until = time.monotonic() + 60
    calls = []
    async def overlay(poses, detections, **kwargs):
        stage = kwargs.get('stage', 'complete')
        calls.append(stage)
        assert any(d.label == 'person' for d in detections)
    async def pose(_):
        if main_person:
            assert calls == ['location']
        return [], time.monotonic(), 1
    async def weapon(*args):
        assert 'pose_location' in calls
        calls.append('weapon')
        return [], 1
    async def face(frame, detections, *args):
        assert 'pose_location' in calls
        for d in detections:
            if d.label == 'person':
                d.face_status = 'recognized'
                d.identity_id = 7
        calls.append('face')
    async def decision(detections, *args, **kwargs):
        assert all(d.face_status == 'recognized' and d.identity_id == 7 for d in detections if d.label == 'person')
        assert calls[-1] == 'complete'
        calls.append('decision')
    service = SimpleNamespace(ensure_initialized=AsyncMock(), annotate_frame=face, status=lambda: {'available':True, 'enabled':True})
    monkeypatch.setattr('backend.services_face_identities.get_face_identity_service', lambda: service)
    monkeypatch.setattr(worker, '_infer_pose', pose)
    monkeypatch.setattr(worker, '_infer_weapon', weapon)
    monkeypatch.setattr(worker, '_broadcast_pose_overlay', overlay)
    monkeypatch.setattr(worker, '_process_detection', decision)
    for name in ('_maybe_process_weather', '_process_pose_events', '_process_weapon_detections', '_process_fence_events', '_report_face_service_fault'):
        monkeypatch.setattr(worker, name, AsyncMock())
    await worker._detect_and_process_frame(b'frame', 2, frame_read_at=time.monotonic())
    assert calls[-3:] == ['face', 'complete', 'decision']


@pytest.mark.asyncio
async def test_early_payload_is_neutral_and_same_frame_completion_is_not_throttled(tmp_path, monkeypatch):
    worker = _worker(tmp_path, monkeypatch)
    sent = []
    broadcaster = SimpleNamespace(connection_count=1, publish_latest_overlay=lambda message, timeout: sent.append(message))
    monkeypatch.setattr('backend.workers_ai_processing.get_event_broadcaster', lambda: broadcaster)
    monkeypatch.setattr('backend.fence_detection_service.get_fence_detection_service', lambda: None)
    worker._last_pose_overlay_broadcast = time.monotonic()
    worker._current_frame_received_at = time.monotonic() - .1
    person = DetectionResult(label='person', confidence=.9, bbox=(1,2,3,4), face_status='recognized', identity_id=7, display_name='Known')
    await worker._broadcast_pose_overlay([], [person], stage='location', force=True)
    await worker._broadcast_pose_overlay([], [person], force=True)
    assert len(sent) == 2
    first, final = [item['payload'] for item in sent]
    assert first['detections'][0]['face_status'] == 'pending'
    assert first['detections'][0]['identity_id'] is None
    assert final['detections'][0]['identity_id'] == 7
    assert first['frame_received_at_monotonic'] == final['frame_received_at_monotonic']
    assert first['frame_age_ms'] >= 90
    assert person.identity_id == 7
