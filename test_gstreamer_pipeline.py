#!/usr/bin/env python3
"""
逐步测试 GStreamer 推流管道
"""

import subprocess
import sys

print("=" * 80)
print("逐步测试 GStreamer 推流管道")
print("=" * 80)

# 测试 1: 最简单的管道
print("\n[测试 1] 最简单的管道 (videotestsrc -> fakesink)")
pipeline1 = 'gst-launch-1.0 -q videotestsrc num-buffers=30 ! fakesink'
print(f"命令: {pipeline1}")

try:
    proc1 = subprocess.run(pipeline1, shell=True, capture_output=True, text=True, timeout=10)
    if proc1.returncode == 0:
        print("[OK] 基本 GStreamer 工作正常")
    else:
        print(f"[失败] 返回码: {proc1.returncode}")
        if proc1.stderr:
            print(f"错误: {proc1.stderr[:500]}")
        sys.exit(1)
except Exception as e:
    print(f"[失败] {e}")
    sys.exit(1)

# 测试 2: 添加 H.264 编码
print("\n[测试 2] H.264 编码 (videotestsrc -> x264enc -> rtph264pay -> fakesink)")
pipeline2 = (
    'gst-launch-1.0 -q '
    'videotestsrc num-buffers=30 '
    '! video/x-raw,width=640,height=480,framerate=30/1 '
    '! x264enc tune=zerolatency speed-preset=ultrafast '
    '! rtph264pay '
    '! fakesink'
)
print(f"命令: {pipeline2}")

try:
    proc2 = subprocess.run(pipeline2, shell=True, capture_output=True, text=True, timeout=10)
    if proc2.returncode == 0:
        print("[OK] H.264 编码工作正常")
    else:
        print(f"[失败] 返回码: {proc2.returncode}")
        if proc2.stderr:
            print(f"错误: {proc2.stderr[:500]}")
        sys.exit(1)
except Exception as e:
    print(f"[失败] {e}")
    sys.exit(1)

# 测试 3: UDP 发送（发送到本地环回）
print("\n[测试 3] UDP 发送 (videotestsrc -> UDP 127.0.0.1:5000)")
pipeline3 = (
    'gst-launch-1.0 -q '
    'videotestsrc num-buffers=30 '
    '! video/x-raw,width=640,height=480,framerate=30/1 '
    '! x264enc tune=zerolatency speed-preset=ultrafast '
    '! rtph264pay '
    '! udpsink host=127.0.0.1 port=5000 sync=false'
)
print(f"命令: {pipeline3}")

try:
    proc3 = subprocess.run(pipeline3, shell=True, capture_output=True, text=True, timeout=10)
    if proc3.returncode == 0:
        print("[OK] UDP 发送工作正常")
    else:
        print(f"[失败] 返回码: {proc3.returncode}")
        if proc3.stderr:
            print(f"错误: {proc3.stderr[:500]}")
        sys.exit(1)
except Exception as e:
    print(f"[失败] {e}")
    sys.exit(1)

# 测试 4: 发送到实际目标
print("\n[测试 4] 发送到实际目标 (192.168.144.30:5000)")
pipeline4 = (
    'gst-launch-1.0 -q '
    'videotestsrc pattern=ball is-live=true '
    '! video/x-raw,width=1280,height=720,framerate=30/1 '
    '! videoconvert '
    '! x264enc bitrate=2000 tune=zerolatency speed-preset=ultrafast '
    '! rtph264pay config-interval=1 pt=96 '
    '! udpsink host=192.168.144.30 port=5000 sync=false bind-address=192.168.144.30'
)
print(f"命令: {pipeline4}")
print("注意: 此测试需要后端正在监听端口 5000")

try:
    proc4 = subprocess.Popen(pipeline4, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    print(f"[OK] 推流进程已启动 (PID: {proc4.pid})")
    print("等待 5 秒...")
    import time
    time.sleep(5)

    if proc4.poll() is None:
        print("[OK] 推流进程仍在运行")
        proc4.terminate()
        proc4.wait(timeout=3)
    else:
        print(f"[失败] 推流进程退出，代码: {proc4.returncode}")
        if proc4.stderr:
            print(f"错误: {proc4.stderr.read()[:500]}")
        sys.exit(1)

except Exception as e:
    print(f"[失败] {e}")
    sys.exit(1)

print("\n" + "=" * 80)
print("所有测试通过！")
print("=" * 80)
