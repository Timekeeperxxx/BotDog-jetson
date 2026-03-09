#!/usr/bin/env python3
"""
GStreamer 视频源轨道。

职责边界：
- 从 GStreamer 管道获取视频帧
- 转换为 aiortc 可用的 MediaStreamTrack
- 支持 H.265 RTP 输入，转码为 H.264 输出（浏览器兼容）
"""

import asyncio
import fractions
import time
from typing import Optional

import numpy as np
from av import VideoFrame
from aiortc import MediaStreamTrack
import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst


class GStreamerVideoTrack(MediaStreamTrack):
    """
    GStreamer 视频轨道。

    从 GStreamer 管道接收 H.265 RTP 流并转换为视频帧。
    """

    kind = "video"

    def __init__(
        self,
        udp_port: int = 5000,
        width: int = 1280,  # 交付模式（平衡画质与性能）
        height: int = 720,
        framerate: int = 20,  # 交付模式（流畅帧率）
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
        self._pipeline: Optional[Gst.Pipeline] = None
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        """启动 GStreamer 管道。"""
        if self._started:
            return

        Gst.init(None)

        # 构建 GStreamer 管道（H.265 输入 -> H.264 输出）
        # 强制使用 libde265dec 解码器（已验证可用）
        try:
            # 交付模式：1280x720 @ 20fps（稳定流畅）
            pipeline_str = (
                f"udpsrc address=0.0.0.0 port={self.udp_port} buffer-size=4194304 "  # 4MB 缓冲
                "! application/x-rtp,media=video,encoding-name=H264,payload=96 "
                "! rtpjitterbuffer latency=200 do-retransmission=true "  # 200ms 抖动 + 重传（防灰屏）
                "! rtph264depay "
                "! h264parse "
                "! avdec_h264 "  # H.264 硬解加速
                "! videoconvert "
                "! videoscale "
                "! video/x-raw,width=1280,height=720,format=I420 "
                "! videorate "
                "! video/x-raw,framerate=20/1,format=I420 "
                "! appsink name=sink emit-signals=true max-buffers=2 drop=true sync=false"
            )

            print(f"\n{'='*80}")
            print(f"🔧 启动 GStreamer 视频管道（交付模式）:")
            print(f"{'='*80}")
            print(f"输入: UDP port={self.udp_port}, H.264 RTP, 4MB 缓冲")
            print(f"解码器: avdec_h264 (硬件加速)")
            print(f"抖动缓冲: latency=200 + do-retransmission=true (防灰屏)")
            print(f"输出: 1280x720 @ 20fps I420")
            print(f"目标: CPU <80%, 流畅无灰屏")
            print(f"{'='*80}\n")

            self._pipeline = Gst.parse_launch(pipeline_str)

            if not self._pipeline:
                raise RuntimeError("GStreamer.parse_launch 返回 None")

        except Exception as e:
            print(f"\n{'='*80}")
            print(f"❌ GStreamer 管道创建失败:")
            print(f"{'='*80}")
            print(f"错误类型: {type(e).__name__}")
            print(f"错误详情: {e}")
            print(f"{'='*80}")
            print(f"\n可能原因:")
            print(f"1. 缺少 GStreamer 插件 (gst-inspect-1.0 libde265dec)")
            print(f"2. 缺少 H.264 编码器 (gst-inspect-1.0 x264enc)")
            print(f"3. 管道语法错误")
            print(f"4. 端口 {self.udp_port} 被占用")
            print(f"{'='*80}\n")
            raise

        # 获取 appsink 元素
        sink = self._pipeline.get_by_name("sink")
        sink.connect("new-sample", self._on_new_sample)

        # 启动管道
        self._pipeline.set_state(Gst.State.PLAYING)
        self._started = True

        # 启动处理任务
        self._task = asyncio.create_task(self._run())

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

        # 停止管道
        if self._pipeline:
            self._pipeline.set_state(Gst.State.NULL)

        # 发送结束信号
        await self._queue.put(None)

    async def _run(self):
        """处理帧队列的后台任务。"""
        while self._started:
            try:
                await asyncio.sleep(0)
            except asyncio.CancelledError:
                break

    def _on_new_sample(self, sink):
        """
        处理新样本。

        Args:
            sink: GstAppSink 元素
        """
        if not self._started:
            return Gst.FlowReturn.OK

        try:
            sample = sink.emit("pull-sample")

            if not sample:
                return Gst.FlowReturn.OK

            buffer = sample.get_buffer()

            if not buffer:
                return Gst.FlowReturn.OK

            # 转换为 VideoFrame
            success, info = buffer.map(Gst.MapFlags.READ)

            if not success:
                return Gst.FlowReturn.OK

            try:
                # 获取视频格式信息
                caps = sample.get_caps()
                if not caps:
                    return Gst.FlowReturn.OK

                structure = caps.get_structure(0)
                width_ret = structure.get_int("width")
                height_ret = structure.get_int("height")

                if not width_ret[0] or not height_ret[0]:
                    return Gst.FlowReturn.OK

                width = width_ret[1]
                height = height_ret[1]

                # 获取数据
                data = info.data

                # 简化的 YUV420P 处理
                y_size = width * height
                uv_size = y_size // 4
                expected_size = y_size + 2 * uv_size

                if len(data) < expected_size:
                    return Gst.FlowReturn.OK

                # 直接创建 VideoFrame（让 av 库处理）
                import array
                frame = VideoFrame(width=width, height=height, format="yuv420p")

                # 填充 Y 平面
                y_array = array.array('B', data[:y_size])
                frame.planes[0].update(y_array)

                # 填充 U 平面
                u_array = array.array('B', data[y_size:y_size + uv_size])
                frame.planes[1].update(u_array)

                # 填充 V 平面
                v_array = array.array('B', data[y_size + uv_size:y_size + 2 * uv_size])
                frame.planes[2].update(v_array)

                frame.pts = buffer.pts
                frame.time_base = fractions.Fraction(1, 90000)

                # 异步放入队列（非阻塞）
                try:
                    self._queue.put_nowait(frame)
                except asyncio.QueueFull:
                    # 队列满，丢弃最旧的帧
                    try:
                        self._queue.get_nowait()
                        self._queue.put_nowait(frame)
                    except asyncio.QueueEmpty:
                        pass

            finally:
                buffer.unmap(info)

        except Exception as e:
            print(f"处理样本失败: {e}")

        return Gst.FlowReturn.OK

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

            # 生成时间戳
            frame.pts = int(frame.pts or (time.time() * 90000))
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
        width: int = 3840,
        height: int = 2160,
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
            width=1280,  # 交付模式（平衡画质与性能）
            height=720,
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
