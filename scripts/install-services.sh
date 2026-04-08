#!/usr/bin/env bash
# BotDog systemd 服务一键安装脚本
# 在 OrangePi 上运行：bash scripts/install-services.sh
# 需要 sudo 权限

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CURRENT_USER="${SUDO_USER:-$(whoami)}"

echo "========================================"
echo "  BotDog 开机自启服务安装脚本"
echo "========================================"
echo "项目目录: $PROJECT_DIR"
echo "运行用户: $CURRENT_USER"
echo ""

# 检查是否以 root 运行
if [[ $EUID -ne 0 ]]; then
  echo "ERROR: 请用 sudo 运行此脚本"
  echo "  sudo bash scripts/install-services.sh"
  exit 1
fi

# 检查 .venv 是否存在
if [[ ! -f "$PROJECT_DIR/.venv/bin/python" ]]; then
  echo "ERROR: 未找到 Python 虚拟环境: $PROJECT_DIR/.venv"
  echo "  请先执行: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

# 检查 mediamtx 是否存在
if [[ ! -x "$SCRIPT_DIR/mediamtx" ]]; then
  echo "WARNING: 未找到可执行的 mediamtx: $SCRIPT_DIR/mediamtx"
  echo "  视频流水线服务可能无法启动，请确认 mediamtx 已下载并赋权 (chmod +x)"
fi

echo ">>> 复制 service 文件到 /etc/systemd/system/ ..."
# 动态替换 service 文件中的用户名和路径（适配不同 OrangePi 用户名）
sed "s|/home/orangepi|/home/${CURRENT_USER}|g; s|User=orangepi|User=${CURRENT_USER}|g" \
  "$SCRIPT_DIR/botdog-backend.service" > /etc/systemd/system/botdog-backend.service

sed "s|/home/orangepi|/home/${CURRENT_USER}|g; s|User=orangepi|User=${CURRENT_USER}|g" \
  "$SCRIPT_DIR/botdog-pipeline.service" > /etc/systemd/system/botdog-pipeline.service

echo ">>> 重载 systemd daemon ..."
systemctl daemon-reload

echo ">>> 启用开机自启 ..."
systemctl enable botdog-backend.service
systemctl enable botdog-pipeline.service

echo ""
echo "========================================"
echo "  安装完成！"
echo "========================================"
echo ""
echo "现在立即启动服务："
echo "  sudo systemctl start botdog-backend"
echo "  sudo systemctl start botdog-pipeline"
echo ""
echo "查看实时日志："
echo "  journalctl -u botdog-backend -f"
echo "  journalctl -u botdog-pipeline -f"
echo ""
echo "停止服务："
echo "  sudo systemctl stop botdog-pipeline botdog-backend"
echo ""
echo "禁用开机自启（如需）："
echo "  sudo systemctl disable botdog-backend botdog-pipeline"
echo ""
