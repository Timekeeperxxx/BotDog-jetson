from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Response, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from ...auth.dependencies import require_admin, require_operator
from ...auth.schemas import AuthUserInternal
from ...auth.service import safe_write_audit_log
from ...database import get_db
from ...schemas import (
    DeleteWaypointResponse,
    NavFenceCreateRequest,
    NavFenceDTO,
    NavFenceEnabledRequest,
    NavFenceListResponse,
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
    from ...services_nav_localization import load_current_scene, save_current_scene
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
        try:
            previous_scene = load_current_scene(strict=False)
        except (FileNotFoundError, ValueError):
            previous_scene = {}
        result = save_current_scene(scene_id)
        if previous_scene.get("scene_id") != scene_id:
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
    from ...services_pcd_maps import PcdMapError, prepare_scene_preview_binary

    try:
        # Full-resolution scenes can take noticeable CPU and memory bandwidth;
        # keep the main asyncio loop responsive for robot pose/path WebSockets.
        cache_path = await asyncio.to_thread(
            prepare_scene_preview_binary,
            scene_id,
            max_points=max_points,
        )
        return FileResponse(
            path=cache_path,
            media_type="application/vnd.botdog.pointcloud",
            # Float32 已经紧凑；允许 ETag 重验证但避免旧场景长期驻留。
            headers={
                "Content-Encoding": "identity",
                "Cache-Control": "no-cache",
            },
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"场景目录不存在: {scene_id}")
    except PcdMapError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/pcd-scenes/{scene_id}/potree/manifest")
async def nav_get_potree_manifest(scene_id: str):
    from ...pcd_potree import request_scene
    from ...pcd_errors import PcdMapError
    try:
        result = await asyncio.to_thread(request_scene, scene_id)
        if result.get("status") == "error":
            raise HTTPException(status_code=500, detail=result["message"])
        return JSONResponse(result, status_code=202 if "status" in result else 200,
                            headers={"Cache-Control": "no-store"})
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PcdMapError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/pcd-scenes/{scene_id}/potree/{cache_key}/{role}/{filename}")
async def nav_get_potree_asset(scene_id: str, cache_key: str, role: str, filename: str, request: Request):
    from ...pcd_potree import resolve_asset
    from ...pcd_errors import PcdMapError
    import re
    try:
        path = await asyncio.to_thread(resolve_asset, scene_id, cache_key, role, filename)
    except (FileNotFoundError, PcdMapError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    size = path.stat().st_size
    headers = {"Accept-Ranges": "bytes", "Content-Encoding": "identity",
               "Cache-Control": "public, max-age=31536000, immutable"}
    media_type = "application/json" if filename.endswith(".json") else "application/octet-stream"
    range_header = request.headers.get("range")
    if not range_header:
        return FileResponse(path, media_type=media_type, headers=headers)
    match = re.fullmatch(r"bytes=(\d+)-(\d*)", range_header)
    if not match:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
    start = int(match[1])
    end = min(int(match[2]) if match[2] else size - 1, size - 1)
    if start > end or start >= size:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
    headers.update({"Content-Range": f"bytes {start}-{end}/{size}", "Content-Length": str(end - start + 1)})
    def content():
        with path.open("rb") as stream:
            stream.seek(start)
            remaining = end - start + 1
            while remaining:
                data = stream.read(min(remaining, 1024 * 1024))
                if not data:
                    break
                remaining -= len(data)
                yield data
    return StreamingResponse(content(), status_code=206, headers=headers, media_type=media_type)


@router.get("/pcd-scenes/{scene_id}/tiles/manifest")
async def nav_get_pcd_scene_tile_manifest(scene_id: str):
    from ...pcd_tiles import prepare_scene_tile_manifest
    from ...services_pcd_maps import PcdMapError

    try:
        manifest_path = await asyncio.to_thread(prepare_scene_tile_manifest, scene_id)
        return FileResponse(
            path=manifest_path,
            media_type="application/json",
            headers={"Cache-Control": "no-cache"},
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PcdMapError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/pcd-scenes/{scene_id}/tiles/{tile_file}")
async def nav_get_pcd_scene_tile(scene_id: str, tile_file: str):
    from ...pcd_tiles import resolve_scene_tile_file
    from ...services_pcd_maps import PcdMapError

    try:
        tile_path = await asyncio.to_thread(resolve_scene_tile_file, scene_id, tile_file)
        return FileResponse(
            path=tile_path,
            media_type="application/vnd.botdog.pointcloud-tile",
            headers={
                "Content-Encoding": "identity",
                "Cache-Control": "public, max-age=31536000, immutable",
            },
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
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


@router.get("/pcd-maps/{map_id}/fences", response_model=NavFenceListResponse)
async def nav_list_fences(map_id: str):
    from ...services_nav_fences import list_fences
    from ...services_pcd_maps import PcdMapError

    try:
        return list_fences(map_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"场景不存在或缺少 ground.pcd: {map_id}")
    except PcdMapError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/pcd-maps/{map_id}/fences", response_model=NavFenceDTO)
async def nav_create_fence(
    map_id: str,
    body: NavFenceCreateRequest,
    user: AuthUserInternal = Depends(require_operator),
    db=Depends(get_db),
):
    from ...services_nav_fences import create_fence
    from ...services_pcd_maps import PcdMapError

    try:
        fence = create_fence(map_id, body.model_dump())
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"场景不存在或缺少 ground.pcd: {map_id}")
    except (PcdMapError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await safe_write_audit_log(
        db,
        level="INFO",
        module="BACKEND",
        message=(
            f"用户={user.username} 角色={user.role} 操作=nav.fence.create "
            f"目标={fence['id']} scene={map_id} 结果=success"
        ),
    )
    return fence


@router.put("/pcd-maps/{map_id}/fences/{fence_id}", response_model=NavFenceDTO)
async def nav_set_fence_enabled(
    map_id: str,
    fence_id: str,
    body: NavFenceEnabledRequest,
    user: AuthUserInternal = Depends(require_operator),
    db=Depends(get_db),
):
    from ...services_nav_fences import set_fence_enabled
    from ...services_pcd_maps import PcdMapError

    try:
        fence = set_fence_enabled(map_id, fence_id, body.enabled)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"围栏不存在: {fence_id}")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"场景不存在或缺少 ground.pcd: {map_id}")
    except PcdMapError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await safe_write_audit_log(
        db,
        level="INFO",
        module="BACKEND",
        message=(
            f"用户={user.username} 角色={user.role} 操作=nav.fence.enabled "
            f"目标={fence_id} scene={map_id} enabled={body.enabled} 结果=success"
        ),
    )
    return fence


@router.delete("/pcd-maps/{map_id}/fences/{fence_id}", response_model=DeleteWaypointResponse)
async def nav_delete_fence(
    map_id: str,
    fence_id: str,
    user: AuthUserInternal = Depends(require_operator),
    db=Depends(get_db),
):
    from ...services_nav_fences import delete_fence
    from ...services_pcd_maps import PcdMapError

    try:
        deleted = delete_fence(map_id, fence_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"场景不存在或缺少 ground.pcd: {map_id}")
    except PcdMapError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not deleted:
        raise HTTPException(status_code=404, detail=f"围栏不存在: {fence_id}")

    await safe_write_audit_log(
        db,
        level="WARN",
        module="BACKEND",
        message=(
            f"用户={user.username} 角色={user.role} 操作=nav.fence.delete "
            f"目标={fence_id} scene={map_id} 结果=success"
        ),
    )
    return {"success": True}
