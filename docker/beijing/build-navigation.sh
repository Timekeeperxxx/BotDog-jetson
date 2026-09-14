#!/usr/bin/env bash
set -e
cd /workspace/project/Navigation
export CMAKE_BUILD_PARALLEL_LEVEL=2 MAKEFLAGS=-j2
exec colcon build --symlink-install --executor sequential \
    --cmake-args -DCMAKE_MODULE_PATH=/opt/project-cmake -DBUILD_TESTING=OFF
