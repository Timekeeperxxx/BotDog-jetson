#!/usr/bin/env bash
# BotDog 视频流水线启动脚本（Linux 版）
# 启动 MediaMTX + FFmpeg 看门狗（cam1 + cam2）
# 使用 RTMP 推流（避免 FFmpeg 4.2 RTSP 输出端口冲突）

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.."
PID_DIR="$ROOT_DIR/logs"

MEDIAMTX="${MEDIAMTX_EXE:-$ROOT_DIR/scripts/mediamtx}"
CAMERA_RTSP_URL="${CAMERA_RTSP_URL:-rtsp://192.168.144.25:8554/main.264}"
# cam2 暂时禁用（.26 当前无法访问）
# CAMERA2_RTSP_URL="${CAMERA2_RTSP_URL:-rtsp://192.168.144.26:8554/main.264}"
# 使用 RTMP 推流（mediamtx 已在 1935 监听）
MEDIA_MTX_CAM1="rtmp://127.0.0.1:1935/cam"
MEDIA_MTX_CAM2="rtmp://127.0.0.1:1935/cam2"

mkdir -p "$PID_DIR"

# ── 停止旧进程 ──
stop_pipeline() {
  for pidfile in "$PID_DIR"/{mediamtx,ffmpeg_cam1,ffmpeg_cam2}.pid; do
    if [ -f "$pidfile" ]; then
      local pid
      pid=$(cat "$pidfile")
      kill -- -"$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
      rm -f "$pidfile"
    fi
  done
  pkill -f "mediamtx.*mediamtx.yml" 2>/dev/null || true
  killall ffmpeg 2>/dev/null || true
  sleep 1
}

if [ "${1:-}" = "stop" ]; then
  stop_pipeline
  echo "Pipeline stopped."
  exit 0
fi

echo "Stopping existing pipeline (if any)..."
stop_pipeline

[ -x "$MEDIAMTX" ] || { echo "ERROR: MediaMTX not found: $MEDIAMTX"; exit 1; }
command -v ffmpeg &>/dev/null || { echo "ERROR: FFmpeg not found"; exit 1; }

# ── 启动 MediaMTX ──
echo "Starting MediaMTX..."
setsid "$MEDIAMTX" "$ROOT_DIR/config/mediamtx.yml" >> "$ROOT_DIR/logs/mediamtx.log" 2>&1 &
echo $! > "$PID_DIR/mediamtx.pid"
echo "MediaMTX PID: $(cat "$PID_DIR/mediamtx.pid")"
sleep 2

# ── cam1 看门狗（.25 → cam，RTMP 推流）──
echo "Starting FFmpeg watchdog cam1..."
setsid bash -c '
  while true; do
    echo "[$(date "+%F %T")] Starting FFmpeg cam1..." >> "'"$ROOT_DIR"'/logs/ffmpeg.log"
    ffmpeg -fflags nobuffer -rtsp_transport tcp -stimeout 5000000 \
      -i "'"$CAMERA_RTSP_URL"'" \
      -c:v libx264 -preset ultrafast -tune zerolatency -threads 4 \
      -b:v 800k -maxrate 1200k -bufsize 400k -g 15 -bf 0 -pix_fmt yuv420p \
      -vf "scale=1280:720" -r 15 \
      -f rtsp -rtsp_transport tcp "rtsp://127.0.0.1:8554/cam" \
      >> "'"$ROOT_DIR"'/logs/ffmpeg.log" 2>&1 || true
    echo "[$(date "+%F %T")] FFmpeg cam1 exited, restarting in 3s..." >> "'"$ROOT_DIR"'/logs/ffmpeg.log"
    sleep 3
  done
' &
echo $! > "$PID_DIR/ffmpeg_cam1.pid"
echo "FFmpeg cam1 PID: $(cat "$PID_DIR/ffmpeg_cam1.pid")"

# cam2 管道已禁用（.26 无法访问）
# echo "FFmpeg cam2 PID: $(cat "$PID_DIR/ffmpeg_cam2.pid")"

echo ""
echo "Pipeline started."
echo "  Logs: $ROOT_DIR/logs/{mediamtx,ffmpeg}.log"
echo "  WHEP cam:  http://127.0.0.1:8889/cam/whep"
echo "  WHEP cam2: http://127.0.0.1:8889/cam2/whep"
echo "  Stop: bash $0 stop"
