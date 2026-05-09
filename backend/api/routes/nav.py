"""导航巡逻 / PCD 点云地图路由。

从 backend/main.py 拆分出的 /api/v1/nav/* 接口，
路径、response_model、请求参数、返回字段与原始实现完全一致。
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from ...auth.dependencies import require_admin, require_operator
from ...auth.schemas import AuthUserInternal
from ...auth.service import safe_write_audit_log
from ...database import get_db
from ...schemas import (
    DeleteWaypointResponse,
    LocalizationPoseDTO,
    LocalizationPoseSetRequest,
    LocalizationRestartResponse,
    MappingControlRequest,
    MappingControlResponse,
    NavWaypointCreateRequest,
    NavWaypointDTO,
    NavWaypointListResponse,
    NavStateResponse,
    PcdMapListResponse,
    PcdMetadataResponse,
    PcdPreviewResponse,
    PcdSceneDeleteResponse,
    PcdSceneListResponse,
    PcdSceneMetadataResponse,
    PcdScenePreviewResponse,
    NavCurrentSceneResponse,
    NavTaskListResponse,
    NavTaskUpsertRequest,
)
from ...nav_bridge_state import get_ros_nav_bridge

router = APIRouter(prefix="/api/v1/nav", tags=["nav"])


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


@router.get("/pcd-maps", response_model=PcdMapListResponse)
async def nav_list_pcd_maps():
    from ...services_pcd_maps import PcdMapError, list_pcd_maps

    try:
        return list_pcd_maps()
    except PcdMapError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/pcd-scenes", response_model=PcdSceneListResponse)
async def nav_list_pcd_scenes():
    from ...services_pcd_maps import PcdMapError, list_pcd_scenes

    try:
        return list_pcd_scenes()
    except PcdMapError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/pcd-scenes/{scene_id}", response_model=PcdSceneDeleteResponse)
async def nav_delete_pcd_scene(
    scene_id: str,
    user: AuthUserInternal = Depends(require_admin),
    db=Depends(get_db),
):
    from ...services_pcd_maps import PcdMapError, delete_pcd_scene

    try:
        result = delete_pcd_scene(scene_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"场景目录不存在: {scene_id}")
    except PcdMapError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await safe_write_audit_log(
        db,
        level="WARN",
        module="BACKEND",
        message=(
            f"用户={user.username} 角色={user.role} 操作=nav.scene.delete "
            f"目标={scene_id} 路径={result['deleted_path']} 结果=success"
        ),
    )
    return result


@router.post("/pcd-scenes/{scene_id}/select", response_model=NavCurrentSceneResponse)
async def nav_select_pcd_scene(
    scene_id: str,
    user: AuthUserInternal = Depends(require_operator),
    db=Depends(get_db),
):
    from ...services_nav_localization import save_current_scene
    from ...services_pcd_maps import PcdMapError, find_scene_pcd_files, resolve_scene_path

    try:
        scene_path = resolve_scene_path(scene_id)
        files = find_scene_pcd_files(scene_path)
        if files["wall"] is None:
            raise HTTPException(status_code=400, detail="场景缺少 map.pcd")
        if files["ground"] is None:
            raise HTTPException(status_code=400, detail="场景缺少 ground.pcd")
        result = save_current_scene(scene_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PcdMapError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await safe_write_audit_log(
        db,
        level="INFO",
        module="BACKEND",
        message=(
            f"用户={user.username} 角色={user.role} 操作=nav.scene.select "
            f"目标={scene_id} 路径={scene_path} 结果=success"
        ),
    )
    return result


@router.get("/state", response_model=NavStateResponse)
async def nav_get_state():
    from ...services_nav_state import get_nav_state

    return get_nav_state()


@router.post("/page-open")
async def nav_page_open():
    bridge = get_ros_nav_bridge()
    if bridge is None:
        raise HTTPException(status_code=503, detail="ROS2 导航桥未初始化")

    try:
        return bridge.publish_navigation_page_open()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.post("/localization/set-pose", response_model=LocalizationPoseDTO)
async def nav_set_localization_pose(
    body: LocalizationPoseSetRequest,
    user: AuthUserInternal = Depends(require_operator),
    db=Depends(get_db),
):
    from ...services_nav_localization import save_localization_pose
    from ...services_nav_state import update_localization_status
    from ...services_pcd_maps import PcdMapError

    bridge = get_ros_nav_bridge()
    if bridge is None:
        raise HTTPException(status_code=503, detail="ROS2 导航桥未初始化")

    try:
        pose = save_localization_pose(body.model_dump())
        result = bridge.publish_set_pose()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"场景不存在或缺少 ground.pcd: {body.map_id}")
    except (PcdMapError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    update_localization_status(
        {
            "status": "initializing",
            "frame_id": pose["frame_id"],
            "source": result["topic"],
            "message": (
                f"已保存重定位位姿并发布重定位信号: "
                f"x={pose['x']:.3f}, y={pose['y']:.3f}, yaw={pose['yaw']:.3f}"
            ),
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

    try:
        result = restart_navigation_localization()
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
            f"结果=success pid={result['pid']}"
        ),
    )
    return result


@router.post("/mapping/set-enabled", response_model=MappingControlResponse)
async def nav_set_mapping_enabled(
    body: MappingControlRequest,
    user: AuthUserInternal = Depends(require_operator),
    db=Depends(get_db),
):
    from ...services_mapping import MappingError, get_mapping_service

    mapping_service = get_mapping_service()

    try:
        if body.enabled:
            if body.scene_name is None:
                raise MappingError("请输入场景名称")
            result = await asyncio.to_thread(mapping_service.start, body.scene_name)
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

        result = await asyncio.to_thread(mapping_service.stop)
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


@router.get("/pcd-maps/{map_id}/metadata", response_model=PcdMetadataResponse)
async def nav_get_pcd_metadata(map_id: str):
    from ...services_pcd_maps import PcdMapError, get_pcd_metadata

    try:
        return get_pcd_metadata(map_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"PCD 文件不存在: {map_id}")
    except PcdMapError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/pcd-maps/{map_id}/preview", response_model=PcdPreviewResponse)
async def nav_get_pcd_preview(map_id: str, max_points: int | None = None):
    from ...services_pcd_maps import PcdMapError, get_pcd_preview

    try:
        return get_pcd_preview(map_id, max_points=max_points)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"PCD 文件不存在: {map_id}")
    except PcdMapError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/pcd-scenes/{scene_id}/metadata", response_model=PcdSceneMetadataResponse)
async def nav_get_pcd_scene_metadata(scene_id: str):
    from ...services_pcd_maps import PcdMapError, get_scene_metadata

    try:
        return get_scene_metadata(scene_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"场景目录不存在: {scene_id}")
    except PcdMapError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/pcd-scenes/{scene_id}/preview", response_model=PcdScenePreviewResponse)
async def nav_get_pcd_scene_preview(scene_id: str, max_points: int | None = None):
    from ...services_pcd_maps import PcdMapError, get_scene_preview

    try:
        return get_scene_preview(scene_id, max_points=max_points)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"场景目录不存在: {scene_id}")
    except PcdMapError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/pcd-maps/{map_id}/waypoints", response_model=NavWaypointListResponse)
async def nav_list_waypoints(map_id: str):
    from ...services_pcd_maps import PcdMapError
    from ...services_nav_waypoints import list_waypoints

    try:
        return list_waypoints(map_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"场景不存在或缺少 ground.pcd: {map_id}")
    except PcdMapError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/pcd-maps/{map_id}/waypoints", response_model=NavWaypointDTO)
async def nav_create_waypoint(
    map_id: str,
    body: NavWaypointCreateRequest,
    user: AuthUserInternal = Depends(require_operator),
    db=Depends(get_db),
):
    from ...services_nav_waypoints import create_waypoint
    from ...services_pcd_maps import PcdMapError

    try:
        waypoint = create_waypoint(map_id, body.model_dump())
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"场景不存在或缺少 ground.pcd: {map_id}")
    except (PcdMapError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await safe_write_audit_log(
        db,
        level="INFO",
        module="BACKEND",
        message=(
            f"用户={user.username} 角色={user.role} 操作=nav.waypoint.create "
            f"目标={waypoint['id']} map={map_id} 结果=success"
        ),
    )
    return waypoint


@router.post("/pcd-maps/{map_id}/waypoints/{waypoint_id}")
@router.post("/pcd-maps/{map_id}/waypoints/{waypoint_id}/go-to")
async def nav_go_to_waypoint(
    map_id: str,
    waypoint_id: str,
    user: AuthUserInternal = Depends(require_operator),
    db=Depends(get_db),
):
    from ...services_nav_state import update_navigation_status
    from ...services_nav_waypoints import get_waypoint
    from ...services_pcd_maps import PcdMapError

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
        nav_start_result = bridge.publish_navigation_start()
        goal_result = bridge.publish_goal_xyz_yaw(waypoint)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    await safe_write_audit_log(
        db,
        level="INFO",
        module="BACKEND",
        message=(
            f"用户={user.username} 角色={user.role} 操作=nav.go_to "
            f"目标={waypoint_id} map={map_id} 结果=success "
            f"nav_start_topic={nav_start_result['topic']} "
            f"clicked_point_topic={goal_result['xyz_topic']} yaw_topic={goal_result['yaw_topic']}"
        ),
    )
    update_navigation_status(
        {
            "status": "navigating",
            "target_waypoint_id": waypoint["id"],
            "target_name": waypoint["name"],
            "message": (
                f"已发布 nav_start，随后发布 clicked_point 和 goal_yaw: {waypoint['name']} "
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
        "nav_start_topic": nav_start_result["topic"],
        "xyz_topic": goal_result["xyz_topic"],
        "yaw_topic": goal_result["yaw_topic"],
        "nav_start": nav_start_result,
        "goal": goal_result,
    }


@router.post("/e-stop")
async def nav_emergency_stop(
    user: AuthUserInternal = Depends(require_operator),
    db=Depends(get_db),
):
    from ...control_service import get_control_service
    from ...services_nav_localization import stop_navigation_processes
    from ...services_nav_state import clear_global_path, set_navigation_idle
    control_service = get_control_service()

    try:
        control_result = None
        if control_service is not None:
            control_result = await control_service.force_stop()

        nav_result = stop_navigation_processes()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    clear_global_path()
    set_navigation_idle("已触发导航急停")
    await safe_write_audit_log(
        db,
        level="WARN",
        module="BACKEND",
        message=(
            f"用户={user.username} 角色={user.role} 操作=nav.e_stop 目标=nav 结果=success "
            f"control_result={getattr(control_result, 'result', 'N/A')} "
            f"nav_pids={nav_result.get('pids') if isinstance(nav_result, dict) else 'N/A'}"
        ),
    )
    return {
        "success": True,
        "message": "已触发导航急停",
        "topic": None,
        "control_stop": {
            "result": getattr(control_result, "result", None),
            "ack_cmd": getattr(control_result, "ack_cmd", None),
        } if control_result is not None else None,
        "nav_stop": nav_result,
    }


@router.delete(
    "/pcd-maps/{map_id}/waypoints/{waypoint_id}",
    response_model=DeleteWaypointResponse,
)
async def nav_delete_waypoint(
    map_id: str,
    waypoint_id: str,
    user: AuthUserInternal = Depends(require_admin),
    db=Depends(get_db),
):
    from ...services_nav_waypoints import delete_waypoint
    from ...services_pcd_maps import PcdMapError

    try:
        ok = delete_waypoint(map_id, waypoint_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"场景不存在或缺少 ground.pcd: {map_id}")
    except PcdMapError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not ok:
        raise HTTPException(status_code=404, detail=f"导航点不存在: {waypoint_id}")

    await safe_write_audit_log(
        db,
        level="WARN",
        module="BACKEND",
        message=(
            f"用户={user.username} 角色={user.role} 操作=nav.waypoint.delete "
            f"目标={waypoint_id} map={map_id} 结果=success"
        ),
    )
    return {"success": True}
