from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .config import settings
from .repositories.json_store import atomic_write_json
from .services_nav_tasks import NavTaskError, get_nav_task
from .services_nav_waypoints import get_waypoint, list_waypoints
from .services_pcd_maps import find_scene_pcd_files, resolve_scene_path


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="milliseconds") + "Z"


def _runtime_dir() -> Path:
    path = Path(settings.NAV_RUNTIME_DIR).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _runtime_file() -> Path:
    return _runtime_dir() / "current_task.json"


def _materialize_step(scene_id: str, step: dict[str, Any]) -> dict[str, Any]:
    step_type = str(step.get("type") or "").strip()

    if step_type == "select_map":
        return {
            "type": "select_map",
            "scene_id": scene_id,
        }

    if step_type == "relocalize":
        return {
            "type": "relocalize",
            "mode": str(step.get("mode") or "auto"),
        }

    if step_type == "navigate_waypoint":
        waypoint_id = str(step.get("waypointId") or step.get("waypoint_id") or "").strip()
        if not waypoint_id:
            raise NavTaskError("navigate_waypoint 步骤缺少 waypointId")
        waypoint = get_waypoint(scene_id, waypoint_id)
        return {
            "type": "navigate_waypoint",
            "waypoint_id": waypoint["id"],
            "waypoint_name": waypoint["name"],
            "x": float(waypoint["x"]),
            "y": float(waypoint["y"]),
            "z": float(waypoint.get("z", 0.0)),
            "yaw": float(waypoint.get("yaw", 0.0)),
            "frame_id": str(waypoint.get("frame_id") or settings.PCD_FRAME_ID),
        }

    raise NavTaskError(f"不支持的任务步骤类型: {step_type or 'unknown'}")


def materialize_nav_task_runtime(task_id: str) -> dict[str, Any]:
    task = get_nav_task(task_id)
    scene_id = str(task.get("mapId") or task.get("sceneId") or "").strip()
    if not scene_id:
        raise NavTaskError("任务缺少 mapId/sceneId")

    scene_path = resolve_scene_path(scene_id)
    files = find_scene_pcd_files(scene_path)
    if files["ground"] is None:
        raise FileNotFoundError(f"场景缺少 ground.pcd: {scene_id}")

    runtime_steps = [_materialize_step(scene_id, step) for step in list(task.get("steps") or [])]
    if not runtime_steps:
        raise NavTaskError("任务 steps 不能为空")

    runtime = {
        "task_id": str(task["id"]),
        "task_name": str(task["name"]),
        "scene_id": scene_id,
        "frame_id": settings.PCD_FRAME_ID,
        "created_at": str(task.get("createdAt") or _utc_now_iso()),
        "updated_at": _utc_now_iso(),
        "steps": runtime_steps,
        "scene_dir": str(scene_path),
        "map_pcd": str(files["wall"]) if files["wall"] is not None else None,
        "ground_pcd": str(files["ground"]) if files["ground"] is not None else None,
        "source_waypoints": [item["id"] for item in list_waypoints(scene_id)["items"]],
    }

    atomic_write_json(_runtime_file(), runtime)
    return {
        "runtime_file": str(_runtime_file()),
        "runtime_task": runtime,
    }
