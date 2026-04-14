#!/bin/bash
# 集成测试脚本：测试 ROS2 cmd_vel 桥接器

set -e

echo "=== ROS2 cmd_vel 桥接器集成测试 ==="
echo ""

# 检查是否安装了 ROS2
if ! command -v ros2 &> /dev/null; then
    echo "错误: ROS2 未安装或不在 PATH 中"
    echo "请先安装 ROS2 (Humble Hawksbill)"
    exit 1
fi

# 检查 Python 依赖
echo "检查 Python 依赖..."
python3 -c "import rclpy" 2>/dev/null || {
    echo "错误: rclpy 未安装"
    echo "请运行: pip install rclpy"
    exit 1
}

python3 -c "from geometry_msgs.msg import Twist" 2>/dev/null || {
    echo "错误: geometry_msgs 未安装"
    echo "请运行: sudo apt install ros-humble-geometry-msgs"
    exit 1
}

# 切换到脚本目录
cd "$(dirname "$0")"

# 清理之前的 ROS2 进程
echo "清理之前的 ROS2 进程..."
pkill -f "ros2_cmd_vel_to_adapter.py" 2>/dev/null || true
pkill -f "test_ros2_cmd_vel_bridge.py" 2>/dev/null || true
sleep 1

# 启动桥接器（模拟模式）
echo "启动 ROS2 cmd_vel 桥接器（模拟模式）..."
python3 ros2_cmd_vel_to_adapter.py --adapter simulation &
BRIDGE_PID=$!
echo "桥接器 PID: $BRIDGE_PID"

# 等待桥接器启动
echo "等待桥接器启动..."
sleep 3

# 检查桥接器是否在运行
if ! kill -0 $BRIDGE_PID 2>/dev/null; then
    echo "错误: 桥接器启动失败"
    exit 1
fi

# 启动测试发布器
echo "启动测试发布器..."
python3 test_ros2_cmd_vel_bridge.py &
PUBLISHER_PID=$!
echo "发布器 PID: $PUBLISHER_PID"

# 等待测试完成
echo "等待测试完成..."
wait $PUBLISHER_PID 2>/dev/null || true

# 停止桥接器
echo "停止桥接器..."
kill $BRIDGE_PID 2>/dev/null || true
wait $BRIDGE_PID 2>/dev/null || true

echo ""
echo "=== 测试完成 ==="
echo "如果看到 '收到速度命令' 和 '发布:' 消息，说明桥接器工作正常。"
echo "要测试真实硬件，请运行:"
echo "  python3 ros2_cmd_vel_to_adapter.py --adapter unitree_b2 --network-interface eno1"
echo ""
echo "然后在另一个终端运行:"
echo "  python3 test_ros2_cmd_vel_bridge.py"
echo "或使用 ROS2 工具发布命令:"
echo "  ros2 topic pub /cmd_vel geometry_msgs/msg/Twist \"{linear: {x: 0.2, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.0}}\""
