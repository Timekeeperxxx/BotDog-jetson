"""
任务（Session）领域服务。

职责边界：
- 封装对 `InspectionTask` 的增删改查逻辑；
- 隐藏具体 ORM 细节，对上层提供语义清晰的异步函数。
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import InspectionTask


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="milliseconds") + "Z"


async def create_task(session: AsyncSession, task_name: str) -> InspectionTask:
    """
    创建一个新的巡检任务，状态默认为 running。
    """

    now = _utc_now_iso()
    task = InspectionTask(
        task_name=task_name,
        status="running",
        started_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


async def stop_task(session: AsyncSession, task_id: int) -> Optional[InspectionTask]:
    """
    将任务标记为 completed，并写入结束时间。
    若任务不存在则返回 None。
    """

    stmt = select(InspectionTask).where(InspectionTask.task_id == task_id)
    result = await session.execute(stmt)
    task = result.scalar_one_or_none()
    if task is None:
        return None

    now = _utc_now_iso()
    task.status = "completed"
    task.ended_at = now
    task.updated_at = now
    await session.commit()
    await session.refresh(task)
    return task

