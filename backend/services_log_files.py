"""后端运行日志文件服务。

只允许读取 ``logs`` 目录内的 ``.log`` 文件，但不使用易过期的
文件名白名单，以便 ROS、视频流水线和脚本新增日志后可直接排障。
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from .logging_config import get_logs_dir

MAX_LISTED_LOG_FILES = 500
MAX_EXACT_LINE_COUNT_BYTES = 2 * 1024 * 1024

LOG_CATEGORY_ORDER = {
    "backend": 0,
    "video": 1,
    "navigation": 2,
    "other": 3,
}

BACKEND_LOG_NAMES = {
    "backend.log",
    "access.log",
    "debug.log",
    "ai_ffmpeg.log",
}

NAVIGATION_LOG_NAMES = {
    "restart_navigation_localization.log",
    "start_mapping_debug.log",
    "radar_health.log",
    "dynamic_avoidance_runtime.log",
}


def _to_iso_utc(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _is_allowed_log_path(logs_dir: Path, path: Path) -> bool:
    try:
        relative = path.resolve().relative_to(logs_dir.resolve())
    except ValueError:
        return False

    return bool(relative.parts) and relative.suffix.lower() == ".log"


def _classify_log_path(relative: Path) -> str:
    """Return the stable log-center category for a relative log path."""

    name = relative.name.lower()
    if relative.parts[0].lower() == "ros" or name in NAVIGATION_LOG_NAMES:
        return "navigation"
    if name.startswith(("restart_navigation", "start_mapping", "radar_", "dynamic_avoidance")):
        return "navigation"
    if name in BACKEND_LOG_NAMES or name.startswith("backend_"):
        return "backend"
    if name.startswith(("ffmpeg", "mediamtx", "pipeline")):
        return "video"
    return "other"


def _iter_allowed_log_paths() -> list[Path]:
    logs_dir = get_logs_dir()
    logs_dir.mkdir(parents=True, exist_ok=True)
    paths = [
        candidate
        for candidate in logs_dir.rglob("*.log")
        if candidate.is_file() and _is_allowed_log_path(logs_dir, candidate)
    ]

    def sort_key(path: Path) -> tuple[int, float, str]:
        try:
            relative = path.resolve().relative_to(logs_dir.resolve())
            modified_at = path.stat().st_mtime
        except (OSError, ValueError):
            return (LOG_CATEGORY_ORDER["other"], 0.0, path.as_posix())
        category = _classify_log_path(relative)
        return (LOG_CATEGORY_ORDER[category], -modified_at, relative.as_posix())

    # Keep the API order aligned with the log center categories.
    paths.sort(key=sort_key)
    return paths[:MAX_LISTED_LOG_FILES]


def _line_count_hint(path: Path, size_bytes: int) -> int | None:
    if size_bytes > MAX_EXACT_LINE_COUNT_BYTES:
        return None
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            return sum(1 for _ in f)
    except OSError:
        return None


def list_log_files() -> list[dict[str, object]]:
    logs_dir = get_logs_dir()
    items: list[dict[str, object]] = []
    for path in _iter_allowed_log_paths():
        try:
            stat = path.stat()
            relative = path.resolve().relative_to(logs_dir.resolve())
            relative_name = relative.as_posix()
        except (OSError, ValueError):
            continue
        items.append(
            {
                "name": relative_name,
                "category": _classify_log_path(relative),
                "size_bytes": stat.st_size,
                "modified_at": _to_iso_utc(stat.st_mtime),
                "lines_hint": _line_count_hint(path, stat.st_size),
            }
        )
    return items


def tail_log_file(name: str, lines: int = 300) -> dict[str, object]:
    logs_dir = get_logs_dir()
    logs_dir.mkdir(parents=True, exist_ok=True)
    candidate = (logs_dir / name).resolve()
    if not _is_allowed_log_path(logs_dir, candidate):
        raise FileNotFoundError(name)
    if not candidate.is_file():
        raise FileNotFoundError(name)

    line_limit = max(1, min(int(lines), 10000))
    total_lines = 0
    tail = deque[str](maxlen=line_limit)
    with candidate.open("r", encoding="utf-8", errors="ignore") as f:
        for raw_line in f:
            total_lines += 1
            tail.append(raw_line.rstrip("\n"))

    return {
        "name": name,
        # 保持原始时间顺序，否则 traceback 和 FFmpeg 多行消息会被倒置。
        "lines": list(tail),
        "line_count": len(tail),
        "truncated": total_lines > len(tail),
    }
