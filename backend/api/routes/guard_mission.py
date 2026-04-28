"""自动驱离路由。"""

from fastapi import APIRouter, HTTPException

from ...logging_config import logger
from ...guard_mission_types import GuardStatusDTO

router = APIRouter(prefix="/api/v1/guard-mission", tags=["guard_mission"])


@router.post("/enable")
async def enable_guard_mission():
    from ...guard_mission_service import get_guard_mission_service
    from ...auto_track_service import get_auto_track_service
    from ...control_arbiter import get_control_arbiter

    gm = get_guard_mission_service()
    if gm is None:
        raise HTTPException(status_code=503, detail="驱离服务未初始化")

    arbiter = get_control_arbiter()
    if arbiter:
        arbiter.release_manual_override()

    at = get_auto_track_service()
    if at is not None and at._enabled:
        at.disable()
        logger.info("[GuardMission] 互斥切换：已自动关闭自动跟踪")
    gm.enabled = True
    return {"success": True, "enabled": True}


@router.post("/disable")
async def disable_guard_mission():
    from ...guard_mission_service import get_guard_mission_service

    gm = get_guard_mission_service()
    if gm is None:
        raise HTTPException(status_code=503, detail="驱离服务未初始化")
    gm.enabled = False
    return {"success": True, "enabled": False}


@router.post("/abort")
async def abort_guard_mission():
    from ...guard_mission_service import get_guard_mission_service
    from ...guard_mission_types import GuardMissionState

    gm = get_guard_mission_service()
    if gm is None:
        raise HTTPException(status_code=503, detail="驱离服务未初始化")

    if gm.state.value not in ("STANDBY", "MANUAL_OVERRIDE"):
        gm._abort_mission("API 手动终止")
        gm._state = GuardMissionState.STANDBY
    return {"success": True}


@router.get("/status", response_model=GuardStatusDTO)
async def get_guard_status():
    from ...guard_mission_service import get_guard_mission_service

    gm = get_guard_mission_service()
    if gm is None:
        raise HTTPException(status_code=503, detail="驱离服务未初始化")
    return gm.get_status()
