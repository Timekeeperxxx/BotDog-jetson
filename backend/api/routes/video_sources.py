"""视频源管理路由。"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...database import get_db

router = APIRouter(prefix="/api/v1/video-sources", tags=["video_sources"])


class VideoSourceRequest(BaseModel):
    """视频源请求体。"""

    name: str
    label: str
    source_type: str = "whep"
    whep_url: Optional[str] = None
    rtsp_url: Optional[str] = None
    enabled: bool = True
    is_primary: bool = False
    is_ai_source: bool = False
    sort_order: int = 0


class VideoSourceResponse(BaseModel):
    """视频源响应体。"""

    source_id: int
    name: str
    label: str
    source_type: str
    whep_url: Optional[str] = None
    rtsp_url: Optional[str] = None
    enabled: bool
    is_primary: bool
    is_ai_source: bool
    sort_order: int
    created_at: str
    updated_at: str


@router.get("")
async def list_video_sources(db=Depends(get_db)) -> dict:
    """获取所有视频源列表。"""
    from ...services_video_sources import get_video_source_service

    svc = get_video_source_service()
    sources = await svc.list_all(db)
    return {"sources": sources, "total": len(sources)}


@router.get("/active")
async def list_active_video_sources(db=Depends(get_db)) -> dict:
    """获取所有已启用的视频源（供前端视频播放器消费）。"""
    from ...services_video_sources import get_video_source_service

    svc = get_video_source_service()
    sources = await svc.list_active(db)
    return {"sources": sources, "total": len(sources)}


@router.post("", status_code=201)
async def create_video_source(
    body: VideoSourceRequest,
    db=Depends(get_db),
) -> dict:
    """新增视频源。"""
    from ...services_video_sources import get_video_source_service

    svc = get_video_source_service()
    try:
        source = await svc.create(db, body.model_dump())
        return {"success": True, "source": source}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{source_id}")
async def update_video_source(
    source_id: int,
    body: VideoSourceRequest,
    db=Depends(get_db),
) -> dict:
    """更新视频源。"""
    from ...services_video_sources import get_video_source_service

    svc = get_video_source_service()
    result = await svc.update(db, source_id, body.model_dump())
    if result is None:
        raise HTTPException(status_code=404, detail=f"视频源 id={source_id} 不存在")
    return {"success": True, "source": result}


@router.delete("/{source_id}")
async def delete_video_source(
    source_id: int,
    db=Depends(get_db),
) -> dict:
    """删除视频源。"""
    from ...services_video_sources import get_video_source_service

    svc = get_video_source_service()
    deleted = await svc.delete(db, source_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"视频源 id={source_id} 不存在")
    return {"success": True, "deleted_source_id": source_id}
