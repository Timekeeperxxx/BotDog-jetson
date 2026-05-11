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

cleanup() {
  local exit_code=$?
  echo "收到停止信号，正在终止建图相关进程..."

  for pid in "$TERRAIN_PID" "$SUPERLIO_PID" "$LIVOX_PID"; do
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill -TERM "$pid" 2>/dev/null || true
    fi
  done

  sleep 2

  for pid in "$TERRAIN_PID" "$SUPERLIO_PID" "$LIVOX_PID"; do
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill -KILL "$pid" 2>/dev/null || true
    fi
  done

  wait || true
  exit "$exit_code"
}

trap cleanup TERM INT

MAP_DIR="${MAP_DIR/#\~/$HOME}"

echo "本次建图目录：$MAP_DIR"

echo "开始建图前，清理导航相关后台进程..."

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
  "ros2 launch global_planner path_planning_with_polygon.launch"
  "ros2 launch p2p_move_base go2_localization_launch.py"
  "/home/jetson/superlio/install/livox_ros_driver2/lib/livox_ros_driver2/livox_ros_driver2_node"
  "/home/jetson/superlio/install/super_lio/lib/super_lio/relocation_node"
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

cd "$HOME/superlio"
# colcon 生成的 setup 脚本可能引用未定义环境变量；临时关闭 nounset 避免告警。
set +u
source install/setup.bash
set -u

echo "启动 Livox MID360 驱动..."
ros2 launch livox_ros_driver2 msg_MID360_launch.py &
LIVOX_PID=$!

sleep 5

echo "启动 Super LIO 建图..."
ros2 launch super_lio Livox_mid360.py lio.map.save_map_dir:="$MAP_DIR" &
SUPERLIO_PID=$!

sleep 5

echo "启动 terrain_analysis 地形分析与地图保存..."
ros2 launch terrain_analysis terrain_analysis_with_save.launch map_dir:="$MAP_DIR" &
TERRAIN_PID=$!

echo "建图相关进程已启动："
echo "Livox PID: $LIVOX_PID"
echo "Super LIO PID: $SUPERLIO_PID"
echo "Terrain PID: $TERRAIN_PID"

wait
