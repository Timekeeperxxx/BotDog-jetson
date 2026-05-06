from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db
from ..logging_config import get_logger
from ..models import User
from .schemas import AuthUserInternal
from .service import decode_access_token, role_satisfies

auth_logger = get_logger("鉴权")
bearer_scheme = HTTPBearer(auto_error=False)
_auth_disabled_warning_emitted = False

def get_dev_user() -> AuthUserInternal:
    return AuthUserInternal(id=0, username="dev", role="admin", token_version=0)

async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> AuthUserInternal:
    global _auth_disabled_warning_emitted
    if not settings.AUTH_ENABLED:
        if not _auth_disabled_warning_emitted:
            auth_logger.warning("鉴权已关闭，仅限开发环境")
            _auth_disabled_warning_emitted = True
        return get_dev_user()

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少访问令牌",
        )

    try:
        token_data = decode_access_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    user_id = token_data.get("user_id")
    if not isinstance(user_id, int):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token 载荷无效")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
    if user.username != token_data.get("sub"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token 用户不匹配")
    if not user.enabled:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户已被禁用")
    if user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户已删除")
    if user.token_version != token_data.get("token_version", 0):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token 已失效，请重新登录")

    return AuthUserInternal(
        id=user.id,
        username=user.username,
        role=user.role,
        token_version=user.token_version,
    )


async def require_authenticated(
    user: AuthUserInternal = Depends(get_current_user),
) -> AuthUserInternal:
    return user


async def require_viewer(
    user: AuthUserInternal = Depends(get_current_user),
) -> AuthUserInternal:
    if not role_satisfies(user.role, "viewer"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="权限不足")
    return user


async def require_operator(
    user: AuthUserInternal = Depends(get_current_user),
) -> AuthUserInternal:
    if not role_satisfies(user.role, "operator"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="权限不足")
    return user


async def require_admin(
    user: AuthUserInternal = Depends(get_current_user),
) -> AuthUserInternal:
    if not role_satisfies(user.role, "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="权限不足")
    return user
