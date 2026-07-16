"""主机资源读取与受控系统操作。"""

from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

from .logging_config import get_logger


system_logger = get_logger("系统运维")

_MEMINFO_PATH = Path("/proc/meminfo")
_UPTIME_PATH = Path("/proc/uptime")
_HOST_DISK_PATH = Path("/")
_SUDO_PATH = shutil.which("sudo") or "/usr/bin/sudo"
_SYSTEMCTL_PATH = shutil.which("systemctl") or "/usr/bin/systemctl"
_SYSTEM_ACTION_DELAY_SECONDS = 1.5

_SYSTEMCTL_ACTIONS: dict[str, tuple[str, ...]] = {
    "restart-backend": ("restart", "botdog-backend.service"),
    "restart-video": ("restart", "botdog-pipeline.service"),
    # AI Worker 与后端同进程，完整重载必须重启后端服务。
    "restart-ai": ("restart", "botdog-backend.service"),
    "reboot-device": ("reboot",),
}

_pending_commands: set[tuple[str, ...]] = set()
_pending_commands_lock = threading.Lock()


def _read_kib_values(path: Path) -> dict[str, int]:
    values: dict[str, int] = {}
    with path.open("r", encoding="utf-8", errors="ignore") as file:
        for raw_line in file:
            key, separator, raw_value = raw_line.partition(":")
            if not separator:
                continue
            parts = raw_value.strip().split()
            if not parts:
                continue
            try:
                value = int(parts[0])
            except ValueError:
                continue
            multiplier = 1024 if len(parts) > 1 and parts[1].lower() == "kb" else 1
            values[key] = value * multiplier
    return values


def read_memory_snapshot(path: Path = _MEMINFO_PATH) -> dict[str, int | float]:
    """读取 Linux 内存指标，返回字节值和使用率。"""

    values = _read_kib_values(path)
    total = max(0, values.get("MemTotal", 0))
    available = values.get("MemAvailable")
    if available is None:
        available = sum(values.get(key, 0) for key in ("MemFree", "Buffers", "Cached"))
    available = min(total, max(0, available))
    used = max(0, total - available)
    swap_total = max(0, values.get("SwapTotal", 0))
    swap_free = min(swap_total, max(0, values.get("SwapFree", 0)))
    swap_used = max(0, swap_total - swap_free)

    return {
        "total_bytes": total,
        "used_bytes": used,
        "available_bytes": available,
        "usage_percent": round((used / total * 100) if total else 0.0, 1),
        "swap_total_bytes": swap_total,
        "swap_used_bytes": swap_used,
    }


def read_disk_snapshot(path: Path = _HOST_DISK_PATH) -> dict[str, int | float | str]:
    """读取指定挂载点的真实磁盘占用。"""

    usage = shutil.disk_usage(path)
    used = max(0, usage.total - usage.free)
    return {
        "path": str(path),
        "total_bytes": usage.total,
        "used_bytes": used,
        "free_bytes": usage.free,
        "usage_percent": round((used / usage.total * 100) if usage.total else 0.0, 1),
    }


def _read_host_uptime(path: Path = _UPTIME_PATH) -> float | None:
    try:
        return round(float(path.read_text(encoding="utf-8").split()[0]), 1)
    except (OSError, ValueError, IndexError):
        return None


def get_host_resource_snapshot() -> dict[str, object]:
    """返回后台总览使用的实时主机资源快照。"""

    try:
        load_average = [round(value, 2) for value in os.getloadavg()]
    except (AttributeError, OSError):
        load_average = []

    return {
        "collected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "hostname": socket.gethostname(),
        "platform": platform.platform(aliased=True),
        "architecture": platform.machine(),
        "cpu_count": os.cpu_count() or 0,
        "load_average": load_average,
        "host_uptime_seconds": _read_host_uptime(),
        "memory": read_memory_snapshot(),
        "disk": read_disk_snapshot(),
    }


def _systemctl_command(action_key: str) -> tuple[str, ...]:
    args = _SYSTEMCTL_ACTIONS.get(action_key)
    if args is None:
        raise ValueError(f"不支持的系统操作: {action_key}")
    return (_SYSTEMCTL_PATH, *args)


def ensure_system_action_available(action_key: str) -> tuple[str, ...]:
    """确认 sudoers 已允许指定的固定 systemctl 命令。"""

    command = _systemctl_command(action_key)
    result = subprocess.run(
        [_SUDO_PATH, "-n", "-l", *command],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "系统操作权限尚未安装，请在主机执行 sudo bash scripts/install-system-actions.sh"
        )

    if len(command) >= 3 and command[1] == "restart":
        status = subprocess.run(
            [_SYSTEMCTL_PATH, "is-active", command[2]],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if status.returncode != 0:
            raise RuntimeError(f"{command[2]} 当前未由 systemd 运行，无法从后台重启")

    return command


def _run_scheduled_command(command: tuple[str, ...], action_key: str) -> None:
    try:
        time.sleep(_SYSTEM_ACTION_DELAY_SECONDS)
        system_logger.warning("开始执行系统危险操作：action={} command={}", action_key, command)
        result = subprocess.run(
            [_SUDO_PATH, "-n", *command],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "未知错误").strip()
            system_logger.error(
                "系统危险操作执行失败：action={} returncode={} detail={}",
                action_key,
                result.returncode,
                detail,
            )
    except Exception as exc:  # noqa: BLE001
        system_logger.exception("系统危险操作执行异常：action={} error={}", action_key, exc)
    finally:
        with _pending_commands_lock:
            _pending_commands.discard(command)


def schedule_system_action(action_key: str, command: tuple[str, ...]) -> bool:
    """延迟执行系统命令，让 HTTP 响应有机会先返回给浏览器。"""

    expected_command = _systemctl_command(action_key)
    if command != expected_command:
        raise ValueError("系统操作命令与动作白名单不匹配")

    with _pending_commands_lock:
        if command in _pending_commands:
            return False
        _pending_commands.add(command)

    thread = threading.Thread(
        target=_run_scheduled_command,
        args=(command, action_key),
        daemon=True,
        name=f"system-action-{action_key}",
    )
    thread.start()
    return True


__all__ = [
    "ensure_system_action_available",
    "get_host_resource_snapshot",
    "read_disk_snapshot",
    "read_memory_snapshot",
    "schedule_system_action",
]
