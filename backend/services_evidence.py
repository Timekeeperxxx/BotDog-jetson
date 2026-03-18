"""
异常证据链（抓拍记录）服务。

职责边界：
- 对 `anomaly_evidence` 表提供查询能力；
- 后续可以在此集中实现分页、过滤、权限校验等逻辑。
"""

from pathlib import Path
from typing import List, Optional, Iterable

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


async def delete_evidence_by_ids(
    session: AsyncSession,
    *,
    evidence_ids: Iterable[int],
) -> dict[str, int | list[int]]:
    ids = sorted({int(eid) for eid in evidence_ids if int(eid) > 0})
    if not ids:
        return {
            "deleted": 0,
            "missing_files": 0,
            "not_found_ids": [],
        }

    stmt = select(AnomalyEvidence).where(AnomalyEvidence.evidence_id.in_(ids))
    result = await session.execute(stmt)
    rows = result.scalars().all()
    found_ids = {row.evidence_id for row in rows}
    not_found_ids = [eid for eid in ids if eid not in found_ids]

    missing_files = 0
    for row in rows:
        file_path = Path(row.file_path)
        try:
            file_path.unlink(missing_ok=True)
        except Exception:
            missing_files += 1

    for row in rows:
        await session.delete(row)

    await session.commit()

    return {
        "deleted": len(rows),
        "missing_files": missing_files,
        "not_found_ids": not_found_ids,
    }

