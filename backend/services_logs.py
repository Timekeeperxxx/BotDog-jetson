"""
日志领域服务。

职责边界：
- 向 `operation_logs` 表写入结构化日志；
- 提供按时间倒序分页查询和筛选的接口。
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Select, and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import OperationLog


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="milliseconds") + "Z"


async def write_log(
    session: AsyncSession,
    *,
    level: str,
    module: str,
    message: str,
    task_id: Optional[int] = None,
) -> OperationLog:
    """
    写入一条操作/系统日志。
    """

    log = OperationLog(
        level=level,
        module=module,
        message=message,
        task_id=task_id,
        created_at=_utc_now_iso(),
    )
    session.add(log)
    await session.commit()
    await session.refresh(log)
    return log


async def list_logs(
    session: AsyncSession,
    *,
    limit: int = 100,
    level: str | None = None,
    module: str | None = None,
    keyword: str | None = None,
) -> list[OperationLog]:
    """
    按时间倒序返回最近 N 条日志。
    """

    stmt: Select[tuple[OperationLog]] = select(OperationLog)
    conditions = []
    if level:
        conditions.append(OperationLog.level == level)
    if module:
        conditions.append(OperationLog.module == module)
    if keyword:
        conditions.append(OperationLog.message.ilike(f"%{keyword}%"))
    if conditions:
        stmt = stmt.where(and_(*conditions))
    stmt = stmt.order_by(OperationLog.created_at.desc(), OperationLog.log_id.desc()).limit(limit)
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return list(rows)
