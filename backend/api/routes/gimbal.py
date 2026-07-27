"""先飞 Z2-Mini 云台状态与控制接口。"""

from __future__ import annotations

from typing import Awaitable, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ...auth.dependencies import require_operator, require_viewer
from ...auth.schemas import AuthUserInternal
from ...auth.service import safe_write_audit_log
from ...database import get_db
from ...z2mini_gimbal import (
    GcuProtocolError,
    Z2MiniStatus,
    get_z2mini_gimbal,
)

router = APIRouter(prefix="/api/v1/gimbal", tags=["gimbal"])


class GimbalStatusResponse(BaseModel):
    connected: bool
    timestamp: str | None = None
    error: str | None = None
    mode: str = "unknown"
    mode_code: int = 0
    relative_roll_deg: float = 0.0
    relative_pitch_deg: float = 0.0
    relative_yaw_deg: float = 0.0
    absolute_roll_deg: float = 0.0
    absolute_pitch_deg: float = 0.0
    absolute_yaw_deg: float = 0.0
    angular_velocity_roll_dps: float = 0.0
    angular_velocity_pitch_dps: float = 0.0
    angular_velocity_yaw_dps: float = 0.0
    zoom_ratio: float | None = None
    picture_mode: str = "unknown"
    picture_mode_code: int = 0
    osd_enabled: bool = False
    night_vision_enabled: bool = False
    lighting_enabled: bool = False
    digital_zoom_enabled: bool = False
    camera_recording: bool = False
    hardware_version: int | None = None
    firmware_version: int | None = None
    pod_code: int | None = None
    error_code: int | None = None


class GimbalModeRequest(BaseModel):
    mode: Literal["angle", "head_lock", "head_follow", "fpv"]


class GimbalPositionRequest(BaseModel):
    pitch_deg: float = Field(ge=-90.0, le=30.0)
    yaw_deg: float = Field(ge=-170.0, le=170.0)


class GimbalJogRequest(BaseModel):
    pitch_velocity_dps: float = Field(default=0.0, ge=-20.0, le=20.0)
    yaw_velocity_dps: float = Field(default=0.0, ge=-20.0, le=20.0)


class GimbalZoomRequest(BaseModel):
    action: Literal["in", "out", "stop"]


class GimbalPictureModeRequest(BaseModel):
    mode: Literal[
        "visible",
        "thermal",
        "visible_thermal_pip",
        "thermal_visible_pip",
    ]


class GimbalSettingsRequest(BaseModel):
    osd_enabled: bool | None = None


def _response(status: Z2MiniStatus) -> GimbalStatusResponse:
    return GimbalStatusResponse(**status.as_dict())


async def _execute(action: Awaitable[Z2MiniStatus]) -> GimbalStatusResponse:
    try:
        return _response(await action)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (OSError, GcuProtocolError) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Z2-Mini 云台不可用：{exc}",
        ) from exc


async def _audit(
    db,
    user: AuthUserInternal,
    *,
    action: str,
    target: str,
) -> None:
    await safe_write_audit_log(
        db,
        level="INFO",
        module="BACKEND",
        message=(
            f"用户={user.username} 角色={user.role} "
            f"操作=gimbal.{action} 目标={target} 结果=success"
        ),
    )


@router.get("/status", response_model=GimbalStatusResponse)
async def gimbal_status(
    user: AuthUserInternal = Depends(require_viewer),
) -> GimbalStatusResponse:
    try:
        return _response(await get_z2mini_gimbal().status())
    except (OSError, GcuProtocolError) as exc:
        return GimbalStatusResponse(connected=False, error=str(exc))


@router.post("/mode", response_model=GimbalStatusResponse)
async def gimbal_mode(
    body: GimbalModeRequest,
    user: AuthUserInternal = Depends(require_operator),
    db=Depends(get_db),
) -> GimbalStatusResponse:
    response = await _execute(get_z2mini_gimbal().set_mode(body.mode))
    await _audit(db, user, action="mode", target=body.mode)
    return response


@router.post("/center", response_model=GimbalStatusResponse)
async def gimbal_center(
    user: AuthUserInternal = Depends(require_operator),
    db=Depends(get_db),
) -> GimbalStatusResponse:
    response = await _execute(get_z2mini_gimbal().center())
    await _audit(db, user, action="center", target="neutral")
    return response


@router.post("/position", response_model=GimbalStatusResponse)
async def gimbal_position(
    body: GimbalPositionRequest,
    user: AuthUserInternal = Depends(require_operator),
    db=Depends(get_db),
) -> GimbalStatusResponse:
    response = await _execute(
        get_z2mini_gimbal().set_position(
            pitch_deg=body.pitch_deg,
            yaw_deg=body.yaw_deg,
        )
    )
    await _audit(
        db,
        user,
        action="position",
        target=f"pitch={body.pitch_deg:.1f},yaw={body.yaw_deg:.1f}",
    )
    return response


@router.post("/jog", response_model=GimbalStatusResponse)
async def gimbal_jog(
    body: GimbalJogRequest,
    user: AuthUserInternal = Depends(require_operator),
) -> GimbalStatusResponse:
    return await _execute(
        get_z2mini_gimbal().jog(
            pitch_velocity_dps=body.pitch_velocity_dps,
            yaw_velocity_dps=body.yaw_velocity_dps,
        )
    )


@router.post("/zoom", response_model=GimbalStatusResponse)
async def gimbal_zoom(
    body: GimbalZoomRequest,
    user: AuthUserInternal = Depends(require_operator),
) -> GimbalStatusResponse:
    return await _execute(get_z2mini_gimbal().zoom(body.action))


@router.post("/picture-mode", response_model=GimbalStatusResponse)
async def gimbal_picture_mode(
    body: GimbalPictureModeRequest,
    user: AuthUserInternal = Depends(require_operator),
    db=Depends(get_db),
) -> GimbalStatusResponse:
    response = await _execute(get_z2mini_gimbal().set_picture_mode(body.mode))
    await _audit(db, user, action="picture_mode", target=body.mode)
    return response


@router.post("/settings", response_model=GimbalStatusResponse)
async def gimbal_settings(
    body: GimbalSettingsRequest,
    user: AuthUserInternal = Depends(require_operator),
    db=Depends(get_db),
) -> GimbalStatusResponse:
    if body.osd_enabled is None:
        raise HTTPException(status_code=422, detail="至少提供一个相机设置")

    response = await _execute(
        get_z2mini_gimbal().update_settings(
            osd_enabled=body.osd_enabled,
        )
    )
    await _audit(db, user, action="settings", target=body.model_dump_json())
    return response
