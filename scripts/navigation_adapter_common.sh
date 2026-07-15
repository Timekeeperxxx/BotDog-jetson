#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOTDOG_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$BOTDOG_ROOT/.." && pwd)"

BOTDOG_NAV_WS="${BOTDOG_NAV_WS:-$PROJECT_ROOT/Navigation}"
BOTDOG_NAV_ADAPTER_DIR="$BOTDOG_NAV_WS/adapters/legacy_scripts"

if [ ! -d "$BOTDOG_NAV_ADAPTER_DIR" ]; then
  printf '错误：Navigation 适配器目录不存在：%s\n' "$BOTDOG_NAV_ADAPTER_DIR" >&2
  exit 1
fi

# BotDog retains its API/runtime contract while Navigation owns ROS processes.
export NAV_ENV_FILE=/dev/null
export ROBOT_NAV_WS="$BOTDOG_NAV_WS"
export ROBOT_NAV_MAP_ROOT="${ROBOT_NAV_MAP_ROOT:-$PROJECT_ROOT/MAPS}"
export ROBOT_NAV_LOG_ROOT="${ROBOT_NAV_LOG_ROOT:-$BOTDOG_ROOT/logs}"
export ROBOT_NAV_RUNTIME_ROOT="${ROBOT_NAV_RUNTIME_ROOT:-$BOTDOG_ROOT/data/nav_runtime}"

export LIVOX_LIDAR_IP="${LIVOX_LIDAR_IP:-192.168.123.179}"
export LIVOX_HOST_IP="${LIVOX_HOST_IP:-192.168.123.222}"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}"
export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_fastrtps_cpp}"
export NAV_FASTDDS_PROFILE="${NAV_FASTDDS_PROFILE:-$BOTDOG_NAV_ADAPTER_DIR/fastdds_navigation.xml}"
export FASTRTPS_DEFAULT_PROFILES_FILE="$NAV_FASTDDS_PROFILE"
unset FASTDDS_DEFAULT_PROFILES_FILE

export NAV_ENABLE_SCAN_PLANNER="${NAV_ENABLE_SCAN_PLANNER:-true}"
export NAV_ENABLE_SCAN_CONTROLLER="${NAV_ENABLE_SCAN_CONTROLLER:-true}"
export NAV_ENABLE_PATH_FOLLOWER="${NAV_ENABLE_PATH_FOLLOWER:-false}"
export NAV_ENABLE_DYNAMIC_AVOIDANCE="${NAV_ENABLE_DYNAMIC_AVOIDANCE:-true}"
export NAV_ENABLE_WAYPOINT_NAVIGATOR="${NAV_ENABLE_WAYPOINT_NAVIGATOR:-true}"

# BotDog's UnitreeB2Adapter remains the sole B2 hardware writer. Navigation
# emits /cmd_vel_safe; the ROS sender only forwards it to the loopback ingress.
export NAV_ENABLE_ROBOT_CONTROL="${NAV_ENABLE_ROBOT_CONTROL:-false}"
export NAV_ROBOT_MODEL="${NAV_ROBOT_MODEL:-b2}"
export NAV_ROBOT_CMD_VEL_TOPIC="${NAV_ROBOT_CMD_VEL_TOPIC:-/unitree/b2/cmd_vel}"

run_navigation_adapter() {
  local adapter_name="$1"
  shift
  local adapter="$BOTDOG_NAV_ADAPTER_DIR/$adapter_name"
  if [ ! -f "$adapter" ]; then
    printf '错误：Navigation 适配器不存在：%s\n' "$adapter" >&2
    exit 1
  fi
  exec bash "$adapter" "$@"
}
