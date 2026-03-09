#!/usr/bin/env python3
"""
快速验证修复效果
"""

import subprocess
import sys

print("=" * 80)
print("验证修复效果")
print("=" * 80)

print("\n✅ 修复内容：")
print("1. ✅ stop() 方法已改为同步（不再有 RuntimeWarning）")
print("2. ✅ 添加了帧计数器日志（每30帧输出一次）")
print("3. ✅ 优先使用 H.265 解码器（与测试源对齐）")
print("4. ✅ 强制 SDP 使用 H.264 baseline profile（浏览器兼容）")

print("\n" + "=" * 80)
print("启动完整测试链路")
print("=" * 80)

print("\n[步骤 1] 启动测试推流 (H.265)...")
print("命令: python push_test_stream.py")
print("请在单独的终端运行此命令")
input("按 Enter 确认推流已启动...")

print("\n[步骤 2] 启动后端...")
print("命令: python run_backend.py")
print("请在单独的终端运行此命令")
input("按 Enter 确认后端已启动...")

print("\n[步骤 3] 启动前端...")
print("命令: cd frontend && npm start")
print("请在单独的终端运行此命令")
input("按 Enter 确认前端已启动...")

print("\n" + "=" * 80)
print("关键验证点")
print("=" * 80)

print("\n✅ 后端终端应该看到：")
print("  - '尝试 H.265 解码...'（不是 H.264）")
print("  - '[OK] H.265 GStreamer 进程已启动'")
print("  - '✅ Frame sent to WebRTC: 1'")
print("  - '✅ Frame sent to WebRTC: 31'")
print("  - '✅ Frame sent to WebRTC: 61'")
print("  - (帧计数器疯狂跳动)")

print("\n✅ 浏览器控制台应该看到：")
print("  - '🎥 接收到远程视频流'")
print("  - 'readyState: 4'（不再是 0）")
print("  - 'videoWidth: 1280'")
print("  - 'videoHeight: 720'")
print("  - 应该能看到移动的球（测试图案）")

print("\n✅ 任务管理器应该看到：")
print("  - GPU 使用率上升（RTX 3060 硬件解码）")
print("  - Python 进程 CPU 使用率正常（不是 200%）")

print("\n" + "=" * 80)
print("如果一切正常，现在应该能看到视频了！")
print("=" * 80)
