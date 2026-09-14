#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/../../.."
docker run -d --name beijing-dev --init --stop-timeout 30 --network host \
    --env-file docker/development.env \
    --mount "type=bind,src=$PWD,dst=/workspace/project" \
    --mount "type=bind,src=/home/frank/Projects/Models,dst=/workspace/models,readonly" \
    beijing-dev:humble-2204 bash /workspace/project/docker/services.sh
