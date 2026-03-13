#!/usr/bin/env python3
"""
UDP H264 RTP 视频轨道（Windows，无 gi）。

职责边界：
- 从 UDP VIDEO_UDP_PORT 接收 H264 RTP
- 解码为 VideoFrame 提供给 aiortc
"""

from __future__ import annotations

import asyncio
import fractions
import io
import threading
import time
from typing import Optional

import av
from av import VideoFrame
from aiortc import MediaStreamTrack


class GStreamerVideoTrack(MediaStreamTrack):
    """UDP H264 RTP 视频轨道。"""

    kind = "video"

    def __init__(
        self,
        udp_port: int,
        width: int = 1920,
        height: int = 1080,
        framerate: int = 30,
    ):
        super().__init__()
        self.udp_port = udp_port
        self.width = width
        self.height = height
        self.framerate = framerate
        self._queue: asyncio.Queue[Optional[VideoFrame]] = asyncio.Queue(maxsize=1)
        self._started = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._container: Optional[av.container.InputContainer] = None

    async def start(self):
        if self._started:
            return

        self._loop = asyncio.get_running_loop()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()
        self._started = True

    async def stop(self):
        if not self._started:
            return

        self._started = False
        self._stop_event.set()
        if self._container:
            try:
                self._container.close()
            except Exception:
                pass
            self._container = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        await self._queue.put(None)

    def _build_sdp(self) -> str:
        return (
            "v=0\n"
            "o=- 0 0 IN IP4 127.0.0.1\n"
            "s=H264 RTP\n"
            "c=IN IP4 127.0.0.1\n"
            "t=0 0\n"
            f"m=video {self.udp_port} RTP/AVP 96\n"
            "a=rtpmap:96 H264/90000\n"
            "a=fmtp:96 packetization-mode=1;profile-level-id=42e01f;level-asymmetry-allowed=1\n"
        )

    def _reader(self) -> None:
        sdp = self._build_sdp().encode("utf-8")
        options = {
            "protocol_whitelist": "file,udp,rtp",
            "fflags": "nobuffer",
            "flags": "low_delay",
            "analyzeduration": "0",
            "probesize": "32",
            "buffer_size": "52428800",
            "fifo_size": "52428800",
            "max_delay": "0",
            "reorder_queue_size": "0",
        }

        try:
            self._container = av.open(io.BytesIO(sdp), format="sdp", options=options)
            for frame in self._container.decode(video=0):
                if self._stop_event.is_set():
                    break
                if not self._loop:
                    continue
                try:
                    self._loop.call_soon_threadsafe(self._queue.put_nowait, frame)
                except asyncio.QueueFull:
                    try:
                        self._loop.call_soon_threadsafe(self._queue.get_nowait)
                        self._loop.call_soon_threadsafe(self._queue.put_nowait, frame)
                    except Exception:
                        pass
        except Exception:
            return

    async def recv(self) -> VideoFrame:
        try:
            frame = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            if frame is None:
                raise Exception("视频流已结束")
            frame.pts = int(frame.pts or (time.time() * 90000))
            frame.time_base = fractions.Fraction(1, 90000)
            return frame
        except asyncio.TimeoutError:
            fallback = VideoFrame(width=self.width, height=self.height)
            fallback.pts = int(time.time() * 90000)
            fallback.time_base = fractions.Fraction(1, 90000)
            return fallback

    @property
    def active(self) -> bool:
        return self._started


class GStreamerVideoSourceFactory:
    _tracks: dict[int, GStreamerVideoTrack] = {}

    @classmethod
    def create_track(
        cls,
        udp_port: int,
        width: int = 1920,
        height: int = 1080,
        framerate: int = 30,
    ) -> GStreamerVideoTrack:
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
        return cls._tracks.get(udp_port)

    @classmethod
    async def stop_all(cls):
        for track in cls._tracks.values():
            await track.stop()
        cls._tracks.clear()
