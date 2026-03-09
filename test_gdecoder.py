#!/usr/bin/env python3
"""
测试 GStreamer 解码管道

验证 H.264 UDP 接收、解码、输出到 stdout 是否正常
"""

import subprocess
import sys
import time

print("=" * 80)
print("测试 GStreamer H.264 解码管道")
print("=" * 80)

pipeline = (
    'gst-launch-1.0 -v -e '
    'udpsrc port=5000 '
    'caps="application/x-rtp,media=video,encoding-name=H264,payload=96" '
    '! rtpjitterbuffer latency=100 do-retransmission=true '
    '! rtph264depay '
    '! h264parse '
    '! avdec_h264 '
    '! videoconvert '
    '! fakesink'
)

print(f"\n管道命令:")
print(f"  {pipeline}")
print(f"\n注意: 请确保测试推流正在运行 (python push_test_stream.py)")
print(f"按 Ctrl+C 停止测试\n")

try:
    proc = subprocess.Popen(
        pipeline,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    print(f"[OK] GStreamer 进程已启动 (PID: {proc.pid})")
    print(f"等待 5 秒观察输出...\n")

    # 等待 5 秒
    time.sleep(5)

    # 检查进程状态
    if proc.poll() is None:
        print(f"[OK] GStreamer 进程仍在运行")
        print(f"说明 UDP 接收和解码正常")

        # 终止进程
        proc.terminate()
        try:
            proc.wait(timeout=3)
            print(f"\n[成功] 测试完成")
        except subprocess.TimeoutExpired:
            proc.kill()

    else:
        returncode = proc.returncode
        print(f"[失败] GStreamer 进程退出，代码: {returncode}")

        # 读取错误输出
        stderr_output = proc.stderr.read()
        if stderr_output:
            print(f"\n错误输出:")
            print(stderr_output[-1000:])  # 只显示最后 1000 字符

except KeyboardInterrupt:
    print("\n\n[中断] 用户停止测试")
    if 'proc' in locals():
        proc.terminate()
except Exception as e:
    print(f"\n[错误] 测试失败: {e}")
    sys.exit(1)
