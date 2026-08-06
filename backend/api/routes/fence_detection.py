from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ...auth.dependencies import require_operator, require_viewer
from ...auth.schemas import AuthUserInternal
from ...auth.service import safe_write_audit_log
from ...config import settings
from ...database import get_db
from ...fence_detection_service import get_fence_detection_service


router = APIRouter(prefix="/api/v1/fence-detection", tags=["fence-detection"])


@router.get("/status")
async def fence_detection_status(
    user: AuthUserInternal = Depends(require_viewer),
):
    service = get_fence_detection_service()
    if service is None:
        return {
            "enabled": False,
            "state": "disabled",
            "detail": "围栏检测服务未初始化",
            "scene_id": None,
            "target_fence_id": None,
            "target_point": None,
            "distance_m": None,
            "desired_yaw_deg": None,
            "desired_pitch_deg": None,
            "behavior": "normal",
            "behavior_track_id": None,
            "persons": [],
            "missing_calibration": [],
            "gimbal_error": None,
        }
    return service.get_status()


@router.post("/enable")
async def fence_detection_enable(
    user: AuthUserInternal = Depends(require_operator),
    db=Depends(get_db),
):
    service = get_fence_detection_service()
    if service is None:
        raise HTTPException(status_code=503, detail="围栏检测服务未初始化")
    if not settings.AI_ENABLED:
        raise HTTPException(status_code=409, detail="AI 人员检测未启用，不能开启围栏检测")
    if not settings.POSE_ENABLED:
        raise HTTPException(status_code=409, detail="现有姿态检测未启用，不能开启围栏检测")
    status = await service.enable()
    await safe_write_audit_log(
        db,
        level="INFO",
        module="BACKEND",
        message=(
            f"用户={user.username} 角色={user.role} 操作=fence_detection.enable "
            "目标=current_scene 结果=success"
        ),
    )
    return status


@router.post("/disable")
async def fence_detection_disable(
    user: AuthUserInternal = Depends(require_operator),
    db=Depends(get_db),
):
    service = get_fence_detection_service()
    if service is None:
        raise HTTPException(status_code=503, detail="围栏检测服务未初始化")
    status = await service.disable(center_gimbal=True)
    await safe_write_audit_log(
        db,
        level="INFO",
        module="BACKEND",
        message=(
            f"用户={user.username} 角色={user.role} 操作=fence_detection.disable "
            "目标=current_scene 结果=success"
        ),
    )
    return status
