"""
异常证据链（抓拍记录）服务。

职责边界：
- 对 `anomaly_evidence` 表提供查询能力；
- 后续可以在此集中实现分页、过滤、权限校验等逻辑。
"""

from pathlib import Path
from typing import List, Optional, Iterable

from sqlalchemy import Select, select, func, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AnomalyEvidence
from .evidence_labels import EVIDENCE_LABELS, evidence_label


async def list_evidence(
    session: AsyncSession,
    *,
    task_id: Optional[int] = None,
    limit: int = 100,
    offset: int = 0,
    label: Optional[str] = None,
    query: Optional[str] = None,
    severity: Optional[str] = None,
) -> List[AnomalyEvidence]:
    """
    根据可选 task_id 查询最近的异常证据记录。
    """

    stmt: Select[tuple[AnomalyEvidence]] = select(AnomalyEvidence)
    if task_id is not None:
        stmt = stmt.where(AnomalyEvidence.task_id == task_id)
    if label:
        if label.startswith('type:'):
            stmt = stmt.where(and_(
                or_(AnomalyEvidence.event_code.is_(None), AnomalyEvidence.event_code == ''),
                AnomalyEvidence.event_type == label[5:],
            ))
        else:
            stmt = stmt.where(AnomalyEvidence.event_code == label)
    if severity:
        stmt = stmt.where(AnomalyEvidence.severity == severity)
    if query and query.strip():
        term = query.strip()
        label_codes = [code for code, name in EVIDENCE_LABELS.items() if term.casefold() in name.casefold()]
        stmt = stmt.where(or_(
            AnomalyEvidence.message.contains(term, autoescape=True),
            AnomalyEvidence.event_code.contains(term, autoescape=True),
            AnomalyEvidence.event_type.contains(term, autoescape=True),
            AnomalyEvidence.severity.contains(term, autoescape=True),
            AnomalyEvidence.event_code.in_(label_codes),
        ))

    stmt = stmt.order_by(AnomalyEvidence.created_at.desc(), AnomalyEvidence.evidence_id.desc()).limit(limit).offset(offset)

    result = await session.execute(stmt)
    rows = result.scalars().all()
    return list(rows)


async def list_evidence_labels(session: AsyncSession, *, task_id: Optional[int] = None) -> list[dict]:
    """标签及数量从全部记录计算，独立于当前分页和所选标签。"""
    stmt = select(AnomalyEvidence.event_code, AnomalyEvidence.event_type, func.count()).group_by(
        AnomalyEvidence.event_code, AnomalyEvidence.event_type)
    if task_id is not None:
        stmt = stmt.where(AnomalyEvidence.task_id == task_id)
    options = {code: {'value': code, 'label': name, 'count': 0} for code, name in EVIDENCE_LABELS.items()}
    for code, kind, count in (await session.execute(stmt)).all():
        value = code or 'type:' + kind
        option = options.setdefault(value, {'value': value, 'label': evidence_label(code, kind), 'count': 0})
        option['count'] += count
    return sorted(options.values(), key=lambda option: (-option['count'], option['label'], option['value']))


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
        if not row.file_path:
            # 温度告警等无截图文件的证据，跳过文件删除
            continue
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
