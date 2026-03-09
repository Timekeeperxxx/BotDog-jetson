#!/usr/bin/env python3
"""
UDP 端口转发脚本
运行在 Windows 主机上，将 UDP 数据包从 192.168.144.30:19856 转发到虚拟机 192.168.66.129:19856
"""

import socket
import threading
import sys

# 配置参数
LISTEN_HOST = '0.0.0.0'  # 监听所有网络接口（包括 192.168.144.30）
LISTEN_PORT = 19856      # 监听端口
TARGET_HOST = '192.168.66.129'  # 虚拟机 IP
TARGET_PORT = 19856      # 虚拟机端口

# 用于跟踪客户端地址
clients = {}

def forward_to_target(listen_socket, target_socket):
    """转发数据从监听 socket 到目标 socket"""
    while True:
        try:
            data, client_addr = listen_socket.recvfrom(65535)
            print(f"[→] 收到 {len(data)} 字节来自 {client_addr}")

            # 保存客户端地址，用于后续回传
            if client_addr not in clients:
                clients[client_addr] = True
                print(f"[+] 新客户端: {client_addr}")

            # 转发到虚拟机
            target_socket.sendto(data, (TARGET_HOST, TARGET_PORT))
            print(f"[→] 转发到 {TARGET_HOST}:{TARGET_PORT}")

        except Exception as e:
            print(f"[错误] 转发失败: {e}")
            break

def forward_to_client(target_socket, listen_socket):
    """转发数据从目标 socket 回到监听 socket"""
    # 先发送一个空包到虚拟机，建立"连接"
    try:
        target_socket.sendto(b'', (TARGET_HOST, TARGET_PORT))
    except:
        pass

    while True:
        try:
            # 从虚拟机接收数据
            data, addr = target_socket.recvfrom(65535)

            # 只处理来自虚拟机的数据包
            if addr[0] == TARGET_HOST and addr[1] == TARGET_PORT:
                print(f"[←] 收到 {len(data)} 字节来自虚拟机")

                # 转发回所有已知的客户端
                for client_addr in list(clients.keys()):
                    try:
                        listen_socket.sendto(data, client_addr)
                        print(f"[←] 转发回 {client_addr}")
                    except Exception as e:
                        print(f"[错误] 发送到客户端失败 {client_addr}: {e}")
                        del clients[client_addr]

        except socket.timeout:
            continue
        except Exception as e:
            print(f"[错误] 接收失败: {e}")
            break

def main():
    print("=" * 60)
    print("UDP 端口转发脚本")
    print("=" * 60)
    print(f"监听地址: {LISTEN_HOST}:{LISTEN_PORT}")
    print(f"转发目标: {TARGET_HOST}:{TARGET_PORT}")
    print("=" * 60)
    print("按 Ctrl+C 停止脚本")
    print("")

    # 创建 UDP socket
    try:
        listen_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        listen_socket.bind((LISTEN_HOST, LISTEN_PORT))
        print(f"[✓] 成功绑定到 {LISTEN_HOST}:{LISTEN_PORT}")

        target_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        print(f"[✓] 目标 socket 已创建")
        print("")

    except Exception as e:
        print(f"[错误] 无法创建 socket: {e}")
        print("请确保端口 19856 未被占用，并且有管理员权限")
        sys.exit(1)

    # 启动转发线程
    try:
        # 线程1：从客户端转发到目标
        thread_to_target = threading.Thread(
            target=forward_to_target,
            args=(listen_socket, target_socket),
            daemon=True
        )
        thread_to_target.start()

        # 线程2：从目标转发回客户端
        thread_to_client = threading.Thread(
            target=forward_to_client,
            args=(target_socket, listen_socket),
            daemon=True
        )
        thread_to_client.start()

        print("[✓] UDP 转发已启动，等待数据包...")
        print("")

        # 保持主线程运行
        while True:
            threading.Event().wait(1)

    except KeyboardInterrupt:
        print("\n" + "=" * 60)
        print("[停止] 收到中断信号，正在关闭...")
        print("=" * 60)
        listen_socket.close()
        target_socket.close()
        print("[完成] 脚本已停止")
        sys.exit(0)

if __name__ == '__main__':
    main()
