"""
后端运行日志文件服务。

职责边界：
- 只读取 logs 目录下白名单日志文件；
- 不接触 operation_logs 数据表。
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from .logging_config import get_logs_dir

TOP_LEVEL_LOG_NAMES = {"backend.log", "debug.log", "access.log", "ffmpeg.log"}


def _to_iso_utc(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _is_allowed_log_path(logs_dir: Path, path: Path) -> bool:
    try:
        relative = path.resolve().relative_to(logs_dir.resolve())
    except ValueError:
        return False

    if len(relative.parts) == 1 and relative.name in TOP_LEVEL_LOG_NAMES:
        return True

    if relative.parts and relative.parts[0] == "scripts" and relative.suffix == ".log":
        return True

    return False


def _iter_allowed_log_paths() -> list[Path]:
    logs_dir = get_logs_dir()
    logs_dir.mkdir(parents=True, exist_ok=True)
    scripts_dir = logs_dir / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)

    paths: list[Path] = []
    for name in sorted(TOP_LEVEL_LOG_NAMES):
        candidate = logs_dir / name
        if candidate.is_file():
            paths.append(candidate)

    for candidate in sorted(scripts_dir.glob("*.log")):
        if candidate.is_file() and _is_allowed_log_path(logs_dir, candidate):
            paths.append(candidate)

    paths.sort(key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True)
    return paths


def list_log_files() -> list[dict[str, object]]:
    logs_dir = get_logs_dir()
    items: list[dict[str, object]] = []
    for path in _iter_allowed_log_paths():
        stat = path.stat()
        relative_name = path.resolve().relative_to(logs_dir.resolve()).as_posix()
        lines_hint = None
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as f:
                lines_hint = sum(1 for _ in f)
        except Exception:
            lines_hint = None
        items.append(
            {
                "name": relative_name,
                "size_bytes": stat.st_size,
                "modified_at": _to_iso_utc(stat.st_mtime),
                "lines_hint": lines_hint,
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

    line_limit = max(1, min(int(lines), 1000))
    total_lines = 0
    tail = deque[str](maxlen=line_limit)
    with candidate.open("r", encoding="utf-8", errors="ignore") as f:
        for raw_line in f:
            total_lines += 1
            tail.append(raw_line.rstrip("\n"))

    return {
        "name": name,
        "lines": list(tail),
        "line_count": len(tail),
        "truncated": total_lines > len(tail),
    }
