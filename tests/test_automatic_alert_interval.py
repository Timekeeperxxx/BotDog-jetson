import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend import alert_service, database
from backend.alert_service import AlertService
from backend.database import Base
from backend.models import AnomalyEvidence
from backend.temperature_monitor import TemperatureAlert


@pytest.fixture
async def harness(monkeypatch):
    monkeypatch.setattr(alert_service.settings, "WEAPON_ENABLED", True)
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    clock = [100.0]
    base = datetime(2026, 10, 8, tzinfo=timezone.utc)
    monkeypatch.setattr(alert_service.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(alert_service, 'utc_now_iso', lambda: (
        base + timedelta(seconds=clock[0])
    ).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))
    monkeypatch.setattr(database, 'get_session_factory', lambda: factory)
    for key in ('AI_COOLDOWN_SECONDS', 'WEAPON_ALERT_COOLDOWN_SECONDS',
                'POSE_EVENT_COOLDOWN_SECONDS', 'FENCE_ALERT_COOLDOWN_SECONDS',
                'THERMAL_ALERT_COOLDOWN_SECONDS'):
        monkeypatch.setattr(alert_service.settings, key, 30)
    broadcaster = AsyncMock()
    service = AlertService(broadcaster)
    yield service, factory, clock, broadcaster
    await engine.dispose()


async def emit(service, factory, code, **extra):
    async with factory() as session:
        return await service.handle_ai_event(
            event_type='AI_DETECTION', event_code=code, severity='CRITICAL',
            message=code, confidence=.9, file_path=None, image_url=None,
            gps_lat=None, gps_lon=None, task_id=None, session=session, **extra,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize('code', [
    'E_AI_PERSON', 'E_AI_GUNS', 'E_AI_KNIFE', 'E_POSE_CLIMBING_SUSPECTED',
    'E_FENCE_CONTACT', 'E_THERMAL_HIGH',
])
async def test_records_and_broadcasts_wait_for_thirty_seconds(harness, code):
    service, factory, clock, broadcaster = harness
    assert await emit(service, factory, code) is not None
    clock[0] = 129.999
    assert await emit(service, factory, code) is None
    clock[0] = 130
    assert await emit(service, factory, code) is not None
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(AnomalyEvidence)) == 2
    assert broadcaster.broadcast_alert.await_count == 2


@pytest.mark.asyncio
async def test_changed_track_ids_cannot_bypass_category_interval(harness):
    service, factory, clock, broadcaster = harness
    assert await emit(service, factory, 'E_AI_PERSON', track_id=6) is not None
    clock[0] = 101
    assert await emit(service, factory, 'E_AI_PERSON', track_id=18) is None
    assert broadcaster.broadcast_alert.await_count == 1


@pytest.mark.asyncio
async def test_different_event_categories_have_independent_intervals(harness):
    service, factory, clock, broadcaster = harness
    assert await emit(service, factory, 'E_AI_PERSON') is not None
    assert await emit(service, factory, 'E_AI_GUNS') is not None
    assert broadcaster.broadcast_alert.await_count == 2


@pytest.mark.asyncio
async def test_concurrent_same_category_creates_one_record(harness):
    service, factory, clock, broadcaster = harness
    results = await asyncio.gather(*[
        emit(service, factory, 'E_AI_GUNS') for _ in range(5)
    ])
    assert sum(result is not None for result in results) == 1
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(AnomalyEvidence)) == 1
    assert broadcaster.broadcast_alert.await_count == 1


@pytest.mark.asyncio
async def test_reloaded_service_respects_last_saved_record(harness):
    service, factory, clock, broadcaster = harness
    assert await emit(service, factory, 'E_AI_PERSON') is not None
    reloaded = AlertService(broadcaster)
    clock[0] = 115
    assert await emit(reloaded, factory, 'E_AI_PERSON') is None
    clock[0] = 130
    assert await emit(reloaded, factory, 'E_AI_PERSON') is not None


@pytest.mark.asyncio
async def test_failed_emission_does_not_consume_the_interval(harness):
    service, factory, clock, broadcaster = harness
    original = service._handle_ai_event_unlimited
    service._handle_ai_event_unlimited = AsyncMock(side_effect=RuntimeError('capture failed'))
    with pytest.raises(RuntimeError):
        await emit(service, factory, 'E_AI_PERSON')
    service._handle_ai_event_unlimited = original
    assert await emit(service, factory, 'E_AI_PERSON') is not None


@pytest.mark.asyncio
async def test_explicit_manual_snapshots_are_not_automatic_repeats(harness):
    service, factory, clock, broadcaster = harness
    assert await emit(service, factory, 'E_MANUAL_SNAPSHOT') is not None
    assert await emit(service, factory, 'E_MANUAL_SNAPSHOT') is not None
    assert broadcaster.broadcast_alert.await_count == 2


@pytest.mark.asyncio
async def test_temperature_callback_uses_the_same_interval_and_database_seed(harness):
    service, factory, clock, broadcaster = harness
    alert = TemperatureAlert(source='T_MAX', temperature=90, threshold=60, timestamp=100)
    assert await service.handle_temperature_alert(alert) is not None
    reloaded = AlertService(broadcaster)
    clock[0] = 115
    assert await reloaded.handle_temperature_alert(alert) is None
    clock[0] = 130
    assert await reloaded.handle_temperature_alert(alert) is not None
    assert broadcaster.broadcast_alert.await_count == 2
