#!/usr/bin/env python3
"""
ROS2 cmd_vel 到机器狗适配器的桥接器。

这个脚本订阅 ROS2 的 cmd_vel 话题，并将速度命令转发给 BotDog 的 UnitreeB2Adapter。
它使用 BotDog 的 robot_adapter 模块，支持异步速度控制。

使用方法：
    python3 ros2_cmd_vel_to_adapter.py [--network-interface eno1] [--adapter unitree_b2|simulation]

参数：
    --network-interface: 网络接口名称（默认: eno1）
    --adapter: 适配器类型（默认: unitree_b2）
"""

import sys
import argparse
import asyncio
import time
import threading
from typing import Optional

# 添加项目根目录到路径
import os
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

# 尝试导入 ROS2
try:
    import rclpy
    from rclpy.node import Node
    from geometry_msgs.msg import Twist
    ROS2_AVAILABLE = True
except ImportError:
    ROS2_AVAILABLE = False
    print("错误: rclpy 未安装，无法使用 ROS2 功能")
    print("请安装 ROS2: sudo apt install ros-humble-desktop 或 pip install rclpy")
    sys.exit(1)

# 导入 BotDog 的适配器
try:
    from BotDog.backend.robot_adapter import create_adapter, BaseRobotAdapter
    BOTDOG_ADAPTER_AVAILABLE = True
except ImportError as e:
    BOTDOG_ADAPTER_AVAILABLE = False
    print(f"错误: 无法导入 BotDog 适配器: {e}")
    print(f"导入路径: {sys.path}")
    sys.exit(1)


class ROS2CmdVelToAdapter(Node):
    """
    ROS2 cmd_vel 到适配器的桥接节点。
    
    这个节点订阅 ROS2 的 cmd_vel 话题，并将速度命令转发给 BotDog 的适配器。
    """
    
    def __init__(self, adapter_type: str = "unitree_b2", network_interface: str = "eno1"):
        """
        初始化桥接节点。
        
        Args:
            adapter_type: 适配器类型（"unitree_b2" 或 "simulation"）
            network_interface: 网络接口名称
        """
        super().__init__('ros2_cmd_vel_to_adapter')
        
        self.adapter_type = adapter_type
        self.network_interface = network_interface
        
        # 创建适配器
        try:
            self.adapter = create_adapter(
                adapter_type, 
                network_interface=network_interface
            )
            print(f"适配器创建成功: {adapter_type} (网卡: {network_interface})")
        except Exception as e:
            print(f"创建适配器失败: {e}")
            sys.exit(1)
        
        # 创建订阅者
        self.subscription = self.create_subscription(
            Twist,
            'cmd_vel',
            self.cmd_vel_callback,
            10
        )
        
        # 超时检查定时器
        self.last_cmd_time = time.time()
        self.timeout = 0.5  # 超时时间（秒）
        self.timer = self.create_timer(0.1, self.timeout_check_callback)
        
        # 异步事件循环
        self.loop = asyncio.new_event_loop()
        self.loop_thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self.loop_thread.start()
        
        print(f"ROS2 cmd_vel 到适配器桥接器已启动")
        print(f"  适配器类型: {adapter_type}")
        print(f"  网络接口: {network_interface}")
        print(f"  订阅话题: cmd_vel")
        print("等待 cmd_vel 消息...")
    
    def cmd_vel_callback(self, msg: Twist):
        """
        处理 cmd_vel 消息回调。
        
        Args:
            msg: ROS2 Twist 消息
        """
        vx = msg.linear.x
        vy = msg.linear.y
        vyaw = msg.angular.z
        
        # 打印接收到的命令
        print(f"收到速度命令: vx={vx:.2f}, vy={vy:.2f}, vyaw={vyaw:.2f}")
        
        # 更新最后命令时间
        self.last_cmd_time = time.time()
        
        # 检查适配器是否支持速度控制
        if hasattr(self.adapter, 'send_velocity'):
            # 在异步事件循环中发送速度命令
            asyncio.run_coroutine_threadsafe(
                self.adapter.send_velocity(vx, vy, vyaw),
                self.loop
            )
        else:
            # 适配器不支持速度控制，使用离散命令
            print(f"警告: 适配器不支持速度控制，使用离散命令")
            self._send_discrete_command(vx, vy, vyaw)
    
    def _send_discrete_command(self, vx: float, vy: float, vyaw: float):
        """
        发送离散命令（当适配器不支持速度控制时使用）。
        
        Args:
            vx: 前进/后退速度
            vy: 横向平移速度
            vyaw: 偏航转速
        """
        cmd = None
        
        # 根据速度值选择命令
        if abs(vx) > 0.1:
            if vx > 0:
                cmd = "forward"
            else:
                cmd = "backward"
        elif abs(vyaw) > 0.1:
            if vyaw > 0:
                cmd = "left"
            else:
                cmd = "right"
        elif abs(vy) > 0.1:
            if vy > 0:
                cmd = "strafe_left"
            else:
                cmd = "strafe_right"
        else:
            cmd = "stop"
        
        if cmd:
            asyncio.run_coroutine_threadsafe(
                self.adapter.send_command(cmd),
                self.loop
            )
    
    def timeout_check_callback(self):
        """
        超时检查回调。
        
        如果超过超时时间没有收到命令，则停止机器人。
        """
        if time.time() - self.last_cmd_time > self.timeout:
            # 发送停止命令
            if hasattr(self.adapter, 'send_velocity'):
                asyncio.run_coroutine_threadsafe(
                    self.adapter.send_velocity(0.0, 0.0, 0.0),
                    self.loop
                )
            else:
                asyncio.run_coroutine_threadsafe(
                    self.adapter.send_command("stop"),
                    self.loop
                )
            self.last_cmd_time = time.time()  # 重置避免重复停止
    
    def _run_event_loop(self):
        """运行异步事件循环（在单独的线程中）。"""
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()
    
    def shutdown(self):
        """关闭节点和适配器。"""
        print("正在关闭桥接器...")
        
        # 停止机器人
        try:
            if hasattr(self.adapter, 'send_velocity'):
                asyncio.run_coroutine_threadsafe(
                    self.adapter.send_velocity(0.0, 0.0, 0.0),
                    self.loop
                ).result(timeout=1.0)
            else:
                asyncio.run_coroutine_threadsafe(
                    self.adapter.send_command("stop"),
                    self.loop
                ).result(timeout=1.0)
        except:
            pass
        
        # 停止事件循环
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.loop_thread.join(timeout=2.0)
        
        print("桥接器已关闭")


def main():
    """主函数。"""
    parser = argparse.ArgumentParser(description='ROS2 cmd_vel 到机器狗适配器的桥接器')
    parser.add_argument('--network-interface', type=str, default='eno1',
                       help='网络接口名称（默认: eno1）')
    parser.add_argument('--adapter', type=str, default='unitree_b2',
                       choices=['unitree_b2', 'simulation'],
                       help='适配器类型: unitree_b2 (宇树 B2 真实硬件) 或 simulation (模拟模式)')
    
    args = parser.parse_args()
    
    # 检查 ROS2 是否可用
    if not ROS2_AVAILABLE:
        print("错误: ROS2 (rclpy) 不可用")
        sys.exit(1)
    
    # 检查 BotDog 适配器是否可用
    if not BOTDOG_ADAPTER_AVAILABLE:
        print("错误: BotDog 适配器不可用")
        sys.exit(1)
    
    print(f"启动 ROS2 cmd_vel 到适配器桥接器")
    print(f"  适配器: {args.adapter}")
    print(f"  网络接口: {args.network_interface}")
    
    # 初始化 ROS2
    rclpy.init()
    
    node = None
    try:
        # 创建节点
        node = ROS2CmdVelToAdapter(args.adapter, args.network_interface)
        
        # 运行节点
        rclpy.spin(node)
        
    except KeyboardInterrupt:
        print("\n收到中断信号，正在关闭...")
    except Exception as e:
        print(f"运行桥接器时发生错误: {e}")
    finally:
        # 关闭节点
        if node:
            node.shutdown()
            node.destroy_node()
        
        # 关闭 ROS2
        try:
            rclpy.shutdown()
        except:
            pass
        
        print("程序已退出")


if __name__ == '__main__':
    main()
