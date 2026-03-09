#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 WebRTC 连接是否正常
"""

import asyncio
import websockets
import json
import sys

# 修复 Windows 控制台编码问题
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

async def test_webrtc_connection():
    """测试 WebRTC WebSocket 连接"""
    uri = "ws://192.168.144.30:8000/ws/webrtc"

    print("=" * 80)
    print("测试 WebRTC WebSocket 连接")
    print("=" * 80)
    print(f"\n连接到: {uri}\n")

    try:
        async with websockets.connect(uri) as websocket:
            print("[OK] WebSocket 连接成功建立")

            # 等待欢迎消息
            message = await websocket.recv()
            data = json.loads(message)
            print(f"[OK] 收到消息: {data['msg_type']}")
            print(f"   客户端 ID: {data.get('client_id')}")

            # 发送一个简单的 offer（即使不完整也应该触发错误处理）
            test_offer = {
                "msg_type": "offer",
                "payload": {
                    "sdp": "test",
                    "type": "offer"
                }
            }

            await websocket.send(json.dumps(test_offer))
            print("[OK] 已发送测试 offer")

            # 等待响应
            response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            response_data = json.loads(response)
            print(f"[OK] 收到响应: {response_data['msg_type']}")

            if response_data['msg_type'] == 'error':
                print(f"   错误信息: {response_data.get('error', 'Unknown')}")

    except websockets.exceptions.ConnectionClosed as e:
        print(f"[ERROR] 连接被关闭: code={e.code}, reason={e.reason}")
    except asyncio.TimeoutError:
        print(f"[ERROR] 超时: 服务器未在 5 秒内响应")
    except Exception as e:
        print(f"[ERROR] 连接失败: {e}")

    print("\n" + "=" * 80)
    print("测试完成")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(test_webrtc_connection())
