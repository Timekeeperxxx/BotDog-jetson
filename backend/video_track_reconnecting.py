#!/usr/bin/env python3
"""
带指数退避重连的 WebRTC 视频轨道

特性：
- 自动重连机制
- 指数退避（Exponential Backoff）
- 最大重试次数限制
- 网络恢复后自动恢复视频流
"""

import asyncio
from typing import Optional
import logging

from .video_track_native import GStreamerVideoTrack
from .logging_config import logger


class ReconnectingVideoTrack:
    """
    带自动重连的视频轨道

    在主视频轨道失败时自动重启
    """

    def __init__(
        self,
        udp_port: int = 5000,
        width: int = 1920,
        height: int = 1080,
        framerate: int = 30,
        max_retries: int = 10,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
        backoff_multiplier: float = 2.0,
    ):
        """
        初始化重连视频轨道

        Args:
            udp_port: UDP 端口
            width: 视频宽度
            height: 视频高度
            framerate: 帧率
            max_retries: 最大重试次数（0=无限重试）
            initial_delay: 初始重试延迟（秒）
            max_delay: 最大重试延迟（秒）
            backoff_multiplier: 退避乘数
        """
        self.udp_port = udp_port
        self.width = width
        self.height = height
        self.framerate = framerate
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.backoff_multiplier = backoff_multiplier

        self._track: Optional[GStreamerVideoTrack] = None
        self._reconnect_task: Optional[asyncio.Task] = None
        self._is_running = False
        self._retry_count = 0
        self._current_delay = initial_delay

    async def start(self):
        """启动视频轨道（带重连）"""
        if self._is_running:
            return

        self._is_running = True
        await self._start_with_retry()

    async def _start_with_retry(self):
        """启动视频轨道并自动重试"""
        while self._is_running:
            try:
                # 创建新的视频轨道
                logger.info(f"启动视频轨道 (尝试 {self._retry_count + 1}/{self.max_retries or '∞'})")

                self._track = GStreamerVideoTrack(
                    udp_port=self.udp_port,
                    width=self.width,
                    height=self.height,
                    framerate=self.framerate,
                )

                await self._track.start()

                # 重置重试计数
                self._retry_count = 0
                self._current_delay = self.initial_delay

                logger.info("视频轨道启动成功")

                # 监控视频轨道状态
                await self._monitor_track()

                # 如果监控退出，说明轨道失败了，准备重试
                if not self._is_running:
                    break

                # 检查是否超过最大重试次数
                if self.max_retries > 0 and self._retry_count >= self.max_retries:
                    logger.error(f"达到最大重试次数 ({self.max_retries})，停止重试")
                    break

                # 计算下一次重试延迟（指数退避）
                delay = min(self._current_delay, self.max_delay)
                logger.warning(f"视频轨道失败，{delay:.1f}秒后重试...")
                await asyncio.sleep(delay)

                # 增加延迟（指数退避）
                self._current_delay *= self.backoff_multiplier
                self._retry_count += 1

            except asyncio.CancelledError:
                logger.info("重连任务被取消")
                break
            except Exception as e:
                logger.error(f"启动视频轨道失败: {e}")

                if self.max_retries > 0 and self._retry_count >= self.max_retries:
                    logger.error(f"达到最大重试次数，停止重试")
                    break

                delay = min(self._current_delay, self.max_delay)
                logger.warning(f"{delay:.1f}秒后重试...")
                await asyncio.sleep(delay)

                self._current_delay *= self.backoff_multiplier
                self._retry_count += 1

    async def _monitor_track(self):
        """监控视频轨道状态"""
        if not self._track:
            return

        try:
            # 监控 GStreamer 进程
            while self._is_running and self._track._process:
                proc = self._track._process

                # 检查进程是否退出
                if proc.poll() is not None:
                    returncode = proc.returncode
                    logger.warning(f"GStreamer 进程退出，代码: {returncode}")
                    break

                # 等待一小段时间
                await asyncio.sleep(1.0)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"监控视频轨道失败: {e}")

    async def stop(self):
        """停止视频轨道"""
        self._is_running = False

        if self._track:
            await self._track.stop()
            self._track = None

        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass

    # 代理 VideoTrack 的方法
    @property
    def kind(self):
        """轨道类型"""
        return "video"

    async def recv(self):
        """接收下一帧"""
        if not self._track:
            # 如果没有活动的轨道，等待一段时间
            await asyncio.sleep(0.1)
            # 返回空白帧
            from av import VideoFrame
            import time
            frame = VideoFrame(width=self.width, height=self.height)
            frame.pts = int(time.time() * 90000)
            frame.time_base = fractions.Fraction(1, 90000)
            return frame

        try:
            return await self._track.recv()
        except Exception as e:
            logger.warning(f"接收帧失败: {e}")
            # 返回空白帧
            from av import VideoFrame
            import time
            frame = VideoFrame(width=self.width, height=self.height)
            frame.pts = int(time.time() * 90000)
            frame.time_base = fractions.Fraction(1, 90000)
            return frame

    @property
    def active(self) -> bool:
        """轨道是否活跃"""
        return self._track is not None and self._track.active if self._track else False
