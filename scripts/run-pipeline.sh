#!/usr/bin/env bash
# BotDog 视频流水线启动脚本（Linux 版）
# 启动 MediaMTX + FFmpeg 看门狗，启动时自动检测摄像头
#   cam1: Z2 Mini 云台相机 (RTSP 拉流 → MediaMTX)
#   cam2: 后视 USB 摄像头 → MediaMTX
#   cam3: 左视 USB 摄像头 → MediaMTX
#   cam4: 右视 USB 摄像头 → MediaMTX
#   推荐用 CAM*_USB_PATH 绑定 /dev/v4l/by-path 下的 USB 物理口路径。
#   注：GS02 每路摄像头创建 2 个节点（采集+元数据），脚本会自动筛选采集节点。

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.."
PID_DIR="$ROOT_DIR/logs"

# 视频硬件配置独立于后端 .env；手工启动和 systemd 启动共用同一份配置。
# 可用 PIPELINE_ENV_FILE 覆盖，设为空字符串则跳过配置文件。
PIPELINE_ENV_FILE="${PIPELINE_ENV_FILE-$ROOT_DIR/config/pipeline.env}"
if [ -n "$PIPELINE_ENV_FILE" ] && [ -f "$PIPELINE_ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$PIPELINE_ENV_FILE"
  set +a
fi

# RTSP/MediaMTX 是机载本地链路，禁止继承桌面代理。
# 否则 GStreamer 可能把相机 RTSP 请求发到 ALL_PROXY/HTTP_PROXY，
# 地面端代理或网络一抖就会让本机 cam publisher 掉线。
unset http_proxy https_proxy ftp_proxy all_proxy
unset HTTP_PROXY HTTPS_PROXY FTP_PROXY ALL_PROXY

MEDIAMTX="${MEDIAMTX_EXE:-$ROOT_DIR/scripts/mediamtx}"
# cam1：Z2 Mini 云台相机 RTSP 地址（可由 config/pipeline.env 覆盖）
CAMERA_RTSP_URL="${CAMERA_RTSP_URL:-rtsp://192.168.123.108:554/}"
CAMERA_RETRY_DELAY="${CAMERA_RETRY_DELAY:-2}"
FFMPEG_LOGLEVEL="${FFMPEG_LOGLEVEL:-warning}"
# 主摄像头冷启动保护及健康探测。STARTUP_GRACE 每个 Linux boot 只执行一次；
# 后续只在视频轨真正就绪后启动转码，失败时指数退避，避免轰炸相机固件。
CAM1_STARTUP_GRACE="${CAM1_STARTUP_GRACE:-30}"
CAM1_PROBE_TIMEOUT="${CAM1_PROBE_TIMEOUT:-8}"
CAM1_RETRY_INITIAL_DELAY="${CAM1_RETRY_INITIAL_DELAY:-5}"
CAM1_RETRY_MAX_DELAY="${CAM1_RETRY_MAX_DELAY:-30}"
# 部分 Z2-Mini 固件会出现 RTSP 端口存活、图像服务却没有视频轨的假活状态。
# 连续失败达到阈值后，先重启相机原厂图像服务并验证真实视频；验证失败则升级为
# 相机整机重启。冷却期限制的是每一轮两级恢复，避免故障时持续重启硬件。
CAM1_RECOVERY_ENABLED="${CAM1_RECOVERY_ENABLED:-1}"
CAM1_RECOVERY_FAILURES="${CAM1_RECOVERY_FAILURES:-3}"
CAM1_RECOVERY_COOLDOWN="${CAM1_RECOVERY_COOLDOWN:-300}"
CAM1_RECOVERY_SETTLE_DELAY="${CAM1_RECOVERY_SETTLE_DELAY:-15}"
CAM1_RECOVERY_REBOOT_ENABLED="${CAM1_RECOVERY_REBOOT_ENABLED:-1}"
CAM1_RECOVERY_REBOOT_SETTLE_DELAY="${CAM1_RECOVERY_REBOOT_SETTLE_DELAY:-45}"
CAM1_RECOVERY_TELNET_PORT="${CAM1_RECOVERY_TELNET_PORT:-23}"
CAM1_RECOVERY_TIMEOUT="${CAM1_RECOVERY_TIMEOUT:-20}"
# Z2-Mini GCU 私有协议控制。CAM1_OSD=off/on；设为 keep 则不改相机当前状态。
CAM1_OSD="${CAM1_OSD:-off}"
CAM1_CONTROL_PORT="${CAM1_CONTROL_PORT:-2332}"
CAM1_CONTROL_TIMEOUT="${CAM1_CONTROL_TIMEOUT:-2}"
CAM1_CONTROL_RETRIES="${CAM1_CONTROL_RETRIES:-5}"
CAM1_FPS="${CAM1_FPS:-30}"
CAM1_WIDTH="${CAM1_WIDTH:-1280}"
CAM1_HEIGHT="${CAM1_HEIGHT:-720}"
CAM1_THREADS="${CAM1_THREADS:-2}"
CAM1_BITRATE="${CAM1_BITRATE:-2500k}"
CAM1_GST_BITRATE="${CAM1_GST_BITRATE:-2500000}"
CAM1_GST_VBV_SIZE="${CAM1_GST_VBV_SIZE:-300000}"
CAM1_MAXRATE="${CAM1_MAXRATE:-3000k}"
CAM1_BUFSIZE="${CAM1_BUFSIZE:-500k}"
CAM1_GOP="${CAM1_GOP:-15}"
CAM1_ALLOW_SOFTWARE_FALLBACK="${CAM1_ALLOW_SOFTWARE_FALLBACK:-1}"
CAM1_GST_LATENCY="${CAM1_GST_LATENCY:-30}"
# 主摄像头输入编码：Z2 Mini 默认 H.264；旧 HM30 可通过 CAM1_INPUT_CODEC=h265 切回。
CAM1_INPUT_CODEC="${CAM1_INPUT_CODEC:-h264}"
# cam1 转码器：
#   copy          H.264 原码流直通 MediaMTX，资源占用最低，但保留相机不规则时间戳
#   gst-nvenc     GStreamer NVIDIA 硬解 + 硬编 H.264（部分 Z2 固件存在帧率兼容问题）
#   auto          优先硬件 H.264 编码，失败再回退 libx264
#   h264_v4l2m2m  V4L2 mem2mem 硬件编码，Jetson 上通常显著降低 CPU
#   h264_omx      OpenMAX H.264 硬件编码，作为旧 Jetson/FFmpeg 备选
#   libx264       软件回退路径
CAM1_ENCODER="${CAM1_ENCODER:-gst-nvenc}"
# 可选强制硬件解码，例如 HEVC 摄像头可设 CAM1_DECODER=hevc_nvv4l2dec。
# 默认 auto 交给 FFmpeg 探测，避免摄像头编码变化时拉流失败。
CAM1_DECODER="${CAM1_DECODER:-auto}"
# cam_remote：从 cam 派生的远程低延迟 WHEP 档位，远端 Tailscale/WAN 访问优先使用。
CAM_REMOTE_ENABLED="${CAM_REMOTE_ENABLED:-1}"
CAM_REMOTE_SOURCE="${CAM_REMOTE_SOURCE:-rtsp://127.0.0.1:8554/cam}"
CAM_REMOTE_WIDTH="${CAM_REMOTE_WIDTH:-854}"
CAM_REMOTE_HEIGHT="${CAM_REMOTE_HEIGHT:-480}"
CAM_REMOTE_FPS="${CAM_REMOTE_FPS:-10}"
CAM_REMOTE_THREADS="${CAM_REMOTE_THREADS:-2}"
CAM_REMOTE_BITRATE="${CAM_REMOTE_BITRATE:-1200k}"
CAM_REMOTE_GST_BITRATE="${CAM_REMOTE_GST_BITRATE:-1200000}"
CAM_REMOTE_GST_VBV_SIZE="${CAM_REMOTE_GST_VBV_SIZE:-250000}"
CAM_REMOTE_MAXRATE="${CAM_REMOTE_MAXRATE:-1400k}"
CAM_REMOTE_BUFSIZE="${CAM_REMOTE_BUFSIZE:-250k}"
CAM_REMOTE_GOP="${CAM_REMOTE_GOP:-10}"
CAM_REMOTE_ENCODER="${CAM_REMOTE_ENCODER:-ffmpeg}"
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
USB_GST_BITRATE="${USB_GST_BITRATE:-1200000}"
USB_MAXRATE="${USB_MAXRATE:-1600k}"
USB_BUFSIZE="${USB_BUFSIZE:-200k}"
USB_IN_FOV="${USB_IN_FOV:-180}"
USB_OUT_H_FOV="${USB_OUT_H_FOV:-120}"
USB_OUT_V_FOV="${USB_OUT_V_FOV:-75}"
USB_DISCOVERY_DELAY="${USB_DISCOVERY_DELAY:-5}"
# USB 摄像头编码器：
#   gst-nvenc  GStreamer 采集 + NVIDIA H.264 硬编，FFmpeg 仅封装 RTSP
#   ffmpeg     原 FFmpeg libx264 软件编码路径，兼容性最高但 CPU 占用高
USB_ENCODER="${USB_ENCODER:-gst-nvenc}"

mkdir -p "$PID_DIR"

# ── 停止旧进程 ──────────────────────────────────────────────────────────────
stop_pipeline() {
  for pidfile in "$PID_DIR"/{mediamtx,ffmpeg_cam1,ffmpeg_cam_remote,ffmpeg_cam2,ffmpeg_cam3,ffmpeg_cam4}.pid; do
    if [ -f "$pidfile" ]; then
      local pid
      pid=$(cat "$pidfile" 2>/dev/null || true)
      if [ -z "$pid" ]; then
        rm -f "$pidfile"
        continue
      fi
      kill -- -"$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
      rm -f "$pidfile"
    fi
  done
  pkill -f "mediamtx.*mediamtx.yml" 2>/dev/null || true
  # Do not kill every ffmpeg process. The backend AI worker also owns an
  # ffmpeg process that reads rtsp://127.0.0.1:8554/cam; killing it makes AI
  # tracking drop frames until the worker reconnects.
  pkill -f "ffmpeg .* -f rtsp .*rtsp://127\\.0\\.0\\.1:8554/cam([[:space:]]|$)" 2>/dev/null || true
  pkill -f "ffmpeg .* -f rtsp .*rtsp://127\\.0\\.0\\.1:8554/cam_remote([[:space:]]|$)" 2>/dev/null || true
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
command -v ffprobe &>/dev/null || { echo "ERROR: FFprobe not found"; exit 1; }
command -v python3 &>/dev/null || { echo "ERROR: Python 3 not found"; exit 1; }

# ── 摄像头自动检测 ──────────────────────────────────────────────────────────
echo ""
echo "Detecting cameras..."

# cam1：只解析控制命令需要的主机地址。冷启动静默期结束前不连接相机；真正的
# 网络和视频就绪状态统一由下方看门狗通过 ffprobe 验证。
CAM1_HOST=$(echo "$CAMERA_RTSP_URL" | sed 's|rtsp://||' | cut -d'/' -f1 | cut -d':' -f1)
echo "  [INFO] cam1 Z2 Mini 已配置: $CAMERA_RTSP_URL（冷启动静默后探测视频）"

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
      echo "  [WARN] $label USB 物理口暂未找到 ($usb_path)，看门狗稍后持续发现"
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
    echo "  [WARN] $label USB 物理口存在但暂时没有采集节点 ($usb_path)，看门狗稍后持续发现"
  else
    echo "  [WARN] $label USB 摄像头暂未找到或不是采集节点 ($fallback_dev)，看门狗稍后持续发现"
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

# ── cam1 看门狗（Z2 Mini 云台相机 → RTSP → cam）──────────────────────────
echo "Starting FFmpeg watchdog cam1..."
setsid env \
  ROOT_DIR="$ROOT_DIR" \
  CAMERA_RTSP_URL="$CAMERA_RTSP_URL" \
  CAMERA_RETRY_DELAY="$CAMERA_RETRY_DELAY" \
  FFMPEG_LOGLEVEL="$FFMPEG_LOGLEVEL" \
  CAM1_HOST="$CAM1_HOST" \
  CAM1_STARTUP_GRACE="$CAM1_STARTUP_GRACE" \
  CAM1_PROBE_TIMEOUT="$CAM1_PROBE_TIMEOUT" \
  CAM1_RETRY_INITIAL_DELAY="$CAM1_RETRY_INITIAL_DELAY" \
  CAM1_RETRY_MAX_DELAY="$CAM1_RETRY_MAX_DELAY" \
  CAM1_RECOVERY_ENABLED="$CAM1_RECOVERY_ENABLED" \
  CAM1_RECOVERY_FAILURES="$CAM1_RECOVERY_FAILURES" \
  CAM1_RECOVERY_COOLDOWN="$CAM1_RECOVERY_COOLDOWN" \
  CAM1_RECOVERY_SETTLE_DELAY="$CAM1_RECOVERY_SETTLE_DELAY" \
  CAM1_RECOVERY_REBOOT_ENABLED="$CAM1_RECOVERY_REBOOT_ENABLED" \
  CAM1_RECOVERY_REBOOT_SETTLE_DELAY="$CAM1_RECOVERY_REBOOT_SETTLE_DELAY" \
  CAM1_RECOVERY_TELNET_PORT="$CAM1_RECOVERY_TELNET_PORT" \
  CAM1_RECOVERY_TIMEOUT="$CAM1_RECOVERY_TIMEOUT" \
  CAM1_OSD="$CAM1_OSD" \
  CAM1_CONTROL_PORT="$CAM1_CONTROL_PORT" \
  CAM1_CONTROL_TIMEOUT="$CAM1_CONTROL_TIMEOUT" \
  CAM1_CONTROL_RETRIES="$CAM1_CONTROL_RETRIES" \
  CAM1_THREADS="$CAM1_THREADS" \
  CAM1_BITRATE="$CAM1_BITRATE" \
  CAM1_GST_BITRATE="$CAM1_GST_BITRATE" \
  CAM1_GST_VBV_SIZE="$CAM1_GST_VBV_SIZE" \
  CAM1_MAXRATE="$CAM1_MAXRATE" \
  CAM1_BUFSIZE="$CAM1_BUFSIZE" \
  CAM1_GOP="$CAM1_GOP" \
  CAM1_ALLOW_SOFTWARE_FALLBACK="$CAM1_ALLOW_SOFTWARE_FALLBACK" \
  CAM1_GST_LATENCY="$CAM1_GST_LATENCY" \
  CAM1_INPUT_CODEC="$CAM1_INPUT_CODEC" \
  CAM1_FPS="$CAM1_FPS" \
  CAM1_WIDTH="$CAM1_WIDTH" \
  CAM1_HEIGHT="$CAM1_HEIGHT" \
  CAM1_ENCODER="$CAM1_ENCODER" \
  CAM1_DECODER="$CAM1_DECODER" \
  bash -c '
  log_cam1() {
    echo "[$(date "+%F %T")] $*" >> "$ROOT_DIR/logs/ffmpeg.log"
  }

  apply_cold_boot_grace_once() {
    local boot_id marker previous_boot_id
    marker="$ROOT_DIR/logs/camera_startup_boot_id"
    boot_id=$(cat /proc/sys/kernel/random/boot_id 2>/dev/null || true)
    previous_boot_id=$(cat "$marker" 2>/dev/null || true)

    if [ -n "$boot_id" ] && [ "$previous_boot_id" = "$boot_id" ]; then
      return 0
    fi
    if [ "$CAM1_STARTUP_GRACE" -gt 0 ]; then
      log_cam1 "Cold boot detected; leaving camera idle for ${CAM1_STARTUP_GRACE}s before first RTSP probe"
      sleep "$CAM1_STARTUP_GRACE"
    fi
    if [ -n "$boot_id" ]; then
      printf "%s\n" "$boot_id" > "$marker"
    fi
  }

  wait_for_cam1_video() {
    local retry_delay probe_detail next_delay consecutive_failures
    local now_uptime cooldown_elapsed recovery_detail verify_detail reboot_detail
    retry_delay="$CAM1_RETRY_INITIAL_DELAY"
    consecutive_failures=0

    while true; do
      if probe_detail=$(python3 "$ROOT_DIR/scripts/rtsp-healthcheck.py" \
        --url "$CAMERA_RTSP_URL" \
        --timeout "$CAM1_PROBE_TIMEOUT" 2>&1); then
        log_cam1 "RTSP health check passed: ${probe_detail}"
        return 0
      fi

      osd_needs_config=1
      consecutive_failures=$(( consecutive_failures + 1 ))

      if [ "$CAM1_RECOVERY_ENABLED" = "1" ] && \
        [ "$CAM1_RECOVERY_FAILURES" -gt 0 ] && \
        [ "$consecutive_failures" -ge "$CAM1_RECOVERY_FAILURES" ]; then
        now_uptime=$(cut -d. -f1 /proc/uptime)
        cooldown_elapsed=$(( now_uptime - cam1_recovery_last_uptime ))
        if [ "$cam1_recovery_last_uptime" -eq 0 ] || \
          [ "$cooldown_elapsed" -ge "$CAM1_RECOVERY_COOLDOWN" ]; then
          cam1_recovery_last_uptime="$now_uptime"
          log_cam1 "RTSP failed ${consecutive_failures} consecutive checks; starting two-stage camera recovery"
          if recovery_detail=$(python3 "$ROOT_DIR/scripts/z2mini-recover.py" \
            --host "$CAM1_HOST" \
            --port "$CAM1_RECOVERY_TELNET_PORT" \
            --timeout "$CAM1_RECOVERY_TIMEOUT" \
            --mode service 2>&1); then
            log_cam1 "Z2-Mini service recovery verified: ${recovery_detail}; settling for ${CAM1_RECOVERY_SETTLE_DELAY}s"
            sleep "$CAM1_RECOVERY_SETTLE_DELAY"
            if verify_detail=$(python3 "$ROOT_DIR/scripts/rtsp-healthcheck.py" \
              --url "$CAMERA_RTSP_URL" \
              --timeout "$CAM1_PROBE_TIMEOUT" 2>&1); then
              log_cam1 "Z2-Mini service recovery produced healthy video: ${verify_detail}"
              return 0
            fi
            log_cam1 "WARN: Z2-Mini service recovery did not produce video: ${verify_detail}"
          else
            log_cam1 "WARN: Z2-Mini service recovery failed verification: ${recovery_detail}"
          fi

          if [ "$CAM1_RECOVERY_REBOOT_ENABLED" = "1" ]; then
            log_cam1 "Escalating failed service recovery to a complete camera reboot"
            if reboot_detail=$(python3 "$ROOT_DIR/scripts/z2mini-recover.py" \
              --host "$CAM1_HOST" \
              --port "$CAM1_RECOVERY_TELNET_PORT" \
              --timeout "$CAM1_RECOVERY_TIMEOUT" \
              --mode reboot 2>&1); then
              log_cam1 "Z2-Mini reboot accepted: ${reboot_detail}; settling for ${CAM1_RECOVERY_REBOOT_SETTLE_DELAY}s"
              consecutive_failures=0
              retry_delay="$CAM1_RETRY_INITIAL_DELAY"
              sleep "$CAM1_RECOVERY_REBOOT_SETTLE_DELAY"
              continue
            fi
            log_cam1 "WARN: Z2-Mini reboot request failed: ${reboot_detail}"
          fi
        fi
      fi

      log_cam1 "RTSP video not ready: ${probe_detail}; retrying in ${retry_delay}s"
      sleep "$retry_delay"
      next_delay=$(( retry_delay * 2 ))
      if [ "$next_delay" -gt "$CAM1_RETRY_MAX_DELAY" ]; then
        next_delay="$CAM1_RETRY_MAX_DELAY"
      fi
      retry_delay="$next_delay"
    done
  }

  configure_cam1_osd() {
    case "$CAM1_OSD" in
      keep)
        return 0
        ;;
      on|off)
        ;;
      *)
        log_cam1 "Invalid CAM1_OSD=${CAM1_OSD}; expected on, off or keep"
        return 0
        ;;
    esac

    if python3 "$ROOT_DIR/scripts/z2mini-control.py" \
      --host "$CAM1_HOST" \
      --port "$CAM1_CONTROL_PORT" \
      --osd "$CAM1_OSD" \
      --timeout "$CAM1_CONTROL_TIMEOUT" \
      --retries "$CAM1_CONTROL_RETRIES" \
      --retry-delay 1 \
      >> "$ROOT_DIR/logs/ffmpeg.log" 2>&1; then
      log_cam1 "Z2-Mini OSD ${CAM1_OSD} verified"
    else
      log_cam1 "WARN: could not configure Z2-Mini OSD; video startup will continue"
    fi
  }

  run_cam1_ffmpeg() {
    local encoder="$1"
    local decoder_args=()
    local encoder_args=()
    local filter_args=()

    if [ "$CAM1_DECODER" != "auto" ] && [ -n "$CAM1_DECODER" ]; then
      decoder_args=(-c:v "$CAM1_DECODER")
    fi

    case "$encoder" in
      copy)
        encoder_args=(
          -map 0:v:0 -an -c:v copy
        )
        ;;
      h264_v4l2m2m)
        filter_args=(-vf "scale=${CAM1_WIDTH}:${CAM1_HEIGHT}:flags=fast_bilinear")
        encoder_args=(
          -c:v h264_v4l2m2m
          -b:v "$CAM1_BITRATE" -maxrate "$CAM1_MAXRATE" -bufsize "$CAM1_BUFSIZE"
          -g "$CAM1_GOP" -bf 0 -pix_fmt yuv420p
        )
        ;;
      h264_omx)
        filter_args=(-vf "scale=${CAM1_WIDTH}:${CAM1_HEIGHT}:flags=fast_bilinear")
        encoder_args=(
          -c:v h264_omx -profile baseline
          -b:v "$CAM1_BITRATE" -bufsize "$CAM1_BUFSIZE"
          -g "$CAM1_GOP" -bf 0 -pix_fmt yuv420p
        )
        ;;
      libx264)
        filter_args=(-vf "scale=${CAM1_WIDTH}:${CAM1_HEIGHT}:flags=fast_bilinear")
        encoder_args=(
          -c:v libx264 -preset ultrafast -tune zerolatency -threads "$CAM1_THREADS"
          -b:v "$CAM1_BITRATE" -maxrate "$CAM1_MAXRATE" -bufsize "$CAM1_BUFSIZE"
          -g "$CAM1_GOP" -bf 0 -pix_fmt yuv420p
        )
        ;;
      *)
        echo "[$(date "+%F %T")] Unsupported CAM1_ENCODER=${encoder}, fallback to libx264" >> "$ROOT_DIR/logs/ffmpeg.log"
        run_cam1_ffmpeg libx264
        return $?
        ;;
    esac

    log_cam1 "Starting FFmpeg cam1 (encoder=${encoder}, decoder=${CAM1_DECODER})..."
    ffmpeg -hide_banner -nostats -loglevel "$FFMPEG_LOGLEVEL" \
      -fflags nobuffer -flags low_delay -rtsp_transport tcp \
      -stimeout 5000000 -use_wallclock_as_timestamps 1 \
      "${decoder_args[@]}" \
      -i "$CAMERA_RTSP_URL" \
      "${filter_args[@]}" \
      "${encoder_args[@]}" \
      -vsync passthrough \
      -muxdelay 0 -muxpreload 0 \
      -f rtsp -rtsp_transport tcp rtsp://127.0.0.1:8554/cam \
      >> "$ROOT_DIR/logs/ffmpeg.log" 2>&1
  }

  run_cam1_gst_nvenc() {
    local depay_element input_caps

    if ! command -v gst-launch-1.0 >/dev/null 2>&1; then
      echo "[$(date "+%F %T")] gst-launch-1.0 not found, fallback to FFmpeg" >> "$ROOT_DIR/logs/ffmpeg.log"
      return 1
    fi
    if ! gst-inspect-1.0 nvv4l2decoder >/dev/null 2>&1; then
      echo "[$(date "+%F %T")] nvv4l2decoder not found, fallback to FFmpeg" >> "$ROOT_DIR/logs/ffmpeg.log"
      return 1
    fi
    if ! gst-inspect-1.0 nvv4l2h264enc >/dev/null 2>&1; then
      echo "[$(date "+%F %T")] nvv4l2h264enc not found, fallback to FFmpeg" >> "$ROOT_DIR/logs/ffmpeg.log"
      return 1
    fi

    case "$CAM1_INPUT_CODEC" in
      h264|avc)
        depay_element=rtph264depay
        input_caps="video/x-h264,stream-format=(string)byte-stream,alignment=(string)au"
        ;;
      h265|hevc)
        depay_element=rtph265depay
        input_caps="video/x-h265,stream-format=(string)byte-stream,alignment=(string)au"
        ;;
      *)
        echo "[$(date "+%F %T")] Unsupported CAM1_INPUT_CODEC=${CAM1_INPUT_CODEC}" >> "$ROOT_DIR/logs/ffmpeg.log"
        return 1
        ;;
    esac

    log_cam1 "Starting cam1 (input=${CAM1_INPUT_CODEC}, encoder=gst-nvenc, output=${CAM1_WIDTH}x${CAM1_HEIGHT}, decoder=nvv4l2decoder)..."
    gst-launch-1.0 -q \
      rtspsrc location="$CAMERA_RTSP_URL" protocols=tcp latency="$CAM1_GST_LATENCY" drop-on-latency=true do-retransmission=false tcp-timeout=5000000 ! \
      "$depay_element" ! "$input_caps" ! \
      queue max-size-buffers=30 max-size-bytes=0 max-size-time=0 leaky=downstream ! \
      nvv4l2decoder enable-max-performance=true ! \
      nvvidconv ! "video/x-raw(memory:NVMM),width=(int)${CAM1_WIDTH},height=(int)${CAM1_HEIGHT},format=(string)NV12" ! \
      nvv4l2h264enc bitrate="$CAM1_GST_BITRATE" vbv-size="$CAM1_GST_VBV_SIZE" control-rate=1 num-B-Frames=0 num-Ref-Frames=1 poc-type=2 iframeinterval="$CAM1_GOP" idrinterval="$CAM1_GOP" insert-sps-pps=true insert-vui=true maxperf-enable=true preset-level=1 ! \
      "video/x-h264,stream-format=(string)byte-stream,alignment=(string)au" ! \
      fdsink fd=1 sync=false async=false \
      2>> "$ROOT_DIR/logs/ffmpeg.log" | \
    ffmpeg -hide_banner -nostats -loglevel "$FFMPEG_LOGLEVEL" \
      -fflags nobuffer -flags low_delay -use_wallclock_as_timestamps 1 \
      -probesize 1000000 -analyzeduration 1000000 -framerate "$CAM1_FPS" -f h264 -i pipe:0 \
      -c:v copy -muxdelay 0 -muxpreload 0 -flush_packets 1 \
      -f rtsp -rtsp_transport tcp rtsp://127.0.0.1:8554/cam \
      >> "$ROOT_DIR/logs/ffmpeg.log" 2>&1
  }

  run_cam1_gst_nvenc_with_optional_fallback() {
    if run_cam1_gst_nvenc; then
      return 0
    fi
    if [ "$CAM1_ALLOW_SOFTWARE_FALLBACK" = "1" ]; then
      echo "[$(date "+%F %T")] gst-nvenc failed, software fallback enabled" >> "$ROOT_DIR/logs/ffmpeg.log"
      run_cam1_ffmpeg libx264
      return $?
    fi
    echo "[$(date "+%F %T")] gst-nvenc failed, software fallback disabled; retrying hardware path after delay" >> "$ROOT_DIR/logs/ffmpeg.log"
    return 1
  }

  apply_cold_boot_grace_once
  osd_needs_config=1
  cam1_recovery_last_uptime=0
  while true; do
    wait_for_cam1_video
    if [ "$osd_needs_config" = "1" ]; then
      configure_cam1_osd
      osd_needs_config=0
    fi
    if [ "$CAM1_ENCODER" = "auto" ]; then
      run_cam1_gst_nvenc_with_optional_fallback || run_cam1_ffmpeg h264_v4l2m2m || run_cam1_ffmpeg h264_omx || true
    elif [ "$CAM1_ENCODER" = "gst-nvenc" ]; then
      run_cam1_gst_nvenc_with_optional_fallback || true
    else
      run_cam1_ffmpeg "$CAM1_ENCODER" || true
    fi
    log_cam1 "cam1 publisher exited; checking camera health again in ${CAM1_RETRY_INITIAL_DELAY}s"
    sleep "$CAM1_RETRY_INITIAL_DELAY"
  done
' &
echo $! > "$PID_DIR/ffmpeg_cam1.pid"
echo "FFmpeg cam1 watchdog PID: $(cat "$PID_DIR/ffmpeg_cam1.pid")"

# ── cam_remote 看门狗（cam → 远程低延迟转码流）───────────────────────────────
if [ "$CAM_REMOTE_ENABLED" = "1" ]; then
  echo "Starting FFmpeg watchdog cam_remote..."
  setsid env \
    ROOT_DIR="$ROOT_DIR" \
    CAM_REMOTE_SOURCE="$CAM_REMOTE_SOURCE" \
    CAMERA_RETRY_DELAY="$CAMERA_RETRY_DELAY" \
    FFMPEG_LOGLEVEL="$FFMPEG_LOGLEVEL" \
    CAM_REMOTE_WIDTH="$CAM_REMOTE_WIDTH" \
    CAM_REMOTE_HEIGHT="$CAM_REMOTE_HEIGHT" \
    CAM_REMOTE_FPS="$CAM_REMOTE_FPS" \
    CAM_REMOTE_THREADS="$CAM_REMOTE_THREADS" \
    CAM_REMOTE_BITRATE="$CAM_REMOTE_BITRATE" \
    CAM_REMOTE_GST_BITRATE="$CAM_REMOTE_GST_BITRATE" \
    CAM_REMOTE_GST_VBV_SIZE="$CAM_REMOTE_GST_VBV_SIZE" \
    CAM_REMOTE_MAXRATE="$CAM_REMOTE_MAXRATE" \
    CAM_REMOTE_BUFSIZE="$CAM_REMOTE_BUFSIZE" \
    CAM_REMOTE_GOP="$CAM_REMOTE_GOP" \
    CAM_REMOTE_ENCODER="$CAM_REMOTE_ENCODER" \
    bash -c '
    run_cam_remote_ffmpeg() {
      ffmpeg -hide_banner -nostats -loglevel "$FFMPEG_LOGLEVEL" \
        -fflags nobuffer -flags low_delay -rtsp_transport tcp \
        -stimeout 5000000 -use_wallclock_as_timestamps 1 \
        -i "$CAM_REMOTE_SOURCE" \
        -an -vf "fps=${CAM_REMOTE_FPS},scale=${CAM_REMOTE_WIDTH}:${CAM_REMOTE_HEIGHT}:flags=fast_bilinear" \
        -c:v libx264 -preset ultrafast -tune zerolatency -threads "$CAM_REMOTE_THREADS" \
        -b:v "$CAM_REMOTE_BITRATE" -maxrate "$CAM_REMOTE_MAXRATE" -bufsize "$CAM_REMOTE_BUFSIZE" \
        -g "$CAM_REMOTE_GOP" -keyint_min "$CAM_REMOTE_GOP" -bf 0 -pix_fmt yuv420p \
        -r "$CAM_REMOTE_FPS" \
        -muxdelay 0 -muxpreload 0 \
        -f rtsp -rtsp_transport tcp rtsp://127.0.0.1:8554/cam_remote \
        >> "$ROOT_DIR/logs/ffmpeg_cam_remote.log" 2>&1
    }

    run_cam_remote_gst_nvenc() {
      if ! command -v gst-launch-1.0 >/dev/null 2>&1; then
        echo "[$(date "+%F %T")] gst-launch-1.0 not found, fallback to libx264" >> "$ROOT_DIR/logs/ffmpeg_cam_remote.log"
        return 1
      fi
      if ! gst-inspect-1.0 nvv4l2decoder >/dev/null 2>&1; then
        echo "[$(date "+%F %T")] nvv4l2decoder not found, fallback to libx264" >> "$ROOT_DIR/logs/ffmpeg_cam_remote.log"
        return 1
      fi
      if ! gst-inspect-1.0 nvv4l2h264enc >/dev/null 2>&1; then
        echo "[$(date "+%F %T")] nvv4l2h264enc not found, fallback to libx264" >> "$ROOT_DIR/logs/ffmpeg_cam_remote.log"
        return 1
      fi

      gst-launch-1.0 -q \
        rtspsrc location="$CAM_REMOTE_SOURCE" protocols=tcp latency=30 drop-on-latency=true do-retransmission=false tcp-timeout=5000000 ! \
        rtph264depay ! "video/x-h264,stream-format=(string)byte-stream,alignment=(string)au" ! \
        queue max-size-buffers=30 max-size-bytes=0 max-size-time=0 leaky=downstream ! \
        nvv4l2decoder enable-max-performance=true ! \
        nvvidconv ! "video/x-raw(memory:NVMM),width=(int)${CAM_REMOTE_WIDTH},height=(int)${CAM_REMOTE_HEIGHT},format=(string)NV12" ! \
        nvv4l2h264enc bitrate="$CAM_REMOTE_GST_BITRATE" vbv-size="$CAM_REMOTE_GST_VBV_SIZE" control-rate=1 num-B-Frames=0 num-Ref-Frames=1 poc-type=2 iframeinterval="$CAM_REMOTE_GOP" idrinterval="$CAM_REMOTE_GOP" insert-sps-pps=true insert-vui=true maxperf-enable=true preset-level=1 ! \
        "video/x-h264,stream-format=(string)byte-stream,alignment=(string)au" ! \
        fdsink fd=1 sync=false async=false \
        2>> "$ROOT_DIR/logs/ffmpeg_cam_remote.log" | \
      ffmpeg -hide_banner -nostats -loglevel "$FFMPEG_LOGLEVEL" \
        -fflags nobuffer -flags low_delay -use_wallclock_as_timestamps 1 \
        -probesize 1000000 -analyzeduration 1000000 -framerate "$CAM_REMOTE_FPS" -f h264 -i pipe:0 \
        -c:v copy -muxdelay 0 -muxpreload 0 -flush_packets 1 \
        -f rtsp -rtsp_transport tcp rtsp://127.0.0.1:8554/cam_remote \
        >> "$ROOT_DIR/logs/ffmpeg_cam_remote.log" 2>&1
    }

    while true; do
      echo "[$(date "+%F %T")] Starting cam_remote (encoder=${CAM_REMOTE_ENCODER}, ${CAM_REMOTE_WIDTH}x${CAM_REMOTE_HEIGHT}@${CAM_REMOTE_FPS}, ${CAM_REMOTE_BITRATE})..." >> "$ROOT_DIR/logs/ffmpeg_cam_remote.log"
      if [ "$CAM_REMOTE_ENCODER" = "gst-nvenc" ]; then
        run_cam_remote_gst_nvenc || run_cam_remote_ffmpeg || true
      else
        run_cam_remote_ffmpeg || true
      fi
      echo "[$(date "+%F %T")] FFmpeg cam_remote exited, restarting in ${CAMERA_RETRY_DELAY}s..." >> "$ROOT_DIR/logs/ffmpeg_cam_remote.log"
      sleep "$CAMERA_RETRY_DELAY"
    done
  ' &
  echo $! > "$PID_DIR/ffmpeg_cam_remote.pid"
  echo "FFmpeg cam_remote watchdog PID: $(cat "$PID_DIR/ffmpeg_cam_remote.pid")"
else
  echo "cam_remote disabled (CAM_REMOTE_ENABLED=$CAM_REMOTE_ENABLED)."
fi

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
  local usb_path="$3"
  local fallback_dev="$4"
  local rtsp_path="$5"
  local logfile="$ROOT_DIR/logs/ffmpeg_${label}.log"
  echo "Starting USB discovery/watchdog ${label} (current=${dev}, path=${usb_path:-auto})..."
  setsid env \
    label="$label" \
    dev="$dev" \
    usb_path="$usb_path" \
    fallback_dev="$fallback_dev" \
    rtsp_path="$rtsp_path" \
    logfile="$logfile" \
    vf_args="$USB_VF" \
    CAMERA_RETRY_DELAY="$CAMERA_RETRY_DELAY" \
    FFMPEG_LOGLEVEL="$FFMPEG_LOGLEVEL" \
    USB_THREADS="$USB_THREADS" \
    USB_BITRATE="$USB_BITRATE" \
    USB_GST_BITRATE="$USB_GST_BITRATE" \
    USB_MAXRATE="$USB_MAXRATE" \
    USB_BUFSIZE="$USB_BUFSIZE" \
    USB_FPS="$USB_FPS" \
    USB_ENCODER="$USB_ENCODER" \
    USB_DISCOVERY_DELAY="$USB_DISCOVERY_DELAY" \
    bash -c '
    resolve_capture_dev() {
      local candidate info caps
      local candidates=()

      if [ -n "$usb_path" ]; then
        if [ -e "$usb_path" ]; then
          candidates+=("$usb_path")
        fi
        while IFS= read -r candidate; do
          candidates+=("$candidate")
        done < <(compgen -G "${usb_path}-video-index*" || true)
      else
        candidates+=("$fallback_dev")
      fi

      for candidate in "${candidates[@]}"; do
        [ -e "$candidate" ] || continue
        info=$(v4l2-ctl --device="$candidate" --info 2>/dev/null || true)
        caps=$(echo "$info" | grep "Device Caps" | grep -o "0x[0-9a-fA-F]*" | tail -1)
        if [ -n "$caps" ] && [ $(( caps & 1 )) -ne 0 ]; then
          printf "%s\n" "$candidate"
          return 0
        fi
      done
      return 1
    }

    run_usb_ffmpeg() {
      ffmpeg -hide_banner -nostats -loglevel "$FFMPEG_LOGLEVEL" \
        -fflags nobuffer -flags low_delay \
        -f v4l2 -input_format mjpeg -framerate "$USB_FPS" -video_size 1280x720 \
        -i "$dev" \
        ${vf_args} \
        -c:v libx264 -preset ultrafast -tune zerolatency -threads "$USB_THREADS" \
        -b:v "$USB_BITRATE" -maxrate "$USB_MAXRATE" -bufsize "$USB_BUFSIZE" -g 10 -bf 0 -pix_fmt yuv420p \
        -r "$USB_FPS" \
        -f rtsp -rtsp_transport tcp "rtsp://127.0.0.1:8554/${rtsp_path}" \
        >> "$logfile" 2>&1
    }

    run_usb_gst_nvenc() {
      if [ -n "$vf_args" ]; then
        echo "[$(date "+%F %T")] ${label} USB_DEWARP requires FFmpeg filter, fallback to libx264" >> "$logfile"
        return 1
      fi
      if ! command -v gst-launch-1.0 >/dev/null 2>&1; then
        echo "[$(date "+%F %T")] gst-launch-1.0 not found, fallback to libx264" >> "$logfile"
        return 1
      fi
      if ! gst-inspect-1.0 nvv4l2h264enc >/dev/null 2>&1; then
        echo "[$(date "+%F %T")] nvv4l2h264enc not found, fallback to libx264" >> "$logfile"
        return 1
      fi

      gst-launch-1.0 -q \
        v4l2src device="$dev" do-timestamp=true ! watchdog timeout=5000 ! \
        "image/jpeg,width=(int)1280,height=(int)720,framerate=(fraction)30/1" ! \
        jpegdec ! videorate drop-only=true ! "video/x-raw,framerate=(fraction)${USB_FPS}/1" ! \
        videoconvert ! "video/x-raw,format=(string)I420" ! \
        nvvidconv ! "video/x-raw(memory:NVMM),format=(string)NV12" ! \
        nvv4l2h264enc bitrate="$USB_GST_BITRATE" iframeinterval=10 idrinterval=10 insert-sps-pps=true maxperf-enable=true preset-level=1 ! \
        h264parse config-interval=1 ! watchdog timeout=5000 ! fdsink fd=1 \
        2>> "$logfile" | \
      ffmpeg -hide_banner -nostats -loglevel "$FFMPEG_LOGLEVEL" \
        -fflags nobuffer -flags low_delay \
        -f h264 -i pipe:0 \
        -c:v copy \
        -f rtsp -rtsp_transport tcp "rtsp://127.0.0.1:8554/${rtsp_path}" \
        >> "$logfile" 2>&1
    }

    waiting_logged=0
    active_dev=""
    while true; do
      if ! dev=$(resolve_capture_dev); then
        if [ "$waiting_logged" = "0" ]; then
          echo "[$(date "+%F %T")] ${label} has no capture device; discovery remains active (path=${usb_path:-$fallback_dev})" >> "$logfile"
          waiting_logged=1
        fi
        sleep "$USB_DISCOVERY_DELAY"
        continue
      fi
      if [ "$dev" != "$active_dev" ]; then
        real_dev=$(readlink -f "$dev" 2>/dev/null || echo "$dev")
        echo "[$(date "+%F %T")] ${label} capture device discovered: ${dev} -> ${real_dev}" >> "$logfile"
        active_dev="$dev"
      fi
      waiting_logged=0
      echo "[$(date "+%F %T")] Starting ${label} (encoder=${USB_ENCODER}, vf=${vf_args:-none})..." >> "$logfile"
      if [ "$USB_ENCODER" = "gst-nvenc" ]; then
        run_usb_gst_nvenc || run_usb_ffmpeg || true
      else
        run_usb_ffmpeg || true
      fi
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
else
  start_usb_watchdog cam2 "$CAM2_DEV" "$CAM2_USB_PATH" "$CAM2_DEV" cam2
fi

if [ "$CAM3_ENABLED" != "1" ]; then
  CAM3_DETECTED=0
  echo "cam3 disabled (CAM3_ENABLED=$CAM3_ENABLED)."
else
  start_usb_watchdog cam3 "$CAM3_DEV" "$CAM3_USB_PATH" "$CAM3_DEV" cam3
fi

if [ "$CAM4_ENABLED" != "1" ]; then
  CAM4_DETECTED=0
  echo "cam4 disabled (CAM4_ENABLED=$CAM4_ENABLED)."
else
  start_usb_watchdog cam4 "$CAM4_DEV" "$CAM4_USB_PATH" "$CAM4_DEV" cam4
fi

# ── 启动摘要 ───────────────────────────────────────────────────────────────
echo ""
echo "=========================================="
echo "Pipeline started."
echo "  cam1 (Z2 Mini): CHECK 冷启动保护/视频健康看门狗已启动"
echo "  cam2 (后):   $([ "$CAM2_ENABLED" != "1" ] && echo "OFF 已禁用" || { [ "$CAM2_DETECTED" -eq 1 ] && echo "OK 已连接 ($CAM2_DEV)" || echo "WAIT 未连接，持续发现中"; })"
echo "  cam3 (左):   $([ "$CAM3_ENABLED" != "1" ] && echo "OFF 已禁用" || { [ "$CAM3_DETECTED" -eq 1 ] && echo "OK 已连接 ($CAM3_DEV)" || echo "WAIT 未连接，持续发现中"; })"
echo "  cam4 (右):   $([ "$CAM4_ENABLED" != "1" ] && echo "OFF 已禁用" || { [ "$CAM4_DETECTED" -eq 1 ] && echo "OK 已连接 ($CAM4_DEV)" || echo "WAIT 未连接，持续发现中"; })"
echo "  WHEP cam:    http://127.0.0.1:8889/cam/whep"
echo "  WHEP remote: http://127.0.0.1:8889/cam_remote/whep"
echo "  WHEP cam2:   http://127.0.0.1:8889/cam2/whep"
echo "  WHEP cam3:   http://127.0.0.1:8889/cam3/whep"
echo "  WHEP cam4:   http://127.0.0.1:8889/cam4/whep"
echo "  Logs:        $ROOT_DIR/logs/"
echo "  Stop:        bash $0 stop"
echo "=========================================="

# 保持主脚本在前台，让 systemd 能正确监督整条流水线。任一长期组件退出都视为
# 流水线故障：先清理其余组件，再以非零状态退出，由 systemd 统一重启。
shutdown_pipeline() {
  trap - INT TERM
  echo "Stopping video pipeline..."
  stop_pipeline
  exit 0
}

trap shutdown_pipeline INT TERM

if wait -n; then
  component_status=0
else
  component_status=$?
fi

trap - INT TERM
echo "ERROR: video pipeline component exited (status=${component_status}); stopping pipeline for supervised restart."
stop_pipeline
exit 1
