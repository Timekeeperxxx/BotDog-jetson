#!/usr/bin/env bash
# 安装 BotDog 外部进程日志轮转规则。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CURRENT_USER="${SUDO_USER:-$(whoami)}"

if [[ $EUID -ne 0 ]]; then
  echo "ERROR: 请用 sudo 运行此脚本"
  echo "  sudo bash scripts/install-logrotate.sh"
  exit 1
fi

if ! command -v logrotate >/dev/null 2>&1; then
  echo "ERROR: 未找到 logrotate，请先安装"
  exit 1
fi

sed "s|/home/jetson/Project/BOTDOG/BotDog|${PROJECT_DIR}|g; s|su jetson jetson|su ${CURRENT_USER} ${CURRENT_USER}|g" \
  "$SCRIPT_DIR/botdog-logrotate.conf" | tr -d '\r' > /etc/logrotate.d/botdog
chmod 0644 /etc/logrotate.d/botdog

STATE_FILE="/tmp/botdog-logrotate-install.$$.status"
trap 'rm -f "$STATE_FILE"' EXIT
if ! logrotate --debug --state "$STATE_FILE" /etc/logrotate.d/botdog >/dev/null 2>&1; then
  echo "ERROR: logrotate 规则校验失败"
  exit 1
fi
rm -f "$STATE_FILE"
trap - EXIT

echo "BotDog 日志轮转规则已安装：/etc/logrotate.d/botdog"
