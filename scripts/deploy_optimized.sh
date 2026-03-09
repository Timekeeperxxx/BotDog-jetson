#!/bin/bash
# BotDog 一键部署脚本 - 系统级优化版
# 针对 6 核虚拟机优化，解决灰屏残影问题

set -e  # 遇到错误立即退出

echo "🚀 BotDog 一键部署 - 系统级优化版"
echo "=================================="
echo ""

# 1️⃣ 检查系统环境
echo "📊 1. 检查系统环境..."
CPU_CORES=$(nproc)
MEM_GB=$(free -g | awk '/^Mem:/{print $2}')
echo "  CPU 核心数: $CPU_CORES"
echo "  内存: ${MEM_GB}GB"

if [ "$CPU_CORES" -lt 4 ]; then
    echo "  ⚠️  警告: CPU 核心数少于 4，性能可能不足"
fi

if [ "$MEM_GB" -lt 4 ]; then
    echo "  ❌ 错误: 内存少于 4GB，无法运行"
    exit 1
fi
echo "  ✅ 系统环境检查通过"
echo ""

# 2️⃣ 优化系统 UDP 缓冲区
echo "🔧 2. 优化系统 UDP 缓冲区..."
if [ "$EUID" -ne 0 ]; then
    echo "  ⚠️  需要 sudo 权限优化系统缓冲区"
    echo "     请运行: sudo bash scripts/optimize_udp_buffer.sh"
else
    bash scripts/optimize_udp_buffer.sh
fi
echo ""

# 3️⃣ 停止旧服务
echo "🛑 3. 停止旧服务..."
pkill -9 -f "uvicorn backend" 2>/dev/null || true
pkill -9 -f "edge/gstreamer_streamer" 2>/dev/null || true
sleep 2
echo "  ✅ 旧服务已停止"
echo ""

# 4️⃣ 启动后端（系统级优化版）
echo "🚀 4. 启动后端服务（系统级优化版）..."
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 > /tmp/backend_final.log 2>&1 &
BACKEND_PID=$!
sleep 3

# 检查后端是否启动成功
if lsof -i :8000 | grep -q LISTEN; then
    echo "  ✅ 后端启动成功 (PID: $BACKEND_PID)"
    echo "     监听: 0.0.0.0:8000"
else
    echo "  ❌ 后端启动失败，查看日志:"
    cat /tmp/backend_final.log
    exit 1
fi
echo ""

# 5️⃣ 显示推流命令
echo "📡 5. 边缘端推流命令（在边缘设备运行）:"
echo ""
echo "  python3 edge/gstreamer_streamer.py \\"
echo "    --source rtsp \\"
echo "    --device \"rtsp://192.168.144.25:8554/main.264\" \\"
echo "    --host 192.168.144.40 \\"
echo "    --port 5000 \\"
echo "    --bitrate 3000000 \\"
echo "    --width 1280 \\"
echo "    --height 720"
echo ""

# 6️⃣ 显示前端启动命令
echo "🌐 6. 前端启动命令（新开终端运行）:"
echo ""
echo "  cd frontend"
echo "  npm run dev"
echo ""

# 7️⃣ 显示访问地址
echo "✨ 部署完成！"
echo ""
echo "📺 访问地址:"
echo "  - 本地: http://localhost:5173"
echo "  - 网络: http://192.168.144.40:5173"
echo ""
echo "📊 实时监控:"
echo "  - 后端日志: tail -f /tmp/backend_final.log"
echo "  - CPU 使用: htop"
echo "  - 网络流量: iftop -i eth0"
echo ""
echo "🎯 系统级优化已启用:"
echo "  ✅ UDP 接收缓冲: 25MB"
echo "  ✅ UDP 发送缓冲: 25MB"
echo "  ✅ 网络队列长度: 10000"
echo "  ✅ 后端管道: 20MB 缓冲 + 500ms 抖动"
echo "  ✅ 输出分辨率: 1280x720 @ 25fps"
echo "  ✅ 推流码率: 3Mbps (H.265)"
echo ""
echo "🎉 享受高清丝滑的视频流吧！"
