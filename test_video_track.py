#!/usr/bin/env python3
"""
直接测试 GStreamerVideoTrack 是否能正常工作
"""

import asyncio
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(__file__))

async def test_video_track():
    """测试视频轨道"""
    try:
        from backend.video_track_native import GStreamerVideoSourceFactory

        print("=" * 80)
        print("测试 GStreamerVideoTrack")
        print("=" * 80)
        print("\n创建视频轨道...")

        track = GStreamerVideoSourceFactory.create_track(
            udp_port=5000,
            width=1280,
            height=720,
            framerate=30,
        )

        print("启动视频轨道...")
        await track.start()

        print("\n等待 5 秒接收视频帧...")
        await asyncio.sleep(5)

        print("\n尝试接收一帧...")
        frame = await track.recv()

        if frame:
            print(f"[OK] 成功接收到视频帧:")
            print(f"  格式: {frame.format.name}")
            print(f"  宽度: {frame.width}")
            print(f"  高度: {frame.height}")
            print(f"  时间戳: {frame.pts}")
        else:
            print("[失败] 没有接收到视频帧")

        print("\n停止视频轨道...")
        await track.stop()

        print("\n" + "=" * 80)
        print("测试完成")
        print("=" * 80)

    except Exception as e:
        print(f"\n[错误] 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(test_video_track())
