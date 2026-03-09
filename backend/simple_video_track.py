#!/usr/bin/env python3
"""
简单的测试视频轨道。

职责边界：
- 生成彩色测试视频帧
- 不依赖 GStreamer 插件
- 用于验证 WebRTC 连接
"""

import asyncio
import time
import fractions
from typing import Optional

from av import VideoFrame
from aiortc import MediaStreamTrack


class SimpleTestVideoTrack(MediaStreamTrack):
    """
    简单测试视频轨道。

    生成彩色测试图案，不依赖外部插件。
    """

    kind = "video"

    def __init__(
        self,
        width: int = 1920,
        height: int = 1080,
        framerate: int = 30,
    ):
        """
        初始化测试视频轨道。

        Args:
            width: 视频宽度
            height: 视频高度
            framerate: 帧率
        """
        super().__init__()
        self.width = width
        self.height = height
        self.framerate = framerate
        self._frame_count = 0
        self._start_time: Optional[float] = None
        self._last_frame_time: Optional[float] = None

    async def start(self):
        """启动视频生成。"""
        if self._start_time is not None:
            return
        self._start_time = time.time()
        self._last_frame_time = self._start_time
        print(f"测试视频轨道已启动: {self.width}x{self.height}@{self.framerate}fps")

    def stop(self):
        """停止视频生成（同步版本，兼容 aiortc）。"""
        self._start_time = None
        self._last_frame_time = None
        print("测试视频轨道已停止")

    @property
    def active(self) -> bool:
        """轨道是否活跃。"""
        return self._start_time is not None

    async def recv(self):
        """
        接收下一帧。

        Returns:
            VideoFrame 对象
        """
        import numpy as np

        # 确保视频轨道已启动
        if self._start_time is None:
            await self.start()

        # 计算帧间隔时间
        frame_duration = 1.0 / self.framerate
        current_time = time.time()

        # 计算下一帧应该生成的时间
        next_frame_time = self._last_frame_time + frame_duration if self._last_frame_time else current_time

        # 如果还没到时间，等待
        if current_time < next_frame_time:
            await asyncio.sleep(next_frame_time - current_time)

        # 打印调试信息（每秒一次）
        if self._frame_count % self.framerate == 0:
            print(f"[SimpleTestVideoTrack] 生成帧 #{self._frame_count}, 大小: {self.width}x{self.height}")

        # 获取当前时间用于动画
        t = time.time()

        # 创建 RGB 图像（使用矢量化操作，性能更好）
        rgb_frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)

        # 创建渐变色块（矢量化）
        # 上半部分：红色到黄色渐变
        half_height = self.height // 2
        rgb_frame[:half_height, :, 0] = (np.linspace(0, 255, self.width, dtype=np.uint8)).astype(np.uint8)  # R
        rgb_frame[:half_height, :, 1] = (np.linspace(255, 0, self.width, dtype=np.uint8)).astype(np.uint8)  # G
        rgb_frame[:half_height, :, 2] = 0  # B

        # 下半部分：蓝色到绿色渐变
        rgb_frame[half_height:, :, 0] = 0  # R
        rgb_frame[half_height:, :, 1] = (np.linspace(0, 255, self.width, dtype=np.uint8)).astype(np.uint8)  # G
        rgb_frame[half_height:, :, 2] = (np.linspace(255, 0, self.width, dtype=np.uint8)).astype(np.uint8)  # B

        # 添加移动的彩色条（白色）
        bar_pos = int((t * 100) % self.width)
        bar_start = max(0, bar_pos - 20)
        bar_end = min(self.width, bar_pos + 20)
        if bar_start < bar_end:
            rgb_frame[:, bar_start:bar_end, :] = 255

        # 从 RGB 创建视频帧
        frame = VideoFrame.from_ndarray(rgb_frame, format="rgb24")

        # 设置时间戳（基于帧计数）
        time_base = fractions.Fraction(1, 90000)
        frame.pts = int(self._frame_count * 90000 / self.framerate)
        frame.time_base = time_base

        self._last_frame_time = time.time()
        self._frame_count += 1
        return frame


class SimpleTestVideoSourceFactory:
    """
    简单测试视频源工厂。
    """

    _tracks: dict = {}

    @classmethod
    def create_track(
        cls,
        width: int = 1920,
        height: int = 1080,
        framerate: int = 30,
        **kwargs  # 忽略其他参数
    ) -> SimpleTestVideoTrack:
        """
        创建测试视频轨道。

        Args:
            width: 视频宽度
            height: 视频高度
            framerate: 帧率

        Returns:
            SimpleTestVideoTrack 实例
        """
        track = SimpleTestVideoTrack(
            width=width,
            height=height,
            framerate=framerate,
        )
        cls._tracks[id(track)] = track
        return track

    @classmethod
    async def stop_all(cls):
        """停止所有轨道。"""
        for track in cls._tracks.values():
            track.stop()  # 同步调用
        cls._tracks.clear()