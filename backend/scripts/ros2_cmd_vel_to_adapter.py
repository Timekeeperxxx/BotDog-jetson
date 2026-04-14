#!/usr/bin/env python3
"""
ROS2 cmd_vel 到 UnitreeB2Adapter 的桥接脚本。

订阅 ROS2 的 /cmd_vel 话题，并将速度命令转发给 UnitreeB2Adapter。
支持超时自动停止功能。

使用方法：
    python3 ros2_cmd_vel_to_adapter.py [--network-interface eno1] [--timeout 0.5]
"""

import sys
import os
import argparse
import time
import threading
import asyncio
from typing import Optional

# 添加项目根目录到路径
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

# 尝试导入 BotDog 的适配器
try:
    from BotDog.backend.robot_adapter import UnitreeB2Adapter
    ADAPTER_AVAILABLE = True
except ImportError as e:
    ADAPTER_AVAILABLE = False
    print(f"错误: 无法导入 UnitreeB2Adapter: {e}")
    sys.exit(1)


class CmdVelToAdapterBridge(Node):
    """
    ROS2 cmd_vel 到 UnitreeB2Adapter 的桥接节点。
    
    订阅 /cmd_vel 话题，将速度命令转发给 UnitreeB2Adapter。
    支持超时自动停止功能。
    """
    
    def __init__(
        self,
        network_interface: str = "eno1",
        timeout: float = 0.5,
        vx_scale: float = 1.0,
        vy_scale: float = 1.0,
        vyaw_scale: float = 1.0
    ):
        """
        初始化桥接节点。
        
        Args:
            network_interface: 网络接口名称 (默认: eno1)
            timeout: 超时时间（秒），超过此时间未收到命令则自动停止 (默认: 0.5)
            vx_scale: x轴速度缩放因子 (默认: 1.0)
            vy_scale: y轴速度缩放因子 (默认: 1.0)
            vyaw_scale: 偏航角速度缩放因子 (默认: 1.0)
        """
        super().__init__('cmd_vel_to_adapter_bridge')
        
        self.network_interface = network_interface
        self.timeout = timeout
        self.vx_scale = vx_scale
        self.vy_scale = vy_scale
        self.vyaw_scale = vyaw_scale
        
        # 初始化适配器
        print(f"初始化 UnitreeB2Adapter，网络接口: {network_interface}")
        try:
            self.adapter = UnitreeB2Adapter(network_interface=network_interface)
            if not self.adapter._initialized:
                print("错误: UnitreeB2Adapter 初始化失败")
                sys.exit(1)
        except Exception as e:
            print(f"错误: 创建 UnitreeB2Adapter 失败: {e}")
            sys.exit(1)
        
        # 创建订阅者
        self.subscription = self.create_subscription(
            Twist,
            'cmd_vel',
            self.cmd_vel_callback,
            10
        )
        
        # 记录最后收到命令的时间
        self.last_cmd_time = time.time()
        
        # 创建超时检查定时器
        self.timer = self.create_timer(0.1, self.timeout_check_callback)
        
        # 创建异步事件循环
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        print(f"ROS2 cmd_vel 到 UnitreeB2Adapter 桥接器已启动")
        print(f"网络接口: {network_interface}")
        print(f"超时时间: {timeout} 秒")
        print(f"速度缩放: vx_scale={vx_scale}, vy_scale={vy_scale}, vyaw_scale={vyaw_scale}")
        print("等待 /cmd_vel 消息...")
    
    def cmd_vel_callback(self, msg: Twist):
        """
        处理 cmd_vel 消息回调。
        
        Args:
            msg: ROS2 Twist 消息
        """
        # 提取速度值
        vx = msg.linear.x * self.vx_scale
        vy = msg.linear.y * self.vy_scale
        vyaw = msg.angular.z * self.vyaw_scale
        
        # 更新最后收到命令的时间
        self.last_cmd_time = time.time()
        
        # 打印接收到的命令
        self.get_logger().debug(
            f"收到速度命令: vx={vx:.3f}, vy={vy:.3f}, vyaw={vyaw:.3f}"
        )
        
        # 发送速度命令到适配器
        self.send_velocity_to_adapter(vx, vy, vyaw)
    
    def send_velocity_to_adapter(self, vx: float, vy: float, vyaw: float):
        """
        发送速度命令到 UnitreeB2Adapter。
        
        Args:
            vx: x轴速度 (m/s)
            vy: y轴速度 (m/s)
            vyaw: 偏航角速度 (rad/s)
        """
        try:
            # 在异步事件循环中运行
            if self.loop.is_running():
                # 如果事件循环已经在运行，创建任务
                asyncio.create_task(self.adapter.send_velocity(vx, vy, vyaw))
            else:
                # 否则运行直到完成
                self.loop.run_until_complete(self.adapter.send_velocity(vx, vy, vyaw))
        except Exception as e:
            self.get_logger().error(f"发送速度命令失败: {e}")
    
    def timeout_check_callback(self):
        """超时检查回调，如果超时则停止机器人"""
        current_time = time.time()
        if current_time - self.last_cmd_time > self.timeout:
            # 超时，停止机器人
            self.get_logger().debug("超时，停止机器人")
            try:
                if self.loop.is_running():
                    asyncio.create_task(self.adapter.stop())
                else:
                    self.loop.run_until_complete(self.adapter.stop())
            except Exception as e:
                self.get_logger().error(f"停止机器人失败: {e}")
            
            # 重置最后命令时间，避免重复停止
            self.last_cmd_time = current_time
    
    def shutdown(self):
        """关闭节点，停止机器人"""
        print("正在关闭节点...")
        try:
            # 停止机器人
            if self.loop.is_running():
                asyncio.create_task(self.adapter.stop())
            else:
                self.loop.run_until_complete(self.adapter.stop())
        except Exception as e:
            print(f"停止机器人失败: {e}")
        
        # 关闭事件循环
        if self.loop.is_running():
            self.loop.stop()
        
        print("节点已关闭")


def main():
    parser = argparse.ArgumentParser(
        description='ROS2 cmd_vel 到 UnitreeB2Adapter 的桥接脚本'
    )
    parser.add_argument(
        '--network-interface',
        type=str,
        default='eno1',
        help='网络接口名称 (默认: eno1)'
    )
    parser.add_argument(
        '--timeout',
        type=float,
        default=0.5,
        help='超时时间（秒），超过此时间未收到命令则自动停止 (默认: 0.5)'
    )
    parser.add_argument(
        '--vx-scale',
        type=float,
        default=1.0,
        help='x轴速度缩放因子 (默认: 1.0)'
    )
    parser.add_argument(
        '--vy-scale',
        type=float,
        default=1.0,
        help='y轴速度缩放因子 (默认: 1.0)'
    )
    parser.add_argument(
        '--vyaw-scale',
        type=float,
        default=1.0,
        help='偏航角速度缩放因子 (默认: 1.0)'
    )
    parser.add_argument(
        '--ros-domain-id',
        type=int,
        default=0,
        help='ROS2 域 ID (默认: 0)'
    )
    
    args = parser.parse_args()
    
    # 设置 ROS 域 ID
    os.environ['ROS_DOMAIN_ID'] = str(args.ros_domain_id)
    
    print("=" * 60)
    print("ROS2 cmd_vel 到 UnitreeB2Adapter 桥接器")
    print("=" * 60)
    print(f"网络接口: {args.network_interface}")
    print(f"超时时间: {args.timeout} 秒")
    print(f"速度缩放: vx_scale={args.vx_scale}, vy_scale={args.vy_scale}, vyaw_scale={args.vyaw_scale}")
    print(f"ROS 域 ID: {args.ros_domain_id}")
    print("=" * 60)
    
    # 初始化 ROS2
    rclpy.init()
    
    # 创建节点
    node = None
    try:
        node = CmdVelToAdapterBridge(
            network_interface=args.network_interface,
            timeout=args.timeout,
            vx_scale=args.vx_scale,
            vy_scale=args.vy_scale,
            vyaw_scale=args.vyaw_scale
        )
        
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
        rclpy.shutdown()
        
        print("桥接器已关闭")


if __name__ == '__main__':
    main()
