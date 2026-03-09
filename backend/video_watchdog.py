"""
视频看门狗服务。

职责边界：
- 监控视频流健康状态
- 检测视频流中断
- 触发重连机制
- 记录视频流统计
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional, Callable, Awaitable

from .logging_config import logger
from .config import settings


class VideoStreamStats:
    """
    视频流统计信息。
    """

    def __init__(self):
        """初始化统计信息。"""
        self.frames_received = 0
        self.frames_dropped = 0
        self.bytes_received = 0
        self.last_frame_time: Optional[datetime] = None
        self.connection_start_time: Optional[datetime] = None
        self.bitrate_pps = 0  # 码率（bytes/second）
        self.framerate_fps = 0.0  # 帧率（frames/second）

    def reset(self) -> None:
        """重置统计信息。"""
        self.frames_received = 0
        self.frames_dropped = 0
        self.bytes_received = 0
        self.last_frame_time = None
        self.connection_start_time = None
        self.bitrate_pps = 0
        self.framerate_fps = 0.0

    def update_frame_stats(self, frame_size: int) -> None:
        """
        更新帧统计。

        Args:
            frame_size: 帧大小（字节）
        """
        now = datetime.utcnow()
        self.frames_received += 1
        self.bytes_received += frame_size
        self.last_frame_time = now

        if self.connection_start_time is None:
            self.connection_start_time = now

    def calculate_rates(self) -> None:
        """计算码率和帧率。"""
        if self.connection_start_time and self.last_frame_time:
            duration_seconds = (
                self.last_frame_time - self.connection_start_time
            ).total_seconds()

            if duration_seconds > 0:
                self.bitrate_pps = int(self.bytes_received / duration_seconds)
                self.framerate_fps = self.frames_received / duration_seconds


class VideoWatchdog:
    """
    视频看门狗。

    监控视频流健康状态，检测中断并触发恢复机制。
    """

    def __init__(
        self,
        timeout: float = 5.0,
        on_timeout: Optional[Callable[[], Awaitable[None]]] = None,
    ):
        """
        初始化看门狗。

        Args:
            timeout: 超时时间（秒）
            on_timeout: 超时回调函数
        """
        self.timeout = timeout
        self.on_timeout = on_timeout
        self._stats = VideoStreamStats()
        self._last_check_time = datetime.utcnow()
        self._monitor_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._lock = asyncio.Lock()

    @property
    def stats(self) -> VideoStreamStats:
        """获取统计信息。"""
        return self._stats

    async def start(self) -> None:
        """启动看门狗监控任务。"""
        if self._monitor_task is not None:
            logger.warning("视频看门狗已在运行")
            return

        self._stop_event.clear()
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("视频看门狗已启动")

    async def stop(self) -> None:
        """停止看门狗监控任务。"""
        if self._monitor_task is None:
            return

        self._stop_event.set()
        self._monitor_task.cancel()

        try:
            await self._monitor_task
        except asyncio.CancelledError:
            pass

        self._monitor_task = None
        logger.info("视频看门狗已停止")

    async def _monitor_loop(self) -> None:
        """监控循环。"""
        while not self._stop_event.is_set():
            try:
                await asyncio.sleep(1.0)
                await self._check_health()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"视频看门狗检查失败: {e}")

    async def _check_health(self) -> None:
        """检查视频流健康状态。"""
        async with self._lock:
            now = datetime.utcnow()
            self._stats.calculate_rates()

            # 检查是否超时
            if self._stats.last_frame_time:
                elapsed = (now - self._stats.last_frame_time).total_seconds()

                if elapsed > self.timeout:
                    logger.warning(
                        f"视频流超时: {elapsed:.1f}s > {self.timeout}s"
                    )

                    # 触发超时回调
                    if self.on_timeout:
                        try:
                            await self.on_timeout()
                        except Exception as e:
                            logger.error(f"超时回调执行失败: {e}")

                    # 重置统计
                    self._stats.reset()

    async def feed_frame(self, frame_size: int) -> None:
        """
        喂入帧数据。

        Args:
            frame_size: 帧大小（字节）
        """
        async with self._lock:
            self._stats.update_frame_stats(frame_size)

    def get_status(self) -> dict:
        """
        获取看门狗状态。

        Returns:
            状态字典
        """
        self._stats.calculate_rates()

        last_frame_elapsed = None
        if self._stats.last_frame_time:
            last_frame_elapsed = (
                datetime.utcnow() - self._stats.last_frame_time
            ).total_seconds()

        return {
            "is_running": self._monitor_task is not None,
            "frames_received": self._stats.frames_received,
            "frames_dropped": self._stats.frames_dropped,
            "bytes_received": self._stats.bytes_received,
            "bitrate_pps": self._stats.bitrate_pps,
            "framerate_fps": self._stats.framerate_fps,
            "last_frame_elapsed_s": last_frame_elapsed,
            "timeout_s": self.timeout,
        }

    def reset(self) -> None:
        """重置看门狗状态。"""
        self._stats.reset()
        logger.info("视频看门狗已重置")
