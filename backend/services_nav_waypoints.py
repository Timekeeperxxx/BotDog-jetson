from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import settings
from .repositories.json_store import atomic_write_json, read_json, safe_json_path_name, stable_json_path_name
from .services_pcd_maps import resolve_scene_ground_path, snap_xy_to_ground


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="milliseconds") + "Z"


def _store_dir() -> Path:
    path = Path(settings.NAV_WAYPOINT_STORE_DIR).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_waypoint_file(map_id: str) -> Path:
    resolve_scene_ground_path(map_id)
    return _store_dir() / f"{stable_json_path_name(map_id)}.json"


def _legacy_waypoint_file(map_id: str) -> Path:
    return _store_dir() / f"{safe_json_path_name(map_id)}.json"


def _waypoint_file_candidates(map_id: str) -> list[Path]:
    primary = _store_dir() / f"{stable_json_path_name(map_id)}.json"
    legacy = _legacy_waypoint_file(map_id)
    return [primary] if primary == legacy else [primary, legacy]


def _waypoint_files(map_id: str) -> list[Path]:
    resolve_scene_ground_path(map_id)
    return _waypoint_file_candidates(map_id)


def list_waypoints(map_id: str) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for path in _waypoint_files(map_id):
        data = read_json(path, {"map_id": map_id, "items": []})
        if not isinstance(data, dict):
            continue
        raw_items = data.get("items", [])
        if not isinstance(raw_items, list):
            continue
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            item_map_id = str(item.get("map_id") or data.get("map_id") or map_id)
            if item_map_id != map_id:
                continue
            item_id = str(item.get("id") or "")
            if item_id and item_id in seen_ids:
                continue
            if item_id:
                seen_ids.add(item_id)
            items.append(item)
    return {"items": items}


def get_waypoint(map_id: str, waypoint_id: str) -> dict[str, Any]:
    for item in list_waypoints(map_id)["items"]:
        if item.get("id") == waypoint_id:
            return item

    raise KeyError(waypoint_id)


def _write_waypoints(map_id: str, items: list[dict[str, Any]]) -> None:
    path = _safe_waypoint_file(map_id)
    payload = {"map_id": map_id, "items": items}
    atomic_write_json(path, payload)


def delete_scene_waypoint_data(map_id: str) -> dict[str, Any]:
    deleted_files: list[str] = []
    updated_files: list[str] = []
    removed_items = 0

    # 删除失败或未完成的建图场景时可能没有 ground.pcd。这里只需按场景 ID
    # 定位关联 JSON，不应复用读取导航点时的点云完整性校验。
    for path in _waypoint_file_candidates(map_id):
        if not path.exists():
            continue
        data = read_json(path, None)
        if not isinstance(data, dict):
            path.unlink(missing_ok=True)
            deleted_files.append(str(path))
            continue

        raw_items = data.get("items", [])
        if not isinstance(raw_items, list):
            raw_items = []

        keep_items: list[dict[str, Any]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            item_map_id = str(item.get("map_id") or data.get("map_id") or "")
            if item_map_id == map_id:
                removed_items += 1
            else:
                keep_items.append(item)

        if keep_items:
            atomic_write_json(path, {"map_id": data.get("map_id") or map_id, "items": keep_items})
            updated_files.append(str(path))
        else:
            path.unlink(missing_ok=True)
            deleted_files.append(str(path))

    return {
        "deleted_files": deleted_files,
        "updated_files": updated_files,
        "removed_items": removed_items,
    }


def create_waypoint(map_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    existing = list_waypoints(map_id)["items"]
    now = _utc_now_iso()
    snapped = snap_xy_to_ground(
        map_id,
        float(payload["x"]),
        float(payload["y"]),
        fallback_z=float(payload["z"]) if payload.get("z") is not None else None,
    )

    waypoint = {
        "id": f"wp_{uuid.uuid4().hex[:12]}",
        "map_id": map_id,
        "name": payload["name"],
        "x": snapped["x"],
        "y": snapped["y"],
        "z": snapped["z"],
        "yaw": float(payload.get("yaw", 0.0)),
        "frame_id": payload.get("frame_id", settings.PCD_FRAME_ID),
        "created_at": now,
        "updated_at": now,
    }

    if waypoint["frame_id"] != settings.PCD_FRAME_ID:
        raise ValueError(f"frame_id 必须是 {settings.PCD_FRAME_ID}")

    existing.append(waypoint)
    _write_waypoints(map_id, existing)

    return waypoint


def upsert_origin_waypoint(
    map_id: str,
    *,
    x: float | None = None,
    y: float | None = None,
    z: float | None = None,
    yaw: float | None = None,
) -> dict[str, Any]:
    existing = list_waypoints(map_id)["items"]
    now = _utc_now_iso()
    target_name = "原点"
    waypoint = {
        "map_id": map_id,
        "name": target_name,
        "x": float(0.0 if x is None else x),
        "y": float(0.0 if y is None else y),
        "z": float(settings.NAV_ORIGIN_WAYPOINT_Z if z is None else z),
        "yaw": float(settings.NAV_ORIGIN_WAYPOINT_YAW if yaw is None else yaw),
        "frame_id": settings.PCD_FRAME_ID,
        "updated_at": now,
    }

    for index, item in enumerate(existing):
        if item.get("name") != target_name:
            continue

        updated = {
            **item,
            **waypoint,
            "id": item.get("id") or f"wp_{uuid.uuid4().hex[:12]}",
            "created_at": item.get("created_at") or now,
        }
        existing[index] = updated
        _write_waypoints(map_id, existing)
        return updated

    created = {
        **waypoint,
        "id": f"wp_{uuid.uuid4().hex[:12]}",
        "created_at": now,
    }
    existing.insert(0, created)
    _write_waypoints(map_id, existing)
    return created


def delete_waypoint(map_id: str, waypoint_id: str) -> bool:
    existing = list_waypoints(map_id)["items"]
    next_items = [item for item in existing if item.get("id") != waypoint_id]

    if len(next_items) == len(existing):
        return False

    _write_waypoints(map_id, next_items)
    return True
