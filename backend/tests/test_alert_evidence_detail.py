"""告警主键指向已提交证据，导航告警也须可追溯。"""
import asyncio
from unittest.mock import AsyncMock
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from backend.alert_service import AlertService
from backend.api.routes.evidence import get_evidence_detail
from backend.database import Base
from backend.services_ros_nav import RosNavBridge


def test_alert_database_detail(monkeypatch):
    async def check():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        broadcaster = AsyncMock()
        async with factory() as session:
            evidence = await AlertService(broadcaster).handle_ai_event(
                event_type='AI_DETECTION', event_code='E_AI_PERSON',
                severity='CRITICAL', message='检测到人员', confidence=0.8,
                file_path=None, image_url=None, gps_lat=None, gps_lon=None,
                task_id=None, session=session,
            )
            record_id = broadcaster.broadcast_alert.call_args.kwargs['evidence_id']
            assert record_id == evidence.evidence_id and record_id > 0
        async with factory() as session:
            detail = await get_evidence_detail(record_id, user=None, db=session)
            assert detail.message == '检测到人员'
            try:
                await get_evidence_detail(record_id + 1, user=None, db=session)
            except HTTPException as exc:
                assert exc.status_code == 404
            else:
                raise AssertionError('missing record must return 404')
        from backend import database
        monkeypatch.setattr(database, 'get_session_factory', lambda: factory)
        bridge = RosNavBridge.__new__(RosNavBridge)
        bridge._loop = asyncio.get_running_loop()
        bridge._broadcaster = broadcaster
        published = asyncio.Event()
        async def mark_published(**kwargs):
            published.set()
        broadcaster.broadcast_alert.side_effect = mark_published
        bridge._submit_alert(event_type='NAVIGATION', event_code='NAV_PATH_BLOCKED',
                             severity='warning', message='导航持续受阻', obstacle_status='blocked')
        await asyncio.wait_for(published.wait(), timeout=3)
        sent = broadcaster.broadcast_alert.call_args.kwargs
        assert sent['severity'] == 'WARNING'
        assert sent['obstacle_status'] == 'blocked'
        async with factory() as session:
            detail = await get_evidence_detail(sent['evidence_id'], user=None, db=session)
            assert detail.event_code == 'NAV_PATH_BLOCKED'
        await engine.dispose()
    asyncio.run(check())
