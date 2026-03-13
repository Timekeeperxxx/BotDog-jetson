#!/bin/bash
set -e

echo "📹 启动边缘端 GStreamer 推流器..."

# 默认配置
SOURCE=${1:-rtsp}
DEVICE=${2:-rtsp://192.168.144.25:8554/stream}
WIDTH=${3:-1920}
HEIGHT=${4:-1080}
FRAMERATE=${5:-30}
BITRATE=${6:-8000000}
TARGET_HOST=${7:-192.168.144.30}
TARGET_PORT=${8:-5000}
BIND_ADDRESS=${9:-192.168.144.30}

# 参数说明
if [ "$SOURCE" = "help" ] || [ "$SOURCE" = "--help" ] || [ "$SOURCE" = "-h" ]; then
    echo "用法: $0 [source] [device] [width] [height] [framerate] [bitrate] [target_host] [target_port] [bind_address]"
    echo ""
    echo "参数:"
    echo "  source       视频源类型 (rtsp/videotestsrc/v4l2src) [默认: rtsp]"
    echo "  device       设备路径或 RTSP URL [默认: rtsp://192.168.144.25:8554/stream]"
    echo "  width        视频宽度 [默认: 1920]"
    echo "  height       视频高度 [默认: 1080]"
    echo "  framerate    帧率 [默认: 30]"
    echo "  bitrate      码率 bps [默认: 8000000]"
    echo "  target_host  目标主机 [默认: 192.168.144.40]"
    echo "  target_port  目标端口 [默认: 5000]"
    echo "  bind_address 绑定地址 [默认: 192.168.144.40]"
    echo ""
    echo "示例:"
    echo "  $0 rtsp rtsp://192.168.144.25:8554/main.264"
    echo "  $0 videotestsrc /dev/null"
    echo "  $0 v4l2src /dev/video0"
    exit 0
fi

# 检查 GStreamer
if ! command -v gst-launch-1.0 &> /dev/null; then
    echo "❌ 错误: 未安装 GStreamer"
    echo "请安装: sudo apt-get install gstreamer1.0-tools gstreamer1.0-plugins-*"
    exit 1
fi

# 显示配置
echo "📋 推流配置:"
echo "  源类型: $SOURCE"
echo "  设备: $DEVICE"
echo "  分辨率: ${WIDTH}x${HEIGHT}"
echo "  帧率: ${FRAMERATE}fps"
echo "  码率: ${BITRATE}bps"
echo "  目标: ${TARGET_HOST}:${TARGET_PORT}"
echo "  绑定: ${BIND_ADDRESS}"

# 启动推流器
python3 edge/gstreamer_streamer.py \
  --source "$SOURCE" \
  --device "$DEVICE" \
  --width "$WIDTH" \
  --height "$HEIGHT" \
  --framerate "$FRAMERATE" \
  --bitrate "$BITRATE" \
  --host "$TARGET_HOST" \
  --port "$TARGET_PORT" \
  --bind-address "$BIND_ADDRESS"
