from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from .map_access_geometry import validate_polygon


class MapPoint(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra='forbid')
    x: float
    y: float
    z: float


class MapZoneRequest(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra='forbid')
    scene_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=100)
    access_level: int = Field(ge=1, le=3, strict=True)
    vertices: list[MapPoint] = Field(min_length=3, max_length=128)
    enabled: bool = True
    boundary_margin_m: float = Field(default=.15, ge=0, le=5)

    @field_validator('name','scene_id')
    @classmethod
    def trimmed(cls, value):
        if not value.strip(): raise ValueError('名称不能为空')
        return value.strip()

    @model_validator(mode='after')
    def geometry(self):
        validate_polygon([p.model_dump() for p in self.vertices])
        return self
