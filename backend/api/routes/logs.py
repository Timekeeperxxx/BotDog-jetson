"""系统审计日志路由。"""

from fastapi import APIRouter, Depends, Query

from ...auth.dependencies import require_viewer
from ...auth.schemas import AuthUserInternal
from ...database import get_db
from ...schemas import LogsPage
from ...services_logs import list_logs

router = APIRouter(prefix="/api/v1/logs", tags=["logs"])


@router.get("", response_model=LogsPage)
async def get_logs(
    user: AuthUserInternal = Depends(require_viewer),
    db=Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
    level: str | None = Query(default=None, min_length=1, max_length=32),
    module: str | None = Query(default=None, min_length=1, max_length=32),
    keyword: str | None = Query(default=None, min_length=1, max_length=200),
) -> LogsPage:
    """返回 operation_logs 审计日志，不包含完整后端运行日志。"""
    normalized_level = level.strip().upper() if level else None
    normalized_module = module.strip().upper() if module else None
    normalized_keyword = keyword.strip() if keyword else None
    rows = await list_logs(
        db,
        limit=limit,
        level=normalized_level,
        module=normalized_module,
        keyword=normalized_keyword,
    )
    return LogsPage(
        items=[
            {
                "log_id": row.log_id,
                "level": row.level,
                "module": row.module,
                "message": row.message,
                "task_id": row.task_id,
                "created_at": row.created_at,
            }
            for row in rows
        ]
    )
