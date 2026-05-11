#!/usr/bin/env bash
set -euo pipefail

echo "开始清理导航残留进程..."

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
  "/home/jetson/superlio/install/livox_ros_driver2/lib/livox_ros_driver2/livox_ros_driver2_node"
  "/home/jetson/superlio/install/super_lio/lib/super_lio/relocation_node"
  "/home/jetson/dddmr_navigation_new_local/install/global_planner/lib/global_planner/global_planner_node"
  "/home/jetson/dddmr_navigation_new_local/install/mcl_3dl/lib/mcl_3dl/pcl_publisher"
  "/home/jetson/dddmr_navigation_new_local/install/p2p_move_base/lib/p2p_move_base/clicked2goal.py"
  "/home/jetson/Project/BOTDOG/unitree_sdk2_python/example/scripts/cmd_vel.py"
  "/home/jetson/Project/BOTDOG/BotDog/run_backend.py"
  "/home/jetson/Project/BOTDOG/BotDog/scripts/start_backend.sh"
  "ros2 launch livox_ros_driver2 msg_MID360_launch.py"
  "ros2 launch super_lio relocation.py"
  "ros2 launch global_planner path_planning_with_polygon.launch"
  "ros2 launch p2p_move_base go2_localization_launch.py"
)

for needle in "${ROS_NEEDLES[@]}"; do
  kill_needle_term "$needle"
done

sleep 3

for needle in "${ROS_NEEDLES[@]}"; do
  kill_needle_kill "$needle"
done

sleep 1

REMAINING="$(pgrep -af 'livox_ros_driver2_node|relocation_node|global_planner_node|pcl_publisher|clicked2goal.py|cmd_vel.py|msg_MID360_launch.py|go2_localization_launch.py|path_planning_with_polygon.launch|run_backend.py|start_backend.sh' || true)"

if [ -n "$REMAINING" ]; then
  echo "仍有残留进程："
  echo "$REMAINING"
  exit 1
fi

echo "导航残留清理完成。"
