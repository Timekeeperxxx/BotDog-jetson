#!/usr/bin/env python3
"""
完整测试：UDP H.265 接收 + 数据读取
"""

import subprocess
import sys
import time

print("=" * 80)
print("UDP H.265 接收 + 数据读取测试")
print("=" * 80)

# 步骤 1: 启动发送器
print("\n[步骤 1] 启动 H.265 发送器...")
sender_pipeline = (
    'gst-launch-1.0 -q '
    'videotestsrc pattern=ball num-buffers=10 '
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

print(f"发送器 PID: {sender_proc.pid}")

time.sleep(1)  # 等待发送器启动

# 步骤 2: 启动接收器
print("\n[步骤 2] 启动 H.265 接收器（硬件解码）...")
receiver_pipeline = (
    'gst-launch-1.0 -q -e '
    'udpsrc port=9999 '
    '! application/x-rtp '
    '! rtpjitterbuffer latency=100 '
    '! rtph265depay '
    '! h265parse '
    '! d3d11h265dec '
    '! videoconvert '
    '! fdsink fd=1'
)

print(f"接收器管道: {receiver_pipeline}")

receiver_proc = subprocess.Popen(
    receiver_pipeline,
    shell=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE
)

print(f"接收器 PID: {receiver_proc.pid}")

# 步骤 3: 等待并读取数据
print("\n[步骤 3] 接收数据...")
time.sleep(3)

# 终止进程
sender_proc.terminate()
receiver_proc.terminate()

# 等待接收器完成并读取数据
try:
    stdout, stderr = receiver_proc.communicate(timeout=5)
except subprocess.TimeoutExpired:
    receiver_proc.kill()
    stdout, stderr = receiver_proc.communicate()

# 等待发送器完成
try:
    sender_proc.wait(timeout=3)
except subprocess.TimeoutExpired:
    sender_proc.kill()

# 步骤 4: 分析结果
print("\n[步骤 4] 结果分析")
print("=" * 80)
print(f"接收器返回码: {receiver_proc.returncode}")
print(f"Stdout 大小: {len(stdout)} 字节")

if len(stdout) > 0:
    print(f"\n[成功] 从 UDP H.265 流接收到数据！")
    print(f"数据大小: {len(stdout)} 字节")

    # 估算帧数（假设 640x480 RGB）
    frame_size = 640 * 480 * 3
    estimated_frames = len(stdout) / frame_size
    print(f"估算帧数: {estimated_frames:.1f} 帧")

    # 显示前 100 字节
    print(f"\n前 100 字节 (hex): {stdout[:100].hex()}")

    print("\n" + "=" * 80)
    print("SUCCESS!")
    print("H.265 硬件解码 + UDP 接收 + Python 读取全部工作正常！")
    print("=" * 80)
else:
    print(f"\n[失败] 没有接收到数据")
    if stderr:
        print(f"错误输出:\n{stderr.decode('utf-8', errors='ignore')[:1000]}")

print("\n" + "=" * 80)
print("测试完成")
print("=" * 80)
