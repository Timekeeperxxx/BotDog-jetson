"""测试告警路由。"""

from fastapi import APIRouter, Depends

from ...database import get_db
from ...logging_config import logger

router = APIRouter(tags=["test_alert"])


@router.post("/api/v1/test/alert")
async def trigger_test_alert(
    db=Depends(get_db),
):
    """
    测试端点：触发一个温度告警。

    用于验证事件 WebSocket 广播功能。
    """
    import asyncio

    from ...alert_service import get_alert_service
    from ...temperature_monitor import TemperatureAlert

    logger.info("测试端点：触发温度告警")

    alert_service = get_alert_service()

    test_alert = TemperatureAlert(
        temperature=99.0,
        threshold=60.0,
        timestamp=asyncio.get_event_loop().time(),
    )

    evidence = await alert_service.handle_temperature_alert(
        alert=test_alert,
        position={"lat": 39.9087, "lon": 116.3975},
        task_id=None,
        session=db,
    )

    return {
        "success": True,
        "message": "测试告警已触发",
        "evidence": {
            "event_type": evidence.event_type,
            "event_code": evidence.event_code,
            "message": evidence.message,
        },
    }
