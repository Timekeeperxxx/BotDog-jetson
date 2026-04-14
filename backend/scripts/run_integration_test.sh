#!/bin/bash
# ROS2 cmd_vel 桥接器集成测试脚本

set -e

echo "=========================================="
echo "ROS2 cmd_vel 桥接器集成测试"
echo "=========================================="

# 检查 ROS2 环境
if [ -z "$ROS_DISTRO" ]; then
    echo "警告: ROS2 环境未激活，尝试激活..."
    source /opt/ros/humble/setup.bash
fi

# 检查 Python 环境
echo "检查 Python 环境..."
python3 --version

# 检查依赖
echo "检查依赖..."
python3 -c "import rclpy" && echo "✓ rclpy 可用"
python3 -c "import unitree_sdk2py" 2>/dev/null && echo "✓ unitree_sdk2_python 可用" || echo "⚠ unitree_sdk2_python 不可用"

# 清理之前的进程
echo "清理之前的进程..."
pkill -f "ros2_cmd_vel_bridge.py" || true
pkill -f "test_cmd_vel_publisher.py" || true
sleep 1

# 启动桥接器（模拟模式）
echo "启动桥接器（模拟模式）..."
cd /home/jetson/Project/BOTDOG
python3 BotDog/backend/scripts/ros2_cmd_vel_bridge.py --adapter direct --network-interface lo &
BRIDGE_PID=$!
echo "桥接器 PID: $BRIDGE_PID"

# 等待桥接器启动
echo "等待桥接器启动..."
sleep 3

# 检查桥接器是否在运行
if ps -p $BRIDGE_PID > /dev/null; then
    echo "✓ 桥接器正在运行"
else
    echo "✗ 桥接器启动失败"
    exit 1
fi

# 启动测试发布器
echo "启动测试发布器..."
python3 BotDog/backend/scripts/test_cmd_vel_publisher.py &
PUBLISHER_PID=$!
echo "发布器 PID: $PUBLISHER_PID"

# 等待测试完成
echo "等待测试完成（约6秒）..."
sleep 6

# 检查发布器是否完成
if ps -p $PUBLISHER_PID > /dev/null; then
    echo "发布器仍在运行，等待额外时间..."
    sleep 2
    if ps -p $PUBLISHER_PID > /dev/null; then
        echo "强制停止发布器"
        kill $PUBLISHER_PID
    fi
fi

# 停止桥接器
echo "停止桥接器..."
kill $BRIDGE_PID
wait $BRIDGE_PID 2>/dev/null || true

# 检查话题是否有消息
echo "检查话题消息..."
ros2 topic echo --once --field linear.x --field angular.z /cmd_vel 2>/dev/null | head -5 || echo "无法读取话题消息"

echo "=========================================="
echo "集成测试完成"
echo "=========================================="

# 清理
pkill -f "ros2_cmd_vel_bridge.py" || true
pkill -f "test_cmd_vel_publisher.py" || true

exit 0
