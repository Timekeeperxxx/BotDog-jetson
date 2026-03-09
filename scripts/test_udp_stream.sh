#!/bin/bash
# 测试 UDP 视频流接收

echo "=========================================="
echo "UDP 视频流接收测试"
echo "=========================================="
echo "监听端口: 19856"
echo "协议: UDP RTP H.264"
echo "=========================================="
echo ""

# 检查是否有 X11 显示（用于视频输出）
if [ -z "$DISPLAY" ]; then
    echo "⚠️  未检测到图形界面，将使用 fakesink 测试"
    SINK="fakesink"
    echo "输出方式: fakesink（无显示，仅测试数据流）"
else
    echo "✅ 检测到图形界面，将使用 autovideosink 显示视频"
    SINK="autovideosink"
    echo "输出方式: autovideosink（显示视频窗口）"
fi

echo ""
echo "=========================================="
echo "启动 GStreamer 管道..."
echo "=========================================="
echo ""
echo "管道配置："
echo "  udpsrc port=19856"
echo "  ! application/x-rtp,media=video,encoding-name=H264,payload=96"
echo "  ! rtph264depay"
echo "  ! h264parse"
echo "  ! avdec_h264"
echo "  ! videoconvert"
echo "  ! $SINK"
echo ""
echo "=========================================="
echo "按 Ctrl+C 停止测试"
echo "=========================================="
echo ""

# 启动 GStreamer 管道
gst-launch-1.0 \
  udpsrc port=19856 \
  ! application/x-rtp,media=video,encoding-name=H264,payload=96 \
  ! rtph264depay \
  ! h264parse \
  ! avdec_h264 \
  ! videoconvert \
  ! $SINK

echo ""
echo "=========================================="
echo "测试结束"
echo "=========================================="
