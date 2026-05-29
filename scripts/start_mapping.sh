#!/usr/bin/env bash
set -euo pipefail

MAP_DIR="${1:-}"
MAPPING_READY_FLAG=""
LIVOX_PID=""
SUPERLIO_PID=""
TERRAIN_PID=""
CLEANING_UP=0

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
  echo "================================================================================" >> "$DEBUG_LOG"
  echo "  $*" >> "$DEBUG_LOG"
  echo "================================================================================" >> "$DEBUG_LOG"
}

_diag_log() {
  echo "$@" >> "$DEBUG_LOG"
}

_diag_dump_env() {
  _diag_section "环境变量快照 - $(date '+%Y-%m-%d %H:%M:%S')"
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
ros2 launch super_lio Livox_mid360.py --show-args >> "$DEBUG_LOG" 2>&1 || echo "<失败>" >> "$DEBUG_LOG"
_diag_log "--- terrain_analysis_with_save.launch --show-args ---"
ros2 launch terrain_analysis terrain_analysis_with_save.launch --show-args >> "$DEBUG_LOG" 2>&1 || echo "<失败>" >> "$DEBUG_LOG"

_get_pgid() {
  local pid="$1"
  ps -o pgid= -p "$pid" 2>/dev/null | tr -d '[:space:]'
}

_signal_process_group() {
  local pid="$1"
  local sig="$2"
  local pgid

  pgid="$(_get_pgid "$pid")"
  if [ -n "$pgid" ]; then
    kill "-$sig" -- "-$pgid" 2>/dev/null || true
    return 0
  fi

  kill "-$sig" "$pid" 2>/dev/null || true
}

wait_for_log_pattern() {
  local pattern="$1"
  local timeout_seconds="$2"
  local process_pid="${3:-}"
  local stage_name="$4"
  local waited=0

  echo "等待 ${stage_name}..." | tee -a "$DEBUG_LOG"
  while [ "$waited" -lt "$timeout_seconds" ]; do
    if grep -Fq "$pattern" "$DEBUG_LOG" 2>/dev/null; then
      echo "  ${stage_name}已就绪 (${waited}s)" | tee -a "$DEBUG_LOG"
      return 0
    fi

    if [ -n "$process_pid" ] && ! kill -0 "$process_pid" 2>/dev/null; then
      echo "  [ERROR] ${stage_name}前进程已退出 (PID=$process_pid)" | tee -a "$DEBUG_LOG"
      return 1
    fi

    sleep 1
    waited=$((waited + 1))
  done

  echo "  [ERROR] ${stage_name}超时 (${timeout_seconds}s)" | tee -a "$DEBUG_LOG"
  return 1
}

# ── cleanup ──────────────────────────────────────────────────────────────────
cleanup() {
  # 防止重复执行（EXIT trap 可能在 TERM/INT 之后再次触发）
  if [ "$CLEANING_UP" -eq 1 ]; then
    return 0
  fi
  CLEANING_UP=1

  # 先解除 trap，防止 cleanup 内部错误导致无限递归
  trap - TERM INT EXIT

  local exit_code=$?
  echo "" | tee -a "$DEBUG_LOG"
  echo "========================================================================" | tee -a "$DEBUG_LOG"
  echo "  收到停止信号 (exit_code=$exit_code)，正在按序终止建图进程..." | tee -a "$DEBUG_LOG"
  echo "========================================================================" | tee -a "$DEBUG_LOG"

  # 1) terrain_analysis - 优先停止，确保 ground.pcd 完整落盘
  if [ -n "$TERRAIN_PID" ] && kill -0 "$TERRAIN_PID" 2>/dev/null; then
    echo "  [1/3] SIGINT terrain_analysis 进程组 (PID=$TERRAIN_PID)，等待 ground.pcd 保存..." | tee -a "$DEBUG_LOG"
    _signal_process_group "$TERRAIN_PID" INT
    local waited=0
    while [ $waited -lt 60 ] && kill -0 "$TERRAIN_PID" 2>/dev/null; do
      sleep 1
      waited=$((waited + 1))
    done
    if kill -0 "$TERRAIN_PID" 2>/dev/null; then
      echo "  terrain_analysis 60s 未退出，SIGKILL 进程组" | tee -a "$DEBUG_LOG"
      _signal_process_group "$TERRAIN_PID" KILL
    else
      echo "  terrain_analysis 已退出 (${waited}s)" | tee -a "$DEBUG_LOG"
    fi
  else
    echo "  [1/3] terrain_analysis 未在运行，跳过" | tee -a "$DEBUG_LOG"
  fi

  # 2) super_lio - 等待 map.pcd 写入
  if [ -n "$SUPERLIO_PID" ] && kill -0 "$SUPERLIO_PID" 2>/dev/null; then
    echo "  [2/3] SIGINT super_lio 进程组 (PID=$SUPERLIO_PID)，等待 map.pcd 保存..." | tee -a "$DEBUG_LOG"
    _signal_process_group "$SUPERLIO_PID" INT
    local waited=0
    while [ $waited -lt 90 ] && kill -0 "$SUPERLIO_PID" 2>/dev/null; do
      sleep 1
      waited=$((waited + 1))
    done
    if kill -0 "$SUPERLIO_PID" 2>/dev/null; then
      echo "  super_lio 90s 未退出，SIGKILL 进程组" | tee -a "$DEBUG_LOG"
      _signal_process_group "$SUPERLIO_PID" KILL
    else
      echo "  super_lio 已退出 (${waited}s)" | tee -a "$DEBUG_LOG"
    fi
  else
    echo "  [2/3] super_lio 未在运行，跳过" | tee -a "$DEBUG_LOG"
  fi

  # 3) livox - 最后停止，确保 super_lio 保存过程中 LiDAR 数据仍在
  if [ -n "$LIVOX_PID" ] && kill -0 "$LIVOX_PID" 2>/dev/null; then
    echo "  [3/3] SIGINT livox 进程组 (PID=$LIVOX_PID)" | tee -a "$DEBUG_LOG"
    _signal_process_group "$LIVOX_PID" INT
    local waited=0
    while [ $waited -lt 5 ] && kill -0 "$LIVOX_PID" 2>/dev/null; do
      sleep 1
      waited=$((waited + 1))
    done
    if kill -0 "$LIVOX_PID" 2>/dev/null; then
      _signal_process_group "$LIVOX_PID" KILL
    else
      echo "  livox 已退出 (${waited}s)" | tee -a "$DEBUG_LOG"
    fi
  else
    echo "  [3/3] livox 未在运行，跳过" | tee -a "$DEBUG_LOG"
  fi

  # 最终兜底：确保所有子进程终止
  wait || true

  # ── PCD 文件检查 ──────────────────────────────────────────────────────────
  echo "" | tee -a "$DEBUG_LOG"
  echo "------------------------------------------------------------------------" | tee -a "$DEBUG_LOG"
  echo "  检查地图输出文件..." | tee -a "$DEBUG_LOG"
  echo "------------------------------------------------------------------------" | tee -a "$DEBUG_LOG"

  if [ -d "$MAP_DIR" ]; then
    find "$MAP_DIR" -maxdepth 2 -type f -name "*.pcd" \
      -printf "%TY-%Tm-%Td %TH:%TM:%TS  %s  %p\n" 2>/dev/null \
      | sort | tee -a "$DEBUG_LOG" || true

    map_count=$(find "$MAP_DIR" -maxdepth 2 -type f -name "*map.pcd" 2>/dev/null | wc -l)
    ground_count=$(find "$MAP_DIR" -maxdepth 2 -type f -name "*ground.pcd" 2>/dev/null | wc -l)

    echo "" | tee -a "$DEBUG_LOG"
    echo "  *map.pcd 数量:    $map_count" | tee -a "$DEBUG_LOG"
    echo "  *ground.pcd 数量: $ground_count" | tee -a "$DEBUG_LOG"

    if [ "$map_count" -eq 0 ]; then
      echo "  [ERROR] 没有找到 *map.pcd，SuperLIO 可能未正常保存" | tee -a "$DEBUG_LOG"
    fi
    if [ "$ground_count" -eq 0 ]; then
      echo "  [ERROR] 没有找到 *ground.pcd，terrain_analysis 可能未正常保存" | tee -a "$DEBUG_LOG"
    fi
  else
    echo "  [ERROR] 地图目录不存在: $MAP_DIR" | tee -a "$DEBUG_LOG"
  fi

  echo "" | tee -a "$DEBUG_LOG"
  echo "建图进程清理完成" | tee -a "$DEBUG_LOG"
  exit "$exit_code"
}

# EXIT trap 确保无论脚本因何退出（set -e 报错、命令失败、Ctrl+C、SIGTERM）
# 都会触发 cleanup 按序保存 PCD 文件
trap cleanup TERM INT EXIT

# ── 预处理 ──────────────────────────────────────────────────────────────────
MAP_DIR="${MAP_DIR/#\~/$HOME}"
SUPERLIO_ROOT_DIR="${SUPERLIO_ROOT_DIR:-$HOME/superlio/Super-LIO-ros2/src/super_lio}"
SUPERLIO_SAVE_MAP_DIR="$MAP_DIR"
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
MAPPING_READY_FLAG="$MAP_DIR/.ground_generation_started"
rm -f "$MAPPING_READY_FLAG"

# super_lio 内部会把 save_map_dir 再拼到编译期 ROOT 前缀上，因此这里必须传 ROOT 相对路径。
if [ -d "$SUPERLIO_ROOT_DIR" ] && command -v realpath >/dev/null 2>&1; then
  RELATIVE_MAP_DIR="$(realpath --relative-to="$SUPERLIO_ROOT_DIR" "$MAP_DIR" 2>/dev/null || true)"
  if [ -n "$RELATIVE_MAP_DIR" ]; then
    SUPERLIO_SAVE_MAP_DIR="$RELATIVE_MAP_DIR"
  fi
fi
echo "SuperLIO 保存目录参数：$SUPERLIO_SAVE_MAP_DIR" | tee -a "$DEBUG_LOG"

# ── 环境构建 ────────────────────────────────────────────────────────────────
# 与手工 CLI 建图保持一致：直接进入 ~/superlio 并 source 本地 install/setup.bash。
cd "$HOME/superlio"
set +u
source install/setup.bash
set -u

# 3) 记录最终环境（source 后）
_diag_section "环境变量快照（source ~/superlio/install/setup.bash 后）"
_diag_dump_env

_diag_section "ros2 pkg prefix（最终环境）"
for _pkg in livox_ros_driver2 super_lio terrain_analysis; do
  _diag_log "ros2 pkg prefix $_pkg = $(ros2 pkg prefix "$_pkg" 2>&1 || echo '<失败>')"
done
_diag_log ""
_diag_log "建图环境摘要：RMW=${RMW_IMPLEMENTATION:-<unset>} ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-<unset>}"

_remove_path_segment() {
  local var_name="$1"
  local needle="$2"
  local current_value="${!var_name:-}"
  local rebuilt=""
  local entry=""
  local saved_ifs="$IFS"

  IFS=":"
  for entry in $current_value; do
    if [ -z "$entry" ] || [ "$entry" = "$needle" ]; then
      continue
    fi
    rebuilt="${rebuilt:+$rebuilt:}$entry"
  done
  IFS="$saved_ifs"

  printf -v "$var_name" '%s' "$rebuilt"
  export "$var_name"
}

_prepend_path_segment() {
  local var_name="$1"
  local entry="$2"
  local current_value="${!var_name:-}"

  _remove_path_segment "$var_name" "$entry"
  if [ -n "${!var_name:-}" ]; then
    printf -v "$var_name" '%s' "$entry:${!var_name}"
  else
    printf -v "$var_name" '%s' "$entry"
  fi
  export "$var_name"
}

# 后端通过 start_backend.sh 注入的 CycloneDDS/cv2 路径与手工 CLI 不一致。
# 这里只剔除这些后端专属残留，再补上 ~/.bashrc 里手工 shell 自带的基础路径。
unset CYCLONEDDS_HOME
unset CYCLONEDDS_URI
export ROS_DOMAIN_ID=0

_remove_path_segment LD_LIBRARY_PATH "/home/jetson/cyclonedds-0.10x/install/lib"
_remove_path_segment LD_LIBRARY_PATH "/home/jetson/Project/BOTDOG/BotDog/.venv/lib/python3.10/site-packages/cv2/../../lib64"
_remove_path_segment PYTHONPATH "/home/jetson/Project/BOTDOG/BotDog"
_prepend_path_segment PATH "/usr/local/cuda-12.6/bin"
_prepend_path_segment LD_LIBRARY_PATH "/usr/local/lib"
_prepend_path_segment LD_LIBRARY_PATH "/usr/local/cuda-12.6/lib64"
_prepend_path_segment PYTHONPATH "/usr/local/lib/python3.10/site-packages/"

_diag_section "环境变量快照（手工 CLI 对齐后）"
_diag_dump_env

# ── 启动 Livox 驱动 ─────────────────────────────────────────────────────────
echo "启动 Livox MID360 驱动..." | tee -a "$DEBUG_LOG"
ros2 launch livox_ros_driver2 msg_MID360_launch.py >> "$DEBUG_LOG" 2>&1 &
LIVOX_PID=$!
echo "  Livox PID: $LIVOX_PID" | tee -a "$DEBUG_LOG"
wait_for_log_pattern "livox/lidar publish use livox custom format" 30 "$LIVOX_PID" "Livox 开始发布点云/IMU"

# ── 启动 SuperLIO 建图 ──────────────────────────────────────────────────────
echo "启动 Super LIO 建图..." | tee -a "$DEBUG_LOG"
ros2 launch super_lio Livox_mid360.py save_map_dir:="$SUPERLIO_SAVE_MAP_DIR" map_name:="map.pcd" >> "$DEBUG_LOG" 2>&1 &
SUPERLIO_PID=$!
echo "  SuperLIO PID: $SUPERLIO_PID" | tee -a "$DEBUG_LOG"
wait_for_log_pattern "Map init done" 60 "$SUPERLIO_PID" "SuperLIO 完成地图初始化"

# ── 启动 terrain_analysis ───────────────────────────────────────────────────
echo "启动 terrain_analysis 地形分析与地图保存..." | tee -a "$DEBUG_LOG"
ros2 launch terrain_analysis terrain_analysis_with_save.launch map_dir:="$MAP_DIR" >> "$DEBUG_LOG" 2>&1 &
TERRAIN_PID=$!
echo "  terrain_analysis PID: $TERRAIN_PID" | tee -a "$DEBUG_LOG"

sleep 1
if kill -0 "$TERRAIN_PID" 2>/dev/null; then
  printf '%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" > "$MAPPING_READY_FLAG"
  echo "  ground 生成已开始，启动就绪标记已写入：$MAPPING_READY_FLAG" | tee -a "$DEBUG_LOG"
else
  echo "  [WARN] terrain_analysis 启动后立即退出，未写入 ground 就绪标记" | tee -a "$DEBUG_LOG"
fi

echo "" | tee -a "$DEBUG_LOG"
echo "================================================================================" | tee -a "$DEBUG_LOG"
echo "  建图进程已全部启动" | tee -a "$DEBUG_LOG"
echo "  Livox PID:            $LIVOX_PID" | tee -a "$DEBUG_LOG"
echo "  SuperLIO PID:         $SUPERLIO_PID" | tee -a "$DEBUG_LOG"
echo "  terrain_analysis PID: $TERRAIN_PID" | tee -a "$DEBUG_LOG"
echo "  地图保存目录:         $MAP_DIR" | tee -a "$DEBUG_LOG"
echo "================================================================================" | tee -a "$DEBUG_LOG"

wait
