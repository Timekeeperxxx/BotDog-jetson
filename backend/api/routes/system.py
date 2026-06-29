"""系统诊断路由。"""

import asyncio
import subprocess
import threading
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from ...app_runtime_state import APP_START_MONO
from ...auth.dependencies import require_operator
from ...auth.schemas import AuthUserInternal
from ...auth.service import safe_write_audit_log
from ...control_service import get_control_service
from ...database import get_db
from ...safety_supervisor import get_safety_supervisor
from ...schemas import (
    RadarHealthResponse,
    SystemHealthResponse,
    SystemSafetyResponse,
    SystemStartupResponse,
    StartupSummaryItem,
)
from ...startup_summary import coerce_startup_summary
from ...state_machine import SystemState
from ...state_machine_state import get_state_machine

router = APIRouter(tags=["system"])

_PIPELINE_SCRIPT = Path("/home/jetson/Project/BOTDOG/BotDog/scripts/run-pipeline.sh")
_pipeline_restart_proc: subprocess.Popen[str] | None = None
_pipeline_restart_lock = threading.Lock()


def _pipeline_restart_log_path() -> Path:
    return _PIPELINE_SCRIPT.parents[1] / "logs" / "pipeline_restart.log"


def _pipeline_restart_running() -> bool:
    return _pipeline_restart_proc is not None and _pipeline_restart_proc.poll() is None


def _without_proxy_env() -> dict[str, str]:
    """视频 pipeline 是机载本地链路，重启时也不能继承桌面代理。"""
    import os

    env = os.environ.copy()
    for key in (
        "http_proxy",
        "https_proxy",
        "ftp_proxy",
        "all_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "FTP_PROXY",
        "ALL_PROXY",
    ):
        env.pop(key, None)
    return env


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


@router.get("/api/v1/system/startup", response_model=SystemStartupResponse)
async def system_startup(request: Request) -> SystemStartupResponse:
    """返回启动摘要，便于运维和排障时直接查看模块启动结果。"""
    summary = coerce_startup_summary(getattr(request.app.state, "startup_summary", None))
    items = [
        StartupSummaryItem(name=item.name, status=item.status, detail=item.detail)
        for item in summary.items()
    ]
    return SystemStartupResponse(
        status=summary.overall_status(),
        uptime=round(time.monotonic() - APP_START_MONO, 3),
        generated_at=getattr(request.app.state, "startup_summary_generated_at", None),
        snapshot_file=getattr(request.app.state, "startup_summary_snapshot_file", None),
        items=items,
    )


@router.get("/api/v1/system/safety", response_model=SystemSafetyResponse)
async def system_safety() -> SystemSafetyResponse:
    """返回当前运动安全状态，仅用于展示和调试。"""
    state_machine = get_state_machine()
    control_service = get_control_service()
    adapter_status = (
        control_service.get_adapter_status()
        if control_service is not None
        else {"type": None, "ready": False}
    )
    decision = get_safety_supervisor().get_motion_safety(adapter_status=adapter_status)

    return SystemSafetyResponse(
        safe_to_move=decision.allowed,
        reasons=decision.reasons,
        system_state=state_machine.state.value if state_machine is not None else "UNINITIALIZED",
        control_adapter_ready=bool(adapter_status.get("ready")),
    )


@router.get("/api/v1/system/radar/health", response_model=RadarHealthResponse)
async def system_radar_health(
    user: AuthUserInternal = Depends(require_operator),
) -> RadarHealthResponse:
    """检测雷达 ROS2 topic、发布者和数据频率。"""
    from ...services_radar_health import check_radar_health

    result = await asyncio.to_thread(check_radar_health)
    return RadarHealthResponse(**result)


@router.post("/api/v1/system/pipeline/restart")
async def restart_pipeline(
    user: AuthUserInternal = Depends(require_operator),
    db=Depends(get_db),
) -> dict:
    """异步重启视频 pipeline。"""
    global _pipeline_restart_proc

    if not _PIPELINE_SCRIPT.exists():
        raise HTTPException(status_code=404, detail=f"Pipeline 脚本不存在: {_PIPELINE_SCRIPT}")
    if not _PIPELINE_SCRIPT.is_file():
        raise HTTPException(status_code=404, detail=f"Pipeline 脚本不是文件: {_PIPELINE_SCRIPT}")

    with _pipeline_restart_lock:
        if _pipeline_restart_running():
            return {
                "success": True,
                "running": True,
                "pid": _pipeline_restart_proc.pid if _pipeline_restart_proc else None,
                "message": "Pipeline 重启脚本正在运行",
            }

        log_path = _pipeline_restart_log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with log_path.open("a", encoding="utf-8") as log_file:
                _pipeline_restart_proc = subprocess.Popen(
                    ["/bin/bash", str(_PIPELINE_SCRIPT)],
                    cwd=str(_PIPELINE_SCRIPT.parents[1]),
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=_without_proxy_env(),
                    start_new_session=True,
                )
        except OSError as exc:
            raise HTTPException(status_code=503, detail=f"启动 Pipeline 重启脚本失败: {exc}") from exc

    await safe_write_audit_log(
        db,
        level="INFO",
        module="BACKEND",
        message=(
            f"用户={user.username} 角色={user.role} 操作=system.pipeline.restart "
            f"结果=success pid={_pipeline_restart_proc.pid}"
        ),
    )

    return {
        "success": True,
        "running": True,
        "pid": _pipeline_restart_proc.pid,
        "message": "已启动 Pipeline 重启脚本",
    }
