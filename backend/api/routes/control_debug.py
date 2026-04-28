"""控制诊断路由。"""

from fastapi import APIRouter

from ...control_service import get_control_service

router = APIRouter(tags=["control"])


@router.get("/api/v1/control/debug")
async def control_debug() -> dict:
    """诊断端点：返回当前控制服务和适配器的详细状态。"""
    svc = get_control_service()
    if svc is None:
        return {"error": "控制服务未初始化"}
    return {
        "adapter": svc.get_adapter_status(),
        "watchdog_timeout_s": svc._watchdog_timeout_s,
        "rate_limit_s": svc._rate_limit_s,
        "watchdog_active": svc._watchdog_active,
    }
