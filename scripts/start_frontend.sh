#!/bin/bash
set -e

echo "🔄 重启前端开发服务器..."

# 切换到前端目录
cd /home/frank/Code/Project/BotDog/frontend

# 停止现有进程
if pkill -f "vite"; then
  echo "✅ 已停止旧的 Vite 进程"
fi

# 等待端口释放
sleep 1

# 清理 Vite 缓存（关键：强制重新加载环境变量）
echo "🧹 清理 Vite 缓存..."
rm -rf node_modules/.vite

# 确认环境变量配置
echo "📋 当前环境变量配置 (.env):"
grep VITE_API_BASE_URL .env || echo "⚠️  未找到 VITE_API_BASE_URL"

# 启动前端开发服务器（会自动加载 .env 文件）
echo "🚀 启动前端开发服务器..."
npm run dev

# 如果需要后台运行，使用：
# nohup npm run dev > /tmp/vite.log 2>&1 &
