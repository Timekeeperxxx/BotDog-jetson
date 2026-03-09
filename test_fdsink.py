#!/usr/bin/env python3
"""
简化测试：fdsink 数据输出
"""

import subprocess
import sys

print("=" * 80)
print("测试 fdsink 数据输出")
print("=" * 80)

# 测试1: 最简单的 fdsink
print("\n[测试 1] videotestsrc -> RGB -> fdsink")
pipeline = (
    'gst-launch-1.0 -q '
    'videotestsrc num-buffers=2 '
    '! video/x-raw,width=320,height=240,format=RGB '
    'fdsink fd=1'
)

print(f"管道: {pipeline}")

proc = subprocess.Popen(
    pipeline,
    shell=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE
)

stdout, stderr = proc.communicate(timeout=10)

print(f"返回码: {proc.returncode}")
print(f"Stdout 大小: {len(stdout)} 字节")
expected = 320 * 240 * 3 * 2  # 2帧
print(f"预期大小: {expected} 字节")

if len(stdout) >= expected * 0.8:
    print(f"\n[成功] 从 fdsink 读取到数据!")
    print(f"实际数据: {len(stdout)} 字节")
    print(f"完整率: {len(stdout)/expected*100:.1f}%")

    # 显示前 100 字节
    print(f"\n前 100 字节 (hex): {stdout[:100].hex()}")
else:
    print(f"\n[失败] 数据不足")
    print(f"预期: {expected}, 实际: {len(stdout)}")

    if stderr:
        print(f"\n错误输出:")
        print(stderr.decode('utf-8', errors='ignore')[:500])

    # 检查 stdout 内容
    if len(stdout) > 0:
        print(f"\n实际收到的数据:")
        print(stdout[:200])

print("\n" + "=" * 80)
print("测试完成")
print("=" * 80)
