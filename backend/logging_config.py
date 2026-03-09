"""
日志配置模块。

职责边界：
- 定义统一的日志策略（控制台 + 文件），供应用启动时一次性调用。
"""

from pathlib import Path

from loguru import logger


def setup_logging() -> None:
    """
    初始化 Loguru 日志：控制台 + 按天滚动文件。

    设计要点：
    - 移除默认 handler，避免第三方库重复配置导致输出混乱；
    - 文件日志策略与文档要求保持一致，可在运行时通过配置矩阵调整。
    """

    logger.remove()  # 移除默认 handler

    # 控制台输出（面向开发与容器 stdout）
    logger.add(
        sink=lambda msg: print(msg, end=""),
        level="INFO",
        colorize=True,
        backtrace=True,
        diagnose=False,
    )

    # 文件输出（./logs/botdog.log），便于现场排障与长期留存
    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    logger.add(
        logs_dir / "botdog.log",
        level="INFO",
        rotation="500 MB",
        retention="10 days",
        compression="zip",
        enqueue=True,
        backtrace=False,
        diagnose=False,
    )


__all__ = ["logger", "setup_logging"]

