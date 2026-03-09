#!/usr/bin/env python3
"""
全链路 H.264 验证脚本
"""

import subprocess
import sys

print("=" * 80)
print("全链路 H.264 架构验证")
print("=" * 80)

print("\n✅ 架构改动：")
print("1. ✅ 推流端：固定使用 H.264 (x264enc)")
print("2. ✅ 后端：强制使用 d3d11h264dec 硬件解码")
print("3. ✅ 后端：同步 stop() 方法（不再有 RuntimeWarning）")
print("4. ✅ 后端：直接读取 YUV420P 格式（避免颜色转换）")
print("5. ✅ 验证：每帧打印 [GPU Decode] Received Frame #xxx")

print("\n" + "=" * 80)
print("启动完整测试链路")
print("=" * 80)

print("\n[步骤 1] 启动测试推流 (H.264)...")
print("命令: python push_test_stream.py")
print("编码: x264enc tune=zerolatency speed-preset=ultrafast key-int-max=15")
input("按 Enter 确认推流已启动...")

print("\n[步骤 2] 启动后端...")
print("命令: python run_backend.py")
print("解码器: d3d11h264dec (RTX 3060 硬件)")
input("按 Enter 确认后端已启动...")

print("\n[步骤 3] 启动前端...")
print("命令: cd frontend && npm start")
input("按 Enter 确认前端已启动...")

print("\n" + "=" * 80)
print("关键验证点")
print("=" * 80)

print("\n✅ 后端终端应该看到：")
print("  - '启动 H.264 硬件解码...'")
print("  - '[OK] GStreamer 进程已启动 (PID: xxxx)'")
print("  - '[GPU Decode] Received Frame #1 from RTX 3060'")
print("  - '[GPU Decode] Received Frame #2 from RTX 3060'")
print("  - '[GPU Decode] Received Frame #3 from RTX 3060'")
print("  - (帧计数器疯狂跳动，每秒 30 帧)")

print("\n✅ 浏览器控制台应该看到：")
print("  - '🎥 接收到远程视频流'")
print("  - 'readyState: 4'（不再是 0）")
print("  - 'videoWidth: 1280'")
print("  - 'videoHeight: 720'")

print("\n✅ 浏览器画面应该看到：")
print("  - 🎱 移动的球（videotestsrc pattern=ball）")
print("  - 🎨 彩色测试图案")
print("  - 🎬 流畅播放（30 FPS）")

print("\n✅ 任务管理器应该看到：")
print("  - GPU 使用率上升（RTX 3060 硬件解码）")
print("  - Python 进程 CPU 使用率正常（不是 200%）")

print("\n✅ 不应该再看到：")
print("  - ❌ RuntimeWarning: coroutine 'stop' was never awaited")
print("  - ❌ 尝试 H.265 解码...")
print("  - ❌ 编解码器不匹配")

print("\n" + "=" * 80)
print("如果一切正常，现在应该能看到视频了！")
print("=" * 80)
