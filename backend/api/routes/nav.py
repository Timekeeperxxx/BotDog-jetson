"""导航巡逻 / PCD 点云地图路由。

从 backend/main.py 拆分出的 /api/v1/nav/* 接口，
路径、response_model、请求参数、返回字段与原始实现完全一致。
"""

from fastapi import APIRouter, HTTPException

from ...schemas import (
    DeleteWaypointResponse,
    LocalizationPoseDTO,
    LocalizationPoseSetRequest,
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
async def nav_set_localization_pose(body: LocalizationPoseSetRequest):
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
    return pose


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
async def nav_create_waypoint(map_id: str, body: NavWaypointCreateRequest):
    from ...services_nav_waypoints import create_waypoint
    from ...services_pcd_maps import PcdMapError

    try:
        return create_waypoint(map_id, body.model_dump())
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"PCD 文件不存在: {map_id}")
    except (PcdMapError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/pcd-maps/{map_id}/waypoints/{waypoint_id}")
@router.post("/pcd-maps/{map_id}/waypoints/{waypoint_id}/go-to")
async def nav_go_to_waypoint(map_id: str, waypoint_id: str):
    from ...services_nav_state import update_navigation_status
    from ...services_nav_waypoints import get_waypoint
    from ...services_pcd_maps import PcdMapError

    bridge = get_ros_nav_bridge()
    if bridge is None:
        raise HTTPException(status_code=503, detail="ROS2 导航桥未初始化")

    try:
        waypoint = get_waypoint(map_id, waypoint_id)
        start_result = bridge.publish_navigation_start()
        result = bridge.publish_navigation_goal(waypoint)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"PCD 文件不存在: {map_id}")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"导航点不存在: {waypoint_id}")
    except PcdMapError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    update_navigation_status(
        {
            "status": "navigating",
            "target_waypoint_id": waypoint["id"],
            "target_name": waypoint["name"],
            "message": f"已发布导航开始信号并发送目标: {waypoint['name']}",
        }
    )
    return {
        "success": True,
        "topic": result["topic"],
        "waypoint_id": result["waypoint_id"],
        "start": start_result,
        "goal": result,
    }


@router.post("/e-stop")
async def nav_emergency_stop():
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
    return result


@router.delete(
    "/pcd-maps/{map_id}/waypoints/{waypoint_id}",
    response_model=DeleteWaypointResponse,
)
async def nav_delete_waypoint(map_id: str, waypoint_id: str):
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

    return {"success": True}
