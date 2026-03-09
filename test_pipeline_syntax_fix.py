#!/usr/bin/env python3
"""
测试修复后的 GStreamer pipeline
"""

import subprocess
import time
import sys

print("=" * 80)
print("测试修复后的 GStreamer Pipeline")
print("=" * 80)

# 生成修复后的 pipeline
udp_port = 5000
tcp_port = 6000
width = 1920
height = 1080
framerate = 30

pipeline_parts = [
    'gst-launch-1.0 -q -e',
    f'udpsrc port={udp_port}',
    f'caps=application/x-rtp,media=video,encoding-name=H264,payload=96',
    '! rtpjitterbuffer latency=100',
    '! rtph264depay',
    '! h264parse',
    '! d3d11h264dec',
    '! videoconvert',
    f'! video/x-raw,format=I420,width={width},height={height},framerate={framerate}/1',
    f'! tcpserversink host=127.0.0.1 port={tcp_port} sync=false'
]

pipeline = ' '.join(pipeline_parts)

print("\n生成的 Pipeline:")
print(pipeline)

print("\n" + "=" * 80)
print("测试启动 GStreamer（5 秒超时）")
print("=" * 80)

print("\n请确保测试推流正在运行:")
print("  gst-launch-1.0 -v videotestsrc pattern=ball ! x264enc ! rtph264pay ! udpsink host=192.168.144.30 port=5000")

input("\n按 Enter 开始测试...")

try:
    print("\n启动 GStreamer...")
    proc = subprocess.Popen(
        pipeline,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=True
    )

    print(f"进程已启动 (PID: {proc.pid})")
    print("等待 5 秒...")

    time.sleep(5)

    # 检查进程状态
    if proc.poll() is None:
        print("\n[OK] GStreamer 进程仍在运行")
        print("尝试连接 TCP 端口 6000...")

        import socket
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2.0)
            sock.connect(("127.0.0.1", tcp_port))
            print("[OK] TCP 连接成功！")

            # 尝试接收数据
            sock.settimeout(3.0)
            data = sock.recv(65536)
            print(f"[OK] 收到数据: {len(data)} 字节")
            print(f"前16字节: {data[:16].hex()}")

            sock.close()
        except Exception as e:
            print(f"[INFO] TCP 连接失败: {e}")
            print("这可能是因为没有推流数据")

        # 停止进程
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except:
            proc.kill()

        print("\n[SUCCESS] Pipeline 语法正确，GStreamer 正常运行！")

    else:
        returncode = proc.returncode
        print(f"\n[FAIL] GStreamer 进程退出，代码: {returncode}")

        # 读取错误输出
        try:
            stderr_output = proc.stderr.read()
            if stderr_output:
                stderr_str = stderr_output.decode('utf-8', errors='ignore')
                print(f"错误输出:\n{stderr_str[-1000:]}")
        except:
            pass

        sys.exit(1)

except KeyboardInterrupt:
    print("\n\n[中断] 用户停止测试")
    if 'proc' in locals():
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except:
            proc.kill()
except Exception as e:
    print(f"\n[ERROR] 测试失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
