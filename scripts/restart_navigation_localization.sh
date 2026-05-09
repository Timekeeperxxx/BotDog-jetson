#!/usr/bin/env bash
set -euo pipefail

echo "开始重启导航定位..."

echo "清理可能残留的 ROS2 导航定位进程..."

pkill -f "ros2 launch livox_ros_driver2 msg_MID360_launch.py" || true
pkill -f "ros2 launch super_lio relocation.py" || true
pkill -f "ros2 launch global_planner path_planning_with_polygon.launch" || true
pkill -f "ros2 launch p2p_move_base go2_localization_launch.py" || true

pkill -f "msg_MID360_launch.py" || true
pkill -f "relocation.py" || true
pkill -f "path_planning_with_polygon.launch" || true
pkill -f "go2_localization_launch.py" || true

sleep 3

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

  if [ ! -d "$workspace_dir" ]; then
    echo "错误：目录不存在：$workspace_dir" >&2
    exit 1
  fi

  echo "$title"
  cd "$workspace_dir"
  source_ros_setup "$setup_file"
  ros2 launch "$launch_pkg" "$launch_file" &
  local pid=$!
  printf -v "$pid_var" '%s' "$pid"
}

start_background_script() {
  local script_path="$1"
  local title="$2"
  local pid_var="$3"

  if [ ! -f "$script_path" ]; then
    echo "错误：找不到脚本：$script_path" >&2
    exit 1
  fi

  echo "$title"
  (cd "$(dirname "$script_path")" && bash "$(basename "$script_path")") &
  local pid=$!
  printf -v "$pid_var" '%s' "$pid"
}

start_launch "$HOME/superlio" livox_ros_driver2 msg_MID360_launch.py "启动 Livox MID360 驱动..." LIVOX_PID
sleep 5

start_launch "$HOME/superlio" super_lio relocation.py "启动 Super-LIO 重定位..." RELOCATION_PID
sleep 5

start_launch "$HOME/dddmr_navigation_new_local" p2p_move_base go2_localization_launch.py "启动 P2P move base 定位导航..." P2P_MOVE_BASE_PID
sleep 5

start_launch "$HOME/dddmr_navigation_new_local" global_planner path_planning_with_polygon.launch "启动全局路径规划..." GLOBAL_PLANNER_PID
sleep 5

start_background_script "/home/jetson/Project/BOTDOG/test_cmd_vel_fixed.sh" "启动 cmd_vel 测试脚本..." CMD_VEL_TEST_PID

echo "导航定位重启完成。"
echo "Livox PID: $LIVOX_PID"
echo "Relocation PID: $RELOCATION_PID"
echo "Global Planner PID: $GLOBAL_PLANNER_PID"
echo "P2P Move Base PID: $P2P_MOVE_BASE_PID"
echo "Cmd Vel Test PID: $CMD_VEL_TEST_PID"

wait
