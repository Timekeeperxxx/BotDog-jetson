"""
日志配置模块。

职责边界：
- 初始化控制台与文件日志；
- 统一标准 logging / Uvicorn / FastAPI 的输出格式；
- 提供带业务域的 Loguru logger。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

from loguru import logger as _logger

_LOGGING_READY = False

LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level:<8}</level> | "
    "<cyan>{extra[domain]}</cyan> | "
    "<level>{message}</level>"
)


def _patch_record(record: dict[str, Any]) -> None:
    record["extra"].setdefault("domain", "应用服务")
    record["extra"].setdefault("access_log", False)
    record["extra"].setdefault("raw_ffmpeg", False)


logger = _logger.patch(_patch_record)


class InterceptHandler(logging.Handler):
    """将标准 logging 转发到 Loguru。"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame = logging.currentframe()
        depth = 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.bind(domain="标准日志").opt(
            depth=depth,
            exception=record.exc_info,
        ).log(level, record.getMessage())


def get_logger(domain: str):
    return logger.bind(domain=domain)


def get_access_logger():
    return logger.bind(domain="接口访问", access_log=True)


def _console_filter(record: dict[str, Any]) -> bool:
    if record["extra"].get("raw_ffmpeg"):
        return False
    return record["level"].no >= logging.INFO


def _backend_file_filter(record: dict[str, Any]) -> bool:
    return not record["extra"].get("raw_ffmpeg", False)


def _access_file_filter(record: dict[str, Any]) -> bool:
    return record["extra"].get("access_log", False)


def _ffmpeg_file_filter(record: dict[str, Any]) -> bool:
    return record["extra"].get("raw_ffmpeg", False)


def setup_logging() -> None:
    """初始化 Loguru 日志：控制台、业务日志、调试日志、访问日志、FFmpeg 原始日志。"""

    global _LOGGING_READY
    if _LOGGING_READY:
        return

    _logger.remove()

    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)

    logger.add(
        sys.stdout,
        level="INFO",
        colorize=True,
        enqueue=True,
        backtrace=False,
        diagnose=False,
        format=LOG_FORMAT,
        filter=_console_filter,
    )
    logger.add(
        logs_dir / "backend.log",
        level="INFO",
        rotation="100 MB",
        retention="10 days",
        compression="zip",
        enqueue=True,
        backtrace=False,
        diagnose=False,
        format=LOG_FORMAT,
        filter=_backend_file_filter,
    )
    logger.add(
        logs_dir / "debug.log",
        level="DEBUG",
        rotation="100 MB",
        retention="7 days",
        compression="zip",
        enqueue=True,
        backtrace=False,
        diagnose=False,
        format=LOG_FORMAT,
    )
    logger.add(
        logs_dir / "access.log",
        level="INFO",
        rotation="100 MB",
        retention="7 days",
        compression="zip",
        enqueue=True,
        backtrace=False,
        diagnose=False,
        format=LOG_FORMAT,
        filter=_access_file_filter,
    )
    logger.add(
        logs_dir / "ffmpeg.log",
        level="DEBUG",
        rotation="100 MB",
        retention="5 days",
        compression="zip",
        enqueue=True,
        backtrace=False,
        diagnose=False,
        format=LOG_FORMAT,
        filter=_ffmpeg_file_filter,
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


__all__ = ["logger", "setup_logging", "get_logger", "get_access_logger"]
