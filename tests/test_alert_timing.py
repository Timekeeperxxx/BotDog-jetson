import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from backend.alert_service import AlertService
from backend.alert_timing import observation_timing
from backend.api.routes.evidence import record_display, DisplayReceipt, get_evidence_detail
from backend.database import Base


def test_duration_threshold_and_missing_start(monkeypatch):
    monkeypatch.setattr('backend.alert_timing.time.time', lambda: 1000)
    monkeypatch.setattr('backend.alert_timing.time.monotonic', lambda: 100)
    timing = observation_timing(99, duration=5.1, threshold=5)
    start = datetime.fromisoformat(timing['event_started_at'].replace('Z', '+00:00'))
    eligible = datetime.fromisoformat(timing['eligible_at'].replace('Z', '+00:00'))
    assert (eligible-start).total_seconds() == 5
    assert timing['duration_seconds'] == 5.1
    assert 'eligible_at' not in observation_timing(None)


def test_timing_persisted_logged_and_display_receipt_is_idempotent(monkeypatch):
    from backend.logging_config import logger
    messages = []
    sink = logger.add(lambda msg: messages.append(str(msg)), filter=lambda r: r['extra'].get('alert_log', False))
    async def check():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        async with engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        now = datetime.now(timezone.utc)
        start = (now - timedelta(seconds=5.5)).isoformat()
        eligible = (now - timedelta(seconds=.5)).isoformat()
        async with factory() as db:
            alert = await AlertService(AsyncMock()).handle_ai_event(
                event_type='POSE_LOITERING', event_code='E_POSE_LOITERING', severity='WARNING',
                message='人员徘徊', confidence=.9, file_path=None, image_url=None,
                gps_lat=None, gps_lon=None, task_id=None, session=db,
                timing={'event_started_at': start, 'eligible_at': eligible, 'duration_seconds': 5.5})
            assert alert.timing['generation_delay_ms'] >= 500
            detail = await get_evidence_detail(alert.evidence_id, user=None, db=db)
            assert detail.timing['eligible_at'] == eligible
            receipt = DisplayReceipt(displayed_at=datetime.now(timezone.utc), clock_uncertainty_ms=5)
            saved = await record_display(alert.evidence_id, receipt, user=None, db=db)
            assert 500 <= saved['display_delay_ms'] < 2000
            assert saved['clock_uncertainty_ms'] == 5
            assert 0 <= saved['generation_to_display_ms'] < 1500
            same = await record_display(alert.evidence_id, receipt, user=None, db=db)
            assert same == saved
            with pytest.raises(HTTPException):
                await record_display(9999, receipt, user=None, db=db)
        await engine.dispose()
    try:
        asyncio.run(check())
        assert sum('"stage": "generated"' in m for m in messages) == 1
        assert sum('"stage": "displayed"' in m for m in messages) == 1
        assert any('awaiting_visible_page_receipt' in m for m in messages)
    finally:
        logger.remove(sink)


def test_existing_database_adds_timing_without_losing_records(monkeypatch):
    from sqlalchemy import text, inspect
    from backend import database
    async def check():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        async with engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)
            await c.execute(text('ALTER TABLE anomaly_evidence DROP COLUMN timing'))
            await c.execute(text("INSERT INTO anomaly_evidence (event_type,severity,created_at) VALUES ('AI_DETECTION','WARNING','2026-09-17T00:00:00Z')"))
        monkeypatch.setattr(database, 'get_engine', lambda: engine)
        await database.init_db()
        await database.init_db()
        async with engine.connect() as c:
            columns = await c.run_sync(lambda con: {col['name'] for col in inspect(con).get_columns('anomaly_evidence')})
            assert 'timing' in columns
            assert (await c.execute(text('SELECT count(*) FROM anomaly_evidence'))).scalar() == 1
            assert (await c.execute(text('SELECT timing FROM anomaly_evidence'))).scalar() is None
        await engine.dispose()
    asyncio.run(check())


def test_all_alerts_get_delivery_timing_except_blocked_and_cleared():
    from backend.models import AnomalyEvidence
    async def check():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            for code in ('E_AI_KNIFE', 'E_AI_GUNS', 'E_POSE_LYING', 'E_FENCE_CONTACT',
                         'E_AUTO_TRACK_LOCKED', 'E_THERMAL_HIGH', 'NEW_ALERT',
                         'NAV_PATH_BLOCKED', 'NAV_BLOCK_CLEARED'):
                broadcaster = AsyncMock()
                alert = await AlertService(broadcaster).handle_ai_event(
                    event_type='TEST', event_code=code, severity='WARNING', message='test',
                    confidence=None, file_path=None, image_url=None, gps_lat=None,
                    gps_lon=None, task_id=None, session=db)
                saved = await record_display(alert.evidence_id, DisplayReceipt(
                    displayed_at=datetime.now(timezone.utc), clock_uncertainty_ms=5), user=None, db=db)
                row = await db.get(AnomalyEvidence, alert.evidence_id)
                payload = broadcaster.broadcast_alert.call_args.kwargs
                if code in ('NAV_PATH_BLOCKED', 'NAV_BLOCK_CLEARED'):
                    assert saved == row.timing == {}
                    assert payload['timing'] is None
                    assert row.created_at
                else:
                    assert saved['generation_to_display_ms'] >= 0
                    assert 'display_delay_ms' not in saved  # No invented event start.
                    assert payload['timing']['generated_at']
        await engine.dispose()
    asyncio.run(check())
