import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from backend import workers_ai
from backend.weather_detection import WeatherDetectionService
from backend.workers_ai import AIWorker, DetectionResult, _YoloDetector
from backend.workers_ai_packages import PackageDetection
from test_workers_ai_timeout import _worker


@pytest.mark.asyncio
@pytest.mark.parametrize('current_face', ['recognized', 'no_face', 'unavailable'])
async def test_person_alerts_use_current_identity_before_package_and_only_count_once(
    tmp_path, monkeypatch, current_face,
):
    worker = _worker(tmp_path, monkeypatch)
    # A previous recognized state must be replaced before an early decision.
    person = DetectionResult('person', .9, (10, 10, 100, 200),
                             face_status='recognized', identity_id=99)
    worker._detector = SimpleNamespace(detect_many=lambda _: [person])
    monkeypatch.setattr(worker, '_is_weapon_due', lambda *args, **kwargs: False)
    monkeypatch.setattr('backend.fence_detection_service.get_fence_detection_service', lambda: None)
    monkeypatch.setattr('backend.auto_track_service.get_auto_track_service', lambda: None)
    monkeypatch.setattr('backend.guard_mission_service.get_guard_mission_service', lambda: None)
    fusion = SimpleNamespace(enabled=True, ingest_visible=Mock())
    gimbal = SimpleNamespace(get_cached_status=lambda **kwargs: SimpleNamespace(
        picture_mode='visible', relative_yaw_deg=0., relative_pitch_deg=0., zoom_ratio=1.))
    monkeypatch.setattr('backend.multisensor_fusion.get_multisensor_fusion_service', lambda: fusion)
    monkeypatch.setattr('backend.z2mini_gimbal.get_z2mini_gimbal', lambda: gimbal)
    calls = []
    observed_at = time.monotonic()

    async def face(frame, detections, *args):
        assert frame == b'current'
        person.face_status = current_face
        person.identity_id = 7 if current_face == 'recognized' else None
        calls.append('face')

    async def permissions(persons, *, frame_monotonic):
        assert frame_monotonic == observed_at
        person.map_access = {'status': 'allowed' if current_face == 'recognized' else 'indeterminate'}
        calls.append('permissions')

    async def person_alert(detections, frame):
        assert person in detections and frame == b'current'
        assert person.face_status == current_face
        assert person.identity_id == (7 if current_face == 'recognized' else None)
        assert person.map_access is not None
        calls.append('person_alert')

    package_started, release_package = asyncio.Event(), asyncio.Event()
    bag = PackageDetection('backpack', .8, (120, 120, 160, 180))
    async def package(frame, timestamp, *, person_detections):
        assert timestamp == observed_at and person_detections == [person]
        package_started.set()
        await release_package.wait()
        worker._package_updated = True
        worker._last_package_ms = 1.
        calls.append('package')
        return [], [bag]

    async def weather(*args, **kwargs):
        calls.append('weather')

    service = SimpleNamespace(ensure_initialized=AsyncMock(), annotate_frame=face,
                              status=lambda: {'available': True, 'enabled': True})
    monkeypatch.setattr('backend.services_face_identities.get_face_identity_service', lambda: service)
    monkeypatch.setattr('backend.services_map_access.get_map_access_service', lambda: SimpleNamespace(annotate=permissions))
    monkeypatch.setattr(worker, '_report_face_service_fault', AsyncMock())
    early = AsyncMock(side_effect=person_alert)
    monkeypatch.setattr(worker, '_process_person_alerts', early)
    monkeypatch.setattr(worker, '_maybe_infer_packages', package)
    monkeypatch.setattr(worker, '_broadcast_pose_overlay', AsyncMock())
    monkeypatch.setattr(worker, '_maybe_process_weather', weather)
    task = asyncio.create_task(worker._detect_and_process_frame(b'current', 1, frame_read_at=observed_at))
    try:
        await asyncio.wait_for(package_started.wait(), 1)
        assert calls == ['face', 'permissions', 'person_alert']
        fusion.ingest_visible.assert_not_called()
    finally:
        release_package.set()
        await task
    assert calls == ['face', 'permissions', 'person_alert', 'package', 'weather']
    assert early.await_count == 1
    assert worker._frames_processed == 1
    fusion.ingest_visible.assert_called_once()
    assert bag in fusion.ingest_visible.call_args.kwargs['detections']


def test_continuously_busy_cycles_still_complete_spaced_weather_round(monkeypatch):
    now = [100.]
    monkeypatch.setattr('backend.workers_ai.time.monotonic', lambda: now[0])
    samples = []
    class Classifier:
        device = 'cpu'
        def predict(self, frame):
            samples.append((now[0], frame))
            return {'normal': .9}
    service = WeatherDetectionService(enabled=True, classifier=Classifier())
    service.next_sample_at = 100.
    async def inference(label, fn, frame):
        return fn(frame)
    worker = SimpleNamespace(_weather_service=service, _last_weather_inference_at=0.,
        _last_weather_ms=0., _weather_warmed_up=False, _run_inference=inference)
    async def run():
        for step in range(81):
            now[0] = 100. + step * .25
            await AIWorker._maybe_process_weather(worker, str(now[0]).encode(), defer=True)
    asyncio.run(run())
    assert [t for t, frame in samples] == [101., 104., 107., 110., 113., 116.]
    assert all(frame == str(t).encode() for t, frame in samples)
    assert service.get_status()['label'] == 'normal'
    assert service.get_status()['rounds_processed'] == 1
    assert service.next_sample_at == 416.


@pytest.mark.asyncio
async def test_final_packet_preserves_package_before_pose_fallback(tmp_path, monkeypatch):
    worker = _worker(tmp_path, monkeypatch)
    worker._detector = SimpleNamespace(detect_many=lambda _: [DetectionResult('head', .8, (20,20,40,40))])
    worker._latest_pose_observations = [SimpleNamespace(bbox=(10,10,100,200), confidence=.9, track_id=7)]
    monkeypatch.setattr(worker, '_is_weapon_due', lambda *args, **kwargs: False)
    monkeypatch.setattr('backend.fence_detection_service.get_fence_detection_service', lambda: None)
    monkeypatch.setattr('backend.auto_track_service.get_auto_track_service', lambda: None)
    monkeypatch.setattr('backend.guard_mission_service.get_guard_mission_service', lambda: None)
    service = SimpleNamespace(ensure_initialized=AsyncMock(), annotate_frame=AsyncMock(),
                              status=lambda: {'available':True, 'enabled':True})
    monkeypatch.setattr('backend.services_face_identities.get_face_identity_service', lambda: service)
    monkeypatch.setattr('backend.services_map_access.get_map_access_service', lambda: SimpleNamespace(annotate=AsyncMock()))
    monkeypatch.setattr(worker, '_process_person_alerts', AsyncMock())
    monkeypatch.setattr(worker, '_report_face_service_fault', AsyncMock())
    monkeypatch.setattr(worker, '_maybe_process_weather', AsyncMock())
    bag = PackageDetection('backpack', .8, (120,120,160,180))
    monkeypatch.setattr(worker, '_maybe_infer_packages', AsyncMock(return_value=([],[bag])))
    overlay = AsyncMock()
    monkeypatch.setattr(worker, '_broadcast_pose_overlay', overlay)
    await worker._detect_and_process_frame(b'current', 1)
    final = overlay.await_args_list[-1].args[1]
    assert [d.label for d in final] == ['head', 'backpack', 'person']


@pytest.mark.parametrize('tracked', [False, True])
def test_batched_boxes_preserve_coordinates_aliases_confidence_and_track_ids(tracked):
    detector = object.__new__(_YoloDetector)
    detector._class_names = {0: 'guns', 1: 'knife', 2: 'person'}
    detector._target_classes = {'guns', 'knife'}
    rows = [[1.9, 2.1, 30.8, 40.9, .82, 0], [3., 4., 10., 20., .6, 2],
            [5., 6., 15., 26., .7, 1]]
    if tracked:
        rows = [row[:4] + [i + 41] + row[4:] for i, row in enumerate(rows)]
    class Boxes:
        is_track = tracked
        def __len__(self): return len(rows)
        def detach(self): return self
        def cpu(self): return self
        def tolist(self): return rows
    boxes = Boxes()
    boxes.data = boxes
    actual = detector._result_to_detections(SimpleNamespace(boxes=boxes), offset_x=10, offset_y=-2)
    assert actual == [DetectionResult('guns', .82, (11, 0, 40, 38), 41 if tracked else -1),
                      DetectionResult('knife', .7, (15, 4, 25, 24), 43 if tracked else -1)]
    rows.clear()
    assert detector._result_to_detections(SimpleNamespace(boxes=boxes)) == []
