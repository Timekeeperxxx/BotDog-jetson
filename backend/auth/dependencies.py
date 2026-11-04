from __future__ import annotations

from fastapi import Depends, HTTPException, Request, WebSocket, WebSocketException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.requests import HTTPConnection

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db, get_session_factory
from ..logging_config import get_logger
from ..models import User
from .schemas import AuthUserInternal
from .service import decode_access_token, role_satisfies

auth_logger = get_logger("鉴权")
bearer_scheme = HTTPBearer(auto_error=False)
BROWSER_SESSION_COOKIE = "botdog_browser_session"
_auth_disabled_warning_emitted = False

def get_dev_user() -> AuthUserInternal:
    return AuthUserInternal(id=0, username="dev", role="admin", token_version=0)


def _raise_unauthorized(request: HTTPConnection, detail: str) -> None:
    client_host = request.client.host if request.client else "unknown"
    auth_logger.warning(
        "鉴权失败：path={} source={} reason={}",
        request.url.path,
        client_host,
        detail,
    )
    if request.scope["type"] == "websocket":
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason=detail)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
    )


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> AuthUserInternal:
    token = credentials.credentials if credentials is not None else None
    return await _authenticate_access_token(request, token, db)


async def _authenticate_access_token(
    request: HTTPConnection,
    token: str | None,
    db: AsyncSession,
) -> AuthUserInternal:
    global _auth_disabled_warning_emitted
    if not settings.AUTH_ENABLED:
        if not _auth_disabled_warning_emitted:
            auth_logger.warning("鉴权已关闭，仅限开发环境")
            _auth_disabled_warning_emitted = True
        return get_dev_user()

    if token is None:
        _raise_unauthorized(request, "缺少访问令牌")

    try:
        token_data = decode_access_token(token)
    except ValueError as exc:
        _raise_unauthorized(request, str(exc))

    user_id = token_data.get("user_id")
    if not isinstance(user_id, int):
        _raise_unauthorized(request, "token 载荷无效")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        _raise_unauthorized(request, "用户不存在")
    if user.username != token_data.get("sub"):
        _raise_unauthorized(request, "Token 用户不匹配")
    if not user.enabled:
        _raise_unauthorized(request, "用户已被禁用")
    if user.deleted_at is not None:
        _raise_unauthorized(request, "用户已删除")
    if user.token_version != token_data.get("token_version", 0):
        _raise_unauthorized(request, "Token 已失效，请重新登录")

    return AuthUserInternal(
        id=user.id,
        username=user.username,
        role=user.role,
        token_version=user.token_version,
    )


async def require_media_viewer(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> AuthUserInternal:
    # Native <img>/<video> requests cannot attach the API's Bearer header.
    # Cookies are accepted only here and for WebSockets, never for API writes.
    token = credentials.credentials if credentials is not None else None
    if "authorization" not in request.headers:
        token = request.cookies.get(BROWSER_SESSION_COOKIE)
    user = await _authenticate_access_token(request, token, db)
    if not role_satisfies(user.role, "viewer"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="权限不足")
    return user


async def require_websocket_viewer(websocket: WebSocket) -> AuthUserInternal:
    credentials = await bearer_scheme(websocket)
    token = credentials.credentials if credentials is not None else None
    if "authorization" not in websocket.headers and settings.AUTH_ENABLED:
        # Cookie-based WebSocket handshakes must originate from this app or
        # an explicitly configured origin; '*' does not grant cookie access.
        scheme = "https" if websocket.url.scheme == "wss" else "http"
        origin = websocket.headers.get("origin")
        same_origin = f"{scheme}://{websocket.headers['host']}"
        if origin != same_origin and origin not in settings.CORS_ALLOW_ORIGINS:
            raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="不允许的连接来源")
        token = websocket.cookies.get(BROWSER_SESSION_COOKIE)
    # Release the DB session before the long-lived connection starts streaming.
    async with get_session_factory()() as db:
        user = await _authenticate_access_token(websocket, token, db)
    if not role_satisfies(user.role, "viewer"):
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="权限不足")
    return user


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
