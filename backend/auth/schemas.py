from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AuthUserInternal(BaseModel):
    id: int
    username: str
    role: str
    token_version: int

class AuthUserResponse(BaseModel):
    id: int
    username: str
    role: str
    must_change_password: bool


class AuthStatusResponse(BaseModel):
    auth_enabled: bool
    current_user: AuthUserResponse

class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: str
    enabled: bool
    must_change_password: bool
    created_at: str
    updated_at: str
    last_login_at: str | None = None

class UserCreate(BaseModel):
    username: str = Field(..., min_length=1, max_length=50, pattern="^[A-Za-z0-9_-]+$")
    password: str = Field(..., min_length=8)
    role: str = Field(..., pattern="^(viewer|operator|admin)$")
    enabled: bool = True
    must_change_password: bool = False

class UserUpdate(BaseModel):
    role: str | None = Field(None, pattern="^(viewer|operator|admin)$")
    enabled: bool | None = None
    must_change_password: bool | None = None

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=8)

class ResetPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=8)


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: AuthUserResponse
