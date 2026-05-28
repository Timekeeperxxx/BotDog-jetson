#!/usr/bin/env bash
set -euo pipefail

MAP_DIR="${1:-}"
LIVOX_PID=""
SUPERLIO_PID=""
TERRAIN_PID=""

if [ -z "$MAP_DIR" ]; then
  echo "错误：缺少地图保存目录参数"
  echo "用法：bash start_mapping.sh /home/jetson/Project/BOTDOG/MAPS/场景名称"
  exit 1
fi

# ── 诊断日志 ────────────────────────────────────────────────────────────────
DEBUG_LOG="/home/jetson/Project/BOTDOG/BotDog/logs/start_mapping_debug.log"
mkdir -p "$(dirname "$DEBUG_LOG")"

_diag_section() {
  echo "" >> "$DEBUG_LOG"
  echo "════════════════════════════════════════════════════════════════" >> "$DEBUG_LOG"
  echo "  $*" >> "$DEBUG_LOG"
  echo "════════════════════════════════════════════════════════════════" >> "$DEBUG_LOG"
}

_diag_log() {
  echo "$@" >> "$DEBUG_LOG"
}

_diag_dump_env() {
  _diag_section "环境变量快照 — $(date '+%Y-%m-%d %H:%M:%S')"
  _diag_log "whoami  = $(whoami)"
  _diag_log "pwd     = $(pwd)"
  _diag_log "hostname= $(hostname)"
  _diag_log "ROS_DOMAIN_ID          = ${ROS_DOMAIN_ID:-<unset>}"
  _diag_log "RMW_IMPLEMENTATION     = ${RMW_IMPLEMENTATION:-<unset>}"
  _diag_log "AMENT_PREFIX_PATH      = ${AMENT_PREFIX_PATH:-<unset>}"
  _diag_log "COLCON_PREFIX_PATH     = ${COLCON_PREFIX_PATH:-<unset>}"
  _diag_log "CMAKE_PREFIX_PATH      = ${CMAKE_PREFIX_PATH:-<unset>}"
  _diag_log "PYTHONPATH             = ${PYTHONPATH:-<unset>}"
  _diag_log "LD_LIBRARY_PATH        = ${LD_LIBRARY_PATH:-<unset>}"
  _diag_log "CYCLONEDDS_HOME        = ${CYCLONEDDS_HOME:-<unset>}"
  _diag_log "CYCLONEDDS_URI         = ${CYCLONEDDS_URI:-<unset>}"
  _diag_log "VIRTUAL_ENV            = ${VIRTUAL_ENV:-<unset>}"
  _diag_log "---"
  _diag_log "$(printenv | sort | grep -iE 'ROS|DDS|AMENT|COLCON|CMAKE|RMW|CYCLONE|FASTRTPS|PYTHONPATH|LD_LIBRARY' || echo '(none)')"
}

# 1) 记录继承环境（重置前）
echo "--- 建图启动 $(date) ---" > "$DEBUG_LOG"
_diag_dump_env

# 2) ros2 pkg prefix（依赖当前环境，必须在 reset 前执行）
_diag_section "ros2 pkg prefix（继承环境）"
for _pkg in livox_ros_driver2 super_lio terrain_analysis; do
  _diag_log "ros2 pkg prefix $_pkg = $(ros2 pkg prefix "$_pkg" 2>&1 || echo '<失败>')"
done

_diag_section "launch 参数"
_diag_log "--- super_lio Livox_mid360.py --show-args ---"
ros2 launch super_lio Livox_mid360.py --show-args 2>&1 | _diag_log || _diag_log '<失败>'
_diag_log "--- terrain_analysis_with_save.launch --show-args ---"
ros2 launch terrain_analysis terrain_analysis_with_save.launch --show-args 2>&1 | _diag_log || _diag_log '<失败>'

# ── cleanup ──────────────────────────────────────────────────────────────────
cleanup() {
  local exit_code=$?
  echo "" | tee -a "$DEBUG_LOG"
  echo "收到停止信号，正在按序终止建图进程..." | tee -a "$DEBUG_LOG"

  # 1) terrain_analysis — 优先停止，确保 ground.pcd 完整落盘
  if [ -n "$TERRAIN_PID" ] && kill -0 "$TERRAIN_PID" 2>/dev/null; then
    echo "  [1/3] SIGINT terrain_analysis (PID=$TERRAIN_PID)，等待 ground.pcd 保存..." | tee -a "$DEBUG_LOG"
    kill -INT "$TERRAIN_PID" 2>/dev/null || true
    local waited=0
    while [ $waited -lt 15 ] && kill -0 "$TERRAIN_PID" 2>/dev/null; do
      sleep 1
      waited=$((waited + 1))
    done
    if kill -0 "$TERRAIN_PID" 2>/dev/null; then
      echo "  terrain_analysis 15s 未退出，SIGKILL" | tee -a "$DEBUG_LOG"
      kill -KILL "$TERRAIN_PID" 2>/dev/null || true
    else
      echo "  terrain_analysis 已退出 (${waited}s)" | tee -a "$DEBUG_LOG"
    fi
  fi

  # 2) super_lio — 等待 map.pcd 写入
  if [ -n "$SUPERLIO_PID" ] && kill -0 "$SUPERLIO_PID" 2>/dev/null; then
    echo "  [2/3] SIGINT super_lio (PID=$SUPERLIO_PID)，等待 map.pcd 保存..." | tee -a "$DEBUG_LOG"
    kill -INT "$SUPERLIO_PID" 2>/dev/null || true
    local waited=0
    while [ $waited -lt 60 ] && kill -0 "$SUPERLIO_PID" 2>/dev/null; do
      sleep 1
      waited=$((waited + 1))
    done
    if kill -0 "$SUPERLIO_PID" 2>/dev/null; then
      echo "  super_lio 60s 未退出，SIGKILL" | tee -a "$DEBUG_LOG"
      kill -KILL "$SUPERLIO_PID" 2>/dev/null || true
    else
      echo "  super_lio 已退出 (${waited}s)" | tee -a "$DEBUG_LOG"
    fi
  fi

  # 3) livox — 最后停止，确保 super_lio 保存过程中 LiDAR 数据仍在
  if [ -n "$LIVOX_PID" ] && kill -0 "$LIVOX_PID" 2>/dev/null; then
    echo "  [3/3] SIGINT livox (PID=$LIVOX_PID)" | tee -a "$DEBUG_LOG"
    kill -INT "$LIVOX_PID" 2>/dev/null || true
    local waited=0
    while [ $waited -lt 5 ] && kill -0 "$LIVOX_PID" 2>/dev/null; do
      sleep 1
      waited=$((waited + 1))
    done
    if kill -0 "$LIVOX_PID" 2>/dev/null; then
      kill -KILL "$LIVOX_PID" 2>/dev/null || true
    else
      echo "  livox 已退出 (${waited}s)" | tee -a "$DEBUG_LOG"
    fi
  fi

  # 最终兜底：确保所有子进程终止
  wait || true
  echo "建图进程清理完成" | tee -a "$DEBUG_LOG"
  exit "$exit_code"
}

trap cleanup TERM INT

# ── 预处理 ──────────────────────────────────────────────────────────────────
MAP_DIR="${MAP_DIR/#\~/$HOME}"
echo "本次建图目录：$MAP_DIR" | tee -a "$DEBUG_LOG"

echo "开始建图前，清理导航相关后台进程..." | tee -a "$DEBUG_LOG"

find_matching_pids() {
  local needle="$1"
  ps -eo pid=,args= | awk -v needle="$needle" 'index($0, needle) {print $1}'
}

kill_pid_tree() {
  local pid="$1"
  local child
  while IFS= read -r child; do
    [ -n "$child" ] || continue
    kill_pid_tree "$child"
  done < <(pgrep -P "$pid" 2>/dev/null || true)
  kill -TERM "$pid" 2>/dev/null || true
}

kill_needle_term() {
  local needle="$1"
  local pid
  while IFS= read -r pid; do
    [ -n "$pid" ] || continue
    kill_pid_tree "$pid"
  done < <(find_matching_pids "$needle" | sort -u)
}

kill_needle_kill() {
  local needle="$1"
  local pid
  while IFS= read -r pid; do
    [ -n "$pid" ] || continue
    kill -KILL "$pid" 2>/dev/null || true
    while IFS= read -r child; do
      [ -n "$child" ] || continue
      kill -KILL "$child" 2>/dev/null || true
    done < <(pgrep -P "$pid" 2>/dev/null || true)
  done < <(find_matching_pids "$needle" | sort -u)
}

NAV_NEEDLES=(
  "ros2 launch livox_ros_driver2 msg_MID360_launch.py"
  "ros2 launch super_lio relocation.py"
  "ros2 launch super_lio Livox_mid360.py"
  "ros2 launch terrain_analysis terrain_analysis_with_save.launch"
  "ros2 launch global_planner path_planning_with_polygon.launch"
  "ros2 launch p2p_move_base go2_localization_launch.py"
  "/home/jetson/superlio/install/livox_ros_driver2/lib/livox_ros_driver2/livox_ros_driver2_node"
  "/home/jetson/superlio/install/super_lio/lib/super_lio/super_lio_node"
  "/home/jetson/superlio/install/super_lio/lib/super_lio/relocation_node"
  "/home/jetson/superlio/install/terrain_analysis/lib/terrain_analysis/terrainAnalysis"
  "/home/jetson/superlio/install/terrain_analysis/lib/terrain_analysis/save_terrain_map"
  "/home/jetson/dddmr_navigation_new_local/install/global_planner/lib/global_planner/global_planner_node"
  "/home/jetson/dddmr_navigation_new_local/install/mcl_3dl/lib/mcl_3dl/pcl_publisher"
  "/home/jetson/dddmr_navigation_new_local/install/p2p_move_base/lib/p2p_move_base/clicked2goal.py"
  "/home/jetson/Project/BOTDOG/unitree_sdk2_python/example/scripts/cmd_vel.py"
  "/home/jetson/Project/BOTDOG/test_cmd_vel_fixed.sh"
)

for needle in "${NAV_NEEDLES[@]}"; do
  kill_needle_term "$needle"
done

sleep 3

for needle in "${NAV_NEEDLES[@]}"; do
  kill_needle_kill "$needle"
done

sleep 1

mkdir -p "$MAP_DIR"

# ── 环境重置 ────────────────────────────────────────────────────────────────
reset_ros_mapping_env() {
  echo "重置继承的 ROS/DDS 环境，避免后端运行时 overlay 干扰建图..." | tee -a "$DEBUG_LOG"

  unset RMW_IMPLEMENTATION
  unset CYCLONEDDS_URI
  unset CYCLONEDDS_HOME
  unset FASTRTPS_DEFAULT_PROFILES_FILE
  unset ROS_DOMAIN_ID
  unset ROS_LOCALHOST_ONLY
  unset ROS_DISTRO
  unset ROS_VERSION
  unset ROS_PYTHON_VERSION
  unset AMENT_PREFIX_PATH
  unset COLCON_PREFIX_PATH
  unset CMAKE_PREFIX_PATH
  unset LD_LIBRARY_PATH
  unset PYTHONPATH
  unset VIRTUAL_ENV
  unset PYTHONHOME

  _clean_path=""
  _ifs_saved="$IFS"
  IFS=":"
  for _p in $PATH; do
    case "$_p" in
      *"/.venv/"*) ;;
      *"/virtualenv/"*) ;;
      *) _clean_path="${_clean_path}:${_p}" ;;
    esac
  done
  IFS="$_ifs_saved"
  export PATH="${_clean_path#:}"
  unset _clean_path _p _ifs_saved
}

reset_ros_mapping_env

# ── 环境构建 ────────────────────────────────────────────────────────────────
# 只使用纯 ROS2 Humble + SuperLIO 环境，不再 source yahboom_ws。
# yahboom_ws 可能 overlay 了与建图无关的 ROS 包（camera/interfaces/largemodel/text_chat），
# 导致 AMENT_PREFIX_PATH 包含非预期的 package share 目录，
# 影响 ros2 pkg prefix / get_package_share_directory 的解析结果。

if [ -f "/opt/ros/humble/setup.bash" ]; then
  set +u
  source /opt/ros/humble/setup.bash
  set -u
fi

cd "$HOME/superlio"
set +u
source install/setup.bash
set -u

# 3) 记录最终环境（重置后）
_diag_section "环境变量快照（重置 + source 后）"
_diag_dump_env

_diag_section "ros2 pkg prefix（最终环境）"
for _pkg in livox_ros_driver2 super_lio terrain_analysis; do
  _diag_log "ros2 pkg prefix $_pkg = $(ros2 pkg prefix "$_pkg" 2>&1 || echo '<失败>')"
done
_diag_log ""
_diag_log "建图环境摘要：RMW=${RMW_IMPLEMENTATION:-<unset>} ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-<unset>}"

# ── 启动 Livox 驱动 ─────────────────────────────────────────────────────────
echo "启动 Livox MID360 驱动..." | tee -a "$DEBUG_LOG"
ros2 launch livox_ros_driver2 msg_MID360_launch.py &
LIVOX_PID=$!
echo "  Livox PID: $LIVOX_PID" | tee -a "$DEBUG_LOG"

# 等待 LiDAR 数据 topic 就绪
_wait_topic() {
  local topic="$1"
  local max_wait="${2:-15}"
  local waited=0
  echo "  等待 topic $topic ..." | tee -a "$DEBUG_LOG"
  while [ $waited -lt $max_wait ]; do
    if ros2 topic list 2>/dev/null | grep -qF "$topic"; then
      echo "  topic $topic 已就绪（等待 ${waited}s）" | tee -a "$DEBUG_LOG"
      return 0
    fi
    sleep 1
    waited=$((waited + 1))
  done
  echo "  ⚠ topic $topic 在 ${max_wait}s 内未出现，继续执行" | tee -a "$DEBUG_LOG"
  return 1
}

echo "等待 Livox 数据 topic 就绪..." | tee -a "$DEBUG_LOG"
_wait_topic "/livox/imu" 15
_wait_topic "/livox/lidar" 15

# 给 IMU 数据积累时间 —— SuperLIO 用前几帧加速度计数据估算重力方向
echo "等待 IMU 数据稳定 (10s)..." | tee -a "$DEBUG_LOG"
sleep 10

# ── 启动 SuperLIO 建图 ──────────────────────────────────────────────────────
echo "启动 Super LIO 建图..." | tee -a "$DEBUG_LOG"
ros2 launch super_lio Livox_mid360.py save_map_dir:="$MAP_DIR" map_name:="map.pcd" &
SUPERLIO_PID=$!
echo "  SuperLIO PID: $SUPERLIO_PID" | tee -a "$DEBUG_LOG"

# ── 等待 SuperLIO 稳定后再启动 terrain_analysis ────────────────────────────
# SuperLIO 启动后前几秒是 IMU 初始化、重力对齐的关键期，此时位姿漂移较大。
# terrain_analysis 过早启动会把初始化阶段的倾斜点云写进 ground.pcd。
# 策略：等待 /tf 出现（证明 SuperLIO 已开始发布位姿），再等待一段时间让估计收敛。
echo "等待 SuperLIO 初始化稳定..." | tee -a "$DEBUG_LOG"

# 等 /tf topic 出现
_wait_topic "/tf" 30

# 再等一段时间让重力估计和初始位姿收敛
echo "等待 SuperLIO 位姿收敛 (20s)..." | tee -a "$DEBUG_LOG"
sleep 20

# ── 启动 terrain_analysis ───────────────────────────────────────────────────
echo "启动 terrain_analysis 地形分析与地图保存..." | tee -a "$DEBUG_LOG"
ros2 launch terrain_analysis terrain_analysis_with_save.launch map_dir:="$MAP_DIR" &
TERRAIN_PID=$!
echo "  terrain_analysis PID: $TERRAIN_PID" | tee -a "$DEBUG_LOG"

echo "" | tee -a "$DEBUG_LOG"
echo "════════════════════════════════════════════════════════════════" | tee -a "$DEBUG_LOG"
echo "  建图进程已全部启动" | tee -a "$DEBUG_LOG"
echo "  Livox PID:          $LIVOX_PID" | tee -a "$DEBUG_LOG"
echo "  SuperLIO PID:       $SUPERLIO_PID" | tee -a "$DEBUG_LOG"
echo "  terrain_analysis PID: $TERRAIN_PID" | tee -a "$DEBUG_LOG"
echo "  地图保存目录:       $MAP_DIR" | tee -a "$DEBUG_LOG"
echo "════════════════════════════════════════════════════════════════" | tee -a "$DEBUG_LOG"

wait
