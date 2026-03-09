#!/usr/bin/env python3
"""
UDP 回显服务器 - 测试 UDP 端口 5000 是否能接收数据
"""

import socket
import sys

print("=" * 80)
print("UDP 回显服务器")
print("=" * 80)
print("\n监听端口: 5000")
print("绑定地址: 0.0.0.0 (所有接口)")
print("\n启动推流: python push_test_stream.py")
print("按 Ctrl+C 停止\n")

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("0.0.0.0", 5000))
sock.settimeout(5.0)

print("[OK] UDP socket 已绑定")
print("等待接收数据...\n")

try:
    packet_count = 0
    while True:
        try:
            data, addr = sock.recvfrom(65536)
            packet_count += 1

            print(f"[收到数据包 #{packet_count}]")
            print(f"  源地址: {addr[0]}:{addr[1]}")
            print(f"  数据大小: {len(data)} 字节")
            print(f"  前16字节: {data[:16].hex()}")
            print()

        except socket.timeout:
            print(f"[等待] {5} 秒内未收到数据...")
            print("请确保推流正在运行: python push_test_stream.py\n")
except KeyboardInterrupt:
    print("\n\n[中断] 用户停止")
finally:
    sock.close()
    print(f"\n总计收到 {packet_count} 个数据包")
