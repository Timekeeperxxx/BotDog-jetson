from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from ...auth.dependencies import require_admin, require_operator
from ...auth.schemas import AuthUserInternal
from ...auth.service import safe_write_audit_log
from ...database import get_db
from ...schemas import (
    DeleteWaypointResponse,
    NavCurrentSceneResponse,
    NavWaypointCreateRequest,
    NavWaypointDTO,
    NavWaypointListResponse,
    PcdMapListResponse,
    PcdMetadataResponse,
    PcdPreviewResponse,
    PcdSceneDeleteResponse,
    PcdSceneListResponse,
    PcdSceneMetadataResponse,
    PcdScenePreviewResponse,
)

from .nav_auto_track_helpers import cancel_pending_auto_track_resume

router = APIRouter()


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
    from ...services_nav_state import reset_localization_tracking
    from ...services_nav_task_runtime import clear_nav_task_runtime
    from ...services_pcd_maps import PcdMapError, find_scene_pcd_files, resolve_scene_path

    try:
        scene_path = resolve_scene_path(scene_id)
        files = find_scene_pcd_files(scene_path)
        if files["wall"] is None:
            raise HTTPException(status_code=400, detail="场景缺少 map.pcd")
        if files["ground"] is None:
            raise HTTPException(status_code=400, detail="场景缺少 ground.pcd")
        result = save_current_scene(scene_id)
        cancel_pending_auto_track_resume("nav_scene_select")
        clear_nav_task_runtime()
        reset_localization_tracking(f"已切换场景 {scene_id}，等待重新定位")
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


@router.get("/pcd-scenes/{scene_id}/preview.bin", response_class=Response)
async def nav_get_pcd_scene_preview_binary(scene_id: str, max_points: int | None = None):
    from ...services_pcd_maps import PcdMapError, get_scene_preview_binary

    try:
        payload = get_scene_preview_binary(scene_id, max_points=max_points)
        return Response(
            content=payload,
            media_type="application/vnd.botdog.pointcloud",
            # Float32 点云已经很紧凑，避免 GZip 中间件再次消耗 CPU。
            headers={"Content-Encoding": "identity"},
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"场景目录不存在: {scene_id}")
    except PcdMapError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/pcd-maps/{map_id}/waypoints", response_model=NavWaypointListResponse)
async def nav_list_waypoints(map_id: str):
    from ...services_nav_waypoints import list_waypoints
    from ...services_pcd_maps import PcdMapError

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
