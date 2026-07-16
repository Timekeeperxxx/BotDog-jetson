#!/usr/bin/env bash
# 为后台危险操作安装最小化 sudo 权限。

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "ERROR: 请用 sudo 运行此脚本"
  echo "  sudo bash scripts/install-system-actions.sh"
  exit 1
fi

TARGET_USER="${SUDO_USER:-}"
if [[ -z "$TARGET_USER" || "$TARGET_USER" = "root" ]]; then
  echo "ERROR: 无法识别运行 BotDog 的普通用户，请通过 sudo 调用本脚本"
  exit 1
fi

SYSTEMCTL_PATH="$(command -v systemctl)"
SUDOERS_FILE="/etc/sudoers.d/botdog-system-actions"
SUDOERS_TMP="$(mktemp)"
trap 'rm -f "$SUDOERS_TMP"' EXIT

printf '%s ALL=(root) NOPASSWD: %s restart botdog-backend.service, %s restart botdog-pipeline.service, %s reboot\n' \
  "$TARGET_USER" "$SYSTEMCTL_PATH" "$SYSTEMCTL_PATH" "$SYSTEMCTL_PATH" > "$SUDOERS_TMP"
chmod 0440 "$SUDOERS_TMP"
visudo -cf "$SUDOERS_TMP" >/dev/null
install -o root -g root -m 0440 "$SUDOERS_TMP" "$SUDOERS_FILE"

echo "后台危险操作权限已安装：$SUDOERS_FILE"
echo "授权用户：$TARGET_USER"
echo "允许操作：重启 BotDog 后端、重启视频流水线、重启设备"
