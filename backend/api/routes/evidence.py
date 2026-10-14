"""证据链路由。"""

from datetime import datetime, timezone
from pydantic import BaseModel, Field, AwareDatetime

from fastapi import APIRouter, Depends, HTTPException, Query

from ...auth.dependencies import require_admin, require_viewer
from ...auth.schemas import AuthUserInternal
from ...auth.service import safe_write_audit_log
from ...database import get_db
from ...models import AnomalyEvidence
from ...schemas import EvidenceItem, EvidenceBulkDeleteRequest, EvidenceDeleteResponse, EvidenceListResponse
from ...services_evidence import delete_evidence_by_ids, list_evidence, list_evidence_labels
from ...evidence_labels import evidence_label

router = APIRouter(prefix="/api/v1/evidence", tags=["evidence"])


@router.get("", response_model=EvidenceListResponse)
async def get_evidence(
    task_id: int | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    label: str | None = Query(None, max_length=128),
    q: str | None = Query(None, max_length=200),
    severity: str | None = Query(None, pattern='^(INFO|WARN|WARNING|ERROR|CRITICAL)$'),
    user: AuthUserInternal = Depends(require_viewer),
    db=Depends(get_db),
) -> EvidenceListResponse:
    """
    查询异常证据链列表。

    - 若提供 `task_id`，则仅返回对应任务的证据记录；
    - 默认按照 `created_at` 倒序，分页返回。
    """
    rows = await list_evidence(db, task_id=task_id, limit=limit + 1, offset=offset,
                               label=label, query=q, severity=severity)
    labels = await list_evidence_labels(db, task_id=task_id)
    has_more = len(rows) > limit
    rows = rows[:limit]
    return EvidenceListResponse(
        items=[
            {
                "evidence_id": row.evidence_id,
                "task_id": row.task_id,
                "event_type": row.event_type,
                "event_code": row.event_code,
                "alert_label": evidence_label(row.event_code, row.event_type),
                "severity": row.severity,
                "message": row.message,
                "confidence": row.confidence,
                "file_path": row.file_path,
                "image_url": row.image_url,
                "gps_lat": row.gps_lat,
                "gps_lon": row.gps_lon,
                "created_at": row.created_at,
                "timing": row.timing,
            }
            for row in rows
        ],
        offset=offset,
        limit=limit,
        has_more=has_more,
        labels=labels,
    )


@router.get("/clock")
async def evidence_clock(user: AuthUserInternal = Depends(require_viewer)):
    from ...schemas import utc_now_iso
    from fastapi.responses import JSONResponse
    return JSONResponse({"server_time": utc_now_iso()}, headers={"Cache-Control": "no-store"})


@router.get("/{evidence_id}", response_model=EvidenceItem)
async def get_evidence_detail(
    evidence_id: int,
    user: AuthUserInternal = Depends(require_viewer),
    db=Depends(get_db),
) -> EvidenceItem:
    row = await db.get(AnomalyEvidence, evidence_id)
    if row is None:
        raise HTTPException(status_code=404, detail="告警记录不存在或已删除")
    return EvidenceItem.model_validate(row, from_attributes=True).model_copy(update={
        'alert_label': evidence_label(row.event_code, row.event_type),
    })


@router.delete("/{evidence_id}", response_model=EvidenceDeleteResponse)
async def delete_evidence(
    evidence_id: int,
    user: AuthUserInternal = Depends(require_admin),
    db=Depends(get_db),
) -> EvidenceDeleteResponse:
    result = await delete_evidence_by_ids(db, evidence_ids=[evidence_id])
    await safe_write_audit_log(
        db,
        level="WARN",
        module="BACKEND",
        message=(
            f"用户={user.username} 角色={user.role} 操作=evidence.delete "
            f"目标={evidence_id} 结果=success"
        ),
    )
    return EvidenceDeleteResponse(success=True, **result)


@router.post("/bulk-delete", response_model=EvidenceDeleteResponse)
async def bulk_delete_evidence(
    request: EvidenceBulkDeleteRequest,
    user: AuthUserInternal = Depends(require_admin),
    db=Depends(get_db),
) -> EvidenceDeleteResponse:
    result = await delete_evidence_by_ids(db, evidence_ids=request.evidence_ids)
    await safe_write_audit_log(
        db,
        level="WARN",
        module="BACKEND",
        message=(
            f"用户={user.username} 角色={user.role} 操作=evidence.bulk_delete "
            f"目标={request.evidence_ids} 结果=success"
        ),
    )
    return EvidenceDeleteResponse(success=True, **result)




class DisplayReceipt(BaseModel):
    displayed_at: AwareDatetime
    clock_uncertainty_ms: float = Field(ge=0, le=10000, allow_inf_nan=False)
    client_id: str | None = Field(default=None, min_length=1, max_length=64, pattern=r'^[A-Za-z0-9_-]+$')
    received_at: AwareDatetime | None = None
    mounted_at: AwareDatetime | None = None
    first_visible_at: AwareDatetime | None = None
    page_visible_on_receive: bool | None = None
    page_visible_on_mount: bool | None = None
    card_visible_on_mount: bool | None = None
    receive_to_mount_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    visibility_wait_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    visible_render_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    receive_to_display_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class ReceiveReceipt(BaseModel):
    client_id: str = Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9_-]+$')
    received_at: AwareDatetime
    page_visible_on_receive: bool
    clock_uncertainty_ms: float = Field(ge=0, le=10000, allow_inf_nan=False)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def _delay(end: str, start: str | None) -> float | None:
    if not start:
        return None
    delay = (datetime.fromisoformat(end.replace('Z', '+00:00')) -
             datetime.fromisoformat(start.replace('Z', '+00:00'))).total_seconds() * 1000
    return round(delay, 1) if delay >= 0 else None


def _validate_time(value: datetime, timing: dict, uncertainty: float) -> None:
    if (value - datetime.now(timezone.utc)).total_seconds() * 1000 > uncertainty + 100:
        raise HTTPException(422, "回执时间超出校时误差范围")
    generated = timing.get('generated_at')
    if generated and (datetime.fromisoformat(generated.replace('Z', '+00:00')) - value).total_seconds() * 1000 > uncertainty:
        raise HTTPException(422, "回执时间早于告警生成时间")


def _merge_client(timing: dict, client_id: str, data: dict) -> dict:
    clients = timing.setdefault('client_receipts', {})
    client = clients.setdefault(client_id, {})
    # A display may arrive before its receive POST. It includes the original
    # receive sample, so retry order cannot replace it with the retry time.
    incoming_display = data.get('displayed_at')
    if incoming_display and (not client.get('displayed_at') or incoming_display < client['displayed_at']):
        client.update(data)
    else:
        for key, value in data.items():
            client.setdefault(key, value)
    if client.get('received_at'):
        client['generation_to_receive_ms'] = _delay(client['received_at'], timing.get('generated_at'))
        client['broadcast_to_receive_ms'] = _delay(client['received_at'], timing.get('broadcast_started_at'))
    return client


@router.post("/{evidence_id}/received")
async def record_receive(evidence_id: int, receipt: ReceiveReceipt,
                         user: AuthUserInternal = Depends(require_viewer), db=Depends(get_db)):
    from ...alert_receipts import merge_alert_timing
    from ...alert_timing import log_alert_timing, UNTIMED_EVENT_CODES
    row = await db.get(AnomalyEvidence, evidence_id)
    if row is None:
        raise HTTPException(404, "告警记录不存在或已删除")
    if row.event_code in UNTIMED_EVENT_CODES:
        return {}
    event_code, message = row.event_code, row.message
    data = receipt.model_dump(exclude={'client_id'}, mode='json')
    data['received_at'] = _iso(receipt.received_at)

    def merge(timing):
        _validate_time(receipt.received_at, timing, receipt.clock_uncertainty_ms)
        _merge_client(timing, receipt.client_id, data)
        return timing

    saved, changed = await merge_alert_timing(db, evidence_id, merge)
    if changed:
        log_alert_timing(evidence_id, event_code, message,
                         {**saved['client_receipts'][receipt.client_id], 'client_id': receipt.client_id}, 'received')
    return saved


@router.post("/{evidence_id}/displayed")
async def record_display(evidence_id: int, receipt: DisplayReceipt,
                         user: AuthUserInternal = Depends(require_viewer), db=Depends(get_db)):
    row = await db.get(AnomalyEvidence, evidence_id)
    if row is None:
        raise HTTPException(404, "告警记录不存在或已删除")
    from ...alert_timing import UNTIMED_EVENT_CODES
    if row.event_code in UNTIMED_EVENT_CODES:
        return {}
    event_code, message = row.event_code, row.message
    from ...alert_receipts import merge_alert_timing
    data = receipt.model_dump(exclude_none=True, exclude={'client_id'}, mode='json')
    for key in ('received_at', 'mounted_at', 'first_visible_at', 'displayed_at'):
        if getattr(receipt, key) is not None:
            data[key] = _iso(getattr(receipt, key))
    data['display_measurement'] = 'visible_page_after_animation_frames'
    data['display_ack_at'] = _iso(datetime.now(timezone.utc))

    def merge(timing):
        # Preserve the original behavior for older frontends and historical fields.
        if receipt.client_id is None and timing.get('displayed_at'):
            return timing
        _validate_time(receipt.displayed_at, timing, receipt.clock_uncertainty_ms)
        previous = None
        for key in ('received_at', 'mounted_at', 'first_visible_at', 'displayed_at'):
            value = getattr(receipt, key)
            if value is None:
                continue
            _validate_time(value, timing, receipt.clock_uncertainty_ms)
            if previous and (previous - value).total_seconds() * 1000 > receipt.clock_uncertainty_ms:
                raise HTTPException(422, "接收、挂载、可见与显示时刻顺序无效")
            previous = value
        client = _merge_client(timing, receipt.client_id, data) if receipt.client_id else data
        # Do not rewrite a display sample recorded by an older frontend.
        replace = not timing.get('displayed_at') or (timing.get('display_client_id') and data['displayed_at'] < timing['displayed_at'])
        if replace:
            timing.update(client)
            if receipt.client_id:
                timing['display_client_id'] = receipt.client_id
            timing['generation_to_display_ms'] = _delay(data['displayed_at'], timing.get('generated_at'))
            if timing.get('eligible_at'):
                timing['display_delay_ms'] = _delay(data['displayed_at'], timing['eligible_at'])
        return timing

    saved, changed = await merge_alert_timing(db, evidence_id, merge)
    if changed:
        from ...alert_timing import log_alert_timing
        sample = saved['client_receipts'][receipt.client_id] if receipt.client_id else saved
        log_alert_timing(evidence_id, event_code, message,
                         {**sample, **({'client_id': receipt.client_id} if receipt.client_id else {})}, 'displayed')
    await db.refresh(row)
    return saved
