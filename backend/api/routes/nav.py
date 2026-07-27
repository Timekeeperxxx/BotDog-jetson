"""导航巡逻 / PCD 点云地图路由。

从 backend/main.py 拆分出的 /api/v1/nav/* 接口，
路径、response_model、请求参数、返回字段与原始实现完全一致。
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...auth.dependencies import require_operator
from ...auth.schemas import AuthUserInternal
from ...auth.service import safe_write_audit_log
from ...config import settings
from ...database import get_db
from ...schemas import (
    LocalizationPoseDTO,
    LocalizationPoseSetRequest,
    LocalizationRestartResponse,
    MappingControlRequest,
    MappingControlResponse,
    NavStateResponse,
    NavTaskExecuteResponse,
    NavTaskListResponse,
    NavTaskUpsertRequest,
    NavTaskStopResponse,
    NavWaypointGoToResponse,
    RosbagRecordingControlRequest,
    RosbagRecordingResponse,
)
from ...nav_bridge_state import get_ros_nav_bridge
from .nav_auto_track_helpers import (
    apply_auto_track_workflow_control as _apply_auto_track_workflow_control,
    cancel_pending_auto_track_resume as _cancel_pending_auto_track_resume,
    ensure_auto_track_enabled_for_navigation as _ensure_auto_track_enabled_for_navigation,
    release_navigation_control as _release_navigation_control,
    request_navigation_control as _request_navigation_control,
    task_has_auto_track_control as _task_has_auto_track_control,
)
from .nav_pcd_routes import (
    nav_create_waypoint,
    nav_delete_pcd_scene,
    nav_delete_waypoint,
    nav_get_pcd_metadata,
    nav_get_pcd_preview,
    nav_get_pcd_scene_metadata,
    nav_get_pcd_scene_preview,
    nav_list_pcd_maps,
    nav_list_pcd_scenes,
    nav_list_waypoints,
    nav_select_pcd_scene,
    router as pcd_router,
)

router = APIRouter(prefix="/api/v1/nav", tags=["nav"])
router.include_router(pcd_router)
_sensor_session_lock = asyncio.Lock()


class NavAutoTrackModeRequest(BaseModel):
    enabled: bool


def _clear_e_stop_for_localization_restart() -> dict[str, object]:
    """重启导航定位前解除所有会持续拦截运动指令的急停状态。"""
    from ...control_arbiter import get_control_arbiter
    from ...services_nav_localization import set_cmd_vel_estop
    from ...state_machine_state import get_state_machine
    from ...tracking_types import ControlOwner

    cmd_vel_estop = set_cmd_vel_estop(False, "nav_localization_restart")

    state_machine = get_state_machine()
    if state_machine is not None:
        state_machine.reset_emergency_stop()

    arbiter = get_control_arbiter()
    if arbiter is not None:
        arbiter.release_control(ControlOwner.E_STOP)

    return cmd_vel_estop


@router.get("/auto-track-mode")
async def nav_get_auto_track_mode(user: AuthUserInternal = Depends(require_operator)):
    from ...auto_track_service import get_auto_track_service

    auto_track = get_auto_track_service()
    auto_track_status = auto_track.get_status() if auto_track is not None else None
    enabled = bool(settings.NAV_AUTO_TRACK_DURING_NAV_ENABLED and settings.NAV_AUTO_TRACK_AUTO_ENABLE)
    return {
        "success": True,
        "enabled": enabled,
        "auto_track_enabled": bool(auto_track_status.get("enabled")) if auto_track_status else False,
        "auto_track_state": auto_track_status.get("state") if auto_track_status else None,
        "message": "导航自动跟踪已开启" if enabled else "导航自动跟踪已关闭",
    }


@router.post("/auto-track-mode")
async def nav_set_auto_track_mode(
    body: NavAutoTrackModeRequest,
    user: AuthUserInternal = Depends(require_operator),
    db=Depends(get_db),
):
    from ...auto_track_service import get_auto_track_service
    from ...control_arbiter import get_control_arbiter
    from ...guard_mission_service import get_guard_mission_service

    settings.NAV_AUTO_TRACK_DURING_NAV_ENABLED = bool(body.enabled)
    settings.NAV_AUTO_TRACK_AUTO_ENABLE = bool(body.enabled)
    try:
        from ...services_config import get_config_service

        config_service = get_config_service()
        value = "true" if body.enabled else "false"
        await config_service.update_config(
            db,
            "nav_auto_track_during_nav_enabled",
            value,
            changed_by=user.username,
            reason="nav_auto_track_mode_button",
        )
        await config_service.update_config(
            db,
            "nav_auto_track_auto_enable",
            value,
            changed_by=user.username,
            reason="nav_auto_track_mode_button",
        )
    except Exception:
        # 旧数据库未初始化新配置项时不阻断运行时开关，下一次启动会补齐默认项。
        pass

    auto_track = get_auto_track_service()
    if auto_track is not None:
        if body.enabled:
            arbiter = get_control_arbiter()
            if arbiter is not None:
                arbiter.release_manual_override()
            guard_mission = get_guard_mission_service()
            if guard_mission is not None and guard_mission.enabled:
                guard_mission.enabled = False
            if hasattr(auto_track, "enable_for_navigation"):
                auto_track.enable_for_navigation()
            else:
                auto_track.enable()
            if hasattr(auto_track, "resume"):
                auto_track.resume()
        elif not body.enabled:
            auto_track.disable()

    await safe_write_audit_log(
        db,
        level="INFO" if body.enabled else "WARN",
        module="BACKEND",
        message=(
            f"用户={user.username} 角色={user.role} 操作=nav.auto_track_mode "
            f"目标=nav 结果=success enabled={body.enabled}"
        ),
    )
    auto_track_status = auto_track.get_status() if auto_track is not None else None
    return {
        "success": True,
        "enabled": bool(body.enabled),
        "auto_track_enabled": bool(auto_track_status.get("enabled")) if auto_track_status else False,
        "auto_track_state": auto_track_status.get("state") if auto_track_status else None,
        "message": "导航自动跟踪已开启" if body.enabled else "导航自动跟踪已关闭",
    }


def _ensure_localization_ready_for_navigation() -> None:
    from ...services_nav_state import get_nav_state

    state = get_nav_state()
    pose = state.get("robot_pose")
    localization = state.get("localization_status") or {}
    if pose is None or localization.get("status") != "ok":
        message = localization.get("message") or "定位未就绪"
        raise HTTPException(status_code=409, detail=f"定位未就绪，禁止启动导航: {message}")


def _ensure_navigation_runtime_ready() -> None:
    from ...services_nav_localization import wait_navigation_runtime_ready

    try:
        wait_navigation_runtime_ready()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/tasks", response_model=NavTaskListResponse)
async def nav_list_tasks():
    from ...services_nav_tasks import NavTaskError, list_nav_tasks

    try:
        return list_nav_tasks()
    except NavTaskError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/tasks/{task_id}")
async def nav_upsert_task(
    task_id: str,
    body: NavTaskUpsertRequest,
    user: AuthUserInternal = Depends(require_operator),
    db=Depends(get_db),
):
    from ...services_nav_tasks import NavTaskError, save_nav_task

    if task_id != body.task.id:
        raise HTTPException(status_code=400, detail="路径 task_id 与请求体 task.id 不一致")

    try:
        result = save_nav_task(body.task.model_dump())
    except NavTaskError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await safe_write_audit_log(
        db,
        level="INFO",
        module="BACKEND",
        message=(
            f"用户={user.username} 角色={user.role} 操作=nav.task.upsert "
            f"目标={task_id} 结果=success"
        ),
    )
    return result


@router.post("/tasks/{task_id}/execute", response_model=NavTaskExecuteResponse)
async def nav_execute_task(
    task_id: str,
    user: AuthUserInternal = Depends(require_operator),
    db=Depends(get_db),
):
    from ...services_nav_state import update_navigation_status
    from ...services_nav_tasks import NavTaskError, get_nav_task
    from ...services_nav_task_runtime import materialize_nav_task_runtime
    from ...services_nav_localization import start_cmd_vel_script, stop_cmd_vel_script

    bridge = get_ros_nav_bridge()
    if bridge is None:
        raise HTTPException(status_code=503, detail="ROS2 导航桥未初始化")

    try:
        task = get_nav_task(task_id)
        runtime_result = materialize_nav_task_runtime(task_id)
        _ensure_localization_ready_for_navigation()
        _ensure_navigation_runtime_ready()
        cmd_vel_result = start_cmd_vel_script()
        auto_track_result = _ensure_auto_track_enabled_for_navigation(task)
        _request_navigation_control()
        try:
            nav_start_result = bridge.publish_navigation_start(True)
            task_start_result = bridge.publish_navigation_task_start(True)
        except RuntimeError:
            try:
                bridge.publish_navigation_start(False)
            except RuntimeError:
                pass
            stop_cmd_vel_script()
            _release_navigation_control()
            raise
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"导航点不存在: {exc}")
    except NavTaskError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    update_navigation_status(
        {
            "status": "navigating",
            "target_waypoint_id": None,
            "target_name": task.get("name"),
            "task_id": task_id,
            "message": "已发布导航启动信号并生成任务运行时文件",
        }
    )
    await safe_write_audit_log(
        db,
        level="INFO",
        module="BACKEND",
        message=(
            f"用户={user.username} 角色={user.role} 操作=nav.task.execute "
            f"目标={task_id} 结果=success topic={nav_start_result['topic']} "
            f"task_start_topic={task_start_result['topic']} "
            f"cmd_vel_pid={cmd_vel_result.get('pid')} "
            f"auto_track_requested={auto_track_result.get('requested')} "
            f"auto_track_enabled={auto_track_result.get('enabled')}"
        ),
    )
    return {
        "success": True,
        "task_id": task_id,
        "topic": nav_start_result["topic"],
        "data": nav_start_result["data"],
        "nav_start": nav_start_result,
        "task_start": task_start_result,
        "cmd_vel": cmd_vel_result,
        "message": "已发布导航启动信号并生成任务运行时文件",
        "runtime_file": runtime_result["runtime_file"],
        "runtime_task": runtime_result["runtime_task"],
        "auto_track": auto_track_result,
    }


@router.post("/tasks/{task_id}/stop", response_model=NavTaskStopResponse)
async def nav_stop_task(
    task_id: str,
    user: AuthUserInternal = Depends(require_operator),
    db=Depends(get_db),
):
    from ...services_nav_state import clear_global_path, update_navigation_status
    from ...services_nav_tasks import NavTaskError, get_nav_task
    from ...services_nav_localization import stop_cmd_vel_script

    bridge = get_ros_nav_bridge()
    if bridge is None:
        raise HTTPException(status_code=503, detail="ROS2 导航桥未初始化")

    try:
        task = get_nav_task(task_id)
        _cancel_pending_auto_track_resume("nav_task_stop")
        if _task_has_auto_track_control(task):
            _apply_auto_track_workflow_control(False)
        try:
            task_stop_result = bridge.publish_navigation_task_start(False)
        except RuntimeError:
            task_stop_result = None
        nav_stop_result = bridge.publish_navigation_start(False)
        cmd_vel_stop_result = stop_cmd_vel_script()
        _release_navigation_control()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except NavTaskError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    clear_global_path()
    update_navigation_status(
        {
            "status": "idle",
            "target_waypoint_id": None,
            "target_name": None,
            "task_id": None,
            "message": "已发布导航停止信号",
        }
    )
    await safe_write_audit_log(
        db,
        level="INFO",
        module="BACKEND",
        message=(
            f"用户={user.username} 角色={user.role} 操作=nav.task.stop "
            f"目标={task_id} 结果=success topic={nav_stop_result['topic']} "
            f"data={nav_stop_result['data']} cmd_vel_pid={cmd_vel_stop_result.get('pid')}"
        ),
    )
    return {
        "success": True,
        "task_id": task_id,
        "topic": nav_stop_result["topic"],
        "data": nav_stop_result["data"],
        "nav_start": nav_stop_result,
        "task_start": task_stop_result,
        "cmd_vel_stop": cmd_vel_stop_result,
        "message": "已发布导航停止信号",
    }


@router.delete("/tasks/{task_id}")
async def nav_delete_task(
    task_id: str,
    user: AuthUserInternal = Depends(require_operator),
    db=Depends(get_db),
):
    from ...services_nav_tasks import NavTaskError, delete_nav_task

    try:
        result = delete_nav_task(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except NavTaskError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await safe_write_audit_log(
        db,
        level="WARN",
        module="BACKEND",
        message=(
            f"用户={user.username} 角色={user.role} 操作=nav.task.delete "
            f"目标={task_id} 结果=success"
        ),
    )
    return result


@router.get("/state", response_model=NavStateResponse)
async def nav_get_state():
    from ...services_nav_state import get_nav_state

    return get_nav_state()


@router.post("/localization/set-pose", response_model=LocalizationPoseDTO)
async def nav_set_localization_pose(
    body: LocalizationPoseSetRequest,
    user: AuthUserInternal = Depends(require_operator),
    db=Depends(get_db),
):
    from ...services_nav_localization import inspect_relocation_initialization, save_localization_pose
    from ...services_nav_state import reset_localization_tracking, update_localization_status
    from ...services_pcd_maps import PcdMapError
    from ...lidar_mount import base_pose_to_lidar_initial_position

    bridge = get_ros_nav_bridge()
    if bridge is None:
        raise HTTPException(status_code=503, detail="ROS2 导航桥未初始化")

    try:
        reset_localization_tracking("已发送重定位请求，等待 TF 恢复")
        pose = save_localization_pose(body.model_dump())
        lidar_x, lidar_y, lidar_z = base_pose_to_lidar_initial_position(
            x=pose["x"],
            y=pose["y"],
            z=pose["z"],
            roll=pose["roll"],
            pitch=pose["pitch"],
            yaw=pose["yaw"],
        )
        initial_pose_result = bridge.publish_initial_pose(
            x=lidar_x,
            y=lidar_y,
            z=lidar_z,
            roll=pose["roll"],
            pitch=pose["pitch"],
            yaw=pose["yaw"],
            frame_id=pose["frame_id"],
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"场景不存在或缺少 ground.pcd: {body.map_id}")
    except (PcdMapError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    relocation_init = inspect_relocation_initialization(timeout_s=2.0)
    relocation_message = relocation_init["message"]
    message = (
        f"已发布 initial_pose: base_footprint="
        f"[{pose['x']:.3f}, {pose['y']:.3f}, {pose['z']:.3f}], "
        f"lidar=[{lidar_x:.3f}, {lidar_y:.3f}, {lidar_z:.3f}], "
        f"roll={pose['roll']:.3f}, pitch={pose['pitch']:.3f}, yaw={pose['yaw']:.3f}；"
        f"{relocation_message}"
    )

    update_localization_status(
        {
            "status": "initializing",
            "frame_id": pose["frame_id"],
            "source": initial_pose_result["topic"],
            "message": message,
        }
    )
    await safe_write_audit_log(
        db,
        level="INFO",
        module="BACKEND",
        message=(
            f"用户={user.username} 角色={user.role} 操作=nav.localization.set_pose "
            f"目标={body.map_id} 结果=success"
        ),
    )
    return pose


@router.post("/localization/restart", response_model=LocalizationRestartResponse)
async def nav_restart_localization(
    user: AuthUserInternal = Depends(require_operator),
    db=Depends(get_db),
):
    from ...services_nav_localization import restart_navigation_localization
    from ...services_nav_state import reset_localization_tracking, set_navigation_idle
    from ...services_nav_task_runtime import clear_nav_task_runtime
    from ...services_radar_health import check_livox_network_preflight

    try:
        # 先做无副作用的物理链路检查。雷达未连接时不能先清任务、解除急停
        # 或重置定位状态，否则一次失败的重启请求会破坏当前运行状态。
        radar_preflight = await asyncio.to_thread(check_livox_network_preflight)
        if not radar_preflight.get("ok"):
            raise RuntimeError(str(radar_preflight.get("message") or "雷达连接异常"))
        _cancel_pending_auto_track_resume("nav_localization_restart")
        cmd_vel_estop = _clear_e_stop_for_localization_restart()
        _release_navigation_control()
        clear_nav_task_runtime()
        set_navigation_idle("导航定位已重启，等待新目标")
        reset_localization_tracking("正在重启导航定位，等待 initialpose")
        result = await asyncio.to_thread(restart_navigation_localization)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    await safe_write_audit_log(
        db,
        level="INFO",
        module="BACKEND",
        message=(
            f"用户={user.username} 角色={user.role} 操作=nav.localization.restart "
            f"结果=success pid={result['pid']} "
            f"自动解除急停={not bool(cmd_vel_estop.get('active'))}"
        ),
    )
    return result


@router.get("/localization/initialpose-ready")
async def nav_wait_initialpose_ready(
    offset: int = 0,
    timeout_s: float = 45.0,
    user: AuthUserInternal = Depends(require_operator),
):
    from ...services_nav_localization import get_relocation_process_status, wait_for_initialpose_log

    bridge = get_ros_nav_bridge()
    if bridge is None:
        raise HTTPException(status_code=503, detail="ROS2 导航桥未初始化")

    timeout = min(max(timeout_s, 1.0), 90.0)
    result = await asyncio.to_thread(wait_for_initialpose_log, offset, timeout)
    if not result["ready"]:
        raise HTTPException(status_code=504, detail=result["message"])
    relocation_status = await asyncio.to_thread(get_relocation_process_status)
    result["relocation_pid"] = relocation_status["pid"]
    result["relocation_running"] = relocation_status["running"]
    if not relocation_status["running"]:
        raise HTTPException(status_code=503, detail=relocation_status["message"])
    try:
        subscriber_result = await asyncio.to_thread(
            bridge.wait_for_initial_pose_subscribers,
            min(max(timeout_s, 1.0), 10.0),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    if not subscriber_result["ready"]:
        raise HTTPException(status_code=504, detail=subscriber_result["message"])
    result["initialpose_subscriber_count"] = subscriber_result["subscriber_count"]
    result["initialpose_graph_subscriber_count"] = subscriber_result["graph_count"]
    result["initialpose_matched_subscriber_count"] = subscriber_result["matched_count"]
    result["initialpose_backend_publisher_count"] = subscriber_result.get("backend_publisher_count", 0)
    result["initialpose_topic"] = subscriber_result["topic"]
    result["message"] = f"{result['message']}；{subscriber_result['message']}"
    return result


@router.get("/localization/navigation-ready")
async def nav_wait_navigation_ready(
    timeout_s: float = 45.0,
    user: AuthUserInternal = Depends(require_operator),
):
    from ...services_nav_localization import wait_navigation_runtime_ready

    # 大场景首次构建 global planner 静态图时允许等待最多 10 分钟。
    timeout = min(max(timeout_s, 1.0), 600.0)
    try:
        result = await asyncio.to_thread(wait_navigation_runtime_ready, timeout, 0.5)
    except RuntimeError as exc:
        raise HTTPException(status_code=504, detail=str(exc))

    result["ready"] = True
    result["message"] = "导航控制链路已恢复，导航和任务可用"
    return result


@router.post("/mapping/set-enabled", response_model=MappingControlResponse)
async def nav_set_mapping_enabled(
    body: MappingControlRequest,
    user: AuthUserInternal = Depends(require_operator),
    db=Depends(get_db),
):
    async with _sensor_session_lock:
        return await _nav_set_mapping_enabled_locked(body, user, db)


async def _nav_set_mapping_enabled_locked(
    body: MappingControlRequest,
    user: AuthUserInternal,
    db,
):
    from ...services_mapping import MappingError, get_mapping_service
    from ...services_rosbag_recording import get_rosbag_recording_service

    mapping_service = get_mapping_service()
    recording_service = get_rosbag_recording_service()

    try:
        stopped_recording = await asyncio.to_thread(
            recording_service.stop_before_mapping_transition,
            reason="mapping_start" if body.enabled else "mapping_stop",
        )
        if body.enabled:
            if body.scene_name is None:
                raise MappingError("请输入场景名称")
            from ...services_radar_health import check_livox_network_preflight

            try:
                # 空闲状态下 Livox 驱动不会常驻，/livox/lidar 此时不存在是正常的。
                # 建图前只能做无驱动依赖的物理链路预检；真实点云由建图脚本
                # 启动驱动后再校验，不能在驱动启动前要求 topic 已存在。
                radar_health = await asyncio.to_thread(check_livox_network_preflight)
            except Exception as exc:
                raise MappingError(f"雷达健康检查失败，已阻止启动建图：{exc}") from exc
            if not radar_health["ok"]:
                raise MappingError(f"建图未启动：{radar_health['message']}")

            _cancel_pending_auto_track_resume("nav_mapping_start")
            _release_navigation_control()
            result = await asyncio.to_thread(mapping_service.start, body.scene_name)
            if stopped_recording is not None:
                result["message"] = f"已先停止录包；{result.get('message') or '建图已启动'}"
            await safe_write_audit_log(
                db,
                level="INFO",
                module="BACKEND",
                message=(
                    f"用户={user.username} 角色={user.role} 操作=nav.mapping.start "
                    f"场景={result['scene_name']} 目录={result['map_dir']} 结果=success pid={result['pid']}"
                ),
            )
            return result

        result = await asyncio.to_thread(mapping_service.stop, wait=False)
        if stopped_recording is not None:
            result["message"] = f"已先停止录包；{result.get('message') or '正在停止建图并保存地图'}"
        await safe_write_audit_log(
            db,
            level="INFO",
            module="BACKEND",
            message=(
                f"用户={user.username} 角色={user.role} 操作=nav.mapping.stop "
                f"场景={result['scene_name'] or '-'} 目录={result['map_dir'] or '-'} 结果=success"
            ),
        )
        return result
    except MappingError as exc:
        raise HTTPException(status_code=409 if "进行中" in str(exc) else 400, detail=str(exc))


@router.get("/mapping/status", response_model=MappingControlResponse)
async def nav_get_mapping_status(
    user: AuthUserInternal = Depends(require_operator),
):
    from ...services_mapping import get_mapping_service

    status = await asyncio.to_thread(get_mapping_service().get_status)
    running = bool(status.get("running"))
    saving = bool(status.get("saving"))
    return {
        "success": True,
        "enabled": running,
        "running": running,
        "saving": saving,
        "saved": bool(status.get("saved")),
        "scene_name": status.get("scene_name"),
        "map_dir": status.get("map_dir"),
        "pid": status.get("pid"),
        "started_at": status.get("started_at"),
        "map_pcd_candidates": status.get("map_pcd_candidates") or [],
        "ground_pcd_candidates": status.get("ground_pcd_candidates") or [],
        "pcd_files": status.get("pcd_files") or [],
        "origin_waypoint": status.get("origin_waypoint"),
        "origin_waypoint_error": status.get("origin_waypoint_error"),
        "message": status.get("message") or (
            "地图正在保存" if saving else "建图正在运行" if running else "建图未运行"
        ),
    }


@router.post("/rosbag/set-enabled", response_model=RosbagRecordingResponse)
async def nav_set_rosbag_recording_enabled(
    body: RosbagRecordingControlRequest,
    user: AuthUserInternal = Depends(require_operator),
    db=Depends(get_db),
):
    from ...services_mapping import get_mapping_service
    from ...services_rosbag_recording import RosbagRecordingError, get_rosbag_recording_service

    async with _sensor_session_lock:
        mapping_status = await asyncio.to_thread(get_mapping_service().get_status)
        mapping_running = bool(mapping_status.get("running"))
        mapping_saving = bool(mapping_status.get("saving"))
        recording_service = get_rosbag_recording_service()
        try:
            if body.enabled:
                if mapping_saving:
                    raise RosbagRecordingError("地图正在保存，暂不能开始录包")
                result = await asyncio.to_thread(recording_service.start, mapping_active=mapping_running)
                operation = "start"
            else:
                result = await asyncio.to_thread(recording_service.stop, reason="user")
                operation = "stop"
        except RosbagRecordingError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

        await safe_write_audit_log(
            db,
            level="INFO",
            module="BACKEND",
            message=(
                f"用户={user.username} 角色={user.role} 操作=nav.rosbag.{operation} "
                f"目录={result.get('output_dir') or '-'} 雷达模式={result.get('lidar_mode') or '-'} "
                f"结果=success"
            ),
        )
        return result


@router.get("/rosbag/status", response_model=RosbagRecordingResponse)
async def nav_get_rosbag_recording_status(
    user: AuthUserInternal = Depends(require_operator),
):
    from ...services_rosbag_recording import get_rosbag_recording_service

    del user
    return await asyncio.to_thread(get_rosbag_recording_service().get_status)


@router.post("/pcd-maps/{map_id}/waypoints/{waypoint_id}")
@router.post("/pcd-maps/{map_id}/waypoints/{waypoint_id}/go-to", response_model=NavWaypointGoToResponse)
async def nav_go_to_waypoint(
    map_id: str,
    waypoint_id: str,
    user: AuthUserInternal = Depends(require_operator),
    db=Depends(get_db),
):
    from ...control_service import get_control_service
    from ...services_nav_state import update_navigation_status
    from ...services_nav_waypoints import get_waypoint
    from ...services_pcd_maps import PcdMapError
    from ...services_nav_localization import start_cmd_vel_script, stop_cmd_vel_script

    bridge = get_ros_nav_bridge()
    if bridge is None:
        raise HTTPException(status_code=503, detail="ROS2 导航桥未初始化")

    try:
        waypoint = get_waypoint(map_id, waypoint_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"场景不存在或缺少 ground.pcd: {map_id}")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"导航点不存在: {waypoint_id}")
    except PcdMapError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        _ensure_localization_ready_for_navigation()
        _ensure_navigation_runtime_ready()
        try:
            stop_task_result = bridge.publish_navigation_task_start(False)
        except RuntimeError:
            stop_task_result = None
        stop_task_nav_result = bridge.publish_navigation_start(False)
        control_service = get_control_service()
        if control_service is None:
            raise RuntimeError("控制服务未就绪")
        motion_prepare_result = await control_service.prepare_navigation_motion()
        cmd_vel_result = start_cmd_vel_script()
        _request_navigation_control()
        try:
            goal_result = bridge.publish_goal_xyz_yaw(waypoint)
            nav_start_result = bridge.publish_navigation_start(True)
        except RuntimeError:
            stop_cmd_vel_script()
            _release_navigation_control()
            raise
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    await safe_write_audit_log(
        db,
        level="INFO",
        module="BACKEND",
        message=(
            f"用户={user.username} 角色={user.role} 操作=nav.go_to "
            f"目标={waypoint_id} map={map_id} 结果=success "
            f"clicked_point_topic={goal_result['xyz_topic']} yaw_topic={goal_result['yaw_topic']} "
            f"stop_task_nav_topic={stop_task_nav_result['topic']} "
            f"stop_task_topic={stop_task_result['topic'] if stop_task_result else 'unavailable'} "
            f"nav_start={nav_start_result['data']} cmd_vel_pid={cmd_vel_result.get('pid')}"
        ),
    )
    update_navigation_status(
        {
            "status": "navigating",
            "target_waypoint_id": waypoint["id"],
            "target_name": waypoint["name"],
            "message": (
                f"已发布 clicked_point 和 goal_yaw: {waypoint['name']} "
                f"x={float(waypoint['x']):.3f}, "
                f"y={float(waypoint['y']):.3f}, "
                f"z={float(waypoint.get('z', 0.0)):.3f}, "
                f"yaw={float(waypoint.get('yaw', 0.0)):.3f}"
            ),
        }
    )
    return {
        "success": True,
        "topic": goal_result["xyz_topic"],
        "waypoint_id": waypoint["id"],
        "xyz_topic": goal_result["xyz_topic"],
        "yaw_topic": goal_result["yaw_topic"],
        "goal": goal_result,
        "stop_task_nav": stop_task_nav_result,
        "stop_task": stop_task_result,
        "nav_start": nav_start_result,
        "cmd_vel": cmd_vel_result,
        "motion_prepare": motion_prepare_result,
        "message": "已发布 clicked_point 和 goal_yaw",
    }


@router.post("/e-stop")
async def nav_emergency_stop(
    user: AuthUserInternal = Depends(require_operator),
    db=Depends(get_db),
):
    from ...control_service import get_control_service
    from ...services_nav_localization import set_cmd_vel_estop
    from ...services_nav_state import clear_global_path, set_navigation_idle
    control_service = get_control_service()

    try:
        _cancel_pending_auto_track_resume("nav_e_stop")
        cmd_vel_estop_result = set_cmd_vel_estop(True, "nav_e_stop")
        cmd_vel_zero_result = None
        bridge = get_ros_nav_bridge()
        if bridge is not None:
            try:
                try:
                    bridge.publish_navigation_task_start(False)
                except RuntimeError:
                    pass
                bridge.publish_navigation_start(False)
                cmd_vel_zero_result = bridge.publish_zero_cmd_vel(publish_count=20, interval_s=0.02)
            except RuntimeError as exc:
                cmd_vel_zero_result = {
                    "success": False,
                    "message": str(exc),
                }
        control_zero_sent = None
        if control_service is not None:
            control_zero_sent = await control_service.send_navigation_velocity(0.0, 0.0, 0.0)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    clear_global_path()
    set_navigation_idle("导航已软停：速度已归零，导航定位进程保持运行")
    await safe_write_audit_log(
        db,
        level="WARN",
        module="BACKEND",
        message=(
            f"用户={user.username} 角色={user.role} 操作=nav.e_stop 目标=nav 结果=success "
            f"soft_stop=true control_zero_sent={control_zero_sent} "
            f"cmd_vel_estop={cmd_vel_estop_result.get('active') if isinstance(cmd_vel_estop_result, dict) else 'N/A'} "
            "navigation_processes_preserved=true"
        ),
    )
    return {
        "success": True,
        "message": "导航已软停：全速度为 0，导航定位进程保持运行",
        "topic": cmd_vel_zero_result.get("topic") if isinstance(cmd_vel_zero_result, dict) else None,
        "control_zero": {
            "sent": control_zero_sent,
            "linear": {"x": 0.0, "y": 0.0, "z": 0.0},
            "angular": {"x": 0.0, "y": 0.0, "z": 0.0},
        },
        "cmd_vel_estop": cmd_vel_estop_result,
        "cmd_vel_zero": cmd_vel_zero_result,
        "navigation_processes_preserved": True,
    }
