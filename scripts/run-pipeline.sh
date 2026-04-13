#!/usr/bin/env bash
# BotDog 视频流水线启动脚本（Linux 版）
# 启动 MediaMTX + FFmpeg 看门狗，启动时自动检测摄像头
#   cam1: HM30 IP 摄像头 (RTSP 拉流 → MediaMTX)
#   cam2: USB 摄像头 Logitech C920 (/dev/video1 → MediaMTX)

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.."
PID_DIR="$ROOT_DIR/logs"

MEDIAMTX="${MEDIAMTX_EXE:-$ROOT_DIR/scripts/mediamtx}"
# cam1：HM30 IP 摄像头 RTSP 地址
CAMERA_RTSP_URL="${CAMERA_RTSP_URL:-rtsp://192.168.144.25:8554/main.264}"
# cam2：USB 摄像头设备节点（C920 = /dev/video1）
CAM2_DEV="${CAM2_DEV:-/dev/video0}"

mkdir -p "$PID_DIR"

# ── 停止旧进程 ──────────────────────────────────────────────────────────────
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

# ── 摄像头自动检测 ──────────────────────────────────────────────────────────
echo ""
echo "Detecting cameras..."

# cam1：从 RTSP URL 提取 host:port，nc 探测连通性（2秒超时）
CAM1_HOST=$(echo "$CAMERA_RTSP_URL" | sed 's|rtsp://||' | cut -d'/' -f1 | cut -d':' -f1)
CAM1_PORT=$(echo "$CAMERA_RTSP_URL" | sed 's|rtsp://||' | cut -d'/' -f1 | cut -d':' -f2)
CAM1_PORT="${CAM1_PORT:-8554}"
if nc -z -w 2 "$CAM1_HOST" "$CAM1_PORT" 2>/dev/null; then
  CAM1_DETECTED=1
  echo "  [OK]   cam1 HM30 摄像头可达: $CAM1_HOST:$CAM1_PORT"
else
  CAM1_DETECTED=0
  echo "  [WARN] cam1 HM30 摄像头不可达 ($CAM1_HOST:$CAM1_PORT)，看门狗将持续重试"
fi

# cam2：检测 USB 设备节点是否存在
if [ -e "$CAM2_DEV" ]; then
  CAM2_DETECTED=1
  CAM2_NAME=$(v4l2-ctl --device="$CAM2_DEV" --info 2>/dev/null \
    | grep "Card type" | sed 's/.*: //' || echo "USB Camera")
  echo "  [OK]   cam2 USB 摄像头已连接: $CAM2_DEV ($CAM2_NAME)"
else
  CAM2_DETECTED=0
  echo "  [WARN] cam2 USB 摄像头未找到 ($CAM2_DEV)，跳过 cam2 推流"
fi

# ── 启动 MediaMTX ──────────────────────────────────────────────────────────
echo ""
echo "Starting MediaMTX..."
setsid "$MEDIAMTX" "$ROOT_DIR/config/mediamtx.yml" >> "$ROOT_DIR/logs/mediamtx.log" 2>&1 &
echo $! > "$PID_DIR/mediamtx.pid"
echo "MediaMTX PID: $(cat "$PID_DIR/mediamtx.pid")"
sleep 2

# ── cam1 看门狗（HM30 IP 摄像头 → RTSP → cam）─────────────────────────────
echo "Starting FFmpeg watchdog cam1..."
setsid bash -c '
  while true; do
    echo "[$(date "+%F %T")] Starting FFmpeg cam1..." >> "'"$ROOT_DIR"'/logs/ffmpeg.log"
    ffmpeg -fflags nobuffer -rtsp_transport tcp -stimeout 5000000 \
      -i "'"$CAMERA_RTSP_URL"'" \
      -c:v libx264 -preset ultrafast -tune zerolatency -threads 4 \
      -b:v 1500k -maxrate 2000k -bufsize 500k -g 30 -bf 0 -pix_fmt yuv420p \
      -r 30 \
      -f rtsp -rtsp_transport tcp rtsp://127.0.0.1:8554/cam \
      >> "'"$ROOT_DIR"'/logs/ffmpeg.log" 2>&1 || true
    echo "[$(date "+%F %T")] FFmpeg cam1 exited, restarting in 3s..." >> "'"$ROOT_DIR"'/logs/ffmpeg.log"
    sleep 3
  done
' &
echo $! > "$PID_DIR/ffmpeg_cam1.pid"
echo "FFmpeg cam1 watchdog PID: $(cat "$PID_DIR/ffmpeg_cam1.pid")"

# ── cam2 看门狗（USB C920 → /dev/video1 → cam2）───────────────────────────
if [ "$CAM2_DETECTED" -eq 1 ]; then
  echo "Starting FFmpeg watchdog cam2 (USB C920)..."
  setsid bash -c '
    while true; do
      if [ ! -e "'"$CAM2_DEV"'" ]; then
        echo "[$(date "+%F %T")] cam2 '"$CAM2_DEV"' disconnected, waiting..." >> "'"$ROOT_DIR"'/logs/ffmpeg_cam2.log"
        sleep 5; continue
      fi
      echo "[$(date "+%F %T")] Starting FFmpeg cam2..." >> "'"$ROOT_DIR"'/logs/ffmpeg_cam2.log"
      ffmpeg -f v4l2 -input_format mjpeg -framerate 30 -video_size 1280x720 \
        -i "'"$CAM2_DEV"'" \
        -c:v libx264 -preset ultrafast -tune zerolatency -threads 2 \
        -b:v 1500k -maxrate 2000k -bufsize 500k -g 30 -bf 0 -pix_fmt yuv420p \
        -r 15 \
        -f rtsp -rtsp_transport tcp rtsp://127.0.0.1:8554/cam2 \
        >> "'"$ROOT_DIR"'/logs/ffmpeg_cam2.log" 2>&1 || true
      echo "[$(date "+%F %T")] FFmpeg cam2 exited, restarting in 3s..." >> "'"$ROOT_DIR"'/logs/ffmpeg_cam2.log"
      sleep 3
    done
  ' &
  echo $! > "$PID_DIR/ffmpeg_cam2.pid"
  echo "FFmpeg cam2 watchdog PID: $(cat "$PID_DIR/ffmpeg_cam2.pid")"
else
  echo "cam2 skipped (not connected at startup)."
fi

# ── 启动摘要 ───────────────────────────────────────────────────────────────
echo ""
echo "=========================================="
echo "Pipeline started."
echo "  cam1 (HM30): $([ "$CAM1_DETECTED" -eq 1 ] && echo "OK  已连接" || echo "WARN 不可达，重试中")"
echo "  cam2 (USB):  $([ "$CAM2_DETECTED" -eq 1 ] && echo "OK  已连接 ($CAM2_DEV)" || echo "N/A 未连接，已跳过")"
echo "  WHEP cam:    http://127.0.0.1:8889/cam/whep"
echo "  WHEP cam2:   http://127.0.0.1:8889/cam2/whep"
echo "  Logs:        $ROOT_DIR/logs/"
echo "  Stop:        bash $0 stop"
echo "=========================================="
