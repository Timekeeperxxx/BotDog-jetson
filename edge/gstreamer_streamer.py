#!/usr/bin/env python3
"""
边缘端 GStreamer 推流脚本。

职责边界：
- 从摄像头采集视频
- H.264 硬件编码
- 通过 RTP UDP 推流到后端
- 支持测试源模式

部署位置：Jetson 设备
依赖：GStreamer 1.0 + H.264 编码器插件
"""

import argparse
import sys
import time

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib


class GStreamerStreamer:
    """
    GStreamer 推流器。

    从视频源采集并推流到后端服务器。
    """

    def __init__(
        self,
        source: str = "v4l2src",
        device: str = "/dev/video0",
        width: int = 3840,
        height: int = 2160,
        framerate: int = 30,
        bitrate: int = 1000000,  # 1Mbps 激进优化（适配 1.64Mbps 带宽）
        host: str = "127.0.0.1",
        port: int = 5000,
        bind_address: str = "0.0.0.0",
        passthrough: bool = False,
    ):
        """
        初始化推流器。

        Args:
            source: 视频源类型（v4l2src/videotestsrc/rtsp）
            device: 设备路径或 RTSP URL
            width: 视频宽度
            height: 视频高度
            framerate: 帧率
            bitrate: 码率（bps）
            host: 目标主机
            port: 目标端口
            bind_address: 绑定地址（用于多网卡环境）
            passthrough: 直通模式（RTSP→UDP 不重新编码）
        """
        self.source = source
        self.device = device
        self.width = width
        self.height = height
        self.framerate = framerate
        self.bitrate = bitrate
        self.host = host
        self.port = port
        self.bind_address = bind_address
        self.passthrough = passthrough
        self.pipeline: Gst.Pipeline | None = None
        self.loop = GLib.MainLoop()

    def build_pipeline(self) -> str:
        """
        构建 GStreamer 管道字符串。

        Returns:
            管道描述字符串
        """
        # 视频源部分
        if self.source == "videotestsrc":
            # 测试源（用于开发测试）
            source_pipeline = (
                f"videotestsrc pattern=ball is-live=true "
                f"! video/x-raw,width={self.width},height={self.height},framerate={self.framerate}/1"
            )
        elif self.source == "rtsp":
            # RTSP 网络摄像头（HM30 图传，HEVC H.265）
            # 透传模式：不解码，直接转发 H.265 RTP 流，节省巡逻狗算力
            source_pipeline = (
                f"rtspsrc location={self.device} latency=100 protocols=tcp timeout=10000000 retry=2 "
                f"! rtph265depay "
                f"! h265parse"
            )
            # RTSP 模式透传 H.265，后端负责解码
        elif self.source == "v4l2src":
            # USB/MIPI 摄像头
            source_pipeline = (
                f"{self.source} device={self.device} "
                f"! video/x-raw,width={self.width},height={self.height},framerate={self.framerate}/1 "
                f"! videoconvert"
            )
        elif self.source == "nvarguscamerasrc":
            # Jetson MIPI CSI 摄像头
            source_pipeline = (
                f"{self.source} "
                f"! 'video/x-raw(memory:NVMM),width={self.width},height={self.height},format=NV12,framerate={self.framerate}/1' "
                f"! nvvidconv "
                f"! 'video/x-raw,width={self.width},height={self.height},format=I420'"
            )
        else:
            raise ValueError(f"不支持的视频源: {self.source}")

        # 编码器部分
        encoder_pipeline = self._build_encoder()

        # 完整管道（H.265 编码，RTSP 透传模式）
        if self.source == "rtsp" and not encoder_pipeline:
            # RTSP 透传模式：直接转发 H.265
            pipeline_str = (
                f"{source_pipeline} "
                f"! rtph265pay config-interval=1 pt=96 "    # H.265 RTP 负载
                f"! udpsink host={self.host} port={self.port} bind-address={self.bind_address} "
                f"buffer-size=2097152 "
                f"sync=false "
                f"qos=true"
            )
        else:
            # 其他源：需要编码
            pipeline_str = (
                f"{source_pipeline} "
                f"{encoder_pipeline} "
                f"! rtph265pay config-interval=1 pt=96 "    # H.265 RTP 负载
                f"! udpsink host={self.host} port={self.port} bind-address={self.bind_address} "
                f"buffer-size=2097152 "
                f"sync=false "
                f"qos=true"
            )

        return pipeline_str

    def _build_encoder(self) -> str:
        """
        构建 H.265 编码器管道（透传模式）。

        RTSP 源直接透传，不需要重新编码。
        其他源（videotestsrc、摄像头）才需要编码。

        Returns:
            编码器管道字符串（空字符串表示透传）
        """
        # RTSP 模式直接透传 H.265，不需要编码
        if self.source == "rtsp":
            return ""  # 透传模式

        # 其他源使用 H.265 编码器（后端会解码）
        # Jetson 硬件 H.265 编码器（优先）
        encoders = [
            # Jetson Xavier NX / Orin (H.265)
            "nvv4l2h265enc",
            # Jetson Nano / TX2 (H.265)
            "omxh265enc",
            # 软件编码（降级为 H.265）
            "x265enc",
        ]

        for encoder in encoders:
            try:
                # 尝试创建元素以检查是否可用
                element_factory = Gst.ElementFactory.find(encoder)
                if element_factory:
                    if encoder == "nvv4l2h265enc":
                        return (
                            f"! {encoder} bitrate={self.bitrate // 1000} "
                            f"! 'video/x-h265,profile=main'"
                        )
                    elif encoder == "omxh265enc":
                        return (
                            f"! {encoder} target-bitrate={self.bitrate} control-rate=variable "
                            f"! 'video/x-h265,profile=main'"
                        )
                    else:  # x265enc
                        return (
                            f"! {encoder} bitrate={self.bitrate // 1000} speed-preset=ultrafast tune=zerolatency "
                            f"! video/x-h265,profile=main"
                        )
            except Exception:
                continue

        raise RuntimeError("没有可用的 H.265 编码器")

    def start(self):
        """启动推流。"""
        # 初始化 GStreamer
        Gst.init(None)

        # 构建管道
        pipeline_str = self.build_pipeline()
        print(f"GStreamer 管道:\n{pipeline_str}")

        # 创建管道
        try:
            self.pipeline = Gst.parse_launch(pipeline_str)
        except Exception as e:
            print(f"错误: 无法创建 GStreamer 管道: {e}")
            sys.exit(1)

        if not self.pipeline:
            print("错误: GStreamer 管道创建失败")
            sys.exit(1)

        # 监听总线消息
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()

        def on_message(bus, message):
            """处理总线消息。"""
            t = message.type

            if t == Gst.MessageType.EOS:
                print("收到流结束消息")
                self.loop.quit()

            elif t == Gst.MessageType.ERROR:
                err, debug = message.parse_error()
                print(f"错误: {err}")
                print(f"调试信息: {debug}")
                self.loop.quit()

            elif t == Gst.MessageType.WARNING:
                err, debug = message.parse_warning()
                print(f"警告: {err}")

            elif t == Gst.MessageType.STATE_CHANGED:
                if message.src == self.pipeline:
                    old_state, new_state, pending_state = message.parse_state_changed()
                    print(f"管道状态: {old_state} -> {new_state}")

        bus.connect("message", on_message)

        # 启动管道
        print("启动推流...")
        ret = self.pipeline.set_state(Gst.State.PLAYING)

        if ret == Gst.StateChangeReturn.FAILURE:
            print("错误: 无法启动管道")
            sys.exit(1)

        # 运行主循环
        try:
            self.loop.run()
        except KeyboardInterrupt:
            print("\n收到中断信号，停止推流...")

        # 清理
        self.stop()

    def stop(self):
        """停止推流。"""
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            print("管道已停止")
        self.loop.quit()


def main():
    """主函数。"""
    parser = argparse.ArgumentParser(description="BotDog 边缘端 GStreamer 推流器")

    # 视频源配置
    parser.add_argument(
        "--source",
        choices=["v4l2src", "videotestsrc", "nvarguscamerasrc", "rtsp"],
        default="videotestsrc",
        help="视频源类型（默认: videotestsrc）",
    )
    parser.add_argument(
        "--device",
        default="/dev/video0",
        help="设备路径（默认: /dev/video0）",
    )

    # 视频参数
    parser.add_argument(
        "--width", type=int, default=3840, help="视频宽度（默认: 3840）"
    )
    parser.add_argument(
        "--height", type=int, default=2160, help="视频高度（默认: 2160）"
    )
    parser.add_argument(
        "--framerate", type=int, default=30, help="帧率（默认: 30）"
    )
    parser.add_argument(
        "--bitrate", type=int, default=8000000, help="码率（默认: 8000000）"
    )

    # 网络配置
    parser.add_argument(
        "--host", default="192.168.144.40", help="目标主机（默认: 192.168.144.40）"
    )
    parser.add_argument("--port", type=int, default=5000, help="目标端口（默认: 5000）")
    parser.add_argument(
        "--bind-address", default="192.168.144.40",
        help="绑定地址（默认: 192.168.144.40，用于多网卡环境）"
    )

    args = parser.parse_args()

    # 创建推流器
    streamer = GStreamerStreamer(
        source=args.source,
        device=args.device,
        width=args.width,
        height=args.height,
        framerate=args.framerate,
        bitrate=args.bitrate,
        host=args.host,
        port=args.port,
        bind_address=args.bind_address,
    )

    # 启动推流
    streamer.start()


if __name__ == "__main__":
    main()
