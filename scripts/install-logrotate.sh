#!/usr/bin/env bash
# 安装 BotDog 外部进程日志轮转规则。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CURRENT_USER="${SUDO_USER:-$(whoami)}"
CURRENT_GROUP="$(id -gn "$CURRENT_USER")"

if [[ $EUID -ne 0 ]]; then
  echo "ERROR: 请用 sudo 运行此脚本"
  echo "  sudo bash scripts/install-logrotate.sh"
  exit 1
fi

if ! command -v logrotate >/dev/null 2>&1; then
  echo "ERROR: 未找到 logrotate，请先执行 sudo apt install logrotate"
  exit 1
fi

TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TEMP_DIR"' EXIT
for name in botdog-logrotate.conf botdog-logrotate.service botdog-logrotate.timer; do
  sed "s|@BOTDOG_PROJECT_DIR@|${PROJECT_DIR}|g; s|@BOTDOG_USER@|${CURRENT_USER}|g; s|@BOTDOG_GROUP@|${CURRENT_GROUP}|g" \
    "$SCRIPT_DIR/$name" | tr -d '\r' > "$TEMP_DIR/$name"
done
logrotate --debug --state "$TEMP_DIR/status" "$TEMP_DIR/botdog-logrotate.conf"
systemd-analyze verify "$TEMP_DIR/botdog-logrotate.service" "$TEMP_DIR/botdog-logrotate.timer"
install -d -m 0755 /etc/botdog
# A dedicated timer/state avoids a second daily rotation from /etc/logrotate.conf.
if [[ -f /etc/logrotate.d/botdog ]]; then
  mv /etc/logrotate.d/botdog /etc/botdog/logrotate.legacy.conf
fi
install -m 0644 "$TEMP_DIR/botdog-logrotate.conf" /etc/botdog/logrotate.conf
install -m 0644 "$TEMP_DIR/botdog-logrotate.service" /etc/systemd/system/botdog-logrotate.service
install -m 0644 "$TEMP_DIR/botdog-logrotate.timer" /etc/systemd/system/botdog-logrotate.timer
systemctl daemon-reload
systemctl enable --now botdog-logrotate.timer
systemctl start botdog-logrotate.service
echo "BotDog 日志轮转已启用：每 5 分钟检查、20 MiB 轮转、7 份/14 天、外部日志总预算 1 GiB"
