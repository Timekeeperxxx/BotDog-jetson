"""音频控制路由。"""

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/v1/audio", tags=["audio"])


@router.post("/play")
async def audio_play():
    """手动触发驱离音频循环播放。"""
    from ...guard_mission_service import get_guard_mission_service

    gm = get_guard_mission_service()
    if gm is None:
        raise HTTPException(status_code=503, detail="驱离服务未初始化")
    await gm.start_audio()
    return {"success": True, "playing": True}


@router.post("/stop")
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
