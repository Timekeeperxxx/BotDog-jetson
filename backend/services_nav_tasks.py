from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import settings
from .repositories.json_store import atomic_write_json, read_json


class NavTaskError(Exception):
    pass


def _task_store_dir() -> Path:
    root = Path(settings.NAV_TASK_STORE_DIR).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _task_store_path() -> Path:
    return _task_store_dir() / "workflows.json"


def _validate_task_payload(task: dict[str, Any]) -> None:
    if not isinstance(task, dict):
        raise NavTaskError("任务必须是对象")
    if not str(task.get("id", "")).strip():
        raise NavTaskError("任务 id 不能为空")
    if not str(task.get("name", "")).strip():
        raise NavTaskError("任务名称不能为空")
    scene_id = str(task.get("sceneId", "")).strip()
    map_id = str(task.get("mapId", "")).strip()
    if not scene_id and not map_id:
        raise NavTaskError("任务 sceneId/mapId 不能为空")
    if not str(task.get("mapName", "")).strip():
        raise NavTaskError("任务 mapName 不能为空")
    if not str(task.get("createdAt", "")).strip():
        raise NavTaskError("任务 createdAt 不能为空")
    steps = task.get("steps")
    if not isinstance(steps, list):
        raise NavTaskError("任务 steps 必须是数组")
    for step in steps:
        if not isinstance(step, dict):
            raise NavTaskError("任务 steps 元素必须是对象")


def _load_raw_tasks() -> list[dict[str, Any]]:
    path = _task_store_path()
    data = read_json(path, [])

    if not isinstance(data, list):
        raise NavTaskError("任务 JSON 根节点必须是数组")

    for task in data:
        _validate_task_payload(task)
    return data


def list_nav_tasks() -> dict[str, Any]:
    return {"items": _load_raw_tasks()}


def get_nav_task(task_id: str) -> dict[str, Any]:
    normalized = str(task_id).strip()
    if not normalized:
        raise NavTaskError("task_id 不能为空")

    for task in _load_raw_tasks():
        if str(task.get("id")) == normalized:
            return task

    raise FileNotFoundError(f"任务不存在: {normalized}")


def save_nav_task(task: dict[str, Any]) -> dict[str, Any]:
    _validate_task_payload(task)
    normalized = dict(task)
    scene_id = str(normalized.get("sceneId", "")).strip()
    map_id = str(normalized.get("mapId", "")).strip()
    if not scene_id and map_id:
        normalized["sceneId"] = map_id
    elif scene_id and not map_id:
        normalized["mapId"] = scene_id
    elif scene_id and map_id and scene_id != map_id:
        raise NavTaskError("任务 sceneId 与 mapId 不一致")

    tasks = _load_raw_tasks()
    task_id = str(normalized["id"])
    replaced = False

    for index, current in enumerate(tasks):
        if str(current.get("id")) == task_id:
            tasks[index] = normalized
            replaced = True
            break

    if not replaced:
        tasks.insert(0, normalized)

    path = _task_store_path()
    atomic_write_json(path, tasks)
    return {"success": True, "task": normalized}


def delete_nav_task(task_id: str) -> dict[str, Any]:
    normalized = str(task_id).strip()
    if not normalized:
        raise NavTaskError("task_id 不能为空")

    tasks = _load_raw_tasks()
    next_tasks = [task for task in tasks if str(task.get("id")) != normalized]
    if len(next_tasks) == len(tasks):
        raise FileNotFoundError(f"任务不存在: {normalized}")

    path = _task_store_path()
    atomic_write_json(path, next_tasks)
    return {"success": True, "task_id": normalized}
