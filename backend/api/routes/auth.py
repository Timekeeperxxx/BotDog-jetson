"""认证路由。"""

from fastapi import APIRouter, Depends, HTTPException, status

from ...auth.dependencies import require_authenticated
from ...auth.schemas import LoginRequest, LoginResponse
from ...auth.service import (
    authenticate_admin,
    create_access_token,
    safe_write_audit_log,
)
from ...database import get_db

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def auth_login(
    body: LoginRequest,
    db=Depends(get_db),
) -> LoginResponse:
    user = authenticate_admin(body.username, body.password)
    if user is None:
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

    token = create_access_token(user)
    await safe_write_audit_log(
        db,
        level="INFO",
        module="BACKEND",
        message=f"登录成功 user={user.username} role={user.role} action=auth.login result=success",
    )
    return LoginResponse(
        access_token=token,
        token_type="bearer",
        user=user,
    )


@router.get("/me")
async def auth_me(user=Depends(require_authenticated)) -> dict[str, str]:
    return {
        "username": user.username,
        "role": user.role,
    }
