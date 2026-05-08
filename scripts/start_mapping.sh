#!/usr/bin/env bash
set -euo pipefail

MAP_DIR="${1:-}"
LIVOX_PID=""
SUPER_LIO_PID=""
TERRAIN_PID=""

if [ -z "$MAP_DIR" ]; then
  echo "错误：缺少地图保存目录参数"
  echo "用法：bash start_mapping.sh /home/jetson/Project/BOTDOG/MAPS/场景名称"
  exit 1
fi

cleanup() {
  local exit_code=$?
  echo "收到停止信号，正在终止建图相关进程..."

  for pid in "$TERRAIN_PID" "$SUPER_LIO_PID" "$LIVOX_PID"; do
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill -TERM "$pid" 2>/dev/null || true
    fi
  done

  sleep 2

  for pid in "$TERRAIN_PID" "$SUPER_LIO_PID" "$LIVOX_PID"; do
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

mkdir -p "$MAP_DIR"

cd "$HOME/super_lio"
source install/setup.bash

echo "启动 Livox MID360 驱动..."
ros2 launch livox_ros_driver2 msg_MID360_launch.py &
LIVOX_PID=$!

sleep 5

echo "启动 Super LIO 建图..."
ros2 launch super_lio Livox_mid360.py map_dir:="$MAP_DIR" &
SUPER_LIO_PID=$!

sleep 5

echo "启动 terrain_analysis 地形分析与地图保存..."
ros2 launch terrain_analysis terrain_analysis_with_save.launch map_dir:="$MAP_DIR" &
TERRAIN_PID=$!

echo "建图相关进程已启动："
echo "Livox PID: $LIVOX_PID"
echo "Super LIO PID: $SUPER_LIO_PID"
echo "Terrain PID: $TERRAIN_PID"

wait
