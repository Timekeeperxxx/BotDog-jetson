#!/usr/bin/env python3
"""
实时诊断工具 - 检查视频流状态
"""

import socket
import time
import sys

print("=" * 80)
print("实时诊断工具")
print("=" * 80)

print("\n[1] 检查 UDP 端口 5000 是否有数据...")
try:
    # 创建一个简单的 UDP 接收器测试
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(5.0)
    sock.bind(("0.0.0.0", 5001))  # 绑定到 5001 避免冲突

    print("  [INFO] 监听 UDP 端口 5001（测试用）")
    print("  [INFO] 如果机器狗推流到 5000，请改为 5000")
    print("  [等待] 5 秒内接收 UDP 数据...")

    try:
        data, addr = sock.recvfrom(65536)
        print(f"  [OK] 收到 UDP 数据:")
        print(f"    源地址: {addr[0]}:{addr[1]}")
        print(f"    数据大小: {len(data)} 字节")
        print(f"    前16字节: {data[:16].hex()}")
    except socket.timeout:
        print(f"  [WARNING] 5 秒内未收到 UDP 数据")
        print(f"  [原因] 机器狗可能没有推流，或者推流到错误的端口")
    finally:
        sock.close()

except Exception as e:
    print(f"  [ERROR] UDP 监听失败: {e}")

print("\n[2] 检查 TCP 端口 6000 是否可连接...")
try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2.0)
    try:
        sock.connect(("127.0.0.1", 6000))
        print(f"  [OK] TCP 端口 6000 可连接")
        print(f"  [INFO] GStreamer TCP 服务器正在运行")

        # 尝试接收一些数据
        sock.settimeout(3.0)
        try:
            data = sock.recv(65536)
            print(f"  [OK] 收到 TCP 数据: {len(data)} 字节")
            print(f"    前16字节: {data[:16].hex()}")
        except socket.timeout:
            print(f"  [INFO] 3 秒内未收到 TCP 数据（可能机器狗未推流）")
        finally:
            sock.close()
    except Exception as e:
        print(f"  [ERROR] TCP 连接失败: {e}")
        print(f"  [原因] GStreamer TCP 服务器可能未启动")

except Exception as e:
    print(f"  [ERROR] TCP 检查失败: {e}")

print("\n[3] 检查 GStreamer 进程...")
try:
    import subprocess
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq gst-launch-1.0.exe"],
        capture_output=True,
        text=True,
        timeout=5
    )

    if "gst-launch-1.0.exe" in result.stdout:
        print(f"  [OK] 发现 GStreamer 进程:")
        for line in result.stdout.split("\n"):
            if "gst-launch-1.0.exe" in line:
                print(f"    {line.strip()}")
    else:
        print(f"  [WARNING] 未发现 GStreamer 进程")

except Exception as e:
    print(f"  [ERROR] 检查进程失败: {e}")

print("\n" + "=" * 80)
print("诊断完成")
print("=" * 80)

print("\n下一步：")
print("1. 如果未收到 UDP 数据：请检查机器狗是否正在推流")
print("2. 如果收到 UDP 数据但未收到 TCP 数据：GStreamer 解码可能失败")
print("3. 如果都收到数据：检查后端日志是否有 🔥 符号跳动")
