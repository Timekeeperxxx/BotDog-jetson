from __future__ import annotations

from pydantic import BaseModel, Field


class AuthUser(BaseModel):
    username: str
    role: str


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: AuthUser
