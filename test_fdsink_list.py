#!/usr/bin/env python3
"""
使用不同的方法构建管道
"""

import subprocess
import sys

print("=" * 80)
print("测试 GStreamer 管道 - 方法 2")
print("=" * 80)

# 方法: 使用 list 而不是字符串
print("\n[测试] 使用 list 参数")

gst_args = [
    'gst-launch-1.0',
    '-q',
    'videotestsrc',
    'num-buffers=2',
    '!',
    'video/x-raw,width=320,height=240,format=RGB',
    '!',
    'fdsink',
    'fd=1'
]

print(f"命令: {' '.join(gst_args)}")

proc = subprocess.Popen(
    gst_args,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE
)

stdout, stderr = proc.communicate(timeout=10)

print(f"返回码: {proc.returncode}")
print(f"Stdout 大小: {len(stdout)} 字节")
expected = 320 * 240 * 3 * 2
print(f"预期大小: {expected} 字节")

if len(stdout) >= expected * 0.8:
    print(f"\n[成功] 从 fdsink 读取到数据!")
    print(f"实际数据: {len(stdout)} 字节")
    print(f"完整率: {len(stdout)/expected*100:.1f}%")
    print(f"\n前 100 字节 (hex): {stdout[:100].hex()}")
else:
    print(f"\n[失败] 数据不足")
    if stderr:
        print(f"\n错误输出:")
        print(stderr.decode('utf-8', errors='ignore')[:500])

print("\n" + "=" * 80)
