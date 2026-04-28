"""真实控制路由。"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...control_service import get_control_service
from ...database import get_db
from ...schemas import ControlAckDTO, EStopResetResponse, EStopResponse, utc_now_iso
from ...services_logs import write_log
from ...state_machine_state import get_state_machine

router = APIRouter(prefix="/api/v1/control", tags=["control"])


class ControlCommandRequest(BaseModel):
    """控制命令请求体。"""

    cmd: str


@router.post("/command", response_model=ControlAckDTO)
async def control_command(body: ControlCommandRequest) -> ControlAckDTO:
    """
    发送控制命令到机器狗。

    支持的命令：forward / backward / left / right / sit / stand / stop

    - 按下时前端每 500ms 发一次，松手时立即发 stop
    - 非 stop 命令：自动向 ControlArbiter 申请 WEB_MANUAL 控制权（压制自动跟踪）
    - stop 命令：自动释放 WEB_MANUAL 覆盖权（允许自动跟踪恢复）
    - E_STOP 状态下所有命令被拒绝（返回 REJECTED_E_STOP）
    - Watchdog 超时后自动执行 stop
    """
    svc = get_control_service()
    if svc is None:
        raise HTTPException(status_code=503, detail="控制服务未就绪")

    from ...control_arbiter import get_control_arbiter
    from ...tracking_types import ControlOwner

    arbiter = get_control_arbiter()
    if arbiter is not None:
        if body.cmd != "stop":
            arbiter.request_control(ControlOwner.WEB_MANUAL)

    return await svc.handle_command(body.cmd)


@router.post("/stop", response_model=ControlAckDTO)
async def control_stop() -> ControlAckDTO:
    """快捷停止接口（等同于发送 cmd='stop'），供前端紧急停止使用。"""
    svc = get_control_service()
    if svc is None:
        raise HTTPException(status_code=503, detail="控制服务未就绪")

    return await svc.handle_command("stop")


@router.post("/e-stop", response_model=EStopResponse)
async def emergency_stop(
    db=Depends(get_db),
) -> EStopResponse:
    """
    触发紧急制动。

    功能：
    - 更新系统状态为 E_STOP_TRIGGERED
    - 记录日志
    - 触发事件广播
    """
    state_machine = get_state_machine()
    if state_machine is None:
        raise HTTPException(
            status_code=503,
            detail="状态机未初始化",
        )

    state_machine.trigger_emergency_stop()

    await write_log(
        db,
        level="WARN",
        module="BACKEND",
        message="Emergency stop triggered via API",
        task_id=None,
    )

    return EStopResponse(
        success=True,
        timestamp=utc_now_iso(),
        message="紧急制动已触发",
    )


@router.post("/e-stop/reset", response_model=EStopResetResponse)
async def emergency_stop_reset(
    db=Depends(get_db),
) -> EStopResetResponse:
    """
    重置紧急制动状态。

    功能：
    - 将系统状态从 E_STOP_TRIGGERED 恢复到正常状态
    - 记录日志
    - 允许恢复控制指令
    """
    state_machine = get_state_machine()
    if state_machine is None:
        raise HTTPException(
            status_code=503,
            detail="状态机未初始化",
        )

    old_state = state_machine.state
    state_machine.reset_emergency_stop()

    await write_log(
        db,
        level="INFO",
        module="BACKEND",
        message=f"Emergency stop reset: {old_state} -> {state_machine.state}",
        task_id=None,
    )

    return EStopResetResponse(
        success=True,
        timestamp=utc_now_iso(),
        message="紧急制动已重置，控制已恢复",
        state_after=state_machine.state,
    )
