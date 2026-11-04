"""音频控制路由。"""

from fastapi import APIRouter, Depends, HTTPException
from ...auth.dependencies import require_viewer, require_operator

router = APIRouter(prefix="/api/v1/audio", tags=["audio"], dependencies=[Depends(require_viewer)])


@router.post("/play", dependencies=[Depends(require_operator)])
async def audio_play():
    """手动触发驱离音频循环播放。"""
    from ...guard_mission_service import get_guard_mission_service

    gm = get_guard_mission_service()
    if gm is None:
        raise HTTPException(status_code=503, detail="驱离服务未初始化")
    await gm.start_audio()
    return {"success": True, "playing": True}


@router.post("/stop", dependencies=[Depends(require_operator)])
async def audio_stop():
    """手动停止驱离音频。"""
    from ...guard_mission_service import get_guard_mission_service

    gm = get_guard_mission_service()
    if gm is None:
        raise HTTPException(status_code=503, detail="驱离服务未初始化")
    await gm.stop_audio()
    return {"success": True, "playing": False}


@router.get("/status")
async def audio_status():
    """查询驱离音频是否正在播放。"""
    from ...guard_mission_service import get_guard_mission_service

    gm = get_guard_mission_service()
    playing = gm.is_audio_playing if gm is not None else False
    return {"playing": playing}
