"""真实控制路由。"""

import asyncio
import math

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...auth.dependencies import require_admin, require_operator
from ...auth.schemas import AuthUserInternal
from ...auth.service import safe_write_audit_log
from ...control_service import (
    UNITREE_B2_MAX_VX,
    UNITREE_B2_MAX_VYAW,
    get_control_service,
)
from ...database import get_db
from ...nav_bridge_state import get_ros_nav_bridge
from ...schemas import ControlAckDTO, EStopResetResponse, EStopResponse, utc_now_iso
from ...services_nav_localization import set_cmd_vel_estop, stop_cmd_vel_script
from ...state_machine_state import get_state_machine

router = APIRouter(prefix="/api/v1/control", tags=["control"])


class ControlCommandRequest(BaseModel):
    """控制命令请求体。"""

    cmd: str
    vx: float | None = None
    vyaw: float | None = None


def _clamp_optional(value: float | None, limit: float) -> float | None:
    if value is None:
        return None
    return max(-limit, min(limit, value))


@router.post("/command", response_model=ControlAckDTO)
async def control_command(
    body: ControlCommandRequest,
    user: AuthUserInternal = Depends(require_operator),
    db=Depends(get_db),
) -> ControlAckDTO:
    """
    发送控制命令到机器狗。

    支持的命令：forward / backward / left / right / sit / stand / stop

    - 按下时前端每 500ms 发一次，松手时立即发 stop
    - 非 stop 命令：自动向 ControlArbiter 申请 WEB_MANUAL 控制权（压制自动跟踪）
    - stop 命令：保持 WEB_MANUAL 覆盖，避免导航或自动跟踪立即重新驱动
    - E_STOP 状态下所有命令被拒绝（返回 REJECTED_E_STOP）
    - Watchdog 超时后自动执行 stop
    """
    # Validate before clamping or claiming control: min/max can turn NaN into a limit.
    if any(value is not None and not math.isfinite(value) for value in (body.vx, body.vyaw)):
        raise HTTPException(status_code=422, detail="vx、vyaw 必须是有限数值，不能为 NaN 或 Infinity")

    svc = get_control_service()
    if svc is None:
        raise HTTPException(status_code=503, detail="控制服务未就绪")

    from ...control_arbiter import get_control_arbiter
    from ...tracking_types import ControlOwner

    arbiter = get_control_arbiter()
    if arbiter is not None:
        arbiter.request_control(ControlOwner.WEB_MANUAL)

    ack = await svc.handle_command(
        body.cmd,
        vx=_clamp_optional(body.vx, UNITREE_B2_MAX_VX),
        vyaw=_clamp_optional(body.vyaw, UNITREE_B2_MAX_VYAW),
    )
    # 只对失败/拒绝命令写审计日志；ACCEPTED 跳过，避免高频写 SQLite 阻塞响应
    if ack.result != "ACCEPTED":
        await safe_write_audit_log(
            db,
            level="WARN",
            module="BACKEND",
            message=f"用户={user.username} 角色={user.role} 操作=control.command 目标={body.cmd} 结果={ack.result}",
        )
    return ack


@router.post("/stop", response_model=ControlAckDTO)
async def control_stop(
    user: AuthUserInternal = Depends(require_operator),
    db=Depends(get_db),
) -> ControlAckDTO:
    """快捷停止接口（等同于发送 cmd='stop'），供前端紧急停止使用。"""
    svc = get_control_service()
    if svc is None:
        raise HTTPException(status_code=503, detail="控制服务未就绪")

    from ...control_arbiter import get_control_arbiter
    from ...tracking_types import ControlOwner

    arbiter = get_control_arbiter()
    if arbiter is not None:
        arbiter.request_control(ControlOwner.WEB_MANUAL)
    ack = await svc.force_stop()
    if ack.result != "ACCEPTED":
        await safe_write_audit_log(
            db,
            level="WARN",
            module="BACKEND",
            message=f"用户={user.username} 角色={user.role} 操作=control.stop 目标=stop 结果={ack.result}",
        )
    return ack


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

    from ...control_arbiter import get_control_arbiter
    from ...control_service import get_control_service

    state_machine.trigger_emergency_stop()
    errors: list[str] = []
    try:
        set_cmd_vel_estop(True, "control_e_stop")
    except Exception as exc:
        errors.append(f"导航速度锁定失败：{type(exc).__name__}: {exc}")
    arbiter = get_control_arbiter()
    if arbiter is not None:
        arbiter.activate_e_stop()
    else:
        errors.append("控制权仲裁器未就绪")
    bridge = get_ros_nav_bridge()
    service = get_control_service()

    def stop_navigation_channels() -> list[str]:
        failures = []
        if bridge is not None:
            for method, args, kwargs in [
                ("publish_navigation_task_start", (False,), {}),
                ("publish_navigation_start", (False,), {}),
                ("publish_navigation_stop", (), {}),
                ("publish_zero_cmd_vel", (), {"publish_count": 20, "interval_s": 0.02}),
            ]:
                try:
                    getattr(bridge, method)(*args, **kwargs)
                except Exception as exc:
                    failures.append(f"导航停止信号 {method} 失败：{type(exc).__name__}: {exc}")
        try:
            stop_cmd_vel_script()
        except Exception as exc:
            failures.append(f"停止导航速度桥失败：{type(exc).__name__}: {exc}")
        return failures

    async def stop_robot() -> tuple[ControlAckDTO | None, list[str]]:
        if service is None:
            return None, ["机器人控制服务未就绪，底盘停车未确认"]
        try:
            ack = await service.force_stop()
        except Exception as exc:
            return None, [f"底盘停车异常：{type(exc).__name__}: {exc}"]
        if ack.result != "ACCEPTED":
            return ack, [f"底盘停车未确认：{ack.result}"]
        return ack, []

    # A slow/failing ROS publisher or script cleanup must not delay the SDK stop.
    navigation_errors, (ack, robot_errors) = await asyncio.gather(
        asyncio.to_thread(stop_navigation_channels), stop_robot(),
    )
    errors.extend(navigation_errors)
    errors.extend(robot_errors)
    stop_confirmed = ack is not None and ack.result == "ACCEPTED"
    success = stop_confirmed and not errors
    if not stop_confirmed:
        message = "急停已锁定，但底盘停车未确认，请立即检查设备"
    elif errors:
        message = "急停已锁定，底盘停车已确认；部分导航停止步骤失败"
    else:
        message = "急停已锁定，底盘停车已确认"

    await safe_write_audit_log(
        db,
        level="WARN",
        module="BACKEND",
        message=(
            "用户=anonymous 角色=anonymous 操作=control.e_stop 目标=system "
            f"结果={'success' if success else 'incomplete'} stop_confirmed={stop_confirmed} errors={errors}"
        ),
    )
    return EStopResponse(
        success=success, e_stop_latched=True, stop_confirmed=stop_confirmed,
        control_ack=ack, errors=errors, timestamp=utc_now_iso(), message=message,
    )



@router.post("/e-stop/reset", response_model=EStopResetResponse)
async def emergency_stop_reset(
    user: AuthUserInternal = Depends(require_admin),
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
    set_cmd_vel_estop(False, "control_e_stop_reset")
    from ...control_arbiter import get_control_arbiter
    from ...tracking_types import ControlOwner

    arbiter = get_control_arbiter()
    if arbiter is not None:
        arbiter.release_control(ControlOwner.E_STOP)

    await safe_write_audit_log(
        db,
        level="INFO",
        module="BACKEND",
        message=(
            f"用户={user.username} 角色={user.role} 操作=control.e_stop.reset "
            f"目标=system 结果=success 状态={old_state}->{state_machine.state}"
        ),
    )

    return EStopResetResponse(
        success=True,
        timestamp=utc_now_iso(),
        message="紧急制动已重置，控制已恢复",
        state_after=state_machine.state,
    )
