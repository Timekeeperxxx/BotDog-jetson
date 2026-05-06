"""用户管理路由。"""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.dependencies import require_admin, require_authenticated
from ...auth.schemas import (
    AuthUserInternal,
    ChangePasswordRequest,
    ResetPasswordRequest,
    UserCreate,
    UserResponse,
    UserUpdate,
)
from ...auth.security import get_password_hash, is_valid_password, verify_password
from ...auth.service import safe_write_audit_log
from ...database import get_db
from ...models import User

router = APIRouter(prefix="/api/v1/users", tags=["users"])


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds") + "Z"


async def check_last_admin_protection(db: AsyncSession, user_to_modify: User, action: str):
    if user_to_modify.role != "admin":
        return

    result = await db.execute(
        select(func.count(User.id)).where(
            User.role == "admin",
            User.enabled == 1,
            User.deleted_at.is_(None)
        )
    )
    admin_count = result.scalar() or 0

    if admin_count <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不能{action}最后一名正常状态的 admin 账号"
        )


@router.get("", response_model=list[UserResponse])
async def list_users(
    db: AsyncSession = Depends(get_db),
    admin: AuthUserInternal = Depends(require_admin),
) -> Any:
    result = await db.execute(select(User).where(User.deleted_at.is_(None)))
    return result.scalars().all()


@router.post("", response_model=UserResponse)
async def create_user(
    body: UserCreate,
    db: AsyncSession = Depends(get_db),
    admin: AuthUserInternal = Depends(require_admin),
) -> Any:
    valid, msg = is_valid_password(body.password, body.username)
    if not valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

    result = await db.execute(select(User).where(User.username == body.username))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="用户名已存在")

    new_user = User(
        username=body.username,
        password_hash=get_password_hash(body.password),
        role=body.role,
        enabled=1 if body.enabled else 0,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    await safe_write_audit_log(
        db,
        level="INFO",
        module="BACKEND",
        message=f"创建用户: {body.username} role={body.role} enabled={body.enabled} by admin {admin.username}",
    )
    return new_user


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    body: UserUpdate,
    db: AsyncSession = Depends(get_db),
    admin: AuthUserInternal = Depends(require_admin),
) -> Any:
    result = await db.execute(select(User).where(User.id == user_id, User.deleted_at.is_(None)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    if user.id == admin.id:
        if body.role is not None and body.role != user.role:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能修改自己的角色")
        if body.enabled is not None and not body.enabled:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能禁用自己")

    actions = []
    
    if body.role is not None and body.role != user.role:
        await check_last_admin_protection(db, user, "降级")
        actions.append(f"role: {user.role} -> {body.role}")
        user.role = body.role
        user.token_version += 1
        
    if body.enabled is not None and bool(user.enabled) != body.enabled:
        if not body.enabled:
            await check_last_admin_protection(db, user, "禁用")
        actions.append(f"enabled: {bool(user.enabled)} -> {body.enabled}")
        user.enabled = 1 if body.enabled else 0
        if not body.enabled:
            user.token_version += 1

    if body.must_change_password is not None and bool(user.must_change_password) != body.must_change_password:
        actions.append(f"must_change_password: {bool(user.must_change_password)} -> {body.must_change_password}")
        user.must_change_password = 1 if body.must_change_password else 0

    if actions:
        user.updated_at = utc_now_iso()
        await db.commit()
        await db.refresh(user)
        await safe_write_audit_log(
            db,
            level="INFO",
            module="BACKEND",
            message=f"修改用户信息 user_id={user_id} actions=[{', '.join(actions)}] by admin {admin.username}",
        )

    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    admin: AuthUserInternal = Depends(require_admin),
) -> None:
    if user_id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能删除自己")

    result = await db.execute(select(User).where(User.id == user_id, User.deleted_at.is_(None)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    await check_last_admin_protection(db, user, "删除")

    user.enabled = 0
    user.deleted_at = utc_now_iso()
    user.token_version += 1
    await db.commit()

    await safe_write_audit_log(
        db,
        level="INFO",
        module="BACKEND",
        message=f"软删除用户 user_id={user_id} username={user.username} by admin {admin.username}",
    )


@router.post("/{user_id}/reset-password", status_code=status.HTTP_200_OK)
async def reset_password(
    user_id: int,
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
    admin: AuthUserInternal = Depends(require_admin),
) -> dict:
    if user_id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能重置自己的密码，请使用修改密码功能")

    result = await db.execute(select(User).where(User.id == user_id, User.deleted_at.is_(None)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    valid, msg = is_valid_password(body.new_password, user.username)
    if not valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

    user.password_hash = get_password_hash(body.new_password)
    user.token_version += 1
    user.updated_at = utc_now_iso()
    user.must_change_password = 1
    await db.commit()

    await safe_write_audit_log(
        db,
        level="INFO",
        module="BACKEND",
        message=f"重置密码 user_id={user_id} by admin {admin.username}",
    )
    return {"detail": "密码已重置"}


@router.post("/change-password", status_code=status.HTTP_200_OK)
async def change_password(
    body: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: AuthUserInternal = Depends(require_authenticated),
) -> dict:
    result = await db.execute(select(User).where(User.id == current_user.id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="原密码错误")

    valid, msg = is_valid_password(body.new_password, user.username)
    if not valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

    user.password_hash = get_password_hash(body.new_password)
    user.token_version += 1
    user.updated_at = utc_now_iso()
    user.must_change_password = 0
    await db.commit()

    await safe_write_audit_log(
        db,
        level="INFO",
        module="BACKEND",
        message=f"用户自改密码 user_id={user.id} username={user.username}",
    )
    return {"detail": "密码修改成功"}
