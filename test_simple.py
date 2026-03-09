#!/usr/bin/env python3
"""
最简单的测试 - 不用 caps
"""

import subprocess
import sys

print("=" * 80)
print("测试 - 不使用 caps 参数")
print("=" * 80)

# 测试: 最简单的管道
print("\n[测试] videotestsrc -> fdsink")

# 使用转义双引号处理 format=RGB
pipeline = 'gst-launch-1.0 -q videotestsrc num-buffers=2 ! videoconvert ! fdsink fd=1'

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
print(f"Stderr 大小: {len(stderr)} 字节")

if len(stdout) > 0:
    print(f"\n[成功] 获取到数据!")
    print(f"数据大小: {len(stdout)} 字节")
    print(f"前 100 字节 (hex): {stdout[:100].hex()}")
else:
    print(f"\n[失败] 没有数据")
    if stderr:
        print(f"错误:\n{stderr.decode('utf-8', errors='ignore')[:500]}")

print("\n" + "=" * 80)
print("测试完成")
print("=" * 80)
