#!/usr/bin/env python3
"""
调试 GStreamer 管道错误
"""

import subprocess
import sys

print("=" * 80)
print("调试 GStreamer UDP 接收管道")
print("=" * 80)

# 测试管道 - 添加更多调试信息
pipeline = (
    "gst-launch-1.0 -v "
    "udpsrc port=5000 "
    "caps='application/x-rtp,media=video,encoding-name=H265,payload=96' "
    "! rtpjitterbuffer latency=100 do-retransmission=true "
    "! rtph265depay "
    "! h265parse "
    "! d3d11h265dec "
    "! videoconvert "
    "! fakesink"
)

print("\n启动管道...")
print(f"管道: {pipeline}")
print("\n等待 5 秒...")

import time

proc = subprocess.Popen(
    pipeline,
    shell=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True
)

time.sleep(5)

# 终止进程
proc.terminate()
try:
    stdout, stderr = proc.communicate(timeout=3)
except subprocess.TimeoutExpired:
    proc.kill()
    stdout, stderr = proc.communicate()

print("\n" + "=" * 80)
print("STDOUT:")
print("=" * 80)
print(stdout[:1000] if stdout else "(空)")

print("\n" + "=" * 80)
print("STDERR:")
print("=" * 80)
print(stderr[:2000] if stderr else "(空)")

print("\n" + "=" * 80)
print("返回码:", proc.returncode)
print("=" * 80)

# 也测试一个简单的管道
print("\n\n" + "=" * 80)
print("测试简单管道（不使用 UDP）")
print("=" * 80)

pipeline2 = (
    "gst-launch-1.0 -v "
    "videotestsrc num-buffers=10 "
    "! video/x-raw,width=640,height=480 "
    "! x265enc "
    "! h265parse "
    "! d3d11h265dec "
    "! videoconvert "
    "! fakesink"
)

print(f"\n管道: {pipeline2}")
print("\n执行...")

result = subprocess.run(
    pipeline2,
    shell=True,
    capture_output=True,
    text=True,
    timeout=10
)

print("\n" + "=" * 80)
print("返回码:", result.returncode)
print("=" * 80)

if result.returncode == 0:
    print("[OK] 简单管道成功！")
else:
    print("[失败] 简单管道失败")
    print("\nSTDERR:")
    print(result.stderr[:1000])
