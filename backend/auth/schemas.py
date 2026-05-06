from __future__ import annotations

from pydantic import BaseModel, Field


class AuthUser(BaseModel):
    id: int
    username: str
    role: str
    token_version: int

class UserResponse(BaseModel):
    id: int
    username: str
    role: str
    enabled: bool
    must_change_password: bool
    created_at: str
    updated_at: str
    last_login_at: str | None = None

    class Config:
        from_attributes = True

class UserCreate(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=8)
    role: str = Field(..., pattern="^(viewer|operator|admin)$")
    enabled: bool = True

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
    user: AuthUser
