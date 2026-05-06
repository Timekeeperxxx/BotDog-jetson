from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..config import settings
from ..logging_config import get_logger
from .schemas import AuthUser
from .service import decode_access_token, get_dev_user, role_satisfies

auth_logger = get_logger("鉴权")
bearer_scheme = HTTPBearer(auto_error=False)
_auth_disabled_warning_emitted = False


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = None,
) -> AuthUser:
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
        return decode_access_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc


async def require_authenticated(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> AuthUser:
    return await get_current_user(credentials)


async def require_viewer(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> AuthUser:
    user = await get_current_user(credentials)
    if not role_satisfies(user.role, "viewer"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="权限不足")
    return user


async def require_operator(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> AuthUser:
    user = await get_current_user(credentials)
    if not role_satisfies(user.role, "operator"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="权限不足")
    return user


async def require_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> AuthUser:
    user = await get_current_user(credentials)
    if not role_satisfies(user.role, "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="权限不足")
    return user
