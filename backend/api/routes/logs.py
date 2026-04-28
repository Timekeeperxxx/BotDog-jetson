"""系统日志路由。"""

from fastapi import APIRouter, Depends

from ...database import get_db
from ...schemas import LogsPage
from ...services_logs import list_logs

router = APIRouter(prefix="/api/v1/logs", tags=["logs"])


@router.get("", response_model=LogsPage)
async def get_logs(db=Depends(get_db)) -> LogsPage:
    """简单日志查询：返回最近 N 条日志（默认 50 条）。"""
    rows = await list_logs(db, limit=50)
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
