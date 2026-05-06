"""认证路由。"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ...models import User
from ...config import settings
from ...auth.security import verify_password
from ...auth.dependencies import require_authenticated
from ...auth.schemas import (
    AuthStatusResponse,
    AuthUserInternal,
    AuthUserResponse,
    LoginRequest,
    LoginResponse,
)
from ...auth.service import create_access_token, safe_write_audit_log
from ...database import get_db

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def auth_login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    from datetime import datetime, timezone

    result = await db.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(body.password, user.password_hash):
        await safe_write_audit_log(
            db,
            level="WARN",
            module="BACKEND",
            message=f"登录失败 user={body.username} role=anonymous action=auth.login result=fail reason=bad_credentials",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    if user.deleted_at is not None:
        await safe_write_audit_log(
            db,
            level="WARN",
            module="BACKEND",
            message=f"登录失败 user={user.username} role={user.role} action=auth.login result=fail reason=deleted",
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="此账号已被删除")

    if not user.enabled:
        await safe_write_audit_log(
            db,
            level="WARN",
            module="BACKEND",
            message=f"登录失败 user={user.username} role={user.role} action=auth.login result=fail reason=disabled",
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="此账号已被禁用")

    # Update last_login_at
    user.last_login_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds") + "Z"
    await db.commit()

    auth_user = AuthUserInternal(
        id=user.id,
        username=user.username,
        role=user.role,
        token_version=user.token_version,
    )
    token = create_access_token(auth_user)

    await safe_write_audit_log(
        db,
        level="INFO",
        module="BACKEND",
        message=f"登录成功 user={user.username} role={user.role} action=auth.login result=success",
    )
    return LoginResponse(
        access_token=token,
        token_type="bearer",
        user=AuthUserResponse(
            id=user.id,
            username=user.username,
            role=user.role,
            must_change_password=user.must_change_password,
        ),
    )


async def _load_auth_user(db: AsyncSession, user_id: int) -> AuthUserResponse | None:
    result = await db.execute(select(User).where(User.id == user_id))
    db_user = result.scalar_one_or_none()
    if not db_user:
        return None
    return AuthUserResponse(
        id=db_user.id,
        username=db_user.username,
        role=db_user.role,
        must_change_password=db_user.must_change_password,
    )


@router.get("/me", response_model=AuthUserResponse)
async def auth_me(
    user: AuthUserInternal = Depends(require_authenticated),
    db: AsyncSession = Depends(get_db),
) -> AuthUserResponse:
    if not settings.AUTH_ENABLED:
        return AuthUserResponse(id=0, username="dev", role="admin", must_change_password=False)
    current_user = await _load_auth_user(db, user.id)
    if current_user is None:
        raise HTTPException(status_code=401, detail="用户不存在")
    return current_user


@router.get("/status", response_model=AuthStatusResponse)
async def auth_status(
    user: AuthUserInternal = Depends(require_authenticated),
    db: AsyncSession = Depends(get_db),
) -> AuthStatusResponse:
    """返回鉴权状态和当前用户信息，供后台安全总览使用。"""
    if not settings.AUTH_ENABLED:
        return AuthStatusResponse(
            auth_enabled=False,
            current_user=AuthUserResponse(
                id=0,
                username="dev",
                role="admin",
                must_change_password=False,
            ),
        )
    current_user = await _load_auth_user(db, user.id)
    if current_user is None:
        raise HTTPException(status_code=401, detail="用户不存在")
    return AuthStatusResponse(
        auth_enabled=settings.AUTH_ENABLED,
        current_user=current_user,
    )
