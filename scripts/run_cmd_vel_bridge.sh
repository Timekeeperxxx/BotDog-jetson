#!/usr/bin/env bash
set -e

if [ $# -lt 1 ] || [ -z "${1:-}" ]; then
  echo "错误: 缺少项目根目录参数" >&2
  exit 1
fi

PROJECT_ROOT="$1"
cd "$PROJECT_ROOT"

echo "[cmd_vel] cwd=$(pwd)"
echo "[cmd_vel] start $(date "+%F %T")"

UNITREE_ROS2_DIR="./unitree_ros2"
echo "[cmd_vel] unitree_ros2_dir=$UNITREE_ROS2_DIR"
if [ ! -d "$UNITREE_ROS2_DIR" ]; then
  echo "错误: 未找到 unitree_ros2 目录。请确保它在当前目录下。" >&2
  exit 1
fi

echo "[cmd_vel] unitree_ros2 exists"
if [ -f "$UNITREE_ROS2_DIR/install/setup.sh" ]; then
  echo "[cmd_vel] sourcing $UNITREE_ROS2_DIR/install/setup.sh"
  set +u
  # shellcheck disable=SC1090
  source "$UNITREE_ROS2_DIR/install/setup.sh"
  set -u
  echo "已 source unitree_ros2 环境。"
else
  echo "警告: 未找到 $UNITREE_ROS2_DIR/install/setup.sh，可能未构建 unitree_ros2。"
fi

export ROS_DOMAIN_ID=0
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI='<CycloneDDS><Domain Id="any"><General><Interfaces>
                            <NetworkInterface name="eno1" priority="default" multicast="default" />
                        </Interfaces></General></Domain></CycloneDDS>'

echo "[cmd_vel] env prepared"
echo "[cmd_vel] AMENT_PREFIX_PATH=${AMENT_PREFIX_PATH:-}"
echo "[cmd_vel] PYTHONPATH=${PYTHONPATH:-}"
echo "[cmd_vel] ROS_LOG_DIR=${ROS_LOG_DIR:-}"
echo "[cmd_vel] python=$(command -v python3)"
echo "[cmd_vel] python_version=$(python3 --version 2>&1)"
echo "[cmd_vel] exec ./unitree_sdk2_python/example/scripts/cmd_vel.py"
exec python3 ./unitree_sdk2_python/example/scripts/cmd_vel.py
