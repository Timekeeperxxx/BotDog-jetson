"""后端运行日志文件路由。"""

from fastapi import APIRouter, Depends, Query

from ...auth.dependencies import require_viewer
from ...auth.schemas import AuthUserInternal
from ...schemas import LogFileInfo, LogFileTailPage, LogFilesPage
from ...services_log_files import list_log_files, tail_log_file

router = APIRouter(prefix="/api/v1/log-files", tags=["logs"])


@router.get("", response_model=LogFilesPage)
async def get_log_files(
    user: AuthUserInternal = Depends(require_viewer),
) -> LogFilesPage:
    items = list_log_files()
    return LogFilesPage(items=[LogFileInfo(**item) for item in items])


@router.get("/{name:path}/tail", response_model=LogFileTailPage)
async def get_log_file_tail(
    name: str,
    user: AuthUserInternal = Depends(require_viewer),
    lines: int = Query(300, ge=1, le=1000),
) -> LogFileTailPage:
    try:
        result = tail_log_file(name, lines=lines)
    except FileNotFoundError:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="日志文件不存在或不允许访问")

    return LogFileTailPage(**result)
