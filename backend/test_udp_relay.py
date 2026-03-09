#!/usr/bin/env python3
"""
UDP 转发器测试脚本。

用于验证 UDP 转发器是否正常工作。
"""

import asyncio
import socket
import time


async def test_udp_relay():
    """测试 UDP 转发器。"""

    print("🧪 UDP 转发器测试")
    print("=" * 50)

    # 配置
    LISTEN_PORT = 5001  # 使用不同端口避免冲突
    BIND_ADDRESS = "192.168.144.40"
    TARGET_PORT = 5002
    TARGET_ADDRESS = "127.0.0.1"

    # 创建接收 socket（模拟 WebRTC 接收端）
    recv_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    recv_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    recv_socket.bind((TARGET_ADDRESS, TARGET_PORT))
    recv_socket.setblocking(False)

    print(f"✅ 接收端已启动: {TARGET_ADDRESS}:{TARGET_PORT}")

    # 创建转发 socket
    relay_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    relay_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    relay_socket.bind((BIND_ADDRESS, LISTEN_PORT))
    relay_socket.setblocking(False)

    print(f"✅ 转发器已启动: {BIND_ADDRESS}:{LISTEN_PORT} -> {TARGET_ADDRESS}:{TARGET_PORT}")

    # 创建发送 socket（模拟边缘端）
    send_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    send_socket.setblocking(False)

    print(f"✅ 发送端已创建")

    # 测试数据
    test_data = b"Hello from UDP relay!"
    packet_count = 0

    print("\n🔄 开始转发测试...")

    loop = asyncio.get_event_loop()

    start_time = time.time()
    test_duration = 5  # 测试 5 秒

    try:
        while time.time() - start_time < test_duration:
            # 发送测试数据
            try:
                send_socket.sendto(test_data, (BIND_ADDRESS, LISTEN_PORT))
                packet_count += 1
            except BlockingIOError:
                pass
            except Exception as e:
                print(f"❌ 发送失败: {e}")
                break

            # 接收并转发
            try:
                data, addr = relay_socket.recvfrom(65536)

                # 转发
                relay_socket.sendto(data, (TARGET_ADDRESS, TARGET_PORT))

                print(f"📦 转发数据包: {len(data)} bytes from {addr}")
            except BlockingIOError:
                pass
            except Exception as e:
                print(f"❌ 转发失败: {e}")
                import traceback
                traceback.print_exc()
                break

            # 接收转发后的数据
            try:
                data, addr = recv_socket.recvfrom(65536)
                print(f"✅ 接收转发数据: {len(data)} bytes from {addr}")

                if data == test_data:
                    print(f"✅ 数据验证成功")
                else:
                    print(f"❌ 数据验证失败")
            except BlockingIOError:
                pass

            await asyncio.sleep(0.01)

    except KeyboardInterrupt:
        print("\n⏹️  测试中断")

    finally:
        # 清理
        send_socket.close()
        relay_socket.close()
        recv_socket.close()

    print("\n📊 测试结果:")
    print(f"  发送数据包: {packet_count}")
    print(f"  测试时长: {time.time() - start_time:.2f} 秒")
    print(f"  平均速率: {packet_count / (time.time() - start_time):.2f} 包/秒")


if __name__ == "__main__":
    try:
        asyncio.run(test_udp_relay())
    except KeyboardInterrupt:
        print("\n⏹️  测试已中断")
