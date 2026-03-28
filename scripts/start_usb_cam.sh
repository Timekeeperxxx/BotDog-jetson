#!/usr/bin/env bash
# 一键启动视频管线：MediaMTX + USB 摄像头推流

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEVICE=${1:-"/dev/video1"}
MTX_BIN="$SCRIPT_DIR/mediamtx"
MTX_CFG="$SCRIPT_DIR/../config/mediamtx.yml"

# ── 1. 检查并启动 MediaMTX ──────────────────────────────────────────────────
if pgrep -x mediamtx > /dev/null 2>&1; then
  echo "[INFO] MediaMTX 已在运行，跳过启动"
else
  echo "[INFO] 启动 MediaMTX..."
  "$MTX_BIN" "$MTX_CFG" &
  MTX_PID=$!
  # 等待 RTSP 端口就绪（最多 5 秒）
  for i in $(seq 1 10); do
    if nc -z 127.0.0.1 8554 2>/dev/null; then
      echo "[INFO] MediaMTX 已就绪 (PID=$MTX_PID)"
      break
    fi
    sleep 0.5
  done
fi

# ── 2. 检查摄像头设备 ───────────────────────────────────────────────────────
if [ ! -e "$DEVICE" ]; then
  echo "[ERROR] 摄像头设备 $DEVICE 不存在，可用设备："
  ls /dev/video* 2>/dev/null || echo "  （未找到任何 /dev/video* 设备）"
  exit 1
fi

# ── 3. 推流 ─────────────────────────────────────────────────────────────────
echo "[INFO] 开始推流 $DEVICE → rtsp://127.0.0.1:8554/cam"
exec ffmpeg -f v4l2 -i "$DEVICE" \
  -vcodec libx264 -preset ultrafast -tune zerolatency \
  -rtsp_transport tcp \
  -f rtsp rtsp://127.0.0.1:8554/cam
