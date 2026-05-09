from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import settings


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
    if not str(task.get("mapId", "")).strip():
        raise NavTaskError("任务 mapId 不能为空")
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
    if not path.exists():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise NavTaskError(f"任务 JSON 文件损坏: {path}") from exc

    if not isinstance(data, list):
        raise NavTaskError("任务 JSON 根节点必须是数组")

    for task in data:
        _validate_task_payload(task)
    return data


def list_nav_tasks() -> dict[str, Any]:
    return {"items": _load_raw_tasks()}


def save_nav_task(task: dict[str, Any]) -> dict[str, Any]:
    _validate_task_payload(task)
    tasks = _load_raw_tasks()
    task_id = str(task["id"])
    replaced = False

    for index, current in enumerate(tasks):
        if str(current.get("id")) == task_id:
            tasks[index] = task
            replaced = True
            break

    if not replaced:
        tasks.insert(0, task)

    path = _task_store_path()
    path.write_text(
        json.dumps(tasks, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {"success": True, "task": task}


def delete_nav_task(task_id: str) -> dict[str, Any]:
    normalized = str(task_id).strip()
    if not normalized:
        raise NavTaskError("task_id 不能为空")

    tasks = _load_raw_tasks()
    next_tasks = [task for task in tasks if str(task.get("id")) != normalized]
    if len(next_tasks) == len(tasks):
        raise FileNotFoundError(f"任务不存在: {normalized}")

    path = _task_store_path()
    path.write_text(
        json.dumps(next_tasks, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {"success": True, "task_id": normalized}
