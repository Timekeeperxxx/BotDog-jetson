#!/bin/bash
# BotDog 激进低延迟优化脚本
# 针对 1.64Mbps 带宽优化

echo "🚀 BotDog 激进低延迟优化"
echo "========================="
echo ""

# 1. 修改后端管道为激进模式
echo "📝 1. 修改后端管道（10ms 抖动 + 主动丢包）..."
sed -i 's/latency=500 do-retransmission=true/latency=10 drop-on-latency=true/g' backend/video_track.py
sed -i 's/buffer-size=20971520/buffer-size=1048576/g' backend/video_track.py
sed -i 's/max-buffers=2/max-buffers=1/g' backend/video_track.py
echo "  ✅ 后端管道已优化"
echo ""

# 2. 修改推流端码率为 1Mbps
echo "📝 2. 修改推流端码率（1Mbps）..."
sed -i 's/bitrate: int = 3000000/bitrate: int = 1000000/g' edge/gstreamer_streamer.py
echo "  ✅ 推流端码率已优化"
echo ""

# 3. 重启后端
echo "🔄 3. 重启后端服务..."
pkill -9 -f "uvicorn backend" 2>/dev/null || true
sleep 2
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 > /tmp/backend_lowlatency.log 2>&1 &
sleep 3

if lsof -i :8000 | grep -q ".*:8000.*LISTEN"; then
    echo "  ✅ 后端启动成功"
    echo ""
    echo "📊 优化效果："
    echo "  - 推流码率: 1Mbps (适配 1.64Mbps 带宽)"
    echo "  - 抖动缓冲: 10ms (激进低延迟)"
    echo "  - 丢包策略: drop-on-latency=true (宁可丢帧，不要延迟)"
    echo "  - 接收缓冲: 1MB (快速处理)"
    echo "  - 队列深度: 1 (最低延迟)"
    echo ""
    echo "🎯 预期延迟: 50-150ms (毫秒级)"
    echo ""
    echo "📡 启动推流（边缘设备）:"
    echo "  python3 edge/gstreamer_streamer.py \\"
    echo "    --source rtsp \\"
    echo "    --device \"rtsp://192.168.144.25:8554/main.264\" \\"
    echo "    --host 192.168.144.40 \\"
    echo "    --port 5000 \\"
    echo "    --bitrate 1000000 \\"
    echo "    --width 1280 \\"
    echo "    --height 720"
else
    echo "  ❌ 后端启动失败"
    exit 1
fi
