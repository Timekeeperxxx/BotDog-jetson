"""进程内日志配置。

Python 应用、HTTP 访问和 AI FFmpeg 原始输出分别拥有独立文件。
ROS、MediaMTX 与视频流水线等外部进程日志不在此处改写，由 logrotate 管理。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

from loguru import logger as _logger

from .config import settings

_LOGGING_READY = False

LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level:<8}</level> | "
    "<cyan>{extra[domain]}</cyan> | "
    "<magenta>rid={extra[request_id]}</magenta> | "
    "<level>{message}</level>"
)


def _patch_record(record: dict[str, Any]) -> None:
    module_name = str(record.get("name") or "").removeprefix("backend.")
    record["extra"].setdefault("domain", module_name or "应用服务")
    record["extra"].setdefault("access_log", False)
    record["extra"].setdefault("raw_ffmpeg", False)
    record["extra"].setdefault("request_id", "-")


logger = _logger.patch(_patch_record)


def _should_drop_standard_log(record: logging.LogRecord) -> bool:
    if record.levelno >= logging.INFO:
        return False
    return record.name.startswith(("aiosqlite", "sqlalchemy"))


class InterceptHandler(logging.Handler):
    """将标准 logging 转发到 Loguru。"""

    def emit(self, record: logging.LogRecord) -> None:
        if _should_drop_standard_log(record):
            return

        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame = logging.currentframe()
        depth = 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.bind(domain=record.name or "标准日志").opt(
            depth=depth,
            exception=record.exc_info,
        ).log(level, record.getMessage())


def get_logger(domain: str):
    return logger.bind(domain=domain)


def get_access_logger():
    return logger.bind(domain="接口访问", access_log=True)


def get_logs_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "logs"


def _console_filter(record: dict[str, Any]) -> bool:
    if record["extra"].get("raw_ffmpeg") or record["extra"].get("access_log"):
        return False
    return record["level"].no >= logging.INFO


def _backend_file_filter(record: dict[str, Any]) -> bool:
    return not record["extra"].get("raw_ffmpeg", False) and not record["extra"].get("access_log", False)


def _debug_file_filter(record: dict[str, Any]) -> bool:
    return (
        record["level"].no == logging.DEBUG
        and not record["extra"].get("raw_ffmpeg", False)
        and not record["extra"].get("access_log", False)
    )


def _access_file_filter(record: dict[str, Any]) -> bool:
    return record["extra"].get("access_log", False)


def _ffmpeg_file_filter(record: dict[str, Any]) -> bool:
    return record["extra"].get("raw_ffmpeg", False)


def _file_sink_options() -> dict[str, Any]:
    """返回 Python 日志文件的统一轮转策略。"""

    rotation_mb = max(1, int(settings.LOG_ROTATION_SIZE_MB))
    retention_days = max(1, int(settings.LOG_RETENTION_DAYS))
    compression = str(settings.LOG_COMPRESSION).strip() or None
    return {
        "rotation": f"{rotation_mb} MB",
        "retention": f"{retention_days} days",
        "compression": compression,
        "encoding": "utf-8",
        "enqueue": True,
        "backtrace": False,
        "diagnose": False,
        "format": LOG_FORMAT,
    }


def setup_logging(*, force: bool = False) -> None:
    """初始化 Loguru 日志：控制台、业务日志、调试日志、访问日志、FFmpeg 原始日志。"""

    global _LOGGING_READY
    if _LOGGING_READY and not force:
        return

    _logger.remove()

    logs_dir = get_logs_dir()
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / "scripts").mkdir(parents=True, exist_ok=True)

    console_level = str(settings.LOG_CONSOLE_LEVEL).strip().upper() or "INFO"
    logger.add(
        sys.stdout,
        level=console_level,
        colorize=True,
        enqueue=True,
        backtrace=False,
        diagnose=False,
        format=LOG_FORMAT,
        filter=_console_filter,
    )
    file_options = _file_sink_options()
    logger.add(
        logs_dir / "backend.log",
        level="INFO",
        filter=_backend_file_filter,
        **file_options,
    )
    logger.add(
        logs_dir / "debug.log",
        level="DEBUG",
        filter=_debug_file_filter,
        **file_options,
    )
    logger.add(
        logs_dir / "access.log",
        level="INFO",
        filter=_access_file_filter,
        **file_options,
    )
    logger.add(
        logs_dir / "ai_ffmpeg.log",
        level="DEBUG",
        filter=_ffmpeg_file_filter,
        **file_options,
    )

    intercept_handler = InterceptHandler()
    logging.basicConfig(handlers=[intercept_handler], level=0, force=True)

    for name in (
        "uvicorn",
        "uvicorn.error",
        "fastapi",
        "asyncio",
    ):
        std_logger = logging.getLogger(name)
        std_logger.handlers = [intercept_handler]
        std_logger.propagate = False

    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers = []
    access_logger.propagate = False
    access_logger.disabled = True

    _LOGGING_READY = True


__all__ = ["logger", "setup_logging", "get_logger", "get_access_logger", "get_logs_dir"]
