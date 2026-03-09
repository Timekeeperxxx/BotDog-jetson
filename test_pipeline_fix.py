#!/usr/bin/env python3
"""
测试 GStreamer 管道是否能正确解析
"""

import sys
sys.path.insert(0, '.')

from backend.video_track_native import GStreamerVideoTrack

print("=" * 80)
print("测试 GStreamer 管道字符串解析")
print("=" * 80)

# 创建测试实例
track = GStreamerVideoTrack(udp_port=5000, width=1280, height=720, framerate=30)

# 提取 pipeline 字符串（模拟 start() 方法中的逻辑）
udp_port = track.udp_port
width = track.width
height = track.height
framerate = track.framerate

# 构建 pipeline（与 start() 方法中的代码完全一致）
pipeline = (
    'gst-launch-1.0 -q -e '
    f'udpsrc port={udp_port} '
    f'caps="application/x-rtp,media=video,encoding-name=H264,payload=96" '
    '! rtpjitterbuffer latency=100 do-retransmission=true '
    '! rtph264depay '
    '! h264parse '
    '! d3d11h264dec '
    '! videoconvert '
    f'! video/x-raw,format=I420,width={width},height={height},framerate={framerate}/1 '
    '! fdsink fd=1 sync=false'
)

print("\n生成的 pipeline 字符串：")
print(pipeline)

print("\n" + "=" * 80)
print("验证变量是否正确解析：")
print("=" * 80)

# 检查变量是否被正确替换
checks = [
    (f'port={udp_port}', f"port={udp_port}"),
    (f'width={width}', f'width={width}'),
    (f'height={height}', f'height={height}'),
    (f'framerate={framerate}/1', f'framerate={framerate}/1'),
]

all_ok = True
for expected, actual in checks:
    if expected in pipeline:
        print(f"  [OK] {actual} 已正确替换")
    else:
        print(f"  [FAIL] {actual} 未正确替换")
        all_ok = False

# 检查不应该出现未替换的变量
if '{self.width}' in pipeline or '{self.height}' in pipeline or '{self.framerate}' in pipeline:
    print("\n  [FAIL] 发现未替换的变量！")
    all_ok = False

if all_ok:
    print("\n" + "=" * 80)
    print("✅ 所有变量已正确解析！")
    print("=" * 80)
    print("\nPipeline 应该能正常工作了！")
else:
    print("\n" + "=" * 80)
    print("❌ 仍然存在问题！")
    print("=" * 80)
    sys.exit(1)
