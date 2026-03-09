#!/bin/bash
# BotDog 系统级 UDP 缓冲区优化脚本
# 解决灰屏残影和关键帧丢包问题

echo "🔧 BotDog 系统级 UDP 缓冲区优化"
echo "================================"

# 检查是否有 sudo 权限
if [ "$EUID" -ne 0 ]; then
    echo "❌ 请使用 sudo 运行此脚本"
    echo "   sudo bash scripts/optimize_udp_buffer.sh"
    exit 1
fi

echo "📊 当前配置："
echo "  net.core.rmem_max: $(sysctl -n net.core.rmem_max)"
echo "  net.core.rmem_default: $(sysctl -n net.core.rmem_default)"
echo "  net.core.wmem_max: $(sysctl -n net.core.wmem_max)"
echo "  net.core.wmem_default: $(sysctl -n net.core.wmem_default)"
echo "  net.core.netdev_max_backlog: $(sysctl -n net.core.netdev_max_backlog)"
echo ""

echo "⚙️  应用优化配置..."

# 提升 UDP 接收缓冲区到 25MB（20MB 应用缓冲 + 5MB 系统预留）
sysctl -w net.core.rmem_max=26214400
sysctl -w net.core.rmem_default=26214400

# 提升 UDP 发送缓冲区
sysctl -w net.core.wmem_max=26214400
sysctl -w net.core.wmem_default=26214400

# 提升网络队列长度（处理高并发数据包）
sysctl -w net.core.netdev_max_backlog=10000

echo "✅ 优化完成！"
echo ""
echo "📊 新配置："
echo "  net.core.rmem_max: $(sysctl -n net.core.rmem_max) (25MB)"
echo "  net.core.rmem_default: $(sysctl -n net.core.rmem_default) (25MB)"
echo "  net.core.wmem_max: $(sysctl -n net.core.wmem_max) (25MB)"
echo "  net.core.wmem_default: $(sysctl -n net.core.wmem_default) (25MB)"
echo "  net.core.netdev_max_backlog: $(sysctl -n net.core.netdev_max_backlog)"
echo ""

# 持久化配置（重启后仍然生效）
CONF_FILE="/etc/sysctl.d/99-botdog-udp.conf"
echo "💾 持久化配置到 $CONF_FILE ..."
cat > "$CONF_FILE" << EOF
# BotDog UDP 缓冲区优化
# 生成时间: $(date)
net.core.rmem_max = 26214400
net.core.rmem_default = 26214400
net.core.wmem_max = 26214400
net.core.wmem_default = 26214400
net.core.netdev_max_backlog = 10000
EOF

echo "✅ 配置已持久化，重启后仍然生效"
echo ""
echo "🎉 优化完成！现在请重启后端："
echo "   pkill -f 'uvicorn backend'"
echo "   python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000"
