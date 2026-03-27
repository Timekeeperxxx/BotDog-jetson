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
# 强制指向本地手动交叉编译/编译的 CycloneDDS 库路径
export CYCLONEDDS_HOME="${CYCLONEDDS_HOME:-/usr/local}"
echo "[INFO] CYCLONEDDS_HOME 设定为 $CYCLONEDDS_HOME"



source "$VENV/bin/activate"
cd "$ROOT_DIR"
exec python run_backend.py
