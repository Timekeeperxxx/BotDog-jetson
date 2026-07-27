#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOTDOG_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
NAVIGATION_ROOT="${BOTDOG_NAV_WS:-$(cd "$BOTDOG_ROOT/.." && pwd)/Navigation}"
ROS2_SETUP_FILE="${ROS2_SETUP_FILE:-/opt/ros/humble/setup.bash}"
NAVIGATION_SETUP_FILE="$NAVIGATION_ROOT/install/setup.bash"
NAV_FASTDDS_PROFILE="${NAV_FASTDDS_PROFILE:-$NAVIGATION_ROOT/adapters/legacy_scripts/fastdds_navigation.xml}"

if [ ! -f "$ROS2_SETUP_FILE" ]; then
  printf '错误：找不到 ROS2 环境文件：%s\n' "$ROS2_SETUP_FILE" >&2
  exit 1
fi
if [ ! -f "$NAVIGATION_SETUP_FILE" ]; then
  printf '错误：找不到 Navigation 环境文件：%s\n' "$NAVIGATION_SETUP_FILE" >&2
  exit 1
fi

unset PYTHONHOME VIRTUAL_ENV
set +u
# shellcheck disable=SC1090
source "$ROS2_SETUP_FILE"
# shellcheck disable=SC1090
source "$NAVIGATION_SETUP_FILE"
set -u

export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}"
export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_fastrtps_cpp}"
if [ -f "$NAV_FASTDDS_PROFILE" ]; then
  export FASTRTPS_DEFAULT_PROFILES_FILE="$NAV_FASTDDS_PROFILE"
  unset FASTDDS_DEFAULT_PROFILES_FILE
fi

cd "$BOTDOG_ROOT"
exec /usr/bin/python3 "$SCRIPT_DIR/cmd_vel_ros2_udp_sender.py"
