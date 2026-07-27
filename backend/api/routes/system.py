"""系统诊断路由。"""

import asyncio
import shutil
import subprocess
import threading
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from ...app_runtime_state import APP_START_MONO
from ...auth.dependencies import require_admin, require_operator, require_viewer
from ...auth.schemas import AuthUserInternal
from ...auth.service import safe_write_audit_log
from ...config import settings
from ...control_service import get_control_service
from ...database import get_db
from ...safety_supervisor import get_safety_supervisor
from ...schemas import (
    RadarHealthResponse,
    SystemActionRequest,
    SystemActionResponse,
    SystemHealthResponse,
    SystemSafetyResponse,
    SystemStartupResponse,
    StartupSummaryItem,
    utc_now_iso,
)
from ...startup_summary import coerce_startup_summary
from ...state_machine import SystemState
from ...state_machine_state import get_state_machine
from ...services_system import (
    ensure_system_action_available,
    get_host_resource_snapshot,
    schedule_system_action,
)

router = APIRouter(tags=["system"])

_PIPELINE_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "run-pipeline.sh"
_pipeline_restart_proc: subprocess.Popen[str] | None = None
_pipeline_restart_lock = threading.Lock()
_PROJECT_ROOT = _PIPELINE_SCRIPT.parents[1]

_DANGER_ACTIONS = {
    "restart-backend": {
        "confirmation": "重启后端",
        "message": "后端服务将在约 2 秒后重启，页面连接会短暂中断",
    },
    "restart-video": {
        "confirmation": "重启视频流水线",
        "message": "视频流水线重启已提交，视频画面会短暂中断",
    },
    "restart-ai": {
        "confirmation": "重启 AI Worker",
        "message": "AI Worker 与后端同进程，将通过重启后端完成完整重载",
    },
    "reboot-device": {
        "confirmation": "重启设备",
        "message": "主机将在约 2 秒后重启，全部服务和控制链路都会中断",
    },
}


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


def _diagnostic_level(checks: list[dict]) -> str:
    statuses = {str(check.get("status") or "") for check in checks}
    if "failed" in statuses:
        return "error"
    if "degraded" in statuses or "warning" in statuses:
        return "warning"
    return "normal"


def _path_check(name: str, path: Path, *, should_be_dir: bool = False) -> dict:
    exists = path.exists()
    correct_type = path.is_dir() if should_be_dir else path.is_file()
    ok = exists and correct_type
    expected = "目录" if should_be_dir else "文件"
    if ok:
        message = f"{expected}存在"
        status = "ready"
    elif exists:
        message = f"路径存在但不是{expected}"
        status = "failed"
    else:
        message = f"{expected}不存在"
        status = "failed"

    return {
        "name": name,
        "ok": ok,
        "status": status,
        "message": message,
        "details": {"path": str(path)},
    }


def _disk_check(path: Path, *, min_free_gb: float = 1.0) -> dict:
    usage = shutil.disk_usage(path)
    free_gb = usage.free / (1024 ** 3)
    total_gb = usage.total / (1024 ** 3)
    ok = free_gb >= min_free_gb
    return {
        "name": "磁盘空间",
        "ok": ok,
        "status": "ready" if ok else "degraded",
        "message": f"剩余 {free_gb:.1f} GiB / 总计 {total_gb:.1f} GiB",
        "details": {
            "path": str(path),
            "free_bytes": usage.free,
            "total_bytes": usage.total,
            "min_free_gb": min_free_gb,
        },
    }


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


@router.get("/api/v1/system/resources")
async def system_resources(
    _: AuthUserInternal = Depends(require_viewer),
) -> dict[str, object]:
    """返回实时主机内存、磁盘和基础运行信息。"""

    try:
        return await asyncio.to_thread(get_host_resource_snapshot)
    except OSError as exc:
        raise HTTPException(status_code=503, detail=f"读取主机资源失败: {exc}") from exc


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


@router.get("/api/v1/system/diagnostics")
async def system_diagnostics(
    request: Request,
    user: AuthUserInternal = Depends(require_operator),
) -> dict:
    """聚合常用只读诊断项，便于现场一键排查。"""
    health = await system_health()
    startup = await system_startup(request)
    safety = await system_safety()

    startup_ok = not any(item.status in {"failed", "degraded"} for item in startup.items)
    health_ok = health.status == "healthy"
    safety_ok = safety.safe_to_move or bool(safety.reasons)

    checks = [
        {
            "name": "系统健康",
            "ok": health_ok,
            "status": "ready" if health_ok else "degraded",
            "message": f"status={health.status}, mavlink_connected={health.mavlink_connected}",
            "details": health.model_dump(),
        },
        {
            "name": "启动摘要",
            "ok": startup_ok,
            "status": "ready" if startup_ok else "degraded",
            "message": startup.status,
            "details": startup.model_dump(),
        },
        {
            "name": "运动安全",
            "ok": safety_ok,
            "status": "ready" if safety.safe_to_move else "degraded",
            "message": safety.reasons[0] if safety.reasons else "当前允许执行运动命令",
            "details": safety.model_dump(),
        },
        _path_check("视频 Pipeline 脚本", _PIPELINE_SCRIPT),
        _path_check("MediaMTX 配置", _PROJECT_ROOT / "config" / "mediamtx.yml"),
        _path_check("前端构建产物", _PROJECT_ROOT / "frontend" / "dist", should_be_dir=True),
        _disk_check(_PROJECT_ROOT),
    ]
    level = _diagnostic_level(checks)

    return {
        "ok": level == "normal",
        "level": level,
        "checked_at": utc_now_iso(),
        "requested_by": user.username,
        "checks": checks,
        "message": "诊断正常" if level == "normal" else "存在需要关注的诊断项",
    }


@router.get("/api/v1/system/radar/health", response_model=RadarHealthResponse)
async def system_radar_health(
    user: AuthUserInternal = Depends(require_operator),
) -> RadarHealthResponse:
    """检测雷达 ROS2 topic、发布者和数据频率。"""
    from ...services_radar_health import check_radar_health

    result = await asyncio.to_thread(check_radar_health)
    return RadarHealthResponse(**result)


@router.get("/api/v1/system/radar/preflight", response_model=RadarHealthResponse)
async def system_radar_preflight(
    user: AuthUserInternal = Depends(require_operator),
) -> RadarHealthResponse:
    """建图前快速确认雷达物理链路，不要求 Livox 驱动已经运行。"""
    from ...services_radar_health import check_livox_network_preflight

    result = await asyncio.to_thread(check_livox_network_preflight)
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


@router.post("/api/v1/system/actions/{action_key}", response_model=SystemActionResponse)
async def execute_system_action(
    action_key: str,
    payload: SystemActionRequest,
    user: AuthUserInternal = Depends(require_admin),
    db=Depends(get_db),
) -> SystemActionResponse:
    """执行固定白名单内的危险操作，仅允许管理员调用。"""

    if not settings.AUTH_ENABLED:
        raise HTTPException(status_code=503, detail="鉴权关闭时禁止执行系统危险操作")

    definition = _DANGER_ACTIONS.get(action_key)
    if definition is None:
        raise HTTPException(status_code=404, detail="不支持的系统操作")
    if payload.confirmation != definition["confirmation"]:
        raise HTTPException(status_code=400, detail="确认文本不匹配，操作已取消")

    try:
        command = await asyncio.to_thread(ensure_system_action_available, action_key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    await safe_write_audit_log(
        db,
        level="WARNING",
        module="BACKEND",
        message=(
            f"用户={user.username} 角色={user.role} 操作=system.{action_key} "
            "结果=accepted"
        ),
    )

    scheduled = schedule_system_action(action_key, command)
    message = definition["message"] if scheduled else "相同的系统操作已在等待执行"
    return SystemActionResponse(
        success=True,
        action=action_key,
        scheduled=scheduled,
        message=message,
    )
