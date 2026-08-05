from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FaceTemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    identity_id: int
    dimension: int
    model_name: str
    model_version: str
    quality: float
    created_at: str


class FaceIdentityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    display_name: str
    notes: str | None
    enabled: bool
    created_at: str
    updated_at: str
    templates: list[FaceTemplateResponse] = Field(default_factory=list)


class FaceIdentityCreate(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=100)
    notes: str | None = Field(default=None, max_length=500)
    enabled: bool = True

    @field_validator("display_name")
    @classmethod
    def clean_display_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("姓名不能为空")
        return value


class FaceIdentityUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    notes: str | None = Field(default=None, max_length=500)
    enabled: bool | None = None

    @field_validator("display_name")
    @classmethod
    def clean_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("姓名不能为空")
        return value


class FaceRecognitionStatusResponse(BaseModel):
    enabled: bool
    available: bool
    engine_loaded: bool
    model_name: str
    detect_model_path: str
    recognition_model_path: str
    identity_count: int
    template_count: int
    match_threshold: float
    last_reload_at: str | None
    error: str | None
