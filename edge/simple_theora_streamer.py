#!/usr/bin/env python3
"""
简单的GStreamer视频推流脚本 - 使用Theora编码器（不需要H.264）
"""

import sys
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib
import argparse
import time

class SimpleStreamer:
    def __init__(self, source='videotestsrc', width=1280, height=720, framerate=30,
                 host='127.0.0.1', port=5000):
        self.source = source
        self.width = width
        self.height = height
        self.framerate = framerate
        self.host = host
        self.port = port
        self.pipeline = None

    def build_pipeline(self):
        """构建GStreamer管道（使用Theora编码）"""

        # 构建源管道
        if self.source == 'videotestsrc':
            source_pipeline = f"videotestsrc pattern=ball ! video/x-raw,width={self.width},height={self.height},framerate={self.framerate}/1"
        elif self.source == 'v4l2src':
            source_pipeline = f"v4l2src ! video/x-raw,width={self.width},height={self.height},framerate={self.framerate}/1"
        else:
            source_pipeline = self.source

        # 完整的推流管道（使用Theora编码，兼容RTP）
        pipeline_str = (
            f"{source_pipeline} "
            f"! videoconvert "
            f"! theoraenc quality=30 bitrate=256 "
            f"! rtptheorapay "
            f"! udpsink host={self.host} port={self.port} sync=false"
        )

        return pipeline_str

    def start(self):
        """启动推流"""
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

        # 启动管道
        print("启动推流...")
        self.pipeline.set_state(Gst.State.PLAYING)

        # 获取总线并添加监控
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.on_bus_message)

        print(f"视频推流已启动: {self.source} -> udp://{self.host}:{self.port}")
        print("按 Ctrl+C 停止推流")

        # 运行主循环
        try:
            loop = GLib.MainLoop()
            loop.run()
        except KeyboardInterrupt:
            print("\n停止推流...")
            self.pipeline.set_state(Gst.State.NULL)
            print("推流已停止")

    def on_bus_message(self, bus, message):
        """处理GStreamer总线消息"""
        t = message.type
        if t == Gst.MessageType.EOS:
            print("收到流结束信号")
            self.pipeline.set_state(Gst.State.NULL)
        elif t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print(f"GStreamer 错误: {err}")
            print(f"调试信息: {debug}")
            self.pipeline.set_state(Gst.State.NULL)
        elif t == Gst.MessageType.WARNING:
            warning, debug = message.parse_warning()
            print(f"GStreamer 警告: {warning}")
        elif t == Gst.MessageType.STATE_CHANGED:
            if message.src == self.pipeline:
                old_state, new_state, pending_state = message.parse_state_changed()
                print(f"管道状态: {old_state.value_nick} -> {new_state.value_nick}")

def main():
    parser = argparse.ArgumentParser(description='简单的GStreamer视频推流（Theora编码）')
    parser.add_argument('--source', default='videotestsrc',
                       help='视频源: videotestsrc, v4l2src, 或自定义管道')
    parser.add_argument('--width', type=int, default=1280, help='视频宽度')
    parser.add_argument('--height', type=int, default=720, help='视频高度')
    parser.add_argument('--framerate', type=int, default=30, help='帧率')
    parser.add_argument('--host', default='127.0.0.1', help='目标主机')
    parser.add_argument('--port', type=int, default=5000, help='目标端口')

    args = parser.parse_args()

    streamer = SimpleStreamer(
        source=args.source,
        width=args.width,
        height=args.height,
        framerate=args.framerate,
        host=args.host,
        port=args.port
    )

    streamer.start()

if __name__ == "__main__":
    main()