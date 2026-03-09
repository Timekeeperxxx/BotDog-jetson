"""模拟工作器行为单元测试。"""

import asyncio
import re

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import TelemetrySnapshot
from backend.services_tasks import create_task
from backend.workers_simulation import _utc_now_iso


ISO_8601_UTC_MILLIS_Z_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"


@pytest.mark.asyncio
class TestSimulationWorker:
    """模拟工作器基于配置的行为测试。"""

    async def test_simulation_worker_enabled_writes_snapshots(
        self, override_settings, test_app, test_db: AsyncSession
    ) -> None:
        """启用工作器应对运行中任务写入遥测快照。"""
        # 为测试启用 worker
        override_settings(SIMULATION_WORKER_ENABLED=True)

        # 创建运行中的任务
        task = await create_task(test_db, task_name="worker_enabled_test")

        # 运行应用生命周期以启动 worker
        from backend.main import lifespan
        async with lifespan(test_app):
            # 等待 worker 至少运行一个周期
            await asyncio.sleep(1.2)

        # 检查是否写入快照
        stmt = select(TelemetrySnapshot).where(TelemetrySnapshot.task_id == task.task_id)
        result = await test_db.execute(stmt)
        snapshots = result.scalars().all()

        assert len(snapshots) > 0

    async def test_simulation_worker_disabled_no_writes(
        self, override_settings, test_app, test_db: AsyncSession
    ) -> None:
        """禁用工作器不应写入任何遥测快照。"""
        # 显式禁用 worker
        override_settings(SIMULATION_WORKER_ENABLED=False)

        # 创建运行中的任务
        task = await create_task(test_db, task_name="worker_disabled_test")

        # 运行应用生命周期
        from backend.main import lifespan
        async with lifespan(test_app):
            # 等待足够长时间，如果启用 worker 应该已经写入
            await asyncio.sleep(1.2)

        # 检查没有写入快照
        stmt = select(TelemetrySnapshot).where(TelemetrySnapshot.task_id == task.task_id)
        result = await test_db.execute(stmt)
        snapshots = result.scalars().all()

        assert len(snapshots) == 0


class TestTimestampFormat:
    """遥测快照时间戳格式测试。"""

    def test_utc_now_iso_format(self) -> None:
        """_utc_now_iso() 应返回带毫秒和 Z 后缀的 ISO8601 UTC 时间戳。"""
        timestamp = _utc_now_iso()

        assert isinstance(timestamp, str)
        assert re.match(ISO_8601_UTC_MILLIS_Z_PATTERN, timestamp) is not None

    async def test_telemetry_snapshot_timestamp_iso_format(
        self, override_settings, test_app, test_db: AsyncSession
    ) -> None:
        """数据库中的遥测快照时间戳应符合 ISO8601 UTC 格式。"""
        override_settings(SIMULATION_WORKER_ENABLED=True)

        # 创建运行中的任务
        task = await create_task(test_db, task_name="timestamp_test")

        # 让 worker 写入至少一个快照
        from backend.main import lifespan
        async with lifespan(test_app):
            await asyncio.sleep(1.2)

        # 查询快照
        stmt = select(TelemetrySnapshot).where(TelemetrySnapshot.task_id == task.task_id)
        result = await test_db.execute(stmt)
        snapshots = result.scalars().all()

        assert len(snapshots) > 0

        # 验证所有时间戳格式
        for snapshot in snapshots:
            assert snapshot.timestamp is not None
            assert re.match(ISO_8601_UTC_MILLIS_Z_PATTERN, snapshot.timestamp) is not None
