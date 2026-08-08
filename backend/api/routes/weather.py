from __future__ import annotations

from fastapi import APIRouter, Depends

from ...auth.dependencies import require_viewer
from ...auth.schemas import AuthUserInternal
from ...weather_detection import get_weather_detection_service


router = APIRouter(prefix="/api/v1/weather", tags=["weather"])


@router.get("/status")
async def weather_status(
    user: AuthUserInternal = Depends(require_viewer),
):
    service = get_weather_detection_service()
    if service is None:
        return {
            "enabled": False,
            "state": "unavailable",
            "detail": "AI Worker 未初始化，暂无天气结果",
            "label": "unknown",
            "label_zh": "未知",
            "confidence": 0.0,
            "raw_label": None,
            "raw_confidence": 0.0,
            "probabilities": {
                "normal": 0.0,
                "rain": 0.0,
                "snow": 0.0,
                "sandstorm": 0.0,
            },
            "observed_at": None,
            "inference_ms": 0.0,
            "frames_processed": 0,
            "source": "visible_camera",
            "radar_fused": False,
            "last_error": None,
            "errors": 0,
        }
    return service.get_status()
