#!/usr/bin/env python3
"""
修复 GStreamer 管道引号问题 - Windows 版本
"""

import subprocess
import sys
import time

print("=" * 80)
print("测试 GStreamer UDP 接收 - 修复版")
print("=" * 80)

# 方法1: 使用转义的引号
print("\n[测试 1] 使用转义引号")
pipeline1 = (
    'gst-launch-1.0 -q -e '
    f'udpsrc port=5000 caps="application/x-rtp,media=video,encoding-name=H265,payload=96" '
    '! rtpjitterbuffer latency=100 '
    '! rtph265depay '
    '! h265parse '
    '! d3d11h265dec '
    '! videoconvert '
    '! fakesink'
)

print(f"管道: {pipeline1}")

proc1 = subprocess.Popen(
    pipeline1,
    shell=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True
)

time.sleep(3)
proc1.terminate()
stdout1, stderr1 = proc1.communicate(timeout=3)

print(f"返回码: {proc1.returncode}")
if stderr1:
    print(f"STDERR: {stderr1[:500]}")

# 方法2: 测试带数据输出的管道
print("\n" + "=" * 80)
print("[测试 2] 带数据输出（使用 fdsink）")
pipeline2 = (
    'gst-launch-1.0 -q '
    'videotestsrc num-buffers=3 '
    '! video/x-raw,width=640,height=480,format=RGB '
    'fdsink fd=1'
)

print(f"管道: {pipeline2}")

proc2 = subprocess.Popen(
    pipeline2,
    shell=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE
)

time.sleep(2)
proc2.terminate()
try:
    stdout2, stderr2 = proc2.communicate(timeout=3)
except subprocess.TimeoutExpired:
    proc2.kill()
    stdout2, stderr2 = proc2.communicate()

print(f"返回码: {proc2.returncode}")
print(f"Stdout 大小: {len(stdout2)} 字节")
expected = 640 * 480 * 3 * 3
print(f"预期大小: {expected} 字节")

if len(stdout2) >= expected * 0.8:
    print("[成功] 从 fdsink fd=1 读取到数据！")
    print(f"实际数据: {len(stdout2)} 字节")
else:
    print("[警告] 数据大小不对")
    # 检查是否有 GStreamer 消息
    if len(stdout2) > 0:
        print(f"前 200 字节: {stdout2[:200]}")

# 方法3: 完整的 UDP 接收测试（带数据输出）
print("\n" + "=" * 80)
print("[测试 3] 完整 UDP 接收 + 数据输出")

# 先启动发送器
print("启动发送器...")
sender_pipeline = (
    'gst-launch-1.0 -q '
    'videotestsrc num-buffers=5 '
    '! video/x-raw,width=640,height=480,framerate=30/1 '
    '! x265enc '
    '! h265parse '
    '! rtph265pay '
    '! udpsink host=127.0.0.1 port=9999 sync=false'
)

sender_proc = subprocess.Popen(
    sender_pipeline,
    shell=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE
)

time.sleep(1)

# 启动接收器
print("启动接收器...")
receiver_pipeline = (
    'gst-launch-1.0 -q -e '
    'udpsrc port=9999 '
    'caps="application/x-rtp,media=video,encoding-name=H265,payload=96" '
    '! rtpjitterbuffer latency=100 '
    '! rtph265depay '
    '! h265parse '
    '! d3d11h265dec '
    '! videoconvert '
    '! video/x-raw,width=640,height=480,format=RGB '
    'fdsink fd=1'
)

print(f"接收器管道: {receiver_pipeline}")

receiver_proc = subprocess.Popen(
    receiver_pipeline,
    shell=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE
)

time.sleep(3)

# 终止进程
sender_proc.terminate()
receiver_proc.terminate()

try:
    sender_proc.wait(timeout=3)
except subprocess.TimeoutExpired:
    sender_proc.kill()

try:
    stdout3, stderr3 = receiver_proc.communicate(timeout=3)
except subprocess.TimeoutExpired:
    receiver_proc.kill()
    stdout3, stderr3 = receiver_proc.communicate()

print(f"\n接收器返回码: {receiver_proc.returncode}")
print(f"Stdout 大小: {len(stdout3)} 字节")
expected3 = 640 * 480 * 3 * 5
print(f"预期大小: {expected3} 字节")

if len(stdout3) >= expected3 * 0.5:
    print("[成功] 从 UDP H.265 流接收到数据！")
    print(f"实际数据: {len(stdout3)} 字节")
    print(f"完整率: {len(stdout3)/expected3*100:.1f}%")
else:
    print("[警告] 数据不足")
    if stderr3:
        print(f"错误: {stderr3[:500]}")

print("\n" + "=" * 80)
print("测试完成")
print("=" * 80)
