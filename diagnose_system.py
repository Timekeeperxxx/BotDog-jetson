#!/usr/bin/env python3
"""
系统状态诊断脚本

检查所有关键组件是否正常运行
"""

import subprocess
import socket
import time
import sys

print("=" * 80)
print("BotDog 系统状态诊断")
print("=" * 80)

# 1. 检查后端服务
print("\n[1] 检查后端服务 (端口 8000)...")
try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2)
    result = sock.connect_ex(("192.168.144.30", 8000))
    sock.close()
    if result == 0:
        print("    [OK] 后端服务正在运行")
    else:
        print("    [ERROR] 后端服务未运行，请先启动: python run_backend.py")
        sys.exit(1)
except Exception as e:
    print(f"    [ERROR] 无法连接到后端: {e}")
    sys.exit(1)

# 2. 检查 UDP 端口 5000
print("\n[2] 检查 UDP 端口 5000 (视频接收端口)...")
try:
    # Windows: 使用 netstat
    result = subprocess.run(
        ["netstat", "-an"],
        capture_output=True,
        text=True,
        timeout=5
    )

    if ":5000" in result.stdout and "UDP" in result.stdout:
        print("    [OK] UDP 端口 5000 已被监听")
    else:
        print("    [WARNING] UDP 端口 5000 未被监听")
        print("    这可能意味着 GStreamer 视频管道未启动")
except Exception as e:
    print(f"    [WARNING] 无法检查 UDP 端口: {e}")

# 3. 检查测试推流
print("\n[3] 检查测试推流进程...")
try:
    result = subprocess.run(
        ["tasklist"],
        capture_output=True,
        text=True,
        timeout=5
    )

    if "gst-launch-1.0" in result.stdout:
        print("    [OK] 测试推流进程正在运行")
    else:
        print("    [WARNING] 测试推流进程未运行")
        print("    请启动: python push_test_stream.py")
except Exception as e:
    print(f"    [WARNING] 无法检查进程: {e}")

# 4. 检查网络路由
print("\n[4] 检查到相机 IP 的路由...")
try:
    result = subprocess.run(
        ["ping", "-n", "1", "192.168.144.25"],
        capture_output=True,
        text=True,
        timeout=5
    )

    if result.returncode == 0:
        print("    [OK] 可以 Ping 通相机 IP")
    else:
        print("    [WARNING] 无法 Ping 通相机 IP")
except Exception as e:
    print(f"    [WARNING] Ping 测试失败: {e}")

# 5. 测试 WebRTC WebSocket
print("\n[5] 测试 WebRTC WebSocket 连接...")
try:
    import asyncio
    import websockets

    async def test_webrtc():
        try:
            async with websockets.connect("ws://192.168.144.30:8000/ws/webrtc", timeout=5) as ws:
                print("    [OK] WebRTC WebSocket 连接成功")
                return True
        except Exception as e:
            print(f"    [ERROR] WebRTC WebSocket 连接失败: {e}")
            return False

    success = asyncio.run(test_webrtc())
except ImportError:
    print("    [SKIP] 需要安装 websockets 库")
except Exception as e:
    print(f"    [ERROR] WebRTC 测试失败: {e}")

# 6. 总结
print("\n" + "=" * 80)
print("诊断完成")
print("=" * 80)

print("\n如果所有检查都通过，但浏览器中仍然看不到视频：")
print("1. 清除浏览器缓存并刷新页面")
print("2. 打开浏览器开发者工具 (F12) 查看控制台错误")
print("3. 检查后端日志中的 GStreamer 错误信息")
print("4. 检查 GPU 使用率 (任务管理器 → GPU → Video Decoding)")

print("\n快速启动命令:")
print("  后端:    python run_backend.py")
print("  测试推流: python push_test_stream.py")
print("  浏览器:   http://localhost:5174")

print("\n" + "=" * 80)
