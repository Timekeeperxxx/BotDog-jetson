#!/usr/bin/env bash
# BotDog 后端启动脚本（Linux 版）

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.."
VENV="$ROOT_DIR/.venv"

if [ ! -f "$VENV/bin/activate" ]; then
  echo "ERROR: Virtual environment not found at $VENV"
  echo "Run: ~/.pyenv/versions/3.12.9/bin/python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

# 从 backend/.env 解析网卡配置，确保网卡 IP 与 .env 一致
ENV_FILE="$ROOT_DIR/backend/.env"
if [ -f "$ENV_FILE" ]; then
  _iface="$(grep -E '^UNITREE_NETWORK_IFACE=' "$ENV_FILE" | head -1 | cut -d'=' -f2 | tr -d '[:space:]' || true)"
  _ip="$(grep -E '^UNITREE_LOCAL_IP=' "$ENV_FILE" | head -1 | cut -d'=' -f2 | tr -d '[:space:]' || true)"
  [ -n "$_iface" ] && export UNITREE_NETWORK_IFACE="$_iface"
  [ -n "$_ip" ]    && export UNITREE_LOCAL_IP="$_ip"
fi

# 确保宇树 B2 控制网卡 IP 已配置（如 eth0，SDK 通信）
UNITREE_IFACE="${UNITREE_NETWORK_IFACE:-eth0}"
UNITREE_IP="${UNITREE_LOCAL_IP:-192.168.123.222}"
if ! ip addr show "$UNITREE_IFACE" 2>/dev/null | grep -q "$UNITREE_IP"; then
  echo "[INFO] 为 $UNITREE_IFACE 配置 IP $UNITREE_IP/24..."
  echo '123123' | sudo -S ip addr add "${UNITREE_IP}/24" dev "$UNITREE_IFACE" 2>/dev/null || true
fi

# 确保 DDS multicast 路由走 B2 所在网卡（CycloneDDS 发现协议依赖多播）
if ! ip route show | grep -q "224.0.0.0/4.*dev $UNITREE_IFACE"; then
  echo "[INFO] 添加 DDS multicast 路由 → $UNITREE_IFACE ..."
  echo '123123' | sudo -S ip route add 224.0.0.0/4 dev "$UNITREE_IFACE" 2>/dev/null || true
fi

# 修复 ARM64 下 pip cyclonedds==0.10.2 自带 C 库无法创建 Topic 的 Bug
# 强制指向本地编译的 CycloneDDS 库路径，防止加载错误的 C 库
export CYCLONEDDS_HOME="${CYCLONEDDS_HOME:-/home/jetson/cyclonedds-0.10x/install}"
export LD_LIBRARY_PATH="$CYCLONEDDS_HOME/lib:${LD_LIBRARY_PATH:-}"
echo "[INFO] CYCLONEDDS_HOME 设定为 $CYCLONEDDS_HOME, 注入了 LD_LIBRARY_PATH"



source "$VENV/bin/activate"
cd "$ROOT_DIR"
exec python run_backend.py
