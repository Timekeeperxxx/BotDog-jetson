import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from backend.database import Base
from backend.models import AnomalyEvidence
from backend.services_evidence import list_evidence, list_evidence_labels
from backend.api.routes.evidence import get_evidence, get_evidence_detail


@pytest.mark.asyncio
async def test_label_filter_runs_before_pagination_and_returns_all_label_counts():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        # 翻越抓拍比100条其他告警更早，不能只过滤最新一页。
        for i in range(3):
            db.add(AnomalyEvidence(event_type='POSE_VAULTING_SUSPECTED', event_code='E_POSE_VAULTING_SUSPECTED',
                severity='WARNING', message=f'演示 {i}', created_at=f'2026-10-01T00:00:0{i}Z'))
        for i in range(100):
            db.add(AnomalyEvidence(event_type='POSE_CLIMBING_SUSPECTED', event_code='E_POSE_CLIMBING_SUSPECTED',
                severity='CRITICAL', message=f'攀爬 {i}', created_at=f'2026-10-06T00:00:{i:03d}Z'))
        db.add(AnomalyEvidence(event_type='LEGACY', event_code=None, severity='INFO', message='幅度 50%', created_at='2026-09-01'))
        await db.commit()
        first = await get_evidence(task_id=None, offset=0, limit=2, label='E_POSE_VAULTING_SUSPECTED', q=None, severity=None, user=None, db=db)
        assert first.has_more and len(first.items) == 2
        assert all(row.alert_label == '翻越' for row in first.items)
        counts = {item.value: item.count for item in first.labels}
        assert counts['E_POSE_VAULTING_SUSPECTED'] == 3
        assert counts['E_POSE_CLIMBING_SUSPECTED'] == 100
        assert counts['type:LEGACY'] == 1
        later = await get_evidence(task_id=None, offset=2, limit=2, label='E_POSE_VAULTING_SUSPECTED', q=None, severity=None, user=None, db=db)
        assert len(later.items) == 1 and not later.has_more
        assert first.items[0].evidence_id != later.items[0].evidence_id
        detail = await get_evidence_detail(first.items[0].evidence_id, user=None, db=db)
        assert detail.alert_label == '翻越'
        assert len(await list_evidence(db, label='type:LEGACY')) == 1
        assert len(await list_evidence(db, query='%')) == 1  # 关键词中的通配符按字面查找。
        assert len(await list_evidence(db, query='翻越')) == 3
        assert len(await list_evidence(db, label='E_POSE_VAULTING_SUSPECTED', query='演示 1', severity='WARNING')) == 1
        assert await list_evidence(db, label='E_POSE_VAULTING_SUSPECTED', severity='INFO') == []
        assert sum(option['count'] for option in await list_evidence_labels(db)) == 104
    await engine.dispose()
