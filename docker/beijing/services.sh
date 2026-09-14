#!/usr/bin/env bash
set -e
cd /workspace/project
mkdir -p docker MAPS BotDog-jetson/data BotDog-jetson/logs
pids=()
trap 'kill "${pids[@]}" 2>/dev/null || true; wait || true' EXIT
trap 'exit 0' TERM INT
mediamtx docker/mediamtx.yml > docker/video.log 2>&1 &
pids+=("$!")
(cd BotDog-jetson; exec /opt/venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8002) > docker/backend.log 2>&1 &
pids+=("$!")
/opt/venv/bin/python Navigation/tools/test_app/backend/main.py --host 127.0.0.1 --port 8092 --workspace-dir /workspace/project/Navigation > docker/navigation-test.log 2>&1 &
pids+=("$!")
wait -n "${pids[@]}"
exit 1
