import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.database import Base
from backend.models import InspectionTask
from backend.services_tasks import create_task, stop_task
from backend import workers_ai_processing
from backend.workers_ai_processing import AIWorkerProcessingMixin


@pytest.mark.asyncio
async def test_start_reuses_running_session_and_stop_allows_new_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'sessions.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async def start():
        async with factory() as session:
            return (await create_task(session, '巡检')).task_id
    first, duplicate = await asyncio.gather(start(), start())
    assert first == duplicate
    async with factory() as session:
        # 模拟旧版本遗留的另一条 running 会话。
        session.add(InspectionTask(task_name='旧会话', status='running', started_at='2000', created_at='2000', updated_at='2000'))
        await session.commit()
        assert (await create_task(session, '重复点击')).task_id == first
        running = (await session.scalars(select(InspectionTask).where(InspectionTask.status == 'running'))).all()
        assert [task.task_id for task in running] == [first]
        await stop_task(session, first)
    assert await start() != first
    await engine.dispose()


@pytest.mark.asyncio
async def test_task_switch_clears_dedup_even_without_idle_gap(monkeypatch):
    worker = AIWorkerProcessingMixin()
    session = AsyncMock()
    worker._session_factory = lambda: session
    worker._current_task_id = 11
    worker._last_task_check_time = 0
    worker._person_alert_last_seen = {1: 10}
    worker._person_pose_hits = {1: 3}
    worker._person_alert_frame = 10
    worker._reset_misses = 20
    worker._weapon_first_seen = {}
    worker._weapon_hits = {}
    worker._raise_alert = AsyncMock()
    monkeypatch.setattr(workers_ai_processing, '_get_latest_running_task', AsyncMock(return_value=SimpleNamespace(task_id=12)))
    await worker._update_current_task_id()
    assert worker._current_task_id == 12
    assert worker._person_alert_last_seen == {}
    assert worker._person_pose_hits == {}
    person = SimpleNamespace(label='person', track_id=1, face_status='unknown', identity_id=None)
    await worker._process_person_alerts([person], b'frame')
    worker._last_task_check_time = 0
    await worker._update_current_task_id()
    await worker._process_person_alerts([person], b'frame')
    assert worker._raise_alert.await_count == 1
