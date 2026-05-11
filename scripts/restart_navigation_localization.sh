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
NAV_RUNTIME_DIR="$BOTDOG_ROOT/data/nav_runtime"
CMD_VEL_PID_FILE="$NAV_RUNTIME_DIR/cmd_vel.pid"
LIVOX_PID_FILE="$NAV_RUNTIME_DIR/livox.pid"
RELOCATION_PID_FILE="$NAV_RUNTIME_DIR/relocation.pid"
GLOBAL_PLANNER_PID_FILE="$NAV_RUNTIME_DIR/global_planner.pid"
P2P_MOVE_BASE_PID_FILE="$NAV_RUNTIME_DIR/p2p_move_base.pid"

mkdir -p "$NAV_RUNTIME_DIR"

MAPS_ROOT="/home/jetson/Project/BOTDOG/MAPS"
RAW_SCENE_DIR="$1"

if [ ! -d "$RAW_SCENE_DIR" ]; then
  echo "错误：场景目录不存在：$RAW_SCENE_DIR" >&2
  exit 1
fi

SCENE_DIR="$(realpath "$RAW_SCENE_DIR")"

case "$SCENE_DIR" in
  "$MAPS_ROOT"/*) ;;
  *)
    echo "错误：场景目录必须位于 $MAPS_ROOT 下" >&2
    exit 1
    ;;
esac

find_scene_pcd_file() {
  local scene_dir="$1"
  local suffix="$2"
  local label="$3"
  local -a candidates=()
  local selected=""
  local selected_mtime=""

  while IFS= read -r -d '' file; do
    candidates+=("$file")
  done < <(find "$scene_dir" -maxdepth 1 -type f -name "*$suffix" -print0)

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

if ! MAP_PCD="$(find_scene_pcd_file "$SCENE_DIR" "map.pcd" "map.pcd")"; then
  echo "错误：场景缺少 map.pcd：$SCENE_DIR" >&2
  exit 1
fi

if ! GROUND_PCD="$(find_scene_pcd_file "$SCENE_DIR" "ground.pcd" "ground.pcd")"; then
  echo "错误：场景缺少 ground.pcd：$SCENE_DIR" >&2
  exit 1
fi

if [ ! -f "$MAP_PCD" ]; then
  echo "错误：场景缺少 map.pcd：$MAP_PCD" >&2
  exit 1
fi

if [ ! -f "$GROUND_PCD" ]; then
  echo "错误：场景缺少 ground.pcd：$GROUND_PCD" >&2
  exit 1
fi

echo "清理可能残留的 ROS2 导航定位进程..."

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

ROS_NEEDLES=(
  "ros2 launch livox_ros_driver2 msg_MID360_launch.py"
  "ros2 launch super_lio relocation.py"
  "ros2 launch global_planner path_planning_with_polygon.launch"
  "ros2 launch p2p_move_base go2_localization_launch.py"
  "/home/jetson/superlio/install/livox_ros_driver2/lib/livox_ros_driver2/livox_ros_driver2_node"
  "/home/jetson/superlio/install/super_lio/lib/super_lio/relocation_node"
  "/home/jetson/dddmr_navigation_new_local/install/global_planner/lib/global_planner/global_planner_node"
  "/home/jetson/dddmr_navigation_new_local/install/mcl_3dl/lib/mcl_3dl/pcl_publisher"
  "/home/jetson/dddmr_navigation_new_local/install/p2p_move_base/lib/p2p_move_base/clicked2goal.py"
)

for needle in "${ROS_NEEDLES[@]}"; do
  kill_needle_term "$needle"
done

sleep 3

for needle in "${ROS_NEEDLES[@]}"; do
  kill_needle_kill "$needle"
done

sleep 1

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
  printf -v "$pid_var" '%s' "$pid"
  if [ -n "${pid_file:-}" ]; then
    printf '%s\n' "$pid" > "$NAV_RUNTIME_DIR/$pid_file"
  fi
}

start_cmd_vel_test() {
  local title="$1"
  local pid_var="$2"
  local cmd_vel_log_file="$NAV_RUNTIME_DIR/cmd_vel.log"
  local cmd_vel_ros_log_dir="$NAV_RUNTIME_DIR/ros_logs/cmd_vel"
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

  find_cmd_vel_python_pid() {
    local line
    local pid=""
    while IFS= read -r line; do
      [ -n "$line" ] || continue
      pid="${line%% *}"
    done < <(pgrep -af "/home/jetson/Project/BOTDOG/unitree_sdk2_python/example/scripts/cmd_vel.py" || true)

    if [ -n "$pid" ]; then
      printf '%s\n' "$pid"
      return 0
    fi

    return 1
  }

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

  local cmd_vel_pid=""
  local attempt
  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    if cmd_vel_pid="$(find_cmd_vel_python_pid)"; then
      break
    fi
    sleep 1
  done

  if [ -z "$cmd_vel_pid" ]; then
    rm -f "$CMD_VEL_PID_FILE"
    echo "错误: cmd_vel.py 启动失败，请检查 $cmd_vel_log_file" >&2
    exit 1
  fi

  printf '%s\n' "$cmd_vel_pid" > "$CMD_VEL_PID_FILE"
  printf -v "$pid_var" '%s' "$cmd_vel_pid"
}

start_launch "$HOME/superlio" livox_ros_driver2 msg_MID360_launch.py "启动 Livox MID360 驱动..." LIVOX_PID livox.pid
sleep 5

start_launch "$HOME/superlio" super_lio relocation.py "启动 Super-LIO 重定位..." RELOCATION_PID relocation.pid "map_file:=$MAP_PCD"
sleep 5

start_launch "$HOME/dddmr_navigation_new_local" global_planner path_planning_with_polygon.launch "启动全局路径规划..." GLOBAL_PLANNER_PID global_planner.pid "map_dir:=$MAP_PCD" "ground_dir:=$GROUND_PCD"
sleep 5

start_launch "$HOME/dddmr_navigation_new_local" p2p_move_base go2_localization_launch.py "启动 P2P move base 定位导航..." P2P_MOVE_BASE_PID p2p_move_base.pid
sleep 5

start_cmd_vel_test "启动 cmd_vel 测试脚本..." CMD_VEL_TEST_PID

echo "Livox PID: $LIVOX_PID"
echo "Relocation PID: $RELOCATION_PID"
echo "Global Planner PID: $GLOBAL_PLANNER_PID"
echo "P2P Move Base PID: $P2P_MOVE_BASE_PID"
echo "Cmd Vel Test PID: $CMD_VEL_TEST_PID"

wait
