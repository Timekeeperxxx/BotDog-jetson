#!/usr/bin/env python3
"""
直接在命令行测试管道语法
"""

import subprocess
import sys

print("=" * 80)
print("GStreamer 管道语法测试")
print("=" * 80)

# 测试 UDP 接收（不使用复杂 caps）
print("\n[测试] UDP 接收（简化版）")
pipeline = (
    'gst-launch-1.0 -v '
    'udpsrc port=9999 '
    '! rtpjitterbuffer '
    '! rtph265depay '
    '! h265parse '
    '! d3d11h265dec '
    '! fakesink'
)

print(f"管道: {pipeline}")

print("\n启动管道（10秒）...")
proc = subprocess.Popen(
    pipeline,
    shell=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True
)

import time
time.sleep(10)

proc.terminate()
stdout, stderr = proc.communicate(timeout=3)

print(f"\n返回码: {proc.returncode}")

if proc.returncode == 0:
    print("[成功] 管道执行成功！")
else:
    print("[失败] 管道执行失败")
    if stderr:
        print(f"\n错误输出:\n{stderr[:1000]}")

print("\n" + "=" * 80)
