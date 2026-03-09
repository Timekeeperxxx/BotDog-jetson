#!/usr/bin/env python3
"""
从相机 RTSP 推流到后端

使用 ffmpeg 或 GStreamer 从 rtsp://192.168.144.25:8554/main.264
推送到 192.168.144.30:5000
"""

import subprocess
import sys
import time

def pull_rtsp_to_udp():
    """从相机拉取 RTSP 流并推送到 UDP"""
    print("=" * 80)
    print("相机 RTSP 推流器")
    print("=" * 80)
    print("\n相机: rtsp://192.168.144.25:8554/main.264")
    print("目标: 192.168.144.30:5000")

    # 方法 1: 使用 GStreamer (推荐)
    print("\n[方案 1] 使用 GStreamer")
    pipeline = (
        'gst-launch-1.0 -q '
        'rtspsrc location=rtsp://192.168.144.25:8554/main.264 latency=100 timeout=10000000 '
        '! rtph265depay '
        '! h265parse '
        '! rtph265pay config-interval=1 pt=96 '
        '! udpsink host=192.168.144.30 port=5000 sync=false buffer-size=2097152'
    )

    print(f"管道: {pipeline}")
    print("\n启动推流...")
    print("按 Ctrl+C 停止\n")

    try:
        proc = subprocess.Popen(
            pipeline,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        print(f"[OK] 推流进程已启动 (PID: {proc.pid})")

        # 实时读取 stderr 显示日志
        while True:
            line = proc.stderr.readline()
            if not line:
                if proc.poll() is not None:
                    break
                time.sleep(0.1)
                continue

            # 过滤重要信息
            if any(keyword in line.lower() for keyword in ['warning', 'error', 'stream', 'state']):
                print(f"[GStreamer] {line.strip()}")

            if proc.poll() is not None:
                break

        returncode = proc.wait()

        if returncode == 0:
            print(f"\n[成功] 推流正常结束")
        else:
            print(f"\n[失败] 推流异常退出，代码: {returncode}")

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

def test_with_videotestsrc():
    """使用测试源推流"""
    print("=" * 80)
    print("测试推流（videotestsrc）")
    print("=" * 80)
    print("\n目标: 192.168.144.30:5000")
    print("源: videotestsrc (测试图案)")

    pipeline = (
        'gst-launch-1.0 -q '
        'videotestsrc pattern=ball is-live=true '
        '! video/x-raw,width=1280,height=720,framerate=30/1 '
        '! videoconvert '
        '! x264enc bitrate=2000 tune=zerolatency speed-preset=ultrafast '
        '! rtph264pay '
        '! udpsink host=192.168.144.30 port=5000 sync=false'
    )

    print(f"\n管道: {pipeline}")
    print("\n启动推流...")
    print("按 Ctrl+C 停止\n")

    try:
        proc = subprocess.Popen(
            pipeline,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        print(f"[OK] 推流进程已启动 (PID: {proc.pid})")

        # 等待进程结束
        proc.wait()

    except KeyboardInterrupt:
        print("\n\n[中断] 用户停止推流")
        if 'proc' in locals():
            proc.terminate()
    except Exception as e:
        print(f"\n[错误] 推流失败: {e}")
        sys.exit(1)

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="相机 RTSP 推流器")
    parser.add_argument(
        "--test",
        action="store_true",
        help="使用测试源（videotsrc）而不是相机 RTSP"
    )

    args = parser.parse_args()

    if args.test:
        print("\n使用测试源推流...")
        test_with_videotestsrc()
    else:
        print("\n从相机 RTSP 推流...")
        pull_rtsp_to_udp()
