#!/bin/bash
set -e

echo "🔍 BotDog 网络配置验证工具"
echo "================================"

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 检查函数
check_pass() {
    echo -e "${GREEN}✅ $1${NC}"
}

check_fail() {
    echo -e "${RED}❌ $1${NC}"
}

check_warn() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

echo ""
echo "📡 检查网络接口配置..."
echo "--------------------------------"

# 检查 ens33 网卡
if ip addr show ens33 &> /dev/null; then
    check_pass "ens33 网卡存在"

    # 检查 IP 配置
    if ip addr show ens33 | grep -q "inet 192.168.144.40"; then
        check_pass "ens33 已配置 IP 192.168.144.40/24"
        IP_CONFIGURED=true
    else
        check_fail "ens33 未配置 IP 192.168.144.40/24"
        echo "   请运行: sudo ip addr add 192.168.144.40/24 dev ens33"
        IP_CONFIGURED=false
    fi

    # 检查网卡状态
    if ip addr show ens33 | grep -q "state UP"; then
        check_pass "ens33 网卡状态: UP"
    else
        check_warn "ens33 网卡状态: DOWN"
        echo "   请运行: sudo ip link set ens33 up"
    fi
else
    check_fail "ens33 网卡不存在"
    echo "   可用网卡:"
    ip -o link show | awk '{print "   - " $2}' | sed 's/:$//'
    IP_CONFIGURED=false
fi

echo ""
echo "🌐 检查网络连通性..."
echo "--------------------------------"

# 检查本地回环
if ping -c 1 -W 1 127.0.0.1 &> /dev/null; then
    check_pass "本地回环正常"
else
    check_fail "本地回环异常"
fi

# 检查图传地面端（如果 IP 配置正确）
if [ "$IP_CONFIGURED" = true ]; then
    if ping -c 1 -W 2 192.168.144.25 &> /dev/null; then
        check_pass "图传地面端 192.168.144.25 可达"
    else
        check_warn "图传地面端 192.168.144.25 不可达（可能未连接）"
    fi
fi

echo ""
echo "🔧 检查系统网络参数..."
echo "--------------------------------"

# 检查 UDP 缓冲区
RMEM_MAX=$(cat /proc/sys/net/core/rmem_max)
RMEM_DEFAULT=$(cat /proc/sys/net/core/rmem_default)
WMEM_MAX=$(cat /proc/sys/net/core/wmem_max)
WMEM_DEFAULT=$(cat /proc/sys/net/core/wmem_default)

if [ "$RMEM_MAX" -ge 134217728 ]; then
    check_pass "UDP 接收缓冲区最大值: ${RMEM_MAX} bytes"
else
    check_warn "UDP 接收缓冲区最大值偏小: ${RMEM_MAX} bytes"
    echo "   建议运行: sudo sysctl -w net.core.rmem_max=134217728"
fi

if [ "$RMEM_DEFAULT" -ge 134217728 ]; then
    check_pass "UDP 接收缓冲区默认值: ${RMEM_DEFAULT} bytes"
else
    check_warn "UDP 接收缓冲区默认值偏小: ${RMEM_DEFAULT} bytes"
    echo "   建议运行: sudo sysctl -w net.core.rmem_default=134217728"
fi

echo ""
echo "🔌 检查端口占用情况..."
echo "--------------------------------"

# 检查后端端口 8000
if sudo netstat -tuln | grep -q ":8000 "; then
    check_pass "后端端口 8000 已监听"
else
    check_warn "后端端口 8000 未监听（可能未启动）"
fi

# 检查 UDP 转发端口 5000
if sudo netstat -tuln | grep -q ":5000 "; then
    check_pass "UDP 转发端口 5000 已监听"
else
    check_warn "UDP 转发端口 5000 未监听（可能未启动）"
fi

echo ""
echo "📊 检查后端服务状态..."
echo "--------------------------------"

# 检查后端健康状态
if command -v curl &> /dev/null; then
    if curl -s http://localhost:8000/api/v1/system/health | grep -q "status"; then
        check_pass "后端 API 可访问"

        # 检查 UDP 转发器状态
        UDP_STATS=$(curl -s http://localhost:8000/api/v1/video/udp-relay/stats 2>/dev/null)
        if [ $? -eq 0 ]; then
            if echo "$UDP_STATS" | grep -q "video_stream"; then
                check_pass "UDP 转发器运行中"
                echo ""
                echo "📈 UDP 转发器统计:"
                echo "$UDP_STATS" | jq '.' 2>/dev/null || echo "$UDP_STATS"
            elif echo "$UDP_STATS" | grep -q "not_started"; then
                check_warn "UDP 转发器未启动"
            fi
        else
            check_warn "无法获取 UDP 转发器状态"
        fi
    else
        check_warn "后端 API 不可访问（可能未启动）"
    fi
else
    check_warn "curl 未安装，跳过 API 检查"
fi

echo ""
echo "📋 配置文件检查..."
echo "--------------------------------"

CONFIG_FILE="/home/frank/Code/Project/BotDog/backend/config.py"
if [ -f "$CONFIG_FILE" ]; then
    check_pass "配置文件存在: $CONFIG_FILE"

    # 检查关键配置
    if grep -q "UDP_RELAY_BIND_ADDRESS: str = \"192.168.144.40\"" "$CONFIG_FILE"; then
        check_pass "UDP_RELAY_BIND_ADDRESS 配置正确"
    else
        check_warn "UDP_RELAY_BIND_ADDRESS 配置可能不正确"
    fi

    if grep -q "HARDWARE_INTERFACE: str = \"ens33\"" "$CONFIG_FILE"; then
        check_pass "HARDWARE_INTERFACE 配置正确"
    else
        check_warn "HARDWARE_INTERFACE 配置可能不正确"
    fi
else
    check_fail "配置文件不存在: $CONFIG_FILE"
fi

echo ""
echo "================================"
if [ "$IP_CONFIGURED" = true ]; then
    echo -e "${GREEN}✅ 网络配置验证通过！${NC}"
    echo ""
    echo "可以启动后端服务："
    echo "  cd /home/frank/Code/Project/BotDog"
    echo "  ./scripts/start_backend.sh"
else
    echo -e "${RED}❌ 网络配置验证失败！${NC}"
    echo ""
    echo "请先配置网络："
    echo "  sudo ip addr add 192.168.144.40/24 dev ens33"
    echo "  sudo ip link set ens33 up"
fi

echo ""
