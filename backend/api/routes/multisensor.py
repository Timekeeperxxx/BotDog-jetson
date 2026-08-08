from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ...auth.dependencies import require_operator, require_viewer
from ...auth.schemas import AuthUserInternal
from ...auth.service import safe_write_audit_log
from ...database import get_db
from ...multisensor_fusion import get_multisensor_fusion_service

router = APIRouter(prefix="/api/v1/multisensor", tags=["multisensor"])

PositiveFloat = Annotated[float, Field(gt=0)]
PositiveInt = Annotated[int, Field(gt=0)]
Matrix3 = tuple[
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
]


class VisibleIntrinsicsPayload(BaseModel):
    width: PositiveInt
    height: PositiveInt
    fx: PositiveFloat
    fy: PositiveFloat
    cx: float
    cy: float


class ResolutionPayload(BaseModel):
    width: PositiveInt
    height: PositiveInt


class RigidTransformPayload(BaseModel):
    rotation: Matrix3
    translation_m: tuple[float, float, float]


class GimbalReferencePayload(BaseModel):
    yaw_deg: float
    pitch_deg: float
    zoom_ratio: PositiveFloat


class CoordinateValidationPayload(BaseModel):
    sample_count: PositiveInt
    rmse_m: float = Field(ge=0)
    max_error_m: float = Field(ge=0)
    validated_at: str = Field(min_length=1, max_length=100)


class CalibrationPayload(BaseModel):
    version: str = Field(min_length=1, max_length=100)
    calibrated_at: str = Field(min_length=1, max_length=100)
    visible_frame_id: str = Field(min_length=1, max_length=100)
    thermal_frame_id: str = Field(min_length=1, max_length=100)
    lidar_frame_id: str = Field(min_length=1, max_length=100)
    visible_intrinsics: VisibleIntrinsicsPayload
    thermal_resolution: ResolutionPayload
    lidar_to_visible: RigidTransformPayload
    thermal_to_visible_homography: Matrix3
    gimbal_reference: GimbalReferencePayload
    coordinate_validation: CoordinateValidationPayload | None = None


class ThermalSamplePayload(BaseModel):
    timestamp: PositiveFloat = Field(
        description="与雷达和可见光相同设备时钟域中的秒时间戳"
    )
    width: PositiveInt
    height: PositiveInt
    frame_id: str = Field(default="thermal_camera", min_length=1, max_length=100)
    sequence: int | None = Field(default=None, ge=0)


def _service():
    service = get_multisensor_fusion_service()
    if service is None:
        raise HTTPException(status_code=503, detail="多源融合服务未初始化")
    return service


@router.get("/status")
async def multisensor_status(
    user: AuthUserInternal = Depends(require_viewer),
):
    return _service().get_status()


@router.get("/calibration")
async def multisensor_calibration(
    user: AuthUserInternal = Depends(require_viewer),
):
    service = _service()
    return {
        "calibration": service.get_calibration(),
        "status": service.get_status()["calibration"],
    }


@router.put("/calibration")
async def multisensor_update_calibration(
    payload: CalibrationPayload,
    user: AuthUserInternal = Depends(require_operator),
    db=Depends(get_db),
):
    service = _service()
    try:
        calibration = service.update_calibration(payload.model_dump(mode="json"))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await safe_write_audit_log(
        db,
        level="INFO",
        module="BACKEND",
        message=(
            f"用户={user.username} 角色={user.role} 操作=multisensor.calibration.update "
            f"版本={calibration['version']} 结果=success"
        ),
    )
    return {"success": True, "calibration": calibration}


@router.post("/samples/thermal")
async def multisensor_ingest_thermal_sample(
    payload: ThermalSamplePayload,
    user: AuthUserInternal = Depends(require_operator),
):
    service = _service()
    if not service.enabled:
        raise HTTPException(status_code=409, detail="MULTISENSOR_ENABLED=false")
    bundle = service.ingest_thermal(
        timestamp=payload.timestamp,
        width=payload.width,
        height=payload.height,
        frame_id=payload.frame_id,
        sequence=payload.sequence,
    )
    return {
        "accepted": True,
        "bundle_id": bundle.bundle_id if bundle is not None else None,
    }


@router.get("/targets")
async def multisensor_targets(
    user: AuthUserInternal = Depends(require_viewer),
):
    service = _service()
    return {
        "targets": service.get_targets(),
        "fusion": service.get_status()["fusion"],
    }
