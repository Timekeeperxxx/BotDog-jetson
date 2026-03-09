#!/usr/bin/env python3
"""
验证配置是否正确
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(__file__))

try:
    from backend.config import settings

    print("=" * 80)
    print("配置验证")
    print("=" * 80)
    print(f"\n✅ 配置加载成功\n")

    print("视频流配置:")
    print(f"  UDP_RELAY_ENABLED: {settings.UDP_RELAY_ENABLED}")
    print(f"  UDP_RELAY_LISTEN_PORT: {settings.UDP_RELAY_LISTEN_PORT}")
    print(f"  UDP_RELAY_BIND_ADDRESS: {settings.UDP_RELAY_BIND_ADDRESS}")
    print(f"  UDP_RELAY_TARGET_ADDRESS: {settings.UDP_RELAY_TARGET_ADDRESS}")
    print(f"  VIDEO_UDP_PORT: {settings.VIDEO_UDP_PORT}")
    print(f"  CAMERA_RTSP_URL: {settings.CAMERA_RTSP_URL}")

    print("\n系统架构:")
    if settings.UDP_RELAY_ENABLED:
        print("  🔴 使用 UDP 转发器（旧架构）")
        print(f"     相机 → {settings.UDP_RELAY_BIND_ADDRESS}:{settings.UDP_RELAY_LISTEN_PORT}")
        print(f"     → {settings.UDP_RELAY_TARGET_ADDRESS}:{settings.VIDEO_UDP_PORT}")
        print(f"     → WebRTC")
    else:
        print("  🟢 直接监听模式（新架构）")
        print(f"     相机 → {settings.UDP_RELAY_BIND_ADDRESS}:{settings.UDP_RELAY_LISTEN_PORT}")
        print(f"     → GStreamer (d3d11h265dec)")
        print(f"     → WebRTC")

    print("\n" + "=" * 80)
    print("配置验证完成")
    print("=" * 80)

except Exception as e:
    print(f"\n❌ 配置加载失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
