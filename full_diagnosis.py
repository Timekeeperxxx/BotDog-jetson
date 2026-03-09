#!/usr/bin/env python3
"""
完整链路诊断
"""

import subprocess
import sys
import time

print("=" * 80)
print("完整链路诊断")
print("=" * 80)

# 1. 检查测试推流是否正在运行
print("\n[1] 检查测试推流进程...")
try:
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq gst-launch-1.0.exe"],
        capture_output=True,
        text=True,
        timeout=5
    )

    if "gst-launch-1.0.exe" in result.stdout:
        print("[OK] 测试推流正在运行")
        # 提取 PID
        for line in result.stdout.split("\n"):
            if "gst-launch-1.0.exe" in line:
                print(f"  {line.strip()}")
    else:
        print("[WARNING] 未找到测试推流进程")
        print("请启动: python push_test_stream.py")
        sys.exit(1)
except Exception as e:
    print(f"[ERROR] 检查进程失败: {e}")
    sys.exit(1)

# 2. 检查 UDP 端口 5000
print("\n[2] 检查 UDP 端口 5000...")
try:
    result = subprocess.run(
        ["netstat", "-an"],
        capture_output=True,
        text=True,
        timeout=5
    )

    udp_5000_found = False
    for line in result.stdout.split("\n"):
        if ":5000" in line and "UDP" in line:
            udp_5000_found = True
            print(f"[OK] UDP 端口 5000 已被监听:")
            print(f"  {line.strip()}")

    if not udp_5000_found:
        print("[WARNING] UDP 端口 5000 未被监听")
        print("后端可能没有启动 WebRTC 连接")
except Exception as e:
    print(f"[ERROR] 检查端口失败: {e}")

# 3. 测试 UDP 数据接收
print("\n[3] 测试 UDP 数据接收（5 秒）...")
print("启动简单的 UDP 接收器...")

import socket

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.settimeout(5.0)
sock.bind(("0.0.0.0", 5001))  # 绑定到 5001 避免冲突

print(f"UDP socket 已绑定到端口 5001")
print(f"监听来自 192.168.144.30 的数据...")

try:
    data, addr = sock.recvfrom(65536)
    print(f"\n[OK] 收到 UDP 数据:")
    print(f"  源地址: {addr[0]}:{addr[1]}")
    print(f"  数据大小: {len(data)} 字节")
    print(f"  前16字节: {data[:16].hex()}")
except socket.timeout:
    print("\n[TIMEOUT] 5 秒内未收到 UDP 数据")
    print("可能原因:")
    print("  1. 测试推流未运行")
    print("  2. 推流发送到错误的端口")
    print("  3. 防火墙阻止了 UDP 流量")
finally:
    sock.close()

# 4. 检查后端进程
print("\n[4] 检查后端进程...")
try:
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq python.exe"],
        capture_output=True,
        text=True,
        timeout=5
    )

    python_found = False
    for line in result.stdout.split("\n"):
        if "python.exe" in line and ("run_backend" in line or "uvicorn" in line.lower()):
            python_found = True
            print(f"[OK] 后端进程运行中:")
            print(f"  {line.strip()}")

    if not python_found:
        print("[WARNING] 未找到后端进程")
        print("请启动: python run_backend.py")
except Exception as e:
    print(f"[ERROR] 检查后端失败: {e}")

print("\n" + "=" * 80)
print("诊断完成")
print("=" * 80)

print("\n下一步:")
print("1. 确保测试推流正在运行: python push_test_stream.py")
print("2. 确保后端正在运行: python run_backend.py")
print("3. 在浏览器中刷新页面并查看控制台日志")
print("4. 检查后端终端是否有 GStreamer 日志")
