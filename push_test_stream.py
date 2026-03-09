#!/usr/bin/env python3
"""
使用测试源推流到 UDP 端口 5000
用于验证后端视频处理是否正常
"""

import subprocess
import sys
import time

print("=" * 80)
print("使用测试源推流 (H.264 - 浏览器兼容性最好)")
print("=" * 80)
print("\n目标: 192.168.144.30:5000")
print("源: videotestsrc (测试图案)")
print("编码: H.264 (x264enc, Baseline Profile)")

pipeline = (
    'gst-launch-1.0 -q '
    'videotestsrc pattern=ball is-live=true '
    '! video/x-raw,width=1280,height=720,framerate=30/1 '
    '! videoconvert '
    '! x264enc tune=zerolatency speed-preset=ultrafast key-int-max=15 bitrate=2000 '
    '! rtph264pay config-interval=1 pt=96 '
    '! udpsink host=192.168.144.30 port=5000 sync=false bind-address=192.168.144.30'
)

print(f"\n管道命令:")
print(f"  {pipeline}")

print(f"\n启动推流...")
print("按 Ctrl+C 停止\n")

try:
    proc = subprocess.Popen(
        pipeline,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    print(f"推流进程已启动 (PID: {proc.pid})")
    print(f"正在推送到 192.168.144.30:5000...")
    print(f"这是一个移动球的测试图案，应该能看到视频\n")

    # 等待进程结束
    proc.wait()

    if proc.returncode == 0:
        print(f"\n[成功] 推流正常结束")
    else:
        print(f"\n[失败] 推流异常退出，代码: {proc.returncode}")

except KeyboardInterrupt:
    print("\n\n[中断] 用户停止推流")
    if 'proc' in locals():
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
except Exception as e:
    print(f"\n[错误] 推流失败: {e}")
    sys.exit(1)
