#!/usr/bin/env bash
# BotDog 视频流水线启动脚本（Linux 版）
# 启动 MediaMTX + FFmpeg 看门狗，启动时自动检测摄像头
#   cam1: HM30 IP 摄像头 (RTSP 拉流 → MediaMTX)
#   cam2: 后视 USB 摄像头 → MediaMTX
#   cam3: 左视 USB 摄像头 → MediaMTX
#   cam4: 右视 USB 摄像头 → MediaMTX
#   推荐用 CAM*_USB_PATH 绑定 /dev/v4l/by-path 下的 USB 物理口路径。
#   注：GS02 每路摄像头创建 2 个节点（采集+元数据），脚本会自动筛选采集节点。

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.."
PID_DIR="$ROOT_DIR/logs"

MEDIAMTX="${MEDIAMTX_EXE:-$ROOT_DIR/scripts/mediamtx}"
# cam1：HM30 IP 摄像头 RTSP 地址
CAMERA_RTSP_URL="${CAMERA_RTSP_URL:-rtsp://192.168.144.25:8554/main.264}"
CAMERA_RETRY_DELAY="${CAMERA_RETRY_DELAY:-10}"
FFMPEG_LOGLEVEL="${FFMPEG_LOGLEVEL:-warning}"
CAM1_FPS="${CAM1_FPS:-20}"
CAM1_THREADS="${CAM1_THREADS:-2}"
CAM1_BITRATE="${CAM1_BITRATE:-1200k}"
CAM1_MAXRATE="${CAM1_MAXRATE:-1600k}"
CAM1_BUFSIZE="${CAM1_BUFSIZE:-200k}"
# cam2/3/4：USB 摄像头设备节点（GS02 三路）
CAM2_DEV="${CAM2_DEV:-/dev/video1}"
CAM3_DEV="${CAM3_DEV:-/dev/video0}"
CAM4_DEV="${CAM4_DEV:-/dev/video2}"
CAM2_USB_PATH="${CAM2_USB_PATH:-}"
CAM3_USB_PATH="${CAM3_USB_PATH:-}"
CAM4_USB_PATH="${CAM4_USB_PATH:-}"
CAM2_ENABLED="${CAM2_ENABLED:-1}"
CAM3_ENABLED="${CAM3_ENABLED:-1}"
CAM4_ENABLED="${CAM4_ENABLED:-1}"

# 鱼眼矫正参数（v360 滤镜）
#   USB_DEWARP=1     启用，=0 关闭直接推原始鱼眼；低延迟优先建议关闭
#   USB_IN_FOV       镜头实际视场角（GS02 约 180）
#   USB_OUT_H_FOV    输出水平视场角（越小越"拉近"）
#   USB_OUT_V_FOV    输出垂直视场角
USB_DEWARP="${USB_DEWARP:-0}"
USB_FPS="${USB_FPS:-10}"
USB_THREADS="${USB_THREADS:-2}"
USB_BITRATE="${USB_BITRATE:-1200k}"
USB_MAXRATE="${USB_MAXRATE:-1600k}"
USB_BUFSIZE="${USB_BUFSIZE:-200k}"
USB_IN_FOV="${USB_IN_FOV:-180}"
USB_OUT_H_FOV="${USB_OUT_H_FOV:-120}"
USB_OUT_V_FOV="${USB_OUT_V_FOV:-75}"

mkdir -p "$PID_DIR"

# ── 停止旧进程 ──────────────────────────────────────────────────────────────
stop_pipeline() {
  for pidfile in "$PID_DIR"/{mediamtx,ffmpeg_cam1,ffmpeg_cam2,ffmpeg_cam3,ffmpeg_cam4}.pid; do
    if [ -f "$pidfile" ]; then
      local pid
      pid=$(cat "$pidfile")
      kill -- -"$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
      rm -f "$pidfile"
    fi
  done
  pkill -f "mediamtx.*mediamtx.yml" 2>/dev/null || true
  # Do not kill every ffmpeg process. The backend AI worker also owns an
  # ffmpeg process that reads rtsp://127.0.0.1:8554/cam; killing it makes AI
  # tracking drop frames until the worker reconnects.
  pkill -f "ffmpeg .* -f rtsp .*rtsp://127\\.0\\.0\\.1:8554/cam([[:space:]]|$)" 2>/dev/null || true
  pkill -f "ffmpeg .* -f rtsp .*rtsp://127\\.0\\.0\\.1:8554/cam2([[:space:]]|$)" 2>/dev/null || true
  pkill -f "ffmpeg .* -f rtsp .*rtsp://127\\.0\\.0\\.1:8554/cam3([[:space:]]|$)" 2>/dev/null || true
  pkill -f "ffmpeg .* -f rtsp .*rtsp://127\\.0\\.0\\.1:8554/cam4([[:space:]]|$)" 2>/dev/null || true
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

# cam2/3/4：检测 USB 设备节点是否存在且具备视频采集能力。
# CAM*_USB_PATH 支持两种写法：
# - 精确节点：/dev/v4l/by-path/...-video-index0
# - 端口前缀：/dev/v4l/by-path/...:1.0 ；脚本会枚举其 -video-index* 节点
is_capture_node() {
  local dev="$1"
  if [ ! -e "$dev" ]; then
    return 1
  fi
  local info caps
  info=$(v4l2-ctl --device="$dev" --info 2>/dev/null)
  caps=$(echo "$info" | grep "Device Caps" | grep -o '0x[0-9a-fA-F]*' | tail -1)
  [ -n "$caps" ] && [ $(( caps & 1 )) -ne 0 ]
}

resolve_usb_cam_dev() {
  local label="$1"
  local usb_path="$2"
  local fallback_dev="$3"
  local out_var="$4"
  local candidates=()
  local dev

  if [ -n "$usb_path" ]; then
    if [ -e "$usb_path" ]; then
      candidates+=("$usb_path")
    fi
    while IFS= read -r dev; do
      candidates+=("$dev")
    done < <(compgen -G "${usb_path}-video-index*" || true)

    if [ "${#candidates[@]}" -eq 0 ]; then
      echo "  [WARN] $label USB 物理口未找到 ($usb_path)，跳过 $label 推流"
      return 1
    fi
  else
    candidates+=("$fallback_dev")
  fi

  for dev in "${candidates[@]}"; do
    if is_capture_node "$dev"; then
      printf -v "$out_var" '%s' "$dev"
      return 0
    fi
  done

  if [ -n "$usb_path" ]; then
    echo "  [WARN] $label USB 物理口存在但没有采集节点 ($usb_path)，跳过 $label 推流"
  else
    echo "  [WARN] $label USB 摄像头未找到或不是采集节点 ($fallback_dev)，跳过 $label 推流"
  fi
  return 1
}

describe_usb_cam() {
  local label="$1"
  local dev="$2"
  local info name real_dev
  if ! info=$(v4l2-ctl --device="$dev" --info 2>/dev/null); then
    echo "  [WARN] $label 无法读取摄像头信息: $dev"
    return 1
  fi
  name=$(echo "$info" | grep "Card type" | sed 's/.*: //' || echo "USB Camera")
  real_dev=$(readlink -f "$dev" 2>/dev/null || echo "$dev")
  echo "  [OK]   $label USB 摄像头已连接: $dev -> $real_dev ($name)"
  return 0
}

CAM2_DETECTED=0; resolve_usb_cam_dev cam2 "$CAM2_USB_PATH" "$CAM2_DEV" CAM2_DEV && describe_usb_cam cam2 "$CAM2_DEV" && CAM2_DETECTED=1
CAM3_DETECTED=0; resolve_usb_cam_dev cam3 "$CAM3_USB_PATH" "$CAM3_DEV" CAM3_DEV && describe_usb_cam cam3 "$CAM3_DEV" && CAM3_DETECTED=1
CAM4_DETECTED=0; resolve_usb_cam_dev cam4 "$CAM4_USB_PATH" "$CAM4_DEV" CAM4_DEV && describe_usb_cam cam4 "$CAM4_DEV" && CAM4_DETECTED=1

# ── 启动 MediaMTX ──────────────────────────────────────────────────────────
echo ""
echo "Starting MediaMTX..."
setsid "$MEDIAMTX" "$ROOT_DIR/config/mediamtx.yml" >> "$ROOT_DIR/logs/mediamtx.log" 2>&1 &
echo $! > "$PID_DIR/mediamtx.pid"
echo "MediaMTX PID: $(cat "$PID_DIR/mediamtx.pid")"
sleep 2

# ── cam1 看门狗（HM30 IP 摄像头 → RTSP → cam）─────────────────────────────
echo "Starting FFmpeg watchdog cam1..."
setsid env \
  ROOT_DIR="$ROOT_DIR" \
  CAMERA_RTSP_URL="$CAMERA_RTSP_URL" \
  CAMERA_RETRY_DELAY="$CAMERA_RETRY_DELAY" \
  FFMPEG_LOGLEVEL="$FFMPEG_LOGLEVEL" \
  CAM1_THREADS="$CAM1_THREADS" \
  CAM1_BITRATE="$CAM1_BITRATE" \
  CAM1_MAXRATE="$CAM1_MAXRATE" \
  CAM1_BUFSIZE="$CAM1_BUFSIZE" \
  CAM1_FPS="$CAM1_FPS" \
  bash -c '
  while true; do
    echo "[$(date "+%F %T")] Starting FFmpeg cam1..." >> "$ROOT_DIR/logs/ffmpeg.log"
    ffmpeg -hide_banner -nostats -loglevel "$FFMPEG_LOGLEVEL" \
      -fflags nobuffer -flags low_delay -rtsp_transport tcp -stimeout 5000000 \
      -i "$CAMERA_RTSP_URL" \
      -c:v libx264 -preset ultrafast -tune zerolatency -threads "$CAM1_THREADS" \
      -b:v "$CAM1_BITRATE" -maxrate "$CAM1_MAXRATE" -bufsize "$CAM1_BUFSIZE" -g 10 -bf 0 -pix_fmt yuv420p \
      -r "$CAM1_FPS" \
      -f rtsp -rtsp_transport tcp rtsp://127.0.0.1:8554/cam \
      >> "$ROOT_DIR/logs/ffmpeg.log" 2>&1 || true
    echo "[$(date "+%F %T")] FFmpeg cam1 exited, restarting in ${CAMERA_RETRY_DELAY}s..." >> "$ROOT_DIR/logs/ffmpeg.log"
    sleep "$CAMERA_RETRY_DELAY"
  done
' &
echo $! > "$PID_DIR/ffmpeg_cam1.pid"
echo "FFmpeg cam1 watchdog PID: $(cat "$PID_DIR/ffmpeg_cam1.pid")"

# ── USB 摄像头看门狗（cam2/cam3/cam4）─────────────────────────────────────
# 默认启用 v360 鱼眼矫正：fisheye -> flat，可通过 USB_DEWARP=0 关闭
if [ "$USB_DEWARP" = "1" ]; then
  USB_VF="-vf v360=fisheye:flat:ih_fov=${USB_IN_FOV}:iv_fov=${USB_IN_FOV}:h_fov=${USB_OUT_H_FOV}:v_fov=${USB_OUT_V_FOV}"
  echo "USB 鱼眼矫正：启用 (in_fov=${USB_IN_FOV} out=${USB_OUT_H_FOV}x${USB_OUT_V_FOV})"
else
  USB_VF=""
  echo "USB 鱼眼矫正：关闭（原始鱼眼直推）"
fi

start_usb_watchdog() {
  local label="$1"
  local dev="$2"
  local rtsp_path="$3"
  local logfile="$ROOT_DIR/logs/ffmpeg_${label}.log"
  echo "Starting FFmpeg watchdog ${label} (USB ${dev})..."
  setsid env \
    label="$label" \
    dev="$dev" \
    rtsp_path="$rtsp_path" \
    logfile="$logfile" \
    vf_args="$USB_VF" \
    CAMERA_RETRY_DELAY="$CAMERA_RETRY_DELAY" \
    FFMPEG_LOGLEVEL="$FFMPEG_LOGLEVEL" \
    USB_THREADS="$USB_THREADS" \
    USB_BITRATE="$USB_BITRATE" \
    USB_MAXRATE="$USB_MAXRATE" \
    USB_BUFSIZE="$USB_BUFSIZE" \
    USB_FPS="$USB_FPS" \
    bash -c '
    while true; do
      if [ ! -e "$dev" ]; then
        echo "[$(date "+%F %T")] ${label} ${dev} disconnected, waiting..." >> "$logfile"
        sleep 5; continue
      fi
      echo "[$(date "+%F %T")] Starting FFmpeg ${label} (vf=${vf_args:-none})..." >> "$logfile"
      ffmpeg -hide_banner -nostats -loglevel "$FFMPEG_LOGLEVEL" \
        -fflags nobuffer -flags low_delay \
        -f v4l2 -input_format mjpeg -framerate "$USB_FPS" -video_size 1280x720 \
        -i "$dev" \
        ${vf_args} \
        -c:v libx264 -preset ultrafast -tune zerolatency -threads "$USB_THREADS" \
        -b:v "$USB_BITRATE" -maxrate "$USB_MAXRATE" -bufsize "$USB_BUFSIZE" -g 10 -bf 0 -pix_fmt yuv420p \
        -r "$USB_FPS" \
        -f rtsp -rtsp_transport tcp "rtsp://127.0.0.1:8554/${rtsp_path}" \
        >> "$logfile" 2>&1 || true
      echo "[$(date "+%F %T")] FFmpeg ${label} exited, restarting in ${CAMERA_RETRY_DELAY}s..." >> "$logfile"
      sleep "$CAMERA_RETRY_DELAY"
    done
  ' &
  echo $! > "$PID_DIR/ffmpeg_${label}.pid"
  echo "FFmpeg ${label} watchdog PID: $(cat "$PID_DIR/ffmpeg_${label}.pid")"
}

if [ "$CAM2_ENABLED" != "1" ]; then
  CAM2_DETECTED=0
  echo "cam2 disabled (CAM2_ENABLED=$CAM2_ENABLED)."
elif [ "$CAM2_DETECTED" -eq 1 ]; then
  start_usb_watchdog cam2 "$CAM2_DEV" cam2
else
  echo "cam2 skipped (not connected at startup)."
fi

if [ "$CAM3_ENABLED" != "1" ]; then
  CAM3_DETECTED=0
  echo "cam3 disabled (CAM3_ENABLED=$CAM3_ENABLED)."
elif [ "$CAM3_DETECTED" -eq 1 ]; then
  start_usb_watchdog cam3 "$CAM3_DEV" cam3
else
  echo "cam3 skipped (not connected at startup)."
fi

if [ "$CAM4_ENABLED" != "1" ]; then
  CAM4_DETECTED=0
  echo "cam4 disabled (CAM4_ENABLED=$CAM4_ENABLED)."
elif [ "$CAM4_DETECTED" -eq 1 ]; then
  start_usb_watchdog cam4 "$CAM4_DEV" cam4
else
  echo "cam4 skipped (not connected at startup)."
fi

# ── 启动摘要 ───────────────────────────────────────────────────────────────
echo ""
echo "=========================================="
echo "Pipeline started."
echo "  cam1 (HM30): $([ "$CAM1_DETECTED" -eq 1 ] && echo "OK  已连接" || echo "WARN 不可达，重试中")"
echo "  cam2 (后):   $([ "$CAM2_DETECTED" -eq 1 ] && echo "OK  已连接 ($CAM2_DEV)" || echo "N/A 未连接，已跳过")"
echo "  cam3 (左):   $([ "$CAM3_DETECTED" -eq 1 ] && echo "OK  已连接 ($CAM3_DEV)" || echo "N/A 未连接，已跳过")"
echo "  cam4 (右):   $([ "$CAM4_DETECTED" -eq 1 ] && echo "OK  已连接 ($CAM4_DEV)" || echo "N/A 未连接，已跳过")"
echo "  WHEP cam:    http://127.0.0.1:8889/cam/whep"
echo "  WHEP cam2:   http://127.0.0.1:8889/cam2/whep"
echo "  WHEP cam3:   http://127.0.0.1:8889/cam3/whep"
echo "  WHEP cam4:   http://127.0.0.1:8889/cam4/whep"
echo "  Logs:        $ROOT_DIR/logs/"
echo "  Stop:        bash $0 stop"
echo "=========================================="
