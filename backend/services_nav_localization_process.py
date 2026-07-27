from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from .config import settings
from .logging_config import get_logger
from .repositories.json_store import atomic_write_json

nav_logger = get_logger("导航定位服务")


def _runtime_dir() -> Path:
    path = Path(settings.NAV_RUNTIME_DIR).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cmd_vel_pid_path() -> Path:
    return _runtime_dir() / "cmd_vel.pid"


def _cmd_vel_estop_path() -> Path:
    return _runtime_dir() / "cmd_vel_estop.json"


def _navigation_ready_path() -> Path:
    return _runtime_dir() / "navigation_ready.json"


def _named_pid_path(name: str) -> Path:
    return _runtime_dir() / f"{name}.pid"


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="milliseconds") + "Z"


def get_relocation_process_status() -> dict[str, object]:
    pid = _read_pid_file(_named_pid_path("relocation"))
    running = _is_pid_alive(pid)
    return {
        "running": running,
        "pid": pid,
        "message": "Super-LIO relocation 进程运行中" if running else f"Super-LIO relocation 进程未运行，pid={pid}",
    }


def set_cmd_vel_estop(active: bool, reason: str = "") -> dict[str, object]:
    path = _cmd_vel_estop_path()
    payload = {
        "active": bool(active),
        "reason": reason,
        "updated_at": _utc_now_iso(),
    }
    atomic_write_json(path, payload)
    nav_logger.warning("cmd_vel 急停钳制状态更新：active={} reason={} path={}", active, reason, path)
    return {
        "success": True,
        "active": bool(active),
        "reason": reason,
        "path": str(path),
    }


def get_cmd_vel_estop_status() -> dict[str, object]:
    """Read the persistent navigation velocity clamp without changing it."""
    path = _cmd_vel_estop_path()
    if not path.exists():
        return {"active": False, "reason": "", "path": str(path)}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("payload is not an object")
        return {
            "active": bool(payload.get("active", False)),
            "reason": str(payload.get("reason") or ""),
            "path": str(path),
        }
    except Exception as exc:
        nav_logger.error("读取 cmd_vel 急停钳制失败，按急停处理：{}，path={}", exc, path)
        return {
            "active": True,
            "reason": "cmd_vel 急停状态文件损坏",
            "path": str(path),
        }


def _read_cmd_vel_pid() -> int | None:
    path = _cmd_vel_pid_path()
    if not path.exists():
        return None

    try:
        raw = path.read_text(encoding="utf-8").strip()
        pid = int(raw)
        return pid if pid > 0 else None
    except Exception as exc:
        nav_logger.warning("读取 cmd_vel PID 文件失败：{}，path={}", exc, path)
        return None


def _read_pid_file(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8").strip()
        pid = int(raw)
        return pid if pid > 0 else None
    except Exception as exc:
        nav_logger.warning("读取 PID 文件失败：{}，path={}", exc, path)
        return None


def _wait_for_pid_file(path: Path, timeout_s: float = 30.0) -> int | None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        pid = _read_pid_file(path)
        if pid is not None:
            return pid
        time.sleep(0.2)
    return None


def _wait_for_pid_files(
    paths: dict[str, Path],
    timeout_s: float = 20.0,
    abort_if: Callable[[], bool] | None = None,
) -> dict[str, int | None]:
    deadline = time.time() + timeout_s
    result: dict[str, int | None] = {name: None for name in paths}

    while time.time() < deadline:
        for name, path in paths.items():
            if result[name] is None:
                result[name] = _read_pid_file(path)

        if all(pid is not None for pid in result.values()):
            break
        if abort_if is not None and abort_if():
            break

        time.sleep(0.2)

    return result


def _is_pid_alive(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False

    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except Exception:
        return False


def _find_pids_by_needles(needles: list[str]) -> list[int]:
    pids: list[int] = []

    for needle in needles:
        try:
            result = subprocess.run(
                ["pgrep", "-af", needle],
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception as exc:
            nav_logger.warning("搜索进程失败：needle={} err={}", needle, exc)
            continue

        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            pid_text = line.split(maxsplit=1)[0]
            try:
                pids.append(int(pid_text))
            except ValueError:
                continue

    return sorted(set(pids))


def _find_cmd_vel_pids() -> list[int]:
    project_root = Path(__file__).resolve().parents[1]
    return _find_pids_by_needles([
        str(project_root / "scripts" / "start_cmd_vel_udp_sender.sh"),
        str(project_root / "scripts" / "cmd_vel_ros2_udp_sender.py"),
        "/home/jetson/Project/BOTDOG/unitree_sdk2_python/example/scripts/cmd_vel.py",
        "/home/jetson/Project/BOTDOG/test_cmd_vel_fixed.sh",
        "/home/jetson/Project/BOTDOG/unitree_sdk2_python/example/scripts/cmd_vel_udp_bridge.py",
        "/home/jetson/Project/BOTDOG/unitree_sdk2_python/example/scripts/cmd_vel_ros2_udp_sender.py",
    ])


def _find_cmd_vel_test_publisher_pids() -> list[int]:
    return _find_pids_by_needles([
        "/home/jetson/Project/BOTDOG/backend/scripts/test_cmd_vel_publisher.py",
        "test_cmd_vel_publisher.py",
        "test_ros2_cmd_vel_bridge.py",
    ])


def _kill_pid_tree(pid: int, sig: int) -> None:
    try:
        children = subprocess.run(
            ["pgrep", "-P", str(pid)],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.split()
    except Exception:
        children = []

    for child in children:
        try:
            child_pid = int(child)
        except ValueError:
            continue
        _kill_pid_tree(child_pid, sig)

    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        pass
    except Exception as exc:
        nav_logger.warning("向 cmd_vel 进程发送信号失败：pid={} sig={} err={}", pid, sig, exc)
