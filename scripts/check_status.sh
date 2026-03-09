#!/bin/bash
# BotDog 部署状态检查脚本

echo "🔍 BotDog 部署状态检查"
echo "======================"
echo ""

# 1. 检查后端
echo "1️⃣ 后端状态："
if lsof -i :8000 | grep -q "LISTEN"; then
    LISTEN_ADDR=$(lsof -i :8000 | grep LISTEN | awk '{print $9}')
    echo "  ✅ 后端运行中"
    echo "  📡 监听地址: $LISTEN_ADDR"
    if [[ "$LISTEN_ADDR" == "*:8000" ]]; then
        echo "  ✅ 监听所有网卡（正确）"
    else
        echo "  ⚠️  只监听 localhost（外部无法访问）"
    fi
else
    echo "  ❌ 后端未运行"
    echo "  请运行: python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000"
fi
echo ""

# 2. 检查前端
echo "2️⃣ 前端状态："
if lsof -i :5173 | grep -q "LISTEN"; then
    echo "  ✅ 前端运行中"
    echo "  🌐 访问地址:"
    echo "     - http://localhost:5173 (本地)"
    echo "     - http://192.168.144.40:5173 (网络)"
    echo ""
    echo "  ⚠️  重要：如果 WebSocket 连接失败，请使用网络地址访问"
    echo "     http://192.168.144.40:5173"
else
    echo "  ❌ 前端未运行"
    echo "  请运行: cd frontend && npm run dev"
fi
echo ""

# 3. 检查网络接口
echo "3️⃣ 网络接口："
ip -4 addr show | grep "inet " | grep -v "127.0.0.1" | while read -r line; do
    echo "  $line"
done
echo ""

# 4. 测试后端连接
echo "4️⃣ 后端连接测试："
if curl -s http://192.168.144.40:8000/docs > /dev/null; then
    echo "  ✅ 后端 API 可访问"
    echo "  📚 API 文档: http://192.168.144.40:8000/docs"
else
    echo "  ❌ 后端 API 不可访问"
fi
echo ""

# 5. 检查 UDP 端口
echo "5️⃣ UDP 端口状态："
if lsof -i :5000 | grep -q "UDP"; then
    echo "  ✅ UDP 5000 端口已绑定（视频接收）"
else
    echo "  ⚠️  UDP 5000 端口未绑定（等待推流）"
fi
echo ""

# 6. 推流建议
echo "📡 推流命令（边缘设备）："
echo "  python3 edge/gstreamer_streamer.py \\"
echo "    --source rtsp \\"
echo "    --device \"rtsp://192.168.144.25:8554/main.264\" \\"
echo "    --host 192.168.144.40 \\"
echo "    --port 5000 \\"
echo "    --bitrate 1000000 \\"
echo "    --width 1280 \\"
echo "    --height 720"
echo ""

echo "🎯 访问建议："
echo "  如果浏览器显示 WebSocket 连接错误，请访问："
echo "  http://192.168.144.40:5173"
echo ""
