#!/usr/bin/env python3
"""
测试推流脚本 - 移动的球（H.264）
"""

import subprocess
import sys

print("=" * 80)
print("启动测试推流（H.264 - 移动的球）")
print("=" * 80)
print("\n目标: udp://192.168.144.30:5000")
print("源: videotestsrc pattern=ball")
print("编码: H.264 (x264enc)")
print("封装: RTP")

pipeline = (
    'gst-launch-1.0 -v '
    'videotestsrc pattern=ball is-live=true '
    '! video/x-raw,width=1920,height=1080,framerate=30/1 '
    '! videoconvert '
    '! x264enc tune=zerolatency speed-preset=ultrafast bitrate=2000 '
    '! rtph264pay config-interval=1 pt=96 '
    '! udpsink host=192.168.144.30 port=5000 sync=false'
)

print(f"\nPipeline:\n{pipeline}\n")
print("启动推流...")
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
    print(f"正在向 192.168.144.30:5000 推送 H.264 RTP 流")
    print(f"这是一个移动的球的测试图案\n")

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
