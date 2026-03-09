#!/usr/bin/env python3
"""
简单网络连通性测试
"""

import subprocess
import sys

print("=" * 80)
print("网络连通性测试")
print("=" * 80)

# 测试 1: ping
print("\n[测试 1] Ping 目标主机...")
ping_proc = subprocess.run(
    ["ping", "-n", "2", "192.168.144.30"],
    capture_output=True,
    text=True
)
if ping_proc.returncode == 0:
    print("[OK] Ping 成功")
    print(f"延迟: {ping_proc.stdout}")
else:
    print(f"[失败] Ping 失败")

# 测试 2: 测试端口 5000
print("\n[测试 2] 测试端口 5000...")
import socket
try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2)
    result = sock.connect_ex(("192.168.144.30", 5000))
    sock.close()
    if result == 0:
        print("[OK] 端口 5000 开放")
    else:
        print(f"[失败] 端口 5000 不可用 (错误码: {result})")
except Exception as e:
    print(f"[错误] 无法连接端口: {e}")

# 测试 3: 测试端口 9999
print("\n[测试 3] 测试端口 9999...")
try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2)
    result = sock.connect_ex(("192.168.144.30", 9999))
    sock.close()
    if result == 0:
        print("[OK] 端口 9999 开放")
    else:
        print(f"[失败] 端口 9999 不可用 (错误码: {result})")
except Exception as e:
    print(f"[错误] 无法连接端口: {e}")

# 测试 4: 简单的 GStreamer 测试
print("\n[测试 4] GStreamer 基本测试...")
gst_proc = subprocess.run(
    "gst-launch-1.0 videotestsrc num-buffers=5 ! fakesink",
    shell=True,
    capture_output=True,
    text=True
)

if gst_proc.returncode == 0:
    print("[OK] GStreamer 基本功能正常")
else:
    print(f"[失败] GStreamer 错误")
    if gst_proc.stderr:
        print(f"错误: {gst_proc.stderr[:500]}")

print("\n" + "=" * 80)
print("测试完成")
print("=" * 80)
