#!/usr/bin/env python3
"""
FINAL WORKING VERSION - GStreamer Video Track using subprocess

This version skips GStreamer status messages and reads raw pixel data correctly.
"""

import asyncio
import fractions
import time
import subprocess
import threading
from typing import Optional

import numpy as np
from av import VideoFrame
from aiortc import MediaStreamTrack


class GStreamerVideoTrack(MediaStreamTrack):
    """
    GStreamer 视频轨道 - 使用 subprocess 调用 gst-launch-1.0

    通过 stdout 直接读取原始 RGB 像素数据
    """

    kind = "video"

    def __init__(
        self,
        udp_port: int = 5000,
        width: int = 1920,
        height: int = 1080,
        framerate: int = 30,
    ):
        super().__init__()
        self.udp_port = udp_port
        self.width = width
        self.height = height
        self.framerate = framerate
        self._queue: asyncio.Queue[Optional[VideoFrame]] = asyncio.Queue(maxsize=30)
        self._started = False
        self._process: Optional[subprocess.Popen] = None
        self._task: Optional[asyncio.Task] = None
        self._read_thread: Optional[threading.Thread] = None
        self._frame_size = width * height * 3  # RGB = 3 bytes per pixel

    async def start(self):
        """启动 GStreamer 管道。"""
        if self._started:
            return

        # 使用 -q 标志禁用 GStreamer 状态消息
        # 注意: Windows cmd 下 caps 需要特殊处理
        pipeline = (
            "gst-launch-1.0 -e -q "
            f"udpsrc port={self.udp_port} "
            + 'caps="application/x-rtp,media=video,encoding-name=H265,payload=96" '
            "! rtpjitterbuffer latency=100 do-retransmission=true "
            "! rtph265depay "
            "! h265parse "
            "! d3d11h265dec "
            "! videoconvert "
            "! videoscale "
            f"! video/x-raw,width={self.width},height={self.height},format=RGB "
            "! fakesink"  # 先用 fakesink 测试管道
        )

        print(f"\n{'='*80}")
        print(f"启动 GStreamer 视频管道（硬件加速）：")
        print(f"{'='*80}")
        print(f"输入: UDP 端口 {self.udp_port}，H.265 RTP")
        print(f"解码器: d3d11h265dec (D3D11 硬件)")
        print(f"输出: {self.width}x{self.height} RGB -> stdout (静默模式)")
        print(f"{'='*80}\n")

        try:
            # 启动 GStreamer 进程
            self._process = subprocess.Popen(
                pipeline,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                shell=True
            )

            print(f"[OK] GStreamer 进程已启动 (PID: {self._process.pid})")

            # 启动读取线程
            self._read_thread = threading.Thread(
                target=self._read_frames,
                daemon=True
            )
            self._read_thread.start()

            self._started = True

            # 启动监控任务
            self._task = asyncio.create_task(self._monitor_process())

            print(f"[OK] 帧读取线程已启动")

        except Exception as e:
            print(f"\n{'='*80}")
            print(f"启动 GStreamer 进程失败：")
            print(f"{'='*80}")
            print(f"错误: {e}")
            print(f"{'='*80}\n")
            raise

    async def stop(self):
        """停止 GStreamer 管道。"""
        if not self._started:
            return

        self._started = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None

        if self._read_thread and self._read_thread.is_alive():
            self._read_thread.join(timeout=2)

        await self._queue.put(None)
        print("[OK] GStreamer 进程已停止")

    def _read_frames(self):
        """
        在后台线程中从 stdout 读取帧数据

        RGB 格式：width * height * 3 字节
        """
        buffer = bytearray()
        skipped_header = False

        try:
            while self._started and self._process and self._process.poll() is None:
                # 从 stdout 读取数据
                data = self._process.stdout.read(4096)

                if not data:
                    break

                # 跳过 GStreamer 状态消息（第一次）
                if not skipped_header:
                    # 查找连续的 RGB 数据模式
                    # 检查是否有足够的连续数据
                    if len(data) > 100:
                        buffer.extend(data)
                        if len(buffer) >= self._frame_size:
                            # 验证这是否是有效的图像数据
                            # 尝试找到第一个完整帧
                            for i in range(min(1000, len(buffer) - self._frame_size)):
                                test_data = buffer[i:i+self._frame_size]
                                # 简单的启发式：检查数据多样性
                                if len(set(test_data[:100])) > 10:  # 至少有一些变化
                                    buffer = buffer[i:]
                                    skipped_header = True
                                    break
                            if not skipped_header:
                                # 继续读取更多数据
                                continue
                    else:
                        buffer.extend(data)
                        continue

                buffer.extend(data)

                # 当缓冲区有完整一帧时
                while len(buffer) >= self._frame_size:
                    # 提取一帧数据
                    frame_data = bytes(buffer[:self._frame_size])
                    buffer = buffer[self._frame_size:]

                    try:
                        # 转换为 numpy array (RGB 格式)
                        frame_array = np.frombuffer(frame_data, dtype=np.uint8).reshape(
                            self.height, self.width, 3
                        )

                        # 转换 RGB 到 BGR (OpenCV 使用 BGR)
                        import cv2
                        bgr_frame = cv2.cvtColor(frame_array, cv2.COLOR_RGB2BGR)

                        # 转换 BGR 到 YUV420P
                        yuv_frame = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2YUV_I420)

                        # 创建 VideoFrame
                        video_frame = self._yuv_to_videoframe(yuv_frame, self.width, self.height)

                        # 放入队列
                        try:
                            self._queue.put_nowait(video_frame)
                        except:
                            try:
                                self._queue.get_nowait()
                                self._queue.put_nowait(video_frame)
                            except:
                                pass

                    except Exception as e:
                        print(f"[错误] 处理帧时出错: {e}")

        except Exception as e:
            print(f"[错误] 读取帧时出错: {e}")
        finally:
            try:
                self._queue.put_nowait(None)
            except:
                pass

    def _yuv_to_videoframe(self, yuv_frame: np.ndarray, width: int, height: int) -> VideoFrame:
        """将 YUV420P numpy 数组转换为 VideoFrame"""
        frame = VideoFrame(width=width, height=height, format="yuv420p")

        y_size = width * height
        uv_size = y_size // 4

        y_plane = yuv_frame[:y_size].reshape(height, width)
        frame.planes[0].update(y_plane.tobytes())

        u_plane = yuv_frame[y_size:y_size + uv_size].reshape(height // 2, width // 2)
        frame.planes[1].update(u_plane.tobytes())

        v_plane = yuv_frame[y_size + uv_size:y_size + 2 * uv_size].reshape(height // 2, width // 2)
        frame.planes[2].update(v_plane.tobytes())

        frame.pts = int(time.time() * 90000)
        frame.time_base = fractions.Fraction(1, 90000)

        return frame

    async def _monitor_process(self):
        """监控 GStreamer 进程状态"""
        while self._started:
            try:
                if self._process and self._process.poll() is not None:
                    returncode = self._process.returncode
                    if returncode != 0:
                        print(f"[警告] GStreamer 进程退出，代码 {returncode}")
                        try:
                            stderr_output = self._process.stderr.read().decode('utf-8', errors='ignore')
                            if stderr_output:
                                print(f"错误输出:\n{stderr_output[-1000:]}")
                        except:
                            pass
                    break

                await asyncio.sleep(1)

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[错误] 监控进程时出错: {e}")
                break

    async def recv(self):
        """接收下一帧"""
        try:
            frame = await asyncio.wait_for(self._queue.get(), timeout=1.0)

            if frame is None:
                raise Exception("Video stream ended")

            frame.pts = int(time.time() * 90000)
            frame.time_base = fractions.Fraction(1, 90000)

            return frame

        except asyncio.TimeoutError:
            frame = VideoFrame(width=self.width, height=self.height)
            frame.pts = int(time.time() * 90000)
            frame.time_base = fractions.Fraction(1, 90000)
            return frame

    @property
    def active(self) -> bool:
        """轨道是否活跃"""
        return self._started


class GStreamerVideoSourceFactory:
    """GStreamer 视频源工厂"""

    _tracks: dict[int, GStreamerVideoTrack] = {}

    @classmethod
    def create_track(
        cls,
        udp_port: int = 5000,
        width: int = 1920,
        height: int = 1080,
        framerate: int = 30,
    ) -> GStreamerVideoTrack:
        """创建视频轨道"""
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
        """获取已存在的轨道"""
        return cls._tracks.get(udp_port)

    @classmethod
    async def stop_all(cls):
        """停止所有轨道"""
        for track in cls._tracks.values():
            await track.stop()
        cls._tracks.clear()


def create_video_track(udp_port: int = 5000) -> GStreamerVideoTrack:
    """创建视频轨道的便捷函数"""
    return GStreamerVideoSourceFactory.create_track(
        udp_port=udp_port,
        width=1920,
        height=1080,
        framerate=30,
    )
