#!/usr/bin/env python3
"""
边缘端 GStreamer 推流器 - 无 PyGObject 依赖版本
使用 subprocess 调用 gst-launch-1.0
"""

import subprocess
import sys
import argparse
import time

def push_stream(args):
    """推流函数"""
    print("=" * 80)
    print("BotDog 边缘端推流器")
    print("=" * 80)

    # 构建管道
    if args.source == "videotestsrc":
        # 测试源 - 使用 H.264 (更简单，兼容性更好)
        pipeline = (
            'gst-launch-1.0 -q '
            f'videotestsrc pattern=ball is-live=true '
            f'! video/x-raw,width={args.width},height={args.height},framerate={args.framerate}/1 '
            '! videoconvert '
            '! x264enc bitrate={args.bitrate//1000} tune=zerolatency speed-preset=ultrafast '
            '! rtph264pay '
            f'! udpsink host={args.host} port={args.port} sync=false'
        )
    elif args.source == "rtsp":
        # RTSP 源（需要 avdec_h265）
        pipeline = (
            'gst-launch-1.0 -q -e '
            f'rtspsrc location={args.source} latency=100 '
            f'! rtph265depay '
            f'! h265parse '
            f'! avdec_h265 '
            f'! rtph265pay '
            f'! udpsink host={args.host} port={args.port} sync=false'
        )
    else:
        print(f"不支持的视频源: {args.source}")
        print("支持: videotestsrc, rtsp")
        sys.exit(1)

    print(f"\n推流配置:")
    print(f"  源: {args.source}")
    print(f"  目标: {args.host}:{args.port}")
    print(f"  分辨率: {args.width}x{args.height}")
    print(f"  帧率: {args.framerate}fps")
    print(f"  码率: {args.bitrate//1000}Mbps")

    print(f"\n管道命令:")
    print(f"  {pipeline}")

    print(f"\n启动推流...")
    print("按 Ctrl+C 停止\n")

    try:
        proc = subprocess.Popen(
            pipeline,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        print(f"推流进程已启动 (PID: {proc.pid})")
        print(f"正在推送到 {args.host}:{args.port}...")

        # 等待进程结束
        proc.wait()

        if proc.returncode == 0:
            print(f"\n[成功] 推流正常结束")
        else:
            print(f"\n[失败] 推流异常退出，代码: {proc.returncode}")

    except KeyboardInterrupt:
        print("\n\n[中断] 用户停止推流")
        if 'proc' in locals():
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
    except Exception as e:
        print(f"\n[错误] 推流失败: {e}")
        sys.exit(1)

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="BotDog 边缘端推流器")

    # 视频源
    parser.add_argument(
        "--source",
        choices=["videotestsrc", "rtsp"],
        default="videotestsrc",
        help="视频源（videotestsrc/rtsp）"
    )

    # 视频参数
    parser.add_argument("--width", type=int, default=1280, help="视频宽度")
    parser.add_argument("--height", type=int, default=720, help="视频高度")
    parser.add_argument("--framerate", type=int, default=30, help="帧率")
    parser.add_argument("--bitrate", type=int, default=2000000, help="码率（bps）")

    # 网络参数
    parser.add_argument("--host", default="192.168.144.30", help="目标主机")
    parser.add_argument("--port", type=int, default=5000, help="目标端口")

    args = parser.parse_args()

    push_stream(args)

if __name__ == "__main__":
    main()
