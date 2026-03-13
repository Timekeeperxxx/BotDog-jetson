"""
RTSP → H264 RTP → UDP 桥接（Windows, 无 gi）。

职责边界：
- 通过 gst-launch-1.0 启动/停止子进程
- 将 RTSP(H265) 转码为 H264 RTP 并输出到 UDP(127.0.0.1:5000)
"""

from __future__ import annotations

import subprocess
from typing import Optional

from .config import settings
from .logging_config import logger


class GstRtspBridge:
    def __init__(self) -> None:
        self._process: Optional[subprocess.Popen] = None

    def _build_pipeline(self, use_qsv: bool) -> str:
        if use_qsv:
            decoder = "qsvh265dec"
            encoder = "qsvh264enc bitrate=5000 rate-control=vbr target-usage=1 gop-size=1 b-frames=0"
        else:
            decoder = "avdec_h265"
            encoder = "x264enc tune=zerolatency speed-preset=superfast bitrate=12000 key-int-max=30 bframes=0"

        return (
            f"gst-launch-1.0 -q -e "
            f"rtspsrc location={settings.CAMERA_RTSP_URL} protocols=tcp latency=0 drop-on-latency=true "
            "! rtph265depay "
            "! h265parse "
            "! queue max-size-buffers=1 leaky=downstream "
            f"! {decoder} "
            "! videoconvert "
            "! video/x-raw,format=NV12 "
            f"! {encoder} "
            "! h264parse config-interval=1 "
            "! rtph264pay pt=96 mtu=1200 config-interval=1 "
            f"! udpsink host=127.0.0.1 port={settings.VIDEO_UDP_PORT} sync=false async=false"
        )

    def start(self) -> None:
        if self._process and self._process.poll() is None:
            return

        pipeline = self._build_pipeline(use_qsv=True)
        logger.info("启动 GStreamer RTSP→UDP 桥接")
        logger.info(pipeline)

        self._process = subprocess.Popen(
            pipeline,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=True,
        )

        try:
            self._process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            return

        logger.warning("QSV 管线启动失败，回退到 CPU 编解码")
        pipeline = self._build_pipeline(use_qsv=False)
        logger.info(pipeline)
        self._process = subprocess.Popen(
            pipeline,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=True,
        )

    def stop(self) -> None:
        if not self._process:
            return

        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()

        self._process = None
        logger.info("GStreamer RTSP→UDP 桥接已停止")

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None
