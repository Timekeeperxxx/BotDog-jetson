#!/usr/bin/env bash
set -euo pipefail

echo "开始重启导航定位..."

if [ $# -lt 1 ] || [ -z "${1:-}" ]; then
  echo "错误：缺少场景目录参数" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOTDOG_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
RUNTIME_DIR="$BOTDOG_ROOT/data/nav_runtime"
LOGS_DIR="$BOTDOG_ROOT/logs"
SCRIPT_LOG_DIR="$BOTDOG_ROOT/logs/scripts"
ROOT_LOG_FILE="$LOGS_DIR/restart_navigation_localization.log"
SCRIPT_LOG_FILE="$SCRIPT_LOG_DIR/restart_navigation_localization.log"
CMD_VEL_PID_FILE="$RUNTIME_DIR/cmd_vel.pid"
LIVOX_PID_FILE="$RUNTIME_DIR/livox.pid"
RELOCATION_PID_FILE="$RUNTIME_DIR/relocation.pid"
GLOBAL_PLANNER_PID_FILE="$RUNTIME_DIR/global_planner.pid"
P2P_MOVE_BASE_PID_FILE="$RUNTIME_DIR/p2p_move_base.pid"
CURRENT_TASK_FILE="$RUNTIME_DIR/current_task.json"
NAV_READY_FILE="$RUNTIME_DIR/navigation_ready.json"
SUPERLIO_ROOT_DIR="${SUPERLIO_ROOT_DIR:-$HOME/superlio/Super-LIO-ros2/src/super_lio}"

mkdir -p "$RUNTIME_DIR" "$LOGS_DIR" "$SCRIPT_LOG_DIR"
exec > >(tee -a "$SCRIPT_LOG_FILE") 2>&1

RAW_SCENE_DIR="$1"

if [ ! -d "$RAW_SCENE_DIR" ]; then
  echo "错误：场景目录不存在：$RAW_SCENE_DIR" >&2
  exit 1
fi

SCENE_DIR="$(realpath "$RAW_SCENE_DIR")"

find_scene_pcd_file() {
  local scene_dir="$1"
  local exact_name="$2"
  local fallback_pattern="$3"
  local label="$4"
  local -a exact_candidates=()
  local -a fallback_candidates=()
  local -a candidates=()
  local selected=""
  local selected_mtime=""

  while IFS= read -r -d '' file; do
    exact_candidates+=("$file")
  done < <(find "$scene_dir" -maxdepth 1 -type f -iname "$exact_name" -print0)

  while IFS= read -r -d '' file; do
    fallback_candidates+=("$file")
  done < <(find "$scene_dir" -maxdepth 1 -type f -iname "$fallback_pattern" ! -iname "$exact_name" -print0)

  if [ "${#exact_candidates[@]}" -gt 0 ]; then
    candidates=("${exact_candidates[@]}")
  else
    candidates=("${fallback_candidates[@]}")
  fi

  if [ "${#candidates[@]}" -eq 0 ]; then
    return 1
  fi

  selected="${candidates[0]}"
  selected_mtime="$(stat -c '%Y' "$selected")"

  if [ "${#candidates[@]}" -gt 1 ]; then
    echo "警告：发现多个 $label 候选文件，将选择最近修改的文件" >&2
  fi

  for file in "${candidates[@]}"; do
    local file_mtime
    file_mtime="$(stat -c '%Y' "$file")"
    if [ "$file_mtime" -gt "$selected_mtime" ]; then
      selected="$file"
      selected_mtime="$file_mtime"
    fi
  done

  printf '%s\n' "$selected"
}

if [ ! -d "$SCENE_DIR" ]; then
  echo "错误：场景目录不存在：$SCENE_DIR" >&2
  exit 1
fi

if ! MAP_PCD="$(find_scene_pcd_file "$SCENE_DIR" "map.pcd" "*map.pcd" "map.pcd")"; then
  echo "错误：场景缺少 *map.pcd：$SCENE_DIR" >&2
  exit 1
fi

if ! GROUND_PCD="$(find_scene_pcd_file "$SCENE_DIR" "ground.pcd" "*ground.pcd" "ground.pcd")"; then
  echo "错误：场景缺少 *ground.pcd：$SCENE_DIR" >&2
  exit 1
fi

echo "当前场景目录: $SCENE_DIR"
echo "当前 map.pcd: $MAP_PCD"
echo "当前 ground.pcd: $GROUND_PCD"
echo "PID 目录: $RUNTIME_DIR"

if [ ! -d "$SUPERLIO_ROOT_DIR" ]; then
  echo "错误：找不到 Super-LIO 源码根目录：$SUPERLIO_ROOT_DIR" >&2
  exit 1
fi

rm -f \
  "$LIVOX_PID_FILE" \
  "$RELOCATION_PID_FILE" \
  "$GLOBAL_PLANNER_PID_FILE" \
  "$P2P_MOVE_BASE_PID_FILE" \
  "$CMD_VEL_PID_FILE" \
  "$CURRENT_TASK_FILE" \
  "$NAV_READY_FILE"

echo "清理可能残留的 ROS2 导航定位进程..."

STARTED_PIDS=()

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

cleanup_started_on_error() {
  local status=$?
  local pid
  if [ "$status" -eq 0 ]; then
    return
  fi

  echo "启动失败，清理本轮已启动的导航定位进程..."
  for pid in "${STARTED_PIDS[@]:-}"; do
    [ -n "$pid" ] || continue
    kill_pid_tree "$pid"
  done
  sleep 1
  for pid in "${STARTED_PIDS[@]:-}"; do
    [ -n "$pid" ] || continue
    kill -KILL "$pid" 2>/dev/null || true
  done
}

trap cleanup_started_on_error EXIT

ROS_NEEDLES=(
  "ros2 launch livox_ros_driver2 msg_MID360_launch.py"
  "ros2 launch super_lio relocation.py"
  "ros2 launch global_planner path_planning_with_polygon.launch"
  "ros2 launch p2p_move_base go2_localization_launch.py"
  "local_map_builder"
  "/home/jetson/Project/BOTDOG/test_cmd_vel_fixed.sh"
  "/home/jetson/Project/BOTDOG/unitree_sdk2_python/example/scripts/cmd_vel_udp_bridge.py"
  "/home/jetson/Project/BOTDOG/unitree_sdk2_python/example/scripts/cmd_vel_ros2_udp_sender.py"
  "/home/jetson/superlio/install/livox_ros_driver2/lib/livox_ros_driver2/livox_ros_driver2_node"
  "/home/jetson/superlio/install/super_lio/lib/super_lio/relocation_node"
  "/home/jetson/dddmr_navigation_new_local/install/global_planner/lib/global_planner/global_planner_node"
  "/home/jetson/dddmr_navigation_new_local/install/mcl_3dl/lib/mcl_3dl/pcl_publisher"
  "/home/jetson/dddmr_navigation_new_local/install/p2p_move_base/lib/p2p_move_base/p2p_move_base_node"
  "/home/jetson/dddmr_navigation_new_local/install/p2p_move_base/lib/p2p_move_base/clicked2goal.py"
  "/home/jetson/dddmr_navigation_new_local/install/dddmr_local_map/lib/dddmr_local_map/local_map_builder"
)

for needle in "${ROS_NEEDLES[@]}"; do
  kill_needle_term "$needle"
done

sleep 3

for needle in "${ROS_NEEDLES[@]}"; do
  kill_needle_kill "$needle"
done

sleep 1

reset_ros_env() {
  echo "重置继承的 ROS/DDS 环境，避免后端运行时 overlay 干扰导航..."

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
  unset QT_PLUGIN_PATH
  unset QT_QPA_PLATFORM_PLUGIN_PATH
  unset QT_QPA_PLATFORM
  unset OPENCV_LOG_LEVEL

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

reset_ros_env

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

  _remove_path_segment "$var_name" "$entry"
  if [ -n "${!var_name:-}" ]; then
    printf -v "$var_name" '%s' "$entry:${!var_name}"
  else
    printf -v "$var_name" '%s' "$entry"
  fi
  export "$var_name"
}

source_ros_setup() {
  local setup_file="$1"
  if [ ! -f "$setup_file" ]; then
    echo "错误：找不到 ROS2 环境文件：$setup_file" >&2
    exit 1
  fi

  local had_ament_trace_setup_files=0
  local saved_ament_trace_setup_files=""
  if [ "${AMENT_TRACE_SETUP_FILES+x}" = "x" ]; then
    had_ament_trace_setup_files=1
    saved_ament_trace_setup_files="$AMENT_TRACE_SETUP_FILES"
  fi

  set +u
  # shellcheck disable=SC1090
  source "$setup_file"
  set -u
  if [ "$had_ament_trace_setup_files" -eq 1 ]; then
    export AMENT_TRACE_SETUP_FILES="$saved_ament_trace_setup_files"
  else
    unset AMENT_TRACE_SETUP_FILES 2>/dev/null || true
  fi
}

ROS2_SETUP_FILE="${ROS2_SETUP_FILE:-/opt/ros/humble/setup.bash}"
source_ros_setup "$ROS2_SETUP_FILE"

# 与手工 ROS CLI 环境对齐，避免后端 systemd/.venv 注入的库路径污染 ros2/rviz。
unset CYCLONEDDS_HOME
unset CYCLONEDDS_URI
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}"
_remove_path_segment LD_LIBRARY_PATH "/home/jetson/cyclonedds-0.10x/install/lib"
_remove_path_segment LD_LIBRARY_PATH "/home/jetson/Project/BOTDOG/BotDog/.venv/lib/python3.10/site-packages/cv2/../../lib64"
_remove_path_segment PYTHONPATH "/home/jetson/Project/BOTDOG/BotDog"
_prepend_path_segment PATH "/usr/local/cuda-12.6/bin"
_prepend_path_segment LD_LIBRARY_PATH "/usr/local/lib"
_prepend_path_segment LD_LIBRARY_PATH "/usr/local/cuda-12.6/lib64"
_prepend_path_segment PYTHONPATH "/usr/local/lib/python3.10/site-packages/"

start_launch() {
  local workspace_dir="$1"
  local setup_file="$workspace_dir/install/setup.bash"
  local launch_pkg="$2"
  local launch_file="$3"
  local title="$4"
  local pid_var="$5"
  local pid_file="$6"

  if [ ! -d "$workspace_dir" ]; then
    echo "错误：目录不存在：$workspace_dir" >&2
    exit 1
  fi

  echo "$title"
  cd "$workspace_dir"
  source_ros_setup "$setup_file"
  ros2 launch "$launch_pkg" "$launch_file" "${@:7}" &
  local pid=$!
  STARTED_PIDS+=("$pid")
  printf -v "$pid_var" '%s' "$pid"
  if [ -n "${pid_file:-}" ]; then
    printf '%s\n' "$pid" > "$RUNTIME_DIR/$pid_file"
  fi

  sleep 2
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "错误：$title 启动后立即退出，请检查日志：$ROOT_LOG_FILE" >&2
    exit 1
  fi
}

start_relocation_node() {
  local title="$1"
  local pid_var="$2"
  local pid_file="$3"
  local map_dir
  local map_name
  local relative_map_dir

  map_dir="$(dirname "$MAP_PCD")"
  map_name="$(basename "$MAP_PCD")"
  relative_map_dir="$(realpath --relative-to="$SUPERLIO_ROOT_DIR" "$map_dir" 2>/dev/null || true)"
  if [ -z "$relative_map_dir" ]; then
    echo "错误：无法计算 Super-LIO map 相对路径：root=$SUPERLIO_ROOT_DIR map_dir=$map_dir" >&2
    exit 1
  fi

  echo "$title"
  echo "Relocation map 参数：save_map_dir=$relative_map_dir map_name=$map_name"
  cd "$HOME/superlio"
  source_ros_setup "$HOME/superlio/install/setup.bash"
  ros2 run super_lio relocation_node \
    --ros-args \
    --log-level info \
    --params-file "$HOME/superlio/install/super_lio/share/super_lio/config/relocation.yaml" \
    -p "lio.map.save_map_dir:=$relative_map_dir" \
    -p "lio.map.map_name:=$map_name" &
  local pid=$!
  STARTED_PIDS+=("$pid")
  printf -v "$pid_var" '%s' "$pid"
  if [ -n "${pid_file:-}" ]; then
    printf '%s\n' "$pid" > "$RUNTIME_DIR/$pid_file"
  fi

  sleep 2
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "错误：$title 启动后立即退出，请检查日志：$ROOT_LOG_FILE" >&2
    exit 1
  fi
}

wait_for_topic_once() {
  local topic="$1"
  local timeout_s="$2"
  local label="$3"
  local deadline=$((SECONDS + timeout_s))
  local attempt=1

  echo "等待 $label 数据：$topic ..."
  while [ "$SECONDS" -lt "$deadline" ]; do
    if timeout 5s ros2 topic echo "$topic" --once >/dev/null 2>&1; then
      echo "$label 数据正常：$topic"
      return 0
    fi
    echo "仍在等待 $label 数据：$topic (attempt=$attempt, timeout=${timeout_s}s)"
    attempt=$((attempt + 1))
    sleep 1
  done

  echo "错误：${timeout_s}s 内未收到 $label 数据：$topic" >&2
  return 1
}

wait_for_navigation_maps() {
  local timeout_s="$1"

  wait_for_topic_once /mapcloud "$timeout_s" "global planner mapcloud"
  wait_for_topic_once /mapground "$timeout_s" "global planner mapground"
}

write_navigation_ready_file() {
  local ready_at
  ready_at="$(date -Iseconds)"

  cat > "$NAV_READY_FILE" <<EOF
{
  "ready": true,
  "ready_at": "$ready_at",
  "scene_dir": "$SCENE_DIR",
  "map_pcd": "$MAP_PCD",
  "ground_pcd": "$GROUND_PCD",
  "livox_pid": $LIVOX_PID,
  "relocation_pid": $RELOCATION_PID,
  "global_planner_pid": $GLOBAL_PLANNER_PID,
  "p2p_move_base_pid": $P2P_MOVE_BASE_PID
}
EOF
  echo "导航链路 ready：global planner 静态地图层已发布，ready_file=$NAV_READY_FILE"
}

wait_for_lio_odom_sane() {
  local timeout_s="$1"
  local deadline=$((SECONDS + timeout_s))
  local sample

  echo "等待 /lio/odom 输出 ..."
  echo "提示：Super-LIO relocation 收到 /initialpose 后才会发布有效 /lio/odom，请在前端发送重定位。"
  while [ "$SECONDS" -lt "$deadline" ]; do
    sample="$(timeout 4s ros2 topic echo /lio/odom --once 2>/dev/null || true)"
    if [ -n "$sample" ]; then
      echo "/lio/odom 已输出"
      return 0
    fi
    sleep 1
  done

  echo "错误：${timeout_s}s 内未收到 /lio/odom" >&2
  return 1
}

start_cmd_vel_test() {
  local title="$1"
  local pid_var="$2"
  local cmd_vel_log_file="$RUNTIME_DIR/cmd_vel.log"
  local cmd_vel_ros_log_dir="$RUNTIME_DIR/ros_logs/cmd_vel"
  local cmd_vel_script="$PROJECT_ROOT/test_cmd_vel_fixed.sh"

  if [ ! -d "$PROJECT_ROOT" ]; then
    echo "错误：找不到项目根目录：$PROJECT_ROOT" >&2
    exit 1
  fi

  if [ -f "$CMD_VEL_PID_FILE" ]; then
    local existing_pid
    existing_pid="$(cat "$CMD_VEL_PID_FILE" 2>/dev/null || true)"
  if [ -n "$existing_pid" ] && kill -0 "$existing_pid" 2>/dev/null; then
      echo "已存在 cmd_vel.py，复用现有进程：PID=$existing_pid"
      printf -v "$pid_var" '%s' "$existing_pid"
      return
    fi
  fi

  echo "$title"
  : > "$cmd_vel_log_file"
  mkdir -p "$cmd_vel_ros_log_dir"
  if [ ! -x "$cmd_vel_script" ]; then
    echo "错误：cmd_vel 启动脚本不可执行：$cmd_vel_script" >&2
    exit 1
  fi

  nohup env -i \
    HOME="${HOME:-/home/jetson}" \
    USER="${USER:-jetson}" \
    LOGNAME="${LOGNAME:-jetson}" \
    SHELL=/bin/bash \
    PATH=/usr/bin:/bin \
    ROS_LOG_DIR="$cmd_vel_ros_log_dir" \
    PYTHONUNBUFFERED=1 \
    setsid "$cmd_vel_script" >> "$cmd_vel_log_file" 2>&1 < /dev/null &
  local launcher_pid=$!
  echo "cmd_vel.py PID: $launcher_pid"

  sleep 1
  if ! kill -0 "$launcher_pid" 2>/dev/null; then
    rm -f "$CMD_VEL_PID_FILE"
    echo "错误: cmd_vel 测试脚本启动后立即退出，请检查 $cmd_vel_log_file" >&2
    exit 1
  fi

  printf '%s\n' "$launcher_pid" > "$CMD_VEL_PID_FILE"
  printf -v "$pid_var" '%s' "$launcher_pid"
}

start_launch "$HOME/superlio" livox_ros_driver2 msg_MID360_launch.py "启动 Livox MID360 驱动..." LIVOX_PID livox.pid
echo "Livox PID: $LIVOX_PID"
sleep 5
wait_for_topic_once /livox/imu "${NAV_LIVOX_IMU_WAIT_TIMEOUT_S:-30}" "Livox IMU"
wait_for_topic_once /livox/lidar "${NAV_LIVOX_LIDAR_WAIT_TIMEOUT_S:-60}" "Livox LiDAR"

start_relocation_node "启动 Super-LIO 重定位..." RELOCATION_PID relocation.pid
echo "Relocation PID: $RELOCATION_PID"
sleep 5
wait_for_lio_odom_sane "${NAV_LIO_ODOM_WAIT_TIMEOUT_S:-300}"

start_launch "$HOME/dddmr_navigation_new_local" p2p_move_base go2_localization_launch.py "启动 P2P move base 定位导航..." P2P_MOVE_BASE_PID p2p_move_base.pid "use_sim:=false"
echo "P2P Move Base PID: $P2P_MOVE_BASE_PID"
sleep 5

wait_for_topic_once /tf_static 10 "base 静态 TF"

start_launch "$HOME/dddmr_navigation_new_local" global_planner path_planning_with_polygon.launch "启动全局路径规划..." GLOBAL_PLANNER_PID global_planner.pid "map_dir:=$MAP_PCD" "ground_dir:=$GROUND_PCD"
echo "Global Planner PID: $GLOBAL_PLANNER_PID"
wait_for_navigation_maps "${NAV_GLOBAL_MAP_WAIT_TIMEOUT_S:-90}"
write_navigation_ready_file

if [ "${NAV_START_CMD_VEL_BRIDGE:-false}" = "true" ]; then
  start_cmd_vel_test "启动 cmd_vel 桥接脚本..." CMD_VEL_TEST_PID
  echo "Cmd Vel PID: $CMD_VEL_TEST_PID"
else
  echo "跳过 cmd_vel 硬件桥接启动：NAV_START_CMD_VEL_BRIDGE=${NAV_START_CMD_VEL_BRIDGE:-false}"
fi

wait
