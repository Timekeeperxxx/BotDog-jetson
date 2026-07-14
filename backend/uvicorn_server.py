"""Uvicorn server integration for process-wide SDKs."""

from __future__ import annotations

import signal
import socket
import threading
from collections.abc import Callable
from pathlib import Path
from types import FrameType

import uvicorn
from uvicorn.server import HANDLED_SIGNALS

from .logging_config import get_logger


app_logger = get_logger("应用服务")
SignalHandler = Callable[[int, FrameType | None], None]
SHUTDOWN_MARKER = Path(__file__).resolve().parent.parent / "data" / "runtime" / "backend.stop"


def reinstall_exit_signal_handlers(handler: SignalHandler) -> bool:
    """Restore Uvicorn's handlers after DDS/SDK startup changed them."""

    if threading.current_thread() is not threading.main_thread():
        app_logger.warning("无法在非主线程恢复 Uvicorn 退出信号处理器")
        return False

    for handled_signal in HANDLED_SIGNALS:
        signal.signal(handled_signal, handler)
    return True


class BotDogUvicornServer(uvicorn.Server):
    """Reassert Uvicorn signal ownership after application startup."""

    def __init__(
        self,
        config: uvicorn.Config,
        *,
        shutdown_marker: Path = SHUTDOWN_MARKER,
    ) -> None:
        super().__init__(config)
        self._shutdown_marker = shutdown_marker

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        await super().startup(sockets=sockets)
        if self.should_exit:
            return

        if reinstall_exit_signal_handlers(self.handle_exit):
            app_logger.info("Uvicorn 已恢复 SIGINT/SIGTERM 退出信号处理器")

    async def on_tick(self, counter: int) -> bool:
        if self._consume_shutdown_marker():
            self.should_exit = True
        should_exit = await super().on_tick(counter)
        if not should_exit and counter % 10 == 0:
            # Some native DDS/media components initialize after lifespan
            # startup and can replace process-level handlers later.
            reinstall_exit_signal_handlers(self.handle_exit)
        return should_exit

    def _consume_shutdown_marker(self) -> bool:
        try:
            if not self._shutdown_marker.is_file():
                return False
            self._shutdown_marker.unlink()
        except OSError as exc:
            app_logger.error("读取后台退出标记失败：path={}，原因={}", self._shutdown_marker, exc)
            return False

        app_logger.info("检测到 systemd 退出标记，开始优雅关闭")
        return True
