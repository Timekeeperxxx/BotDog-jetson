"""
异常证据链（抓拍记录）服务。

职责边界：
- 对 `anomaly_evidence` 表提供查询能力；
- 后续可以在此集中实现分页、过滤、权限校验等逻辑。
"""

from typing import List, Optional

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AnomalyEvidence


async def list_evidence(
    session: AsyncSession,
    *,
    task_id: Optional[int] = None,
    limit: int = 100,
) -> List[AnomalyEvidence]:
    """
    根据可选 task_id 查询最近的异常证据记录。
    """

    stmt: Select[tuple[AnomalyEvidence]] = select(AnomalyEvidence)
    if task_id is not None:
        stmt = stmt.where(AnomalyEvidence.task_id == task_id)

    stmt = stmt.order_by(AnomalyEvidence.created_at.desc()).limit(limit)

    result = await session.execute(stmt)
    rows = result.scalars().all()
    return list(rows)

