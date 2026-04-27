from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import settings
from .services_pcd_maps import resolve_pcd_path


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="milliseconds") + "Z"


def _store_dir() -> Path:
    path = Path(settings.NAV_WAYPOINT_STORE_DIR).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_waypoint_file(map_id: str) -> Path:
    resolve_pcd_path(map_id)
    safe_name = map_id.replace("/", "_").replace("\\", "_")
    return _store_dir() / f"{safe_name}.json"


def list_waypoints(map_id: str) -> dict[str, Any]:
    path = _safe_waypoint_file(map_id)
    if not path.exists():
        return {"items": []}

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    return {"items": data.get("items", [])}


def _write_waypoints(map_id: str, items: list[dict[str, Any]]) -> None:
    path = _safe_waypoint_file(map_id)
    payload = {"map_id": map_id, "items": items}

    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def create_waypoint(map_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    existing = list_waypoints(map_id)["items"]
    now = _utc_now_iso()

    waypoint = {
        "id": f"wp_{uuid.uuid4().hex[:12]}",
        "map_id": map_id,
        "name": payload["name"],
        "x": float(payload["x"]),
        "y": float(payload["y"]),
        "z": float(payload.get("z", 0.0)),
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


def delete_waypoint(map_id: str, waypoint_id: str) -> bool:
    existing = list_waypoints(map_id)["items"]
    next_items = [item for item in existing if item.get("id") != waypoint_id]

    if len(next_items) == len(existing):
        return False

    _write_waypoints(map_id, next_items)
    return True
