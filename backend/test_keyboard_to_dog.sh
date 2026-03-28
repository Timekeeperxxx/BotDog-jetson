#!/usr/bin/env bash
# 键盘直控机器狗测试启动脚本
# 环境变量配置逻辑与 scripts/start_backend.sh 保持一致

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT_DIR/.venv"
UNITREE_IFACE="${UNITREE_NETWORK_IFACE:-enP3p49s0}"
UNITREE_IP="${UNITREE_LOCAL_IP:-192.168.123.222}"

# 确保 B2 网卡 IP 已配置
if ! ip addr show "$UNITREE_IFACE" 2>/dev/null | grep -q "$UNITREE_IP"; then
  echo "[INFO] 为 $UNITREE_IFACE 配置 IP $UNITREE_IP/24..."
  echo '123123' | sudo -S ip addr add "${UNITREE_IP}/24" dev "$UNITREE_IFACE" 2>/dev/null || true
fi

# 确保 DDS multicast 路由走 B2 所在网卡
if ! ip route show | grep -q "224.0.0.0/4.*dev $UNITREE_IFACE"; then
  echo "[INFO] 添加 DDS multicast 路由 → $UNITREE_IFACE ..."
  echo '123123' | sudo -S ip route add 224.0.0.0/4 dev "$UNITREE_IFACE" 2>/dev/null || true
fi

# 修复 ARM64 下 pip cyclonedds==0.10.2 自带 C 库无法创建 Topic 的 Bug
export CYCLONEDDS_HOME="${CYCLONEDDS_HOME:-/usr/local}"
export LD_LIBRARY_PATH="$CYCLONEDDS_HOME/lib:${LD_LIBRARY_PATH:-}"
echo "[INFO] CYCLONEDDS_HOME=$CYCLONEDDS_HOME, LD_LIBRARY_PATH 已注入"

source "$VENV/bin/activate"
cd "$ROOT_DIR"

exec python backend/test_keyboard_to_dog.py "$@"
