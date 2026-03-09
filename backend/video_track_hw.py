#!/usr/bin/env python3
"""
GStreamer 视频源轨道 - Windows 硬件加速版本。

职责边界：
- 从 GStreamer 管道获取视频帧（使用 D3D11 硬件解码）
- 转换为 aiortc 可用的 MediaStreamTrack
- 支持 H.265 RTP 输入，使用 GPU 硬件解码
- 避免 PyGObject 依赖，使用 OpenCV + subprocess 方式
"""

import asyncio
import fractions
import subprocess
import time
from typing import Optional

import cv2
import numpy as np
from av import VideoFrame
from aiortc import MediaStreamTrack


class GStreamerVideoTrack(MediaStreamTrack):
    """
    GStreamer 视频轨道 - Windows 硬件加速版本。

    使用 D3D11 硬件解码 H.265，通过 OpenCV 获取帧数据。
    """

    kind = "video"

    def __init__(
        self,
        udp_port: int = 5000,
        width: int = 1920,  # 1080P
        height: int = 1080,
        framerate: int = 30,
    ):
        """
        初始化视频轨道。

        Args:
            udp_port: UDP 接收端口
            width: 视频宽度
            height: 视频高度
            framerate: 帧率
        """
        super().__init__()
        self.udp_port = udp_port
        self.width = width
        self.height = height
        self.framerate = framerate
        self._queue: asyncio.Queue[Optional[VideoFrame]] = asyncio.Queue(maxsize=30)
        self._started = False
        self._capture: Optional[cv2.VideoCapture] = None
        self._task: Optional[asyncio.Task] = None
        self._gst_process: Optional[subprocess.Popen] = None

    async def start(self):
        """启动 GStreamer 管道。"""
        if self._started:
            return

        # 构建 GStreamer 管道（H.265 输入 -> H.264 输出，使用 D3D11 硬解）
        pipeline_str = (
            f"udpsrc port={self.udp_port} "
            f'caps="application/x-rtp,media=video,encoding-name=H265,payload=96" '
            f"! rtpjitterbuffer latency=100 do-retransmission=true "
            f"! rtph265depay "
            f"! h265parse "
            f"! d3d11h265dec "  # Windows D3D11 硬件解码器
            f"! videoconvert "
            f"! video/x-raw,format=I420 "
            f"! x264enc tune=zerolatency speed-preset=ultrafast "
            f"! rtph264pay "
            f"! appsink sync=false"
        )

        print(f"\n{'='*80}")
        print(f"🚀 启动 GStreamer 视频管道（Windows 硬件加速模式）:")
        print(f"{'='*80}")
        print(f"输入: UDP port={self.udp_port}, H.265 RTP")
        print(f"解码器: d3d11h265dec (D3D11 硬件解码)")
        print(f"抖动缓冲: latency=100ms + do-retransmission=true")
        print(f"输出: {self.width}x{self.height} @ {self.framerate}fps I420")
        print(f"目标: GPU 硬解，CPU <30%，无灰屏")
        print(f"{'='*80}\n")

        try:
            # 使用 OpenCV 打开 GStreamer 管道
            self._capture = cv2.VideoCapture(pipeline_str, cv2.CAP_GSTREAMER)

            if not self._capture.isOpened():
                raise RuntimeError("无法打开 GStreamer 管道")

            # 设置帧属性
            self._capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self._capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            self._capture.set(cv2.CAP_PROP_FPS, self.framerate)

            self._started = True

            # 启动帧获取任务
            self._task = asyncio.create_task(self._run())

            print(f"✅ GStreamer 管道启动成功")

        except Exception as e:
            print(f"\n{'='*80}")
            print(f"❌ GStreamer 管道创建失败:")
            print(f"{'='*80}")
            print(f"错误类型: {type(e).__name__}")
            print(f"错误详情: {e}")
            print(f"{'='*80}")
            print(f"\n可能原因:")
            print(f"1. GStreamer 未正确安装或未添加到 PATH")
            print(f"2. 缺少 D3D11 解码插件 (gst-plugins-bad)")
            print(f"3. 缺少 H.264 编码器 (gst-plugins-ugly)")
            print(f"4. OpenCV 未编译 GStreamer 支持")
            print(f"5. 端口 {self.udp_port} 被占用")
            print(f"{'='*80}\n")
            raise

    async def stop(self):
        """停止 GStreamer 管道。"""
        if not self._started:
            return

        self._started = False

        # 停止处理任务
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        # 释放 VideoCapture
        if self._capture:
            self._capture.release()
            self._capture = None

        # 终止 GStreamer 子进程（如果有）
        if self._gst_process:
            self._gst_process.terminate()
            try:
                self._gst_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._gst_process.kill()
            self._gst_process = None

        # 发送结束信号
        await self._queue.put(None)

        print(f"⏹️  GStreamer 管道已停止")

    async def _run(self):
        """从 GStreamer 管道获取帧的后台任务。"""
        consecutive_failures = 0
        max_failures = 10

        while self._started:
            try:
                if not self._capture or not self._capture.isOpened():
                    print(f"⚠️  VideoCapture 未打开，等待重连...")
                    await asyncio.sleep(1)
                    continue

                # 读取帧（带超时）
                ret, frame = self._capture.read()

                if not ret or frame is None:
                    consecutive_failures += 1
                    if consecutive_failures >= max_failures:
                        print(f"❌ 连续 {max_failures} 次读取失败，可能流已断开")
                        break
                    await asyncio.sleep(0.01)
                    continue

                # 重置失败计数
                consecutive_failures = 0

                # 转换 BGR 到 YUV420P
                # OpenCV 默认读取为 BGR，需要转换为 YUV420P
                frame_yuv = cv2.cvtColor(frame, cv2.COLOR_BGR2YUV_I420)

                # 转换为 VideoFrame
                video_frame = self._bgr_to_videoframe(frame, frame_yuv)

                # 异步放入队列（非阻塞）
                try:
                    self._queue.put_nowait(video_frame)
                except asyncio.QueueFull:
                    # 队列满，丢弃最旧的帧
                    try:
                        self._queue.get_nowait()
                        self._queue.put_nowait(video_frame)
                    except asyncio.QueueEmpty:
                        pass

                # 控制帧率
                await asyncio.sleep(1.0 / (self.framerate + 5))  # 稍快于目标帧率

            except Exception as e:
                print(f"❌ 帧获取错误: {e}")
                consecutive_failures += 1
                if consecutive_failures >= max_failures:
                    print(f"❌ 连续 {max_failures} 次错误，停止捕获")
                    break
                await asyncio.sleep(0.1)

    def _bgr_to_videoframe(self, bgr_frame: np.ndarray, yuv_frame: np.ndarray) -> VideoFrame:
        """
        将 BGR 帧和 YUV 帧转换为 VideoFrame。

        Args:
            bgr_frame: BGR 格式的帧
            yuv_frame: YUV420P 格式的帧

        Returns:
            VideoFrame 对象
        """
        height, width = bgr_frame.shape[:2]

        # 创建 VideoFrame（YUV420P 格式）
        frame = VideoFrame(width=width, height=height, format="yuv420p")

        # 转换 YUV 数据为 numpy array
        yuv_data = np.asarray(yuv_frame, dtype=np.uint8)

        # 计算 YUV420P 各平面大小
        y_size = width * height
        uv_size = y_size // 4

        # 填充 Y 平面
        y_plane = yuv_data[:y_size].reshape(height, width)
        frame.planes[0].update(y_plane.tobytes())

        # 填充 U 平面
        u_plane = yuv_data[y_size:y_size + uv_size].reshape(height // 2, width // 2)
        frame.planes[1].update(u_plane.tobytes())

        # 填充 V 平面
        v_plane = yuv_data[y_size + uv_size:y_size + 2 * uv_size].reshape(height // 2, width // 2)
        frame.planes[2].update(v_plane.tobytes())

        # 设置时间戳
        frame.pts = int(time.time() * 90000)
        frame.time_base = fractions.Fraction(1, 90000)

        return frame

    async def recv(self):
        """
        接收下一帧。

        Returns:
            VideoFrame 对象
        """
        try:
            frame = await asyncio.wait_for(self._queue.get(), timeout=1.0)

            if frame is None:
                raise Exception("视频流已结束")

            # 更新时间戳
            frame.pts = int(time.time() * 90000)
            frame.time_base = fractions.Fraction(1, 90000)

            return frame

        except asyncio.TimeoutError:
            # 超时返回黑帧
            frame = VideoFrame(width=self.width, height=self.height)
            frame.pts = int(time.time() * 90000)
            frame.time_base = fractions.Fraction(1, 90000)
            return frame

    @property
    def active(self) -> bool:
        """轨道是否活跃。"""
        return self._started


class GStreamerVideoSourceFactory:
    """
    GStreamer 视频源工厂。

    用于创建和管理视频轨道实例。
    """

    _tracks: dict[int, GStreamerVideoTrack] = {}

    @classmethod
    def create_track(
        cls,
        udp_port: int = 5000,
        width: int = 1920,
        height: int = 1080,
        framerate: int = 30,
    ) -> GStreamerVideoTrack:
        """
        创建视频轨道。

        Args:
            udp_port: UDP 接收端口
            width: 视频宽度
            height: 视频高度
            framerate: 帧率

        Returns:
            GStreamerVideoTrack 实例
        """
        track = GStreamerVideoTrack(
            udp_port=udp_port,
            width=width,
            height=height,
            framerate=framerate,
        )
        cls._tracks[udp_port] = track
        return track

    @classmethod
    def get_track(cls, udp_port: int) -> Optional[GStreamerVideoTrack]:
        """
        获取已存在的轨道。

        Args:
            udp_port: UDP 端口

        Returns:
            GStreamerVideoTrack 实例或 None
        """
        return cls._tracks.get(udp_port)

    @classmethod
    async def stop_all(cls):
        """停止所有轨道。"""
        for track in cls._tracks.values():
            await track.stop()
        cls._tracks.clear()


# 便捷函数
def create_video_track(udp_port: int = 5000) -> GStreamerVideoTrack:
    """
    创建视频轨道的便捷函数。

    Args:
        udp_port: UDP 接收端口

    Returns:
        GStreamerVideoTrack 实例
    """
    return GStreamerVideoSourceFactory.create_track(
        udp_port=udp_port,
        width=1920,
        height=1080,
        framerate=30,
    )
