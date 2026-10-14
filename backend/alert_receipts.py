"""Merge alert timing without losing concurrent send or browser receipts."""

import asyncio
import json
from collections.abc import Callable
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import Text, cast, select, update

from .models import AnomalyEvidence


def merge_broadcast_timing(current: dict, send_timing: dict) -> dict:
    current.update(send_timing)
    for client in current.get('client_receipts', {}).values():
        if client.get('received_at'):
            delay = (datetime.fromisoformat(client['received_at'].replace('Z', '+00:00')) -
                     datetime.fromisoformat(current['broadcast_started_at'].replace('Z', '+00:00'))).total_seconds() * 1000
            client['broadcast_to_receive_ms'] = round(delay, 1) if delay >= 0 else None
    summary = current.get('client_receipts', {}).get(current.get('display_client_id'))
    if summary is not None:
        current['broadcast_to_receive_ms'] = summary.get('broadcast_to_receive_ms')
    return current


async def merge_alert_timing(db, evidence_id: int, merge: Callable[[dict], dict]) -> tuple[dict, bool]:
    # Compare the stored JSON text, rather than a re-serialized dict. Older records
    # may have different whitespace, and multiple clients may update concurrently.
    column = cast(AnomalyEvidence.timing, Text)
    for _ in range(8):
        result = await db.execute(select(column).where(AnomalyEvidence.evidence_id == evidence_id))
        row = result.first()
        if row is None:
            raise HTTPException(404, "告警记录不存在或已删除")
        raw = row[0]
        current = json.loads(raw) if raw else {}
        current = current or {}
        updated = merge(json.loads(json.dumps(current)))
        if updated == current:
            return current, False
        unchanged = column.is_(None) if raw is None else column == raw
        saved = await db.execute(update(AnomalyEvidence).where(
            AnomalyEvidence.evidence_id == evidence_id, unchanged,
        ).values(timing=updated), execution_options={"synchronize_session": False})
        if saved.rowcount:
            await db.commit()
            return updated, True
        await db.rollback()
        await asyncio.sleep(0)
    raise HTTPException(409, "告警计时正在更新，请重试")
