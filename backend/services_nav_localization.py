from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import settings
from .services_pcd_maps import resolve_pcd_path


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="milliseconds") + "Z"


def _store_dir() -> Path:
    path = Path(settings.NAV_LOCALIZATION_STORE_DIR).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_pose_file(map_id: str) -> Path:
    resolve_pcd_path(map_id)
    safe_name = map_id.replace("/", "_").replace("\\", "_")
    return _store_dir() / f"{safe_name}.json"


def save_localization_pose(payload: dict[str, Any]) -> dict[str, Any]:
    map_id = str(payload["map_id"])
    path = _safe_pose_file(map_id)

    pose = {
        "map_id": map_id,
        "x": float(payload["x"]),
        "y": float(payload["y"]),
        "yaw": float(payload.get("yaw", 0.0)),
        "frame_id": str(payload.get("frame_id") or settings.PCD_FRAME_ID),
        "updated_at": _utc_now_iso(),
    }

    if pose["frame_id"] != settings.PCD_FRAME_ID:
        raise ValueError(f"frame_id 必须是 {settings.PCD_FRAME_ID}")

    with path.open("w", encoding="utf-8") as f:
        json.dump(pose, f, ensure_ascii=False, indent=2)

    return pose

