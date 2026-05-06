"""导航巡逻 / PCD 点云地图路由。

从 backend/main.py 拆分出的 /api/v1/nav/* 接口，
路径、response_model、请求参数、返回字段与原始实现完全一致。
"""

from fastapi import APIRouter, Depends, HTTPException

from ...auth.dependencies import require_admin, require_operator
from ...auth.schemas import AuthUser
from ...auth.service import safe_write_audit_log
from ...config import settings
from ...database import get_db
from ...logging_config import get_logger
from ...schemas import (
    DeleteWaypointResponse,
    LocalizationPoseDTO,
    LocalizationPoseSetRequest,
    MappingControlRequest,
    MappingControlResponse,
    NavWaypointCreateRequest,
    NavWaypointDTO,
    NavWaypointListResponse,
    NavStateResponse,
    PcdMapListResponse,
    PcdMetadataResponse,
    PcdPreviewResponse,
)
from ...nav_bridge_state import get_ros_nav_bridge

router = APIRouter(prefix="/api/v1/nav", tags=["nav"])
nav_logger = get_logger("导航巡逻")


@router.get("/pcd-maps", response_model=PcdMapListResponse)
async def nav_list_pcd_maps():
    from ...services_pcd_maps import PcdMapError, list_pcd_maps

    try:
        return list_pcd_maps()
    except PcdMapError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/state", response_model=NavStateResponse)
async def nav_get_state():
    from ...services_nav_state import get_nav_state

    return get_nav_state()


@router.get("/current-goal")
async def nav_get_current_goal():
    from ...services_nav_runtime import read_current_goal

    try:
        return {"current_goal": read_current_goal()}
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


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
    user: AuthUser = Depends(require_operator),
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
        raise HTTPException(status_code=404, detail=f"PCD 文件不存在: {body.map_id}")
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


@router.post("/mapping/set-enabled", response_model=MappingControlResponse)
async def nav_set_mapping_enabled(
    body: MappingControlRequest,
    user: AuthUser = Depends(require_operator),
    db=Depends(get_db),
):
    bridge = get_ros_nav_bridge()
    if bridge is None:
        raise HTTPException(status_code=503, detail="ROS2 导航桥未初始化")

    try:
        result = bridge.publish_mapping_enabled(body.enabled)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    await safe_write_audit_log(
        db,
        level="INFO",
        module="BACKEND",
        message=(
            f"用户={user.username} 角色={user.role} 操作=nav.mapping.set_enabled "
            f"目标={result['topic']} 结果=success enabled={body.enabled}"
        ),
    )
    return result


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


@router.get("/pcd-maps/{map_id}/waypoints", response_model=NavWaypointListResponse)
async def nav_list_waypoints(map_id: str):
    from ...services_pcd_maps import PcdMapError
    from ...services_nav_waypoints import list_waypoints

    try:
        return list_waypoints(map_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"PCD 文件不存在: {map_id}")
    except PcdMapError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/pcd-maps/{map_id}/waypoints", response_model=NavWaypointDTO)
async def nav_create_waypoint(
    map_id: str,
    body: NavWaypointCreateRequest,
    user: AuthUser = Depends(require_operator),
    db=Depends(get_db),
):
    from ...services_nav_waypoints import create_waypoint
    from ...services_pcd_maps import PcdMapError

    try:
        waypoint = create_waypoint(map_id, body.model_dump())
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"PCD 文件不存在: {map_id}")
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
    user: AuthUser = Depends(require_operator),
    db=Depends(get_db),
):
    from ...services_nav_runtime import write_current_goal
    from ...services_nav_state import update_navigation_status
    from ...services_nav_waypoints import get_waypoint
    from ...services_pcd_maps import PcdMapError

    bridge = get_ros_nav_bridge()
    if bridge is None:
        raise HTTPException(status_code=503, detail="ROS2 导航桥未初始化")

    try:
        waypoint = get_waypoint(map_id, waypoint_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"PCD 文件不存在: {map_id}")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"导航点不存在: {waypoint_id}")
    except PcdMapError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        current_goal = write_current_goal(waypoint)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"写入 current_goal.json 失败: {exc}")

    try:
        start_result = bridge.publish_navigation_start()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    goal_pose_compat = {
        "enabled": True,
        "success": True,
        "topic": settings.ROS_NAV_GOAL_TOPIC,
        "result": None,
        "error": None,
    }
    try:
        result = bridge.publish_navigation_goal(waypoint)
        goal_pose_compat = {
            "enabled": True,
            "success": True,
            "topic": result["topic"],
            "result": result,
            "error": None,
        }
    except RuntimeError as exc:
        nav_logger.warning("兼容 /goal_pose 发布失败，但主导航启动已成功：waypoint_id={}，原因={}", waypoint["id"], exc)
        goal_pose_compat = {
            "enabled": True,
            "success": False,
            "topic": settings.ROS_NAV_GOAL_TOPIC,
            "result": None,
            "error": str(exc),
        }

    await safe_write_audit_log(
        db,
        level="INFO" if goal_pose_compat["success"] else "WARN",
        module="BACKEND",
        message=(
            f"用户={user.username} 角色={user.role} 操作=nav.go_to "
            f"目标={waypoint_id} map={map_id} 结果=success "
            f"goal_pose_compat={goal_pose_compat['success']}"
        ),
    )
    update_navigation_status(
        {
            "status": "navigating",
            "target_waypoint_id": waypoint["id"],
            "target_name": waypoint["name"],
            "message": (
                f"已发布导航开始信号并写入当前目标: {waypoint['name']}"
                if not goal_pose_compat["success"]
                else f"已发布导航开始信号并发送目标: {waypoint['name']}"
            ),
        }
    )
    return {
        "success": True,
        "current_goal": current_goal,
        "topic": settings.ROS_NAV_GOAL_TOPIC,
        "waypoint_id": waypoint["id"],
        "start": start_result,
        "goal_pose_compat": goal_pose_compat,
    }


@router.post("/e-stop")
async def nav_emergency_stop(
    user: AuthUser = Depends(require_operator),
    db=Depends(get_db),
):
    from ...services_nav_state import update_navigation_status

    bridge = get_ros_nav_bridge()
    if bridge is None:
        raise HTTPException(status_code=503, detail="ROS2 导航桥未初始化")

    try:
        result = bridge.publish_emergency_stop()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    update_navigation_status(
        {
            "status": "cancelled",
            "target_waypoint_id": None,
            "target_name": None,
            "message": "已发布导航急停",
        }
    )
    await safe_write_audit_log(
        db,
        level="WARN",
        module="BACKEND",
        message=f"用户={user.username} 角色={user.role} 操作=nav.e_stop 目标=nav 结果=success",
    )
    return result


@router.delete(
    "/pcd-maps/{map_id}/waypoints/{waypoint_id}",
    response_model=DeleteWaypointResponse,
)
async def nav_delete_waypoint(
    map_id: str,
    waypoint_id: str,
    user: AuthUser = Depends(require_admin),
    db=Depends(get_db),
):
    from ...services_nav_waypoints import delete_waypoint
    from ...services_pcd_maps import PcdMapError

    try:
        ok = delete_waypoint(map_id, waypoint_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"PCD 文件不存在: {map_id}")
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
