#!/bin/bash
set -e

echo "🚀 启动 BotDog 后端（含 UDP 转发器）..."

# 激活虚拟环境
source .venv/bin/activate

# 检查 Python 版本
if ! command -v python3 &> /dev/null; then
    echo "❌ 错误: 未找到 python3"
    exit 1
fi

echo "✅ Python 版本: $(python3 --version)"

# 检查网络配置
echo "📡 检查网络配置..."
if ip addr show ens33 | grep -q "inet 192.168.144.40"; then
    echo "✅ 硬件网卡 ens33 已配置 IP 192.168.144.40"
else
    echo "❌ 错误: 硬件网卡 ens33 未配置 IP 192.168.144.40"
    echo "请运行: sudo ip addr add 192.168.144.40/24 dev ens33"
    exit 1
fi

# 优化系统参数
echo "⚙️  优化系统网络参数..."
sudo sysctl -w net.core.rmem_max=134217728 >/dev/null 2>&1
sudo sysctl -w net.core.rmem_default=134217728 >/dev/null 2>&1
sudo sysctl -w net.core.wmem_max=134217728 >/dev/null 2>&1
sudo sysctl -w net.core.wmem_default=134217728 >/dev/null 2>&1
echo "✅ UDP 缓冲区已优化至 128MB"

# 启动后端
echo "✅ 启动后端服务器..."
# 从项目根目录启动，这样 Python 模块路径才能正确解析
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
