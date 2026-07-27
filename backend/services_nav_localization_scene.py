from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .config import settings
from .logging_config import get_logger
from .repositories.json_store import atomic_write_json, read_json, safe_json_path_name, stable_json_path_name
from .services_pcd_maps import find_scene_pcd_files, resolve_scene_ground_path, resolve_scene_path, snap_xy_to_ground

nav_logger = get_logger("导航定位服务")


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="milliseconds") + "Z"


def _store_dir() -> Path:
    path = Path(settings.NAV_LOCALIZATION_STORE_DIR).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _runtime_dir() -> Path:
    path = Path(settings.NAV_RUNTIME_DIR).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _current_scene_path() -> Path:
    return _runtime_dir() / "current_scene.json"


def _safe_pose_file(map_id: str) -> Path:
    resolve_scene_ground_path(map_id)
    return _store_dir() / f"{stable_json_path_name(map_id)}.json"


def _legacy_pose_file(map_id: str) -> Path:
    return _store_dir() / f"{safe_json_path_name(map_id)}.json"


def _pose_file_candidates(map_id: str) -> list[Path]:
    primary = _store_dir() / f"{stable_json_path_name(map_id)}.json"
    legacy = _legacy_pose_file(map_id)
    return [primary] if primary == legacy else [primary, legacy]


def _pose_files(map_id: str) -> list[Path]:
    resolve_scene_ground_path(map_id)
    return _pose_file_candidates(map_id)


def delete_scene_localization_data(map_id: str) -> dict[str, Any]:
    deleted_files: list[str] = []
    # 删除场景只需清理关联 JSON；失败建图没有 ground.pcd 也必须可删除。
    for path in _pose_file_candidates(map_id):
        if not path.exists():
            continue
        data = read_json(path, None)
        if not isinstance(data, dict) or str(data.get("map_id") or "") == map_id:
            path.unlink(missing_ok=True)
            deleted_files.append(str(path))

    return {"deleted_files": deleted_files}


def save_localization_pose(payload: dict[str, Any]) -> dict[str, Any]:
    map_id = str(payload["map_id"])
    path = _safe_pose_file(map_id)
    snapped = snap_xy_to_ground(
        map_id,
        float(payload["x"]),
        float(payload["y"]),
        fallback_z=float(payload["z"]) if payload.get("z") is not None else None,
    )

    pose = {
        "map_id": map_id,
        "x": snapped["x"],
        "y": snapped["y"],
        "z": snapped["z"],
        "roll": float(payload.get("roll", 0.0)),
        "pitch": float(payload.get("pitch", 0.0)),
        "yaw": float(payload.get("yaw", 0.0)),
        "frame_id": str(payload.get("frame_id") or settings.PCD_FRAME_ID),
        "updated_at": _utc_now_iso(),
    }

    if pose["frame_id"] != settings.PCD_FRAME_ID:
        raise ValueError(f"frame_id 必须是 {settings.PCD_FRAME_ID}")

    atomic_write_json(path, pose)

    return pose


def save_current_scene(scene_id: str) -> dict[str, Any]:
    scene_path = resolve_scene_path(scene_id)
    files = find_scene_pcd_files(scene_path)
    map_pcd = files["wall"]
    ground_pcd = files["ground"]
    planground_pcd = files["footprint_fill"]

    if map_pcd is None:
        nav_logger.error("场景缺少 map.pcd：{}", scene_path)
        raise FileNotFoundError(f"场景缺少 map.pcd: {scene_id}")
    if ground_pcd is None:
        nav_logger.error("场景缺少 ground.pcd：{}", scene_path)
        raise FileNotFoundError(f"场景缺少 ground.pcd: {scene_id}")
    payload = {
        "scene_id": scene_path.name,
        "scene_dir": str(scene_path),
        "map_pcd": str(map_pcd),
        "ground_pcd": str(ground_pcd),
        "planground_pcd": str(planground_pcd) if planground_pcd else None,
        "updated_at": _utc_now_iso(),
    }

    path = _current_scene_path()
    atomic_write_json(path, payload)

    nav_logger.info("当前选择导航场景：{}", payload["scene_id"])
    nav_logger.info("当前场景 map.pcd：{}", payload["map_pcd"])
    nav_logger.info("当前场景 ground.pcd：{}", payload["ground_pcd"])
    if planground_pcd:
        nav_logger.info("当前场景 footprint_fill.pcd：{}", payload["planground_pcd"])
    else:
        nav_logger.info("当前场景缺少 footprint_fill.pcd，已跳过该辅助图层：{}", scene_path)

    return payload


def load_current_scene(strict: bool = True) -> dict[str, Any]:
    path = _current_scene_path()
    if not path.exists():
        raise FileNotFoundError(f"当前场景运行态文件不存在: {path}")

    data = read_json(path, None)

    if not isinstance(data, dict):
        raise ValueError("current_scene.json 格式非法")

    scene_id = str(data.get("scene_id") or "").strip()
    scene_dir_raw = str(data.get("scene_dir") or "").strip()
    map_pcd_raw = str(data.get("map_pcd") or "").strip()
    ground_pcd_raw = str(data.get("ground_pcd") or "").strip()
    planground_pcd_raw = str(data.get("planground_pcd") or data.get("footprint_fill_pcd") or "").strip()

    if not scene_id:
        raise ValueError("current_scene.json 缺少 scene_id")
    if not scene_dir_raw:
        raise ValueError("current_scene.json 缺少 scene_dir")
    if not map_pcd_raw:
        raise ValueError("current_scene.json 缺少 map_pcd")
    if not ground_pcd_raw:
        raise ValueError("current_scene.json 缺少 ground_pcd")
    if not planground_pcd_raw:
        inferred_files = find_scene_pcd_files(Path(scene_dir_raw).expanduser())
        inferred_planground = inferred_files["footprint_fill"]
        planground_pcd_raw = str(inferred_planground) if inferred_planground else ""

    scene_dir = Path(scene_dir_raw).expanduser()
    map_pcd = Path(map_pcd_raw).expanduser()
    ground_pcd = Path(ground_pcd_raw).expanduser()
    planground_pcd = Path(planground_pcd_raw).expanduser() if planground_pcd_raw else None

    if strict:
        if not scene_dir.exists() or not scene_dir.is_dir():
            raise FileNotFoundError(f"场景目录不存在: {scene_dir}")
        if not map_pcd.exists():
            raise FileNotFoundError(f"场景缺少 map.pcd: {map_pcd}")
        if not ground_pcd.exists():
            raise FileNotFoundError(f"场景缺少 ground.pcd: {ground_pcd}")
        if planground_pcd is not None and not planground_pcd.exists():
            raise FileNotFoundError(f"场景缺少 footprint_fill.pcd: {planground_pcd}")

    return {
        "scene_id": scene_id,
        "scene_dir": str(scene_dir),
        "map_pcd": str(map_pcd),
        "ground_pcd": str(ground_pcd),
        "planground_pcd": str(planground_pcd) if planground_pcd else None,
        "updated_at": str(data.get("updated_at") or ""),
        "scene_ok": scene_dir.exists() and scene_dir.is_dir(),
        "map_pcd_ok": map_pcd.exists(),
        "ground_pcd_ok": ground_pcd.exists(),
        "planground_pcd_ok": bool(planground_pcd and planground_pcd.exists()),
    }
