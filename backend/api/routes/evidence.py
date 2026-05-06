"""证据链路由。"""

from fastapi import APIRouter, Depends

from ...auth.dependencies import require_admin, require_viewer
from ...auth.schemas import AuthUserInternal
from ...auth.service import safe_write_audit_log
from ...database import get_db
from ...schemas import EvidenceBulkDeleteRequest, EvidenceDeleteResponse, EvidenceListResponse
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
            }
            for row in rows
        ]
    )


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
