from __future__ import annotations

import math
import uuid
from pathlib import Path
from typing import Any

from .config import settings
from .repositories.json_store import (
    atomic_write_json,
    read_json,
    safe_json_path_name,
    stable_json_path_name,
)
from .services_pcd_maps import resolve_scene_ground_path

def _store_dir() -> Path:
    path = Path(settings.NAV_FENCE_STORE_DIR).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_fence_file(scene_id: str) -> Path:
    resolve_scene_ground_path(scene_id)
    return _store_dir() / f"{stable_json_path_name(scene_id)}.json"


def _legacy_fence_file(scene_id: str) -> Path:
    return _store_dir() / f"{safe_json_path_name(scene_id)}.json"


def _fence_file_candidates(scene_id: str) -> list[Path]:
    primary = _store_dir() / f"{stable_json_path_name(scene_id)}.json"
    legacy = _legacy_fence_file(scene_id)
    return [primary] if primary == legacy else [primary, legacy]


def _point(value: dict[str, Any], field: str) -> dict[str, float]:
    try:
        x = float(value["x"])
        y = float(value["y"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{field} 必须包含有限的地图 x/y 坐标") from exc
    if not math.isfinite(x) or not math.isfinite(y):
        raise ValueError(f"{field} 必须包含有限的地图 x/y 坐标")
    return {"x": x, "y": y}


def list_fences(scene_id: str) -> dict[str, Any]:
    resolve_scene_ground_path(scene_id)
    items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for path in _fence_file_candidates(scene_id):
        data = read_json(path, {"scene_id": scene_id, "items": []})
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            continue
        for item in data["items"]:
            if not isinstance(item, dict):
                continue
            item_scene_id = str(item.get("scene_id") or data.get("scene_id") or scene_id)
            if item_scene_id != scene_id:
                continue
            item_id = str(item.get("id") or "")
            if not item_id or item_id in seen_ids:
                continue
            try:
                start = _point(item.get("start") or {}, "start")
                end = _point(item.get("end") or {}, "end")
            except ValueError:
                continue
            if math.hypot(end["x"] - start["x"], end["y"] - start["y"]) <= 1e-4:
                continue
            seen_ids.add(item_id)
            # Per-fence persistence deliberately contains no height, distance,
            # camera or behavior thresholds. Those belong to unified settings.
            items.append(
                {
                    "id": item_id,
                    "scene_id": scene_id,
                    "start": start,
                    "end": end,
                    "enabled": bool(item.get("enabled", True)),
                }
            )
    return {"items": items}


def get_fence(scene_id: str, fence_id: str) -> dict[str, Any]:
    for item in list_fences(scene_id)["items"]:
        if item.get("id") == fence_id:
            return item
    raise KeyError(fence_id)


def _write_fences(scene_id: str, items: list[dict[str, Any]]) -> None:
    atomic_write_json(
        _safe_fence_file(scene_id),
        {"scene_id": scene_id, "items": items},
    )


def create_fence(scene_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    start = _point(payload.get("start") or {}, "start")
    end = _point(payload.get("end") or {}, "end")
    if math.hypot(end["x"] - start["x"], end["y"] - start["y"]) <= 1e-4:
        raise ValueError("围栏起点和终点不能重合")

    items = list_fences(scene_id)["items"]
    fence = {
        "id": f"fence_{uuid.uuid4().hex[:12]}",
        "scene_id": scene_id,
        "start": start,
        "end": end,
        "enabled": bool(payload.get("enabled", True)),
    }
    items.append(fence)
    _write_fences(scene_id, items)
    return fence


def set_fence_enabled(scene_id: str, fence_id: str, enabled: bool) -> dict[str, Any]:
    items = list_fences(scene_id)["items"]
    for index, item in enumerate(items):
        if item.get("id") != fence_id:
            continue
        updated = {
            **item,
            "enabled": bool(enabled),
        }
        items[index] = updated
        _write_fences(scene_id, items)
        return updated
    raise KeyError(fence_id)


def delete_fence(scene_id: str, fence_id: str) -> bool:
    items = list_fences(scene_id)["items"]
    next_items = [item for item in items if item.get("id") != fence_id]
    if len(next_items) == len(items):
        return False
    _write_fences(scene_id, next_items)
    return True


def delete_scene_fence_data(scene_id: str) -> dict[str, Any]:
    deleted_files: list[str] = []
    removed_items = 0
    for path in _fence_file_candidates(scene_id):
        if not path.exists():
            continue
        data = read_json(path, None)
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            removed_items += sum(
                1
                for item in data["items"]
                if isinstance(item, dict)
                and str(item.get("scene_id") or data.get("scene_id") or "") == scene_id
            )
        path.unlink(missing_ok=True)
        deleted_files.append(str(path))
    return {"deleted_files": deleted_files, "removed_items": removed_items}
