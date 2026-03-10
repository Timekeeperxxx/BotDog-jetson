#!/usr/bin/env python3
"""
GStreamer 视频源轨道 - RTSP 直连真实相机版本

关键架构改动：
1. RTSP 直连：rtspsrc location=rtsp://192.168.144.25:8554/main.264
2. decodebin 自动解码：自动选择 H.264/H.265 解码器
3. 内部 TCP 环回：tcpserversink host=127.0.0.1 port=6000（避免 Windows stdout 死锁）
4. Python TCP 客户端：socket.SOCK_STREAM 连接 127.0.0.1:6000
5. I420 原始帧数据：video/x-raw,format=I420
6. 同步 stop() 方法：无 RuntimeWarning
7. 真实帧验证日志：🔥 [RTSP 接流] 成功读取真实画面帧 #{frame_count}
"""

import asyncio
import fractions
import socket
import subprocess
import threading
import time
from typing import Optional

from av import VideoFrame
from aiortc import MediaStreamTrack


class GStreamerVideoTrack(MediaStreamTrack):
    """
    GStreamer 视频轨道 - RTSP 直连真实相机版本

    架构：RTSP Camera -> decodebin -> TCP Server(6000) -> Python TCP Client -> WebRTC
    """

    kind = "video"

    def __init__(
        self,
        rtsp_url: str = "rtsp://192.168.144.25:8554/main.264",
        tcp_port: int = 6000,
        width: int = 1920,
        height: int = 1080,
        framerate: int = 30,
    ):
        super().__init__()
        self.rtsp_url = rtsp_url
        self.tcp_port = tcp_port
        self.width = width
        self.height = height
        self.framerate = framerate
        self._queue: asyncio.Queue[Optional[VideoFrame]] = asyncio.Queue(maxsize=30)
        self._started = False
        self._process: Optional[subprocess.Popen] = None
        self._task: Optional[asyncio.Task] = None
        self._read_thread: Optional[threading.Thread] = None
        self._tcp_socket: Optional[socket.socket] = None
        self._frame_size = width * height * 3 // 2  # YUV420P = 1.5 bytes per pixel

    def start(self):
        """启动 GStreamer RTSP 管道（同步方法）"""
        if self._started:
            return

        print(f"\n{'='*80}")
        print(f"启动 GStreamer 视频管道（RTSP 直连真实相机）：")
        print(f"{'='*80}")
        print(f"输入源: RTSP {self.rtsp_url}")
        print(f"解码器: decodebin (自动选择)")
        print(f"内部输出: TCP 127.0.0.1:{self.tcp_port} (避免 stdout 死锁)")
        print(f"分辨率: {self.width}x{self.height} @ {self.framerate} FPS")
        print(f"网络延迟: 100ms (抗撕裂优化)")
        print(f"{'='*80}\n")

        # RTSP -> decodebin -> TCP 环回（优化抗撕裂版本 - 100ms 低延迟）
        # 关键优化：
        # 1. latency=100：100ms 缓冲，平衡延迟和画质（可调 50-200）
        # 2. drop-on-latency=true：超时帧直接丢弃，不输出撕裂画面
        # 3. rtpjitterbuffer latency=100：RTP 层防抖动缓冲
        pipeline = f'gst-launch-1.0 -q -e rtspsrc location={self.rtsp_url} latency=100 drop-on-latency=true ! rtpjitterbuffer latency=100 do-lost=true ! decodebin ! videoconvert ! video/x-raw,format=I420,width={self.width},height={self.height},framerate={self.framerate}/1 ! tcpserversink host=127.0.0.1 port={self.tcp_port} sync=false'

        print(f"GStreamer Pipeline:\n{pipeline}\n")

        try:
            # 启动 GStreamer RTSP 接流进程
            print(f"启动 RTSP 接流和自动解码...")
            self._process = subprocess.Popen(
                pipeline,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                shell=True
            )

            # 等待 GStreamer TCP 服务器启动
            print(f"等待 TCP 服务器启动...")
            time.sleep(2.0)

            # 检查进程是否启动成功
            if self._process.poll() is not None:
                returncode = self._process.returncode
                print(f"[失败] GStreamer 进程退出，代码: {returncode}")

                # 读取错误输出
                try:
                    stderr_output = self._process.stderr.read()
                    if stderr_output:
                        stderr_str = stderr_output.decode('utf-8', errors='ignore')
                        print(f"错误输出:\n{stderr_str[-1000:]}")
                except:
                    pass

                raise RuntimeError(f"GStreamer 启动失败，返回码: {returncode}")

            print(f"[OK] GStreamer 进程已启动 (PID: {self._process.pid})")

            # 连接到 GStreamer TCP 服务器
            print(f"连接到 TCP 服务器 127.0.0.1:{self.tcp_port}...")
            for attempt in range(10):
                try:
                    self._tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    self._tcp_socket.connect(("127.0.0.1", self.tcp_port))
                    print(f"[OK] TCP 连接已建立")
                    break
                except Exception as e:
                    print(f"[尝试 {attempt + 1}/10] TCP 连接失败: {e}")
                    if self._tcp_socket:
                        self._tcp_socket.close()
                    time.sleep(0.5)
            else:
                raise RuntimeError("TCP 连接超时")

            # 启动帧读取线程
            self._read_thread = threading.Thread(
                target=self._read_frames,
                daemon=True
            )
            self._read_thread.start()

            self._started = True

            # 启动进程监控任务
            self._task = asyncio.create_task(self._monitor_process())

            print(f"[OK] 帧读取线程已启动")
            print(f"[验证] 等待真实相机画面...\n")

        except Exception as e:
            print(f"[失败] 启动失败: {e}")
            import traceback
            traceback.print_exc()

            if self._process:
                try:
                    self._process.terminate()
                    self._process.wait(timeout=1)
                except:
                    self._process.kill()
                self._process = None
            if self._tcp_socket:
                self._tcp_socket.close()
                self._tcp_socket = None
            raise

    def stop(self):
        """停止 GStreamer RTSP 管道（同步方法）"""
        if not self._started:
            return

        self._started = False

        if self._task:
            self._task.cancel()

        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None

        if self._read_thread and self._read_thread.is_alive():
            self._read_thread.join(timeout=2)

        if self._tcp_socket:
            self._tcp_socket.close()
            self._tcp_socket = None

        print("[OK] GStreamer RTSP 进程已停止")

    def _read_frames(self):
        """从 TCP Socket 读取 I420 原始帧数据"""
        buffer = bytearray()
        frame_count = 0

        print(f"[读取线程] 开始从 TCP 读取 I420 真实画面数据...")

        try:
            while self._started and self._tcp_socket:
                try:
                    # 疯狂读取，不让 TCP 缓冲区满
                    data = self._tcp_socket.recv(65536)
                    if not data:
                        print(f"[读取线程] TCP 连接已关闭")
                        break

                    buffer.extend(data)

                    # 处理完整帧
                    while len(buffer) >= self._frame_size:
                        # 提取 I420 数据
                        i420_data = bytes(buffer[:self._frame_size])
                        buffer = buffer[self._frame_size:]

                        try:
                            # 转换为 VideoFrame
                            video_frame = self._i420_bytes_to_videoframe(i420_data, self.width, self.height)

                            # 放入队列
                            self._queue.put_nowait(video_frame)

                            frame_count += 1
                            # 关键验证日志：每收到一帧就打印
                            print(f"🔥 [RTSP 接流] 成功读取真实画面帧 #{frame_count}")

                        except Exception as e:
                            print(f"[错误] 处理帧: {e}")
                            import traceback
                            traceback.print_exc()

                except Exception as e:
                    print(f"[错误] 读取 TCP: {e}")
                    import traceback
                    traceback.print_exc()
                    break

        except Exception as e:
            print(f"[错误] 读取帧循环: {e}")
            import traceback
            traceback.print_exc()
        finally:
            try:
                self._queue.put_nowait(None)
            except:
                pass
            print(f"[统计] 总共接收 {frame_count} 帧（真实相机画面）")

    def _i420_bytes_to_videoframe(self, i420_data: bytes, width: int, height: int) -> VideoFrame:
        """将 I420 字节数据转换为 VideoFrame"""
        frame = VideoFrame(width=width, height=height, format="yuv420p")

        y_size = width * height
        uv_size = y_size // 4

        # Y 平面
        frame.planes[0].update(i420_data[:y_size])

        # U 平面
        frame.planes[1].update(i420_data[y_size:y_size + uv_size])

        # V 平面
        frame.planes[2].update(i420_data[y_size + uv_size:y_size + 2 * uv_size])

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
                        print(f"[警告] GStreamer 进程异常退出，代码 {returncode}")
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
                print(f"[错误] 监控: {e}")
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

    _tracks: dict[str, GStreamerVideoTrack] = {}

    @classmethod
    def create_track(
        cls,
        rtsp_url: str = "rtsp://192.168.144.25:8554/main.264",
        tcp_port: int = 6000,
        width: int = 1920,
        height: int = 1080,
        framerate: int = 30,
    ) -> GStreamerVideoTrack:
        """创建视频轨道"""
        track = GStreamerVideoTrack(
            rtsp_url=rtsp_url,
            tcp_port=tcp_port,
            width=width,
            height=height,
            framerate=framerate,
        )
        key = f"{rtsp_url}:{tcp_port}"
        cls._tracks[key] = track
        return track

    @classmethod
    def get_track(cls, rtsp_url: str, tcp_port: int = 6000) -> Optional[GStreamerVideoTrack]:
        """获取已存在的轨道"""
        key = f"{rtsp_url}:{tcp_port}"
        return cls._tracks.get(key)

    @classmethod
    def stop_all(cls):
        """停止所有轨道（同步方法）"""
        for track in cls._tracks.values():
            track.stop()
        cls._tracks.clear()


def create_video_track(rtsp_url: str = "rtsp://192.168.144.25:8554/main.264") -> GStreamerVideoTrack:
    """创建视频轨道的便捷函数"""
    return GStreamerVideoSourceFactory.create_track(
        rtsp_url=rtsp_url,
        tcp_port=6000,
        width=1920,
        height=1080,
        framerate=30,
    )
