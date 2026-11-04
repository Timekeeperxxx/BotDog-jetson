#!/usr/bin/env bash
# Same hardware-free regression command locally and in CI.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
export PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
export AI_ENABLED=false WEATHER_ENABLED=false ROS_NAV_ENABLED=false
export CONTROL_ADAPTER_TYPE=simulation SIMULATION_WORKER_ENABLED=false
PYTHON_BIN="${BOTDOG_TEST_PYTHON:-$ROOT_DIR/.venv/bin/python}"
exec "$PYTHON_BIN" -B -m pytest -p no:cacheprovider -p pytest_asyncio.plugin --noconftest -o addopts= --tb=short -q "$@" tests/
