from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.dependencies import require_admin, require_viewer
from ...auth.schemas import AuthUserInternal
from ...auth.service import safe_write_audit_log
from ...config import settings
from ...database import get_db, get_session_factory
from ...face_recognition.engine import FaceEngineError
from ...face_recognition.schemas import (
    FaceIdentityCreate,
    FaceIdentityResponse,
    FaceIdentityUpdate,
    FaceRecognitionStatusResponse,
    FaceTemplateResponse,
)
from ...models import FaceIdentity, FaceTemplate
from ...schemas import utc_now_iso
from ...services_face_identities import get_face_identity_service

router = APIRouter(prefix="/api/v1", tags=["face-identities"])


async def _ready_service():
    service = get_face_identity_service()
    await service.ensure_initialized(get_session_factory())
    return service


@router.get("/face-identities", response_model=list[FaceIdentityResponse])
async def list_face_identities(
    db: AsyncSession = Depends(get_db),
    _: AuthUserInternal = Depends(require_admin),
):
    return await get_face_identity_service().list_identities(db)


@router.post(
    "/face-identities",
    response_model=FaceIdentityResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_face_identity(
    body: FaceIdentityCreate,
    db: AsyncSession = Depends(get_db),
    admin: AuthUserInternal = Depends(require_admin),
):
    identity = FaceIdentity(
        display_name=body.display_name,
        notes=body.notes,
        enabled=1 if body.enabled else 0,
    )
    db.add(identity)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="人员姓名已存在") from exc
    await db.refresh(identity)
    await safe_write_audit_log(
        db,
        level="INFO",
        module="BACKEND",
        message=f"用户={admin.username} 操作=face_identity.create 目标={identity.id} 姓名={identity.display_name}",
    )
    return await get_face_identity_service().get_identity(db, identity.id)


@router.get("/face-identities/{identity_id}", response_model=FaceIdentityResponse)
async def get_face_identity(
    identity_id: int,
    db: AsyncSession = Depends(get_db),
    _: AuthUserInternal = Depends(require_admin),
):
    identity = await get_face_identity_service().get_identity(db, identity_id)
    if identity is None:
        raise HTTPException(status_code=404, detail="人员不存在")
    return identity


@router.patch("/face-identities/{identity_id}", response_model=FaceIdentityResponse)
async def update_face_identity(
    identity_id: int,
    body: FaceIdentityUpdate,
    db: AsyncSession = Depends(get_db),
    admin: AuthUserInternal = Depends(require_admin),
):
    service = get_face_identity_service()
    identity = await service.get_identity(db, identity_id)
    if identity is None:
        raise HTTPException(status_code=404, detail="人员不存在")
    changes = body.model_dump(exclude_unset=True)
    if "display_name" in changes:
        identity.display_name = changes["display_name"]
    if "notes" in changes:
        identity.notes = changes["notes"]
    if "enabled" in changes:
        identity.enabled = 1 if changes["enabled"] else 0
    identity.updated_at = utc_now_iso()
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="人员姓名已存在") from exc
    await service.reload(db)
    await safe_write_audit_log(
        db,
        level="INFO",
        module="BACKEND",
        message=f"用户={admin.username} 操作=face_identity.update 目标={identity_id}",
    )
    return await service.get_identity(db, identity_id)


@router.delete("/face-identities/{identity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_face_identity(
    identity_id: int,
    db: AsyncSession = Depends(get_db),
    admin: AuthUserInternal = Depends(require_admin),
) -> None:
    service = get_face_identity_service()
    identity = await service.get_identity(db, identity_id)
    if identity is None:
        raise HTTPException(status_code=404, detail="人员不存在")
    display_name = identity.display_name
    await db.delete(identity)
    await db.commit()
    await service.reload(db)
    await safe_write_audit_log(
        db,
        level="INFO",
        module="BACKEND",
        message=f"用户={admin.username} 操作=face_identity.delete 目标={identity_id} 姓名={display_name} hard_delete=true",
    )


@router.post(
    "/face-identities/{identity_id}/templates",
    response_model=FaceTemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_face_template(
    identity_id: int,
    image: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    admin: AuthUserInternal = Depends(require_admin),
):
    if image.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(status_code=415, detail="仅支持 JPEG、PNG 或 WebP 图片")
    service = await _ready_service()
    identity = await service.get_identity(db, identity_id)
    if identity is None:
        raise HTTPException(status_code=404, detail="人员不存在")
    template_count = await db.scalar(
        select(func.count(FaceTemplate.id)).where(FaceTemplate.identity_id == identity_id)
    )
    if int(template_count or 0) >= settings.FACE_MAX_TEMPLATES_PER_IDENTITY:
        raise HTTPException(
            status_code=409,
            detail=f"每个人员最多保存 {settings.FACE_MAX_TEMPLATES_PER_IDENTITY} 个模板",
        )
    image_bytes = await image.read(settings.FACE_MAX_UPLOAD_BYTES + 1)
    await image.close()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="上传图片为空")
    if len(image_bytes) > settings.FACE_MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="图片大小不得超过 8MB")
    try:
        extraction = await asyncio.to_thread(service.extract_template, image_bytes)
    except FaceEngineError as exc:
        code = 503 if not service.status()["available"] else 422
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    template = FaceTemplate(
        identity_id=identity_id,
        embedding=extraction.embedding.tobytes(),
        dimension=int(extraction.embedding.size),
        model_name=service.engine.model_name,
        model_version=service.engine.model_version,
        quality=extraction.quality,
    )
    db.add(template)
    identity.updated_at = utc_now_iso()
    await db.commit()
    await db.refresh(template)
    await service.reload(db)
    await safe_write_audit_log(
        db,
        level="INFO",
        module="BACKEND",
        message=f"用户={admin.username} 操作=face_template.create 人员={identity_id} 模板={template.id}",
    )
    return template


@router.delete(
    "/face-identities/{identity_id}/templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_face_template(
    identity_id: int,
    template_id: int,
    db: AsyncSession = Depends(get_db),
    admin: AuthUserInternal = Depends(require_admin),
) -> None:
    result = await db.execute(
        select(FaceTemplate).where(
            FaceTemplate.id == template_id,
            FaceTemplate.identity_id == identity_id,
        )
    )
    template = result.scalar_one_or_none()
    if template is None:
        raise HTTPException(status_code=404, detail="人脸模板不存在")
    await db.delete(template)
    identity = await db.get(FaceIdentity, identity_id)
    if identity is not None:
        identity.updated_at = utc_now_iso()
    await db.commit()
    service = get_face_identity_service()
    await service.reload(db)
    await safe_write_audit_log(
        db,
        level="INFO",
        module="BACKEND",
        message=f"用户={admin.username} 操作=face_template.delete 人员={identity_id} 模板={template_id}",
    )


@router.get("/face-recognition/status", response_model=FaceRecognitionStatusResponse)
async def get_face_recognition_status(
    _: AuthUserInternal = Depends(require_viewer),
):
    service = await _ready_service()
    return service.status()
