#!/usr/bin/env python3
"""
快速验证后端能否正常启动
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(__file__))

print("=" * 80)
print("验证后端修复")
print("=" * 80)

print("\n[1] 检查依赖...")
try:
    import uvicorn
    print("  ✅ uvicorn 已安装")
except ImportError:
    print("  ❌ uvicorn 未安装")
    sys.exit(1)

try:
    import fastapi
    print("  ✅ fastapi 已安装")
except ImportError:
    print("  ❌ fastapi 未安装")
    sys.exit(1)

try:
    import aiortc
    print("  ✅ aiortc 已安装")
except ImportError:
    print("  ❌ aiortc 未安装")
    sys.exit(1)

try:
    import av
    print("  ✅ av 已安装")
except ImportError:
    print("  ❌ av 未安装")
    sys.exit(1)

print("\n[2] 检查 video_track_native.py...")
try:
    from backend.video_track_native import GStreamerVideoTrack
    print("  ✅ 导入成功")

    # 检查 start() 方法是否是同步的
    import inspect
    if inspect.iscoroutinefunction(GStreamerVideoTrack.start):
        print("  ❌ start() 仍然是异步方法")
        sys.exit(1)
    else:
        print("  ✅ start() 已改为同步方法")

    # 检查 stop() 方法是否是同步的
    if inspect.iscoroutinefunction(GStreamerVideoTrack.stop):
        print("  ❌ stop() 仍然是异步方法")
        sys.exit(1)
    else:
        print("  ✅ stop() 已改为同步方法")

except Exception as e:
    print(f"  ❌ 导入失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n[3] 检查 webrtc_signaling.py...")
try:
    from backend.webrtc_signaling import WebRTCPeerConnection
    print("  ✅ 导入成功")

    # 读取文件内容，检查是否还有 await video_track.start()
    with open('backend/webrtc_signaling.py', 'r', encoding='utf-8') as f:
        content = f.read()
        if 'await video_track.start()' in content:
            print("  ❌ 仍然包含 'await video_track.start()'")
            sys.exit(1)
        else:
            print("  ✅ 已删除 'await video_track.start()'")

except Exception as e:
    print(f"  ❌ 导入失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 80)
print("✅ 所有检查通过！后端应该能正常启动了")
print("=" * 80)

print("\n下一步：")
print("1. 启动测试推流: python push_test_stream.py")
print("2. 启动后端: python run_backend.py")
print("3. 观察后端日志，应该看到：")
print("   - '[GPU Decode] Received Frame #1 from RTX 3060'")
print("   - '[GPU Decode] Received Frame #2 from RTX 3060'")
print("   - ...")
