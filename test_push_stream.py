#!/usr/bin/env python3
"""
调试推流问题
"""

import subprocess
import sys
import time

print("=" * 80)
print("测试 GStreamer 推流管道")
print("=" * 80)

# 测试 1: 最简单的管道
print("\n[测试 1] videotestsrc -> fakesink")
pipeline1 = 'gst-launch-1.0 -q videotestsrc num-buffers=10 ! fakesink'

print(f"命令: {pipeline1}")
proc1 = subprocess.run(pipeline1, shell=True, capture_output=True, text=True, timeout=10)

if proc1.returncode == 0:
    print("[OK] 基本 GStreamer 工作正常")
else:
    print(f"[失败] 返回码: {proc1.returncode}")
    if proc1.stderr:
        print(f"错误: {proc1.stderr[:500]}")

# 测试 2: H.265 编码
print("\n[测试 2] videotestsrc -> rtph265pay -> fakesink")
pipeline2 = (
    'gst-launch-1.0 -q '
    'videotestsrc num-buffers=10 '
    '! video/x-raw,width=1280,height=720,framerate=30/1 '
    '! rtph265pay '
    '! fakesink'
)

print(f"命令: {pipeline2}")
proc2 = subprocess.run(pipeline2, shell=True, capture_output=True, text=True, timeout=10)

if proc2.returncode == 0:
    print("[OK] H.265 编码工作正常")
else:
    print(f"[失败] 返回码: {proc2.returncode}")
    if proc2.stderr:
        print(f"错误: {proc2.stderr[:500]}")

# 测试 3: UDP 发送
print("\n[测试 3] videotestsrc -> UDP 发送")
pipeline3 = (
    'gst-launch-1.0 -q '
    'videotestsrc num-buffers=10 '
    '! video/x-raw,width=640,height=480,framerate=30/1 '
    '! rtph265pay '
    '! udpsink host=127.0.0.1 port=9999 sync=false'
)

print(f"命令: {pipeline3}")
proc3 = subprocess.run(pipeline3, shell=True, capture_output=True, text=True, timeout=10)

if proc3.returncode == 0:
    print("[OK] UDP 发送工作正常")
else:
    print(f"[失败] 返回码: {proc3.returncode}")
    if proc3.stderr:
        print(f"错误: {proc3.stderr[:500]}")

print("\n" + "=" * 80)
print("测试完成")
print("=" * 80)
