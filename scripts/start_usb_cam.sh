#!/usr/bin/env bash
# 一键启动 USB 摄像头推流脚本 (供 MediaMTX WHEP 播放)

# 默认使用 /dev/video1，也可以通过参数指定，例如: ./start_usb_cam.sh /dev/video2
DEVICE=${1:-"/dev/video1"}

echo "正在启动 USB 摄像头推流 ($DEVICE) ..."
echo "如果失败，请检查摄像头设备号(ls /dev/video*) 或确认 MediaMTX 已经启动。"

# 使用 TCP 传输推送到 MediaMTX 本地 RTSP 端口
ffmpeg -f v4l2 -i "$DEVICE" \
  -vcodec libx264 -preset ultrafast -tune zerolatency \
  -rtsp_transport tcp \
  -f rtsp rtsp://127.0.0.1:8554/cam
