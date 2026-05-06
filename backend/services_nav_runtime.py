from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .config import settings
from .schemas import utc_now_iso


def get_nav_runtime_dir() -> Path:
    path = Path(settings.NAV_RUNTIME_DIR).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_current_goal_path() -> Path:
    return get_nav_runtime_dir() / settings.NAV_CURRENT_GOAL_FILE


def build_current_goal_payload(waypoint: dict[str, Any]) -> dict[str, Any]:
    return {
        "event": "nav_goal",
        "map_id": str(waypoint["map_id"]),
        "waypoint_id": str(waypoint["id"]),
        "waypoint_name": str(waypoint["name"]),
        "frame_id": str(waypoint.get("frame_id") or "map"),
        "x": float(waypoint["x"]),
        "y": float(waypoint["y"]),
        "z": float(waypoint.get("z", 0.0)),
        "yaw": float(waypoint.get("yaw", 0.0)),
        "created_at": utc_now_iso(),
        "source": "botdog-backend",
    }


def write_current_goal(waypoint: dict[str, Any]) -> dict[str, Any]:
    payload = build_current_goal_payload(waypoint)
    final_path = get_current_goal_path()
    tmp_path = final_path.with_name(f"{final_path.name}.tmp")

    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())

    os.replace(tmp_path, final_path)
    return payload


def read_current_goal() -> dict[str, Any] | None:
    path = get_current_goal_path()
    if not path.exists():
        return None

    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(f"current_goal.json 解析失败: {exc}") from exc
