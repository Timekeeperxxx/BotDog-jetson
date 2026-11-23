#!/usr/bin/env bash
# 键盘直控机器狗测试启动脚本
# 环境变量配置逻辑与 scripts/start_backend.sh 保持一致

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT_DIR/.venv"
UNITREE_IFACE="${UNITREE_NETWORK_IFACE:-enP3p49s0}"
UNITREE_IP="${UNITREE_LOCAL_IP:-192.168.123.222}"

# 检查 B2 网卡 IP 是否已配置
if ! ip addr show "$UNITREE_IFACE" 2>/dev/null | grep -q "$UNITREE_IP"; then
  echo "[WARN] $UNITREE_IFACE 缺少 IP $UNITREE_IP/24，请用 sudo ip addr add $UNITREE_IP/24 dev $UNITREE_IFACE 配置" >&2
fi

# 检查 DDS 多播路由是否走 B2 所在网卡
if ! ip route show | grep -q "224.0.0.0/4.*dev $UNITREE_IFACE"; then
  echo "[WARN] $UNITREE_IFACE 缺少 DDS 多播路由，请用 sudo ip route add 224.0.0.0/4 dev $UNITREE_IFACE 配置" >&2
fi

# 修复 ARM64 下 pip cyclonedds==0.10.2 自带 C 库无法创建 Topic 的 Bug
export CYCLONEDDS_HOME="${CYCLONEDDS_HOME:-/usr/local}"
export LD_LIBRARY_PATH="$CYCLONEDDS_HOME/lib:${LD_LIBRARY_PATH:-}"
echo "[INFO] CYCLONEDDS_HOME=$CYCLONEDDS_HOME, LD_LIBRARY_PATH 已注入"

source "$VENV/bin/activate"
cd "$ROOT_DIR"

exec python backend/test_keyboard_to_dog.py "$@"
