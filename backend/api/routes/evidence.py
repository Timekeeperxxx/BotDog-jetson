"""证据链路由。"""

from datetime import datetime, timezone
from pydantic import BaseModel, Field, AwareDatetime
from sqlalchemy import update

from fastapi import APIRouter, Depends, HTTPException

from ...auth.dependencies import require_admin, require_viewer
from ...auth.schemas import AuthUserInternal
from ...auth.service import safe_write_audit_log
from ...database import get_db
from ...models import AnomalyEvidence
from ...schemas import EvidenceItem, EvidenceBulkDeleteRequest, EvidenceDeleteResponse, EvidenceListResponse
from ...services_evidence import delete_evidence_by_ids, list_evidence

router = APIRouter(prefix="/api/v1/evidence", tags=["evidence"])


@router.get("", response_model=EvidenceListResponse)
async def get_evidence(
    task_id: int | None = None,
    user: AuthUserInternal = Depends(require_viewer),
    db=Depends(get_db),
) -> EvidenceListResponse:
    """
    查询异常证据链列表。

    - 若提供 `task_id`，则仅返回对应任务的证据记录；
    - 默认按照 `created_at` 倒序，最多返回 100 条。
    """
    rows = await list_evidence(db, task_id=task_id, limit=100)
    return EvidenceListResponse(
        items=[
            {
                "evidence_id": row.evidence_id,
                "task_id": row.task_id,
                "event_type": row.event_type,
                "event_code": row.event_code,
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
        ]
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
    return EvidenceItem.model_validate(row, from_attributes=True)


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


@router.post("/{evidence_id}/displayed")
async def record_display(evidence_id: int, receipt: DisplayReceipt,
                         user: AuthUserInternal = Depends(require_viewer), db=Depends(get_db)):
    row = await db.get(AnomalyEvidence, evidence_id)
    if row is None:
        raise HTTPException(404, "告警记录不存在或已删除")
    timing = dict(row.timing or {})
    if timing.get('displayed_at'):
        return timing
    now = datetime.now(timezone.utc)
    displayed = receipt.displayed_at.astimezone(timezone.utc)
    if (displayed - now).total_seconds() * 1000 > receipt.clock_uncertainty_ms + 100:
        raise HTTPException(422, "显示时间超出校时误差范围")
    generated = timing.get('generated_at')
    if generated and (datetime.fromisoformat(generated.replace('Z', '+00:00')) - displayed).total_seconds() * 1000 > receipt.clock_uncertainty_ms:
        raise HTTPException(422, "显示时间早于告警生成时间")
    timing.update(displayed_at=displayed.isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
                  clock_uncertainty_ms=receipt.clock_uncertainty_ms,
                  display_measurement='visible_page_after_animation_frames',
                  display_ack_at=now.isoformat(timespec='milliseconds').replace('+00:00', 'Z'))
    if timing.get('eligible_at'):
        delay = (displayed - datetime.fromisoformat(timing['eligible_at'].replace('Z', '+00:00'))).total_seconds() * 1000
        timing['display_delay_ms'] = round(delay, 1) if delay >= 0 else None
    # 多个页面同时回执时，仅保留第一份已接收的呈现记录。
    result = await db.execute(update(AnomalyEvidence).where(
        AnomalyEvidence.evidence_id == evidence_id,
        AnomalyEvidence.timing['displayed_at'].as_string().is_(None),
    ).values(timing=timing))
    await db.commit()
    await db.refresh(row)
    if result.rowcount:
        from ...alert_timing import log_alert_timing
        log_alert_timing(row.evidence_id, row.event_code, row.message, row.timing, 'displayed')
    return row.timing
