import asyncio
from unittest.mock import AsyncMock
from types import SimpleNamespace

import pytest
from backend.config import settings
from backend.alert_service import AlertService
from backend.workers_ai import AIWorker, DetectionResult


def make_worker(monkeypatch):
    monkeypatch.setattr(settings, 'WEAPON_ENABLED', True)
    worker = AIWorker.__new__(AIWorker)
    worker._weapon_generation = 0
    worker._weapon_detector = SimpleNamespace(detect_many=lambda frame: [])
    worker._weapon_status = 'ready'
    worker._weapon_frame_skip = 3
    worker._weapon_active_until = 100
    worker._weapon_hits = {'guns': 1, 'knife': 2}
    worker._weapon_last_bbox = {'guns': (0, 0, 10, 10), 'knife': None}
    worker._weapon_first_seen = {'guns': 1}
    worker._weapon_last_alert_at = {'guns': 30, 'knife': 40}
    worker._last_weapon_ms = 1
    worker._weapon_warmed_up = True
    worker._run_inference = AsyncMock(side_effect=lambda stage, function, *args, **kw: function(*args, **kw))
    worker._raise_alert = AsyncMock(return_value=True)
    return worker


@pytest.mark.asyncio
async def test_disable_stops_scheduling_inference_and_alerts(monkeypatch):
    worker = make_worker(monkeypatch)
    await worker.set_weapon_detection_enabled(False)
    assert not settings.WEAPON_ENABLED
    assert worker._weapon_status == 'disabled'
    assert not worker._is_weapon_due(3, now=1)
    assert await worker._infer_weapon(b'frame') == ([], 0.0)
    await worker._process_weapon_detections([DetectionResult('guns', .9, (0, 0, 10, 10))], b'frame')
    worker._run_inference.assert_not_called()
    worker._raise_alert.assert_not_called()
    assert worker._weapon_hits == {'guns': 0, 'knife': 0}
    assert worker._weapon_last_alert_at == {'guns': 30, 'knife': 40}


@pytest.mark.asyncio
async def test_reenable_uses_ready_model_and_keeps_cooldown(monkeypatch):
    worker = make_worker(monkeypatch)
    monkeypatch.setattr(settings, 'AI_SIMULATE_DETECTION', False)
    await worker.set_weapon_detection_enabled(False)
    await worker.set_weapon_detection_enabled(True)
    assert settings.WEAPON_ENABLED
    assert worker._is_weapon_due(3, now=1)
    worker._run_inference.assert_not_called()
    assert worker._weapon_last_alert_at['guns'] == 30


@pytest.mark.asyncio
async def test_enable_after_starting_disabled_loads_model(monkeypatch):
    worker = make_worker(monkeypatch)
    monkeypatch.setattr(settings, 'AI_SIMULATE_DETECTION', False)
    worker._weapon_detector = None
    detector = object()
    worker._create_weapon_detector = lambda: detector
    await worker.set_weapon_detection_enabled(True)
    assert settings.WEAPON_ENABLED and worker._weapon_detector is detector
    assert not worker._weapon_warmed_up


@pytest.mark.asyncio
async def test_failed_model_load_stays_disabled(monkeypatch):
    worker = make_worker(monkeypatch)
    monkeypatch.setattr(settings, 'AI_SIMULATE_DETECTION', False)
    worker._weapon_detector = None
    worker._run_inference = AsyncMock(side_effect=RuntimeError('missing model'))
    with pytest.raises(ValueError, match='加载失败'):
        await worker.set_weapon_detection_enabled(True)
    assert not settings.WEAPON_ENABLED


@pytest.mark.asyncio
async def test_old_inference_result_is_discarded_after_off_on(monkeypatch):
    worker = make_worker(monkeypatch)
    monkeypatch.setattr(settings, 'WEAPON_PERSON_CROP_ENABLED', False)
    monkeypatch.setattr(settings, 'AI_SIMULATE_DETECTION', False)
    started, release = asyncio.Event(), asyncio.Event()
    async def infer(*args, **kwargs):
        started.set()
        await release.wait()
        return [DetectionResult('guns', .9, (0, 0, 10, 10))]
    worker._run_inference = infer
    task = asyncio.create_task(worker._infer_weapon(b'frame'))
    await started.wait()
    await worker.set_weapon_detection_enabled(False)
    await worker.set_weapon_detection_enabled(True)
    release.set()
    assert (await task)[0] == []


@pytest.mark.asyncio
async def test_snapshot_finishing_after_switch_off_does_not_emit(monkeypatch):
    from backend import workers_ai_processing
    worker = make_worker(monkeypatch)
    async def snapshot(frame):
        await worker.set_weapon_detection_enabled(False)
        return 'unused.jpg', '/unused.jpg'
    worker._save_snapshot = snapshot
    service = SimpleNamespace(handle_ai_event=AsyncMock())
    monkeypatch.setattr(workers_ai_processing, 'get_alert_service', lambda: service)
    assert not await AIWorker._raise_alert(worker, DetectionResult('knife', .9, (0, 0, 10, 10)), b'frame')
    service.handle_ai_event.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('code', ['E_AI_GUNS', 'E_AI_KNIFE'])
@pytest.mark.parametrize('interval', [0, 30])
async def test_central_service_blocks_disabled_weapon_even_without_cooldown(monkeypatch, code, interval):
    monkeypatch.setattr(settings, 'WEAPON_ENABLED', False)
    monkeypatch.setattr(settings, 'WEAPON_ALERT_COOLDOWN_SECONDS', interval)
    service = AlertService()
    emit = AsyncMock()
    assert not await service.automatic_event_due(code)
    assert await service._run_automatic_event(code, None, emit) is None
    emit.assert_not_called()


@pytest.mark.asyncio
async def test_pending_alert_rechecks_switch_after_database_await(monkeypatch):
    monkeypatch.setattr(settings, 'WEAPON_ENABLED', True)
    service = AlertService()
    async def due(*args):
        monkeypatch.setattr(settings, 'WEAPON_ENABLED', False)
        return True
    service.automatic_event_due = due
    emit = AsyncMock()
    assert await service._run_automatic_event('E_AI_GUNS', None, emit) is None
    emit.assert_not_called()
