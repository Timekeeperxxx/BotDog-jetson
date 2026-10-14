from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.config import Settings
from backend.pose_detection import PoseEventEngine, RawPose
from backend.temperature_monitor import TemperatureMonitor
from backend import temperature_monitor, workers_ai_processing
from backend.workers_ai_processing import AIWorkerProcessingMixin


def test_all_automatic_alert_defaults_are_thirty_seconds():
    settings = Settings(_env_file=None)
    assert settings.AI_COOLDOWN_SECONDS == 30
    assert settings.PERSON_ALERT_STABLE_HITS == 5
    for key in ('POSE_EVENT_COOLDOWN_SECONDS',
                'WEAPON_ALERT_COOLDOWN_SECONDS', 'FENCE_ALERT_COOLDOWN_SECONDS',
                'THERMAL_ALERT_COOLDOWN_SECONDS'):
        assert getattr(settings, key) == 30


def test_pose_alert_suppresses_inside_two_seconds_and_emits_at_boundary(monkeypatch):
    engine = PoseEventEngine()
    monkeypatch.setattr(engine, '_detect_climb_motion', lambda state: (True, .7))
    pose = RawPose((0, 0, 100, 200), .9, ())
    assert len(engine.update([pose], now=10)[1]) == 1
    for tick in range(11, 40):
        assert not [e for e in engine.update([pose], now=tick)[1] if e.event_type == 'POSE_CLIMBING_SUSPECTED']
    assert len([e for e in engine.update([pose], now=40)[1] if e.event_type == 'POSE_CLIMBING_SUSPECTED']) == 1


def test_temperature_alert_suppresses_inside_two_seconds_and_emits_at_boundary(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(temperature_monitor.asyncio, 'get_event_loop', lambda: SimpleNamespace(time=lambda: now[0]))
    monkeypatch.setattr(temperature_monitor.settings, 'THERMAL_ALERT_COOLDOWN_SECONDS', 2)
    alerts = []
    monitor = TemperatureMonitor(threshold=60, on_alert=alerts.append)
    monitor.update_temperature('T_MAX', 70)
    now[0] = 101.999
    monitor.update_temperature('T_MAX', 71)
    assert len(alerts) == 1
    now[0] = 102
    monitor.update_temperature('T_MAX', 72)
    assert len(alerts) == 2


@pytest.mark.asyncio
async def test_continuously_visible_person_realerts_after_thirty_seconds_per_track(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(workers_ai_processing.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(workers_ai_processing.settings, 'AI_COOLDOWN_SECONDS', 30)
    worker = AIWorkerProcessingMixin()
    worker._person_alert_last_seen = {}
    worker._person_pose_hits = {}
    worker._person_alert_frame = 0
    worker._reset_misses = 20
    worker._raise_alert = AsyncMock()
    persons = [SimpleNamespace(label='person', track_id=i, face_status='unknown', identity_id=None) for i in (1, 2)]
    for _ in range(4):
        await worker._process_person_alerts(persons, b'frame')
        assert worker._raise_alert.await_count == 0
    await worker._process_person_alerts(persons, b'frame')
    assert worker._raise_alert.await_count == 1
    now[0] = 129.999
    await worker._process_person_alerts(persons, b'frame')
    assert worker._raise_alert.await_count == 1
    now[0] = 130
    await worker._process_person_alerts(persons, b'frame')
    assert worker._raise_alert.await_count == 2
