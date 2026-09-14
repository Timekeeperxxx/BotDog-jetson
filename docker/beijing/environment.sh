#!/usr/bin/env bash
source /opt/ros/humble/setup.bash
if [ -f /workspace/project/Navigation/install/setup.bash ]; then
    source /workspace/project/Navigation/install/setup.bash
fi
export NAV_ENV_FILE=/dev/null
export ROBOT_NAV_WS=/workspace/project/Navigation
export BOTDOG_NAV_WS="$ROBOT_NAV_WS"
export ROBOT_NAV_MAP_ROOT=/workspace/project/MAPS
export ROBOT_NAV_LOG_ROOT=/workspace/project/BotDog-jetson/logs
export ROBOT_NAV_RUNTIME_ROOT=/workspace/project/BotDog-jetson/data/nav_runtime
export ROS_LOG_DIR="$ROBOT_NAV_LOG_ROOT/ros"
export ROS2_SETUP_FILE=/opt/ros/humble/setup.bash
export SUPERLIO_ROOT_DIR="$ROBOT_NAV_WS/src/nav_lio"
export LIVOX_CONFIG_PATH="$ROBOT_NAV_RUNTIME_ROOT/livox_mid360_config.json"
export MEDIAMTX_EXE=/usr/local/bin/mediamtx
export PYTHONNOUSERSITE=1
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    exec "$@"
fi
