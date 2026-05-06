"""自动跟踪路由。"""

from fastapi import APIRouter, Depends, HTTPException

from ...auth.dependencies import require_operator, require_viewer
from ...auth.schemas import AuthUserInternal
from ...auth.service import safe_write_audit_log
from ...database import get_db
from ...logging_config import logger

router = APIRouter(prefix="/api/v1/auto-track", tags=["auto_track"])


@router.get("/debug")
async def auto_track_debug(
    user: AuthUserInternal = Depends(require_viewer),
) -> dict:
    """调试端点：返回当前自动跟踪状态快照。"""
    from ...auto_track_service import get_auto_track_service

    svc = get_auto_track_service()
    if svc is None:
        raise HTTPException(status_code=503, detail="自动跟踪服务未初始化")
    return svc.get_status()


@router.post("/enable")
async def auto_track_enable(
    user: AuthUserInternal = Depends(require_operator),
    db=Depends(get_db),
) -> dict:
    """运行时启用自动跟踪。"""
    from ...auto_track_service import get_auto_track_service
    from ...guard_mission_service import get_guard_mission_service

    svc = get_auto_track_service()
    if svc is None:
        raise HTTPException(status_code=503, detail="自动跟踪服务未初始化")
    gm = get_guard_mission_service()
    if gm is not None and gm.enabled:
        gm.enabled = False
        logger.info("[AutoTrack] 互斥切换：已自动关闭自动驱离")
    svc.enable()
    await safe_write_audit_log(
        db,
        level="INFO",
        module="BACKEND",
        message=f"用户={user.username} 角色={user.role} 操作=auto_track.enable 目标=service 结果=success",
    )
    return {"success": True, "state": svc.get_status()["state"]}


@router.post("/disable")
async def auto_track_disable(
    user: AuthUserInternal = Depends(require_operator),
    db=Depends(get_db),
) -> dict:
    """运行时禁用自动跟踪，立即停止并发出 stop 命令。"""
    from ...auto_track_service import get_auto_track_service

    svc = get_auto_track_service()
    if svc is None:
        raise HTTPException(status_code=503, detail="自动跟踪服务未初始化")
    svc.disable()
    await safe_write_audit_log(
        db,
        level="WARN",
        module="BACKEND",
        message=f"用户={user.username} 角色={user.role} 操作=auto_track.disable 目标=service 结果=success",
    )
    return {"success": True, "state": svc.get_status()["state"]}


@router.post("/pause")
async def auto_track_pause(
    user: AuthUserInternal = Depends(require_operator),
    db=Depends(get_db),
) -> dict:
    """暂停自动跟踪（保留目标状态，停发控制命令）。"""
    from ...auto_track_service import get_auto_track_service

    svc = get_auto_track_service()
    if svc is None:
        raise HTTPException(status_code=503, detail="自动跟踪服务未初始化")
    svc.pause()
    await safe_write_audit_log(
        db,
        level="WARN",
        module="BACKEND",
        message=f"用户={user.username} 角色={user.role} 操作=auto_track.pause 目标=service 结果=success",
    )
    return {"success": True, "state": svc.get_status()["state"]}


@router.post("/resume")
async def auto_track_resume(
    user: AuthUserInternal = Depends(require_operator),
    db=Depends(get_db),
) -> dict:
    """恢复自动跟踪。"""
    from ...auto_track_service import get_auto_track_service

    svc = get_auto_track_service()
    if svc is None:
        raise HTTPException(status_code=503, detail="自动跟踪服务未初始化")
    svc.resume()
    await safe_write_audit_log(
        db,
        level="INFO",
        module="BACKEND",
        message=f"用户={user.username} 角色={user.role} 操作=auto_track.resume 目标=service 结果=success",
    )
    return {"success": True, "state": svc.get_status()["state"]}


@router.post("/manual-override")
async def auto_track_manual_override(
    user: AuthUserInternal = Depends(require_operator),
    db=Depends(get_db),
) -> dict:
    """人工接管控制权（自动命令将被拦截）。"""
    from ...control_arbiter import get_control_arbiter
    from ...tracking_types import ControlOwner

    arbiter = get_control_arbiter()
    if arbiter is None:
        raise HTTPException(status_code=503, detail="仲裁器未初始化")
    arbiter.request_control(ControlOwner.WEB_MANUAL)
    await safe_write_audit_log(
        db,
        level="WARN",
        module="BACKEND",
        message=f"用户={user.username} 角色={user.role} 操作=auto_track.manual_override 目标=arbiter 结果=success",
    )
    return {"success": True, "arbiter": arbiter.get_status()}


@router.post("/release-override")
async def auto_track_release_override(
    user: AuthUserInternal = Depends(require_operator),
    db=Depends(get_db),
) -> dict:
    """释放人工覆盖，允许自动跟踪恢复发命令。"""
    from ...control_arbiter import get_control_arbiter

    arbiter = get_control_arbiter()
    if arbiter is None:
        raise HTTPException(status_code=503, detail="仲裁器未初始化")
    arbiter.release_manual_override()
    await safe_write_audit_log(
        db,
        level="INFO",
        module="BACKEND",
        message=f"用户={user.username} 角色={user.role} 操作=auto_track.release_override 目标=arbiter 结果=success",
    )
    return {"success": True, "arbiter": arbiter.get_status()}


@router.get("/arbiter")
async def auto_track_arbiter_status(
    user: AuthUserInternal = Depends(require_viewer),
) -> dict:
    """查询当前控制权仲裁状态。"""
    from ...control_arbiter import get_control_arbiter

    arbiter = get_control_arbiter()
    if arbiter is None:
        raise HTTPException(status_code=503, detail="仲裁器未初始化")
    return arbiter.get_status()


@router.post("/mark-known/{track_id}")
async def auto_track_mark_known(
    track_id: int,
    user: AuthUserInternal = Depends(require_operator),
    db=Depends(get_db),
) -> dict:
    """将指定 track_id 标记为已知人员（不再跟踪）。"""
    from ...stranger_policy import get_stranger_policy
    from ...auto_track_service import get_auto_track_service

    policy = get_stranger_policy()
    if policy is None:
        raise HTTPException(status_code=503, detail="陌生人策略未初始化")
    policy.mark_known(track_id, reason="operator")
    svc = get_auto_track_service()
    if svc and svc._target_manager:
        svc._target_manager.mark_known(track_id)
    await safe_write_audit_log(
        db,
        level="INFO",
        module="BACKEND",
        message=f"用户={user.username} 角色={user.role} 操作=auto_track.mark_known 目标={track_id} 结果=success",
    )
    return {
        "success": True,
        "track_id": track_id,
        "known_count": policy.known_count,
    }


@router.post("/unmark-known/{track_id}")
async def auto_track_unmark_known(
    track_id: int,
    user: AuthUserInternal = Depends(require_operator),
    db=Depends(get_db),
) -> dict:
    """取消 track_id 的已知标记（误操作恢复）。"""
    from ...stranger_policy import get_stranger_policy

    policy = get_stranger_policy()
    if policy is None:
        raise HTTPException(status_code=503, detail="陌生人策略未初始化")
    policy.unmark_known(track_id)
    await safe_write_audit_log(
        db,
        level="INFO",
        module="BACKEND",
        message=f"用户={user.username} 角色={user.role} 操作=auto_track.unmark_known 目标={track_id} 结果=success",
    )
    return {
        "success": True,
        "track_id": track_id,
        "known_count": policy.known_count,
    }


@router.get("/known-list")
async def auto_track_known_list(
    user: AuthUserInternal = Depends(require_viewer),
) -> dict:
    """查询当前会话已知人员列表。"""
    from ...stranger_policy import get_stranger_policy

    policy = get_stranger_policy()
    if policy is None:
        raise HTTPException(status_code=503, detail="陌生人策略未初始化")
    return {
        "known_ids": policy.get_known_ids(),
        "total": policy.known_count,
    }
