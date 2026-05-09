from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import settings
from .logging_config import get_logger, trim_log_file_tail
from .services_pcd_maps import resolve_scene_ground_path


nav_logger = get_logger("导航定位服务")
_restart_proc: subprocess.Popen[str] | None = None
_restart_lock = threading.Lock()


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="milliseconds") + "Z"


def _store_dir() -> Path:
    path = Path(settings.NAV_LOCALIZATION_STORE_DIR).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _restart_script_path() -> Path:
    return _project_root() / "scripts" / "restart_navigation_localization.sh"


def _restart_log_path() -> Path:
    logs_dir = _project_root() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir / "restart_navigation_localization.log"


def _pump_restart_output(proc: subprocess.Popen[str], log_path: Path) -> None:
    with log_path.open("a", encoding="utf-8") as log_file:
        assert proc.stdout is not None
        for line in proc.stdout:
            log_file.write(line)
            log_file.flush()
            trim_log_file_tail(log_path)

    try:
        proc.stdout.close()  # type: ignore[union-attr]
    except Exception:
        pass


def _safe_pose_file(map_id: str) -> Path:
    resolve_scene_ground_path(map_id)
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


def _stop_restart_proc(proc: subprocess.Popen[str] | None) -> None:
    if proc is None or proc.poll() is not None:
        return

    try:
        pgid = os.getpgid(proc.pid)
        nav_logger.info("检测到旧的导航定位重启脚本进程，准备终止：pid={}", proc.pid)
        os.killpg(pgid, signal.SIGTERM)
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            nav_logger.warning("旧的导航定位重启脚本未能及时退出，发送 SIGKILL：pid={}", proc.pid)
            os.killpg(pgid, signal.SIGKILL)
            proc.wait(timeout=5)
    except ProcessLookupError:
        pass
    except Exception as exc:
        nav_logger.warning("终止旧的导航定位重启脚本失败：{}", exc)


def restart_navigation_localization() -> dict[str, Any]:
    global _restart_proc

    script_path = _restart_script_path()
    if not script_path.exists():
        raise FileNotFoundError(f"重启脚本不存在: {script_path}")
    if not script_path.is_file():
        raise FileNotFoundError(f"重启脚本不是文件: {script_path}")

    with _restart_lock:
        nav_logger.info("收到导航定位重启请求，准备清理旧进程并启动脚本")
        _stop_restart_proc(_restart_proc)

        log_path = _restart_log_path()
        nav_logger.info("准备重启导航定位，脚本路径：{}，日志路径：{}", script_path, log_path)

        try:
            _restart_proc = subprocess.Popen(
                ["bash", str(script_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
                cwd=str(_project_root()),
            )
        except Exception:
            raise

        if _restart_proc.stdout is not None:
            threading.Thread(
                target=_pump_restart_output,
                args=(_restart_proc, log_path),
                daemon=True,
                name="restart-localization-log-pump",
            ).start()

        nav_logger.info("已启动导航定位重启脚本：pid={}", _restart_proc.pid)
        return {
            "success": True,
            "running": True,
            "pid": _restart_proc.pid,
            "message": "导航定位重启命令已执行",
        }
