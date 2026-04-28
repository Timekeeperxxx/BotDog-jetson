"""系统诊断路由。"""

import time

from fastapi import APIRouter

from ...app_runtime_state import APP_START_MONO
from ...schemas import SystemHealthResponse
from ...state_machine import SystemState
from ...state_machine_state import get_state_machine

router = APIRouter(tags=["system"])


@router.get("/api/v1/system/health", response_model=SystemHealthResponse)
async def system_health() -> SystemHealthResponse:
    """
    返回系统健康状态。

    阶段 1 更新：
    - status 根据 state_machine 状态映射（healthy/degraded/offline）
    - mavlink_connected 从 state_machine 读取（如果已初始化）
    - uptime 为进程启动以来的秒数
    """

    state_machine = get_state_machine()
    uptime = time.monotonic() - APP_START_MONO

    if state_machine is None:
        status = "offline"
        mavlink_connected = False
    else:
        state = state_machine.state
        if state == SystemState.DISCONNECTED:
            status = "degraded" if uptime > 10 else "offline"
        elif state == SystemState.E_STOP_TRIGGERED:
            status = "degraded"
        else:
            status = "healthy"
        mavlink_connected = state_machine.is_connected

    return SystemHealthResponse(
        status=status,
        mavlink_connected=mavlink_connected,
        uptime=round(uptime, 3),
    )
