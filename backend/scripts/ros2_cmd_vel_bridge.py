#!/usr/bin/env python3
"""
ROS2 cmd_vel 桥接器。

订阅 ROS2 的 cmd_vel 话题，并将速度命令转发给机器狗适配器。
支持三种模式：
1. 使用 UnitreeB2Adapter（集成到 BotDog 项目）
2. 直接使用 SportClient（独立模式）
3. 模拟模式（仅打印命令，不实际发送）

使用方法：
    python3 ros2_cmd_vel_bridge.py [--adapter unitree_b2|direct|simulation] [--network-interface eno1]
"""

import sys
import argparse
import time
import threading
import queue
from typing import Optional

# 尝试导入 ROS2
try:
    import rclpy
    from rclpy.node import Node
    from geometry_msgs.msg import Twist
    ROS2_AVAILABLE = True
except ImportError:
    ROS2_AVAILABLE = False
    print("警告: rclpy 未安装，无法使用 ROS2 功能")
    print("请安装 ROS2: sudo apt install ros-humble-desktop 或 pip install rclpy")

# 尝试导入 unitree_sdk2_python
try:
    from unitree_sdk2py.core.channel import ChannelFactoryInitialize
    from unitree_sdk2py.idl.geometry_msgs.msg.dds_ import Twist_
    from unitree_sdk2py.b2.sport.sport_client import SportClient
    from unitree_sdk2py.comm.motion_switcher.motion_switcher_client import MotionSwitcherClient
    UNITREE_SDK_AVAILABLE = True
except ImportError:
    UNITREE_SDK_AVAILABLE = False
    print("警告: unitree_sdk2_python 未安装，无法直接控制机器狗")
    print("请安装: pip install unitree_sdk2_python")

# 尝试导入 BotDog 的适配器
try:
    # 添加项目根目录到路径
    import os
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.path.insert(0, project_root)
    
    # 现在可以导入 backend 模块
    from BotDog.backend.robot_adapter import create_adapter, BaseRobotAdapter
    BOTDOG_ADAPTER_AVAILABLE = True
except ImportError as e:
    BOTDOG_ADAPTER_AVAILABLE = False
    print(f"警告: 无法导入 BotDog 适配器: {e}")
    print(f"导入路径: {sys.path}")


class DirectSportClientController:
    """直接使用 SportClient 控制机器狗"""
    
    def __init__(self, network_interface="eno1"):
        self.network_interface = network_interface
        self.sport_client = None
        self.initialized = False
        self.last_cmd_time = time.time()
        self.timeout = 0.5  # 超时时间（秒）
        
        if not UNITREE_SDK_AVAILABLE:
            print("错误: unitree_sdk2_python 不可用")
            return
            
        self._init_sport_client()
    
    def _init_sport_client(self):
        """初始化 SportClient"""
        try:
            # 初始化 DDS 频道
            try:
                ChannelFactoryInitialize(0, self.network_interface)
            except Exception as e:
                if "create domain error" in str(e).lower() or "domain" in str(e).lower():
                    raise RuntimeError(f"DDS domain 初始化失败: {e}")
                # 其他异常视为已初始化
                print(f"DDS 已初始化: {e}")
            
            # 切换到 AI 运控模式
            msc = MotionSwitcherClient()
            msc.SetTimeout(5.0)
            msc.Init()
            
            code, data = msc.CheckMode()
            current_mode = data.get("name", "unknown") if data else "unknown"
            print(f"当前运控模式: {current_mode} (code={code})")
            
            if code == 0 and current_mode != "ai":
                print("切换到 AI 运控模式...")
                sel_code, _ = msc.SelectMode("ai")
                if sel_code == 0:
                    print("已切换到 ai 模式")
                    time.sleep(2.0)
                else:
                    print(f"模式切换失败 code={sel_code}，尝试继续")
            
            # 初始化 SportClient
            self.sport_client = SportClient()
            self.sport_client.SetTimeout(1.5)
            self.sport_client.Init()
            
            # 解锁运动模式
            ret_bs = self.sport_client.BalanceStand()
            print(f"BalanceStand ret={ret_bs}")
            time.sleep(0.5)
            ret_mm = self.sport_client.SwitchMoveMode(True)
            print(f"SwitchMoveMode(True) ret={ret_mm}")
            
            self.initialized = True
            print(f"SportClient 初始化成功（网卡={self.network_interface}）")
            
        except Exception as e:
            print(f"SportClient 初始化失败: {e}")
            self.initialized = False
    
    def send_velocity(self, vx: float, vy: float, vyaw: float):
        """发送速度命令"""
        if not self.initialized or self.sport_client is None:
            print("SportClient 未初始化，忽略命令")
            return
        
        try:
            # 检查速度范围
            vx = max(-0.6, min(0.6, vx))
            vy = max(-0.4, min(0.4, vy))
            vyaw = max(-0.8, min(0.8, vyaw))
            
            ret = self.sport_client.Move(vx, vy, vyaw)
            if ret != 0:
                print(f"发送速度命令失败，错误码: {ret}")
            
            self.last_cmd_time = time.time()
            
        except Exception as e:
            print(f"发送速度命令异常: {e}")
    
    def stop(self):
        """停止机器人"""
        if self.initialized and self.sport_client:
            self.sport_client.StopMove()
            print("停止机器人")
    
    def check_timeout(self):
        """检查是否超时，如果超时则停止机器人"""
        if time.time() - self.last_cmd_time > self.timeout:
            self.stop()
            self.last_cmd_time = time.time()  # 重置避免重复停止


class SimulationController:
    """模拟控制器，仅打印命令不实际发送"""
    
    def __init__(self, network_interface="eno1"):
        self.network_interface = network_interface
        self.initialized = True
        self.last_cmd_time = time.time()
        self.timeout = 0.5
        print(f"模拟控制器初始化（网卡={self.network_interface}）")
    
    def send_velocity(self, vx: float, vy: float, vyaw: float):
        """打印速度命令"""
        print(f"[模拟] 发送速度命令: vx={vx:.2f}, vy={vy:.2f}, vyaw={vyaw:.2f}")
        self.last_cmd_time = time.time()
    
    def stop(self):
        """停止机器人"""
        print("[模拟] 停止机器人")
    
    def check_timeout(self):
        """检查是否超时"""
        if time.time() - self.last_cmd_time > self.timeout:
            self.stop()
            self.last_cmd_time = time.time()


class ROS2CmdVelBridge(Node):
    """ROS2 cmd_vel 桥接节点"""
    
    def __init__(self, adapter_type="direct", network_interface="eno1"):
        super().__init__('cmd_vel_bridge')
        
        self.adapter_type = adapter_type
        self.network_interface = network_interface
        
        # 根据适配器类型初始化控制器
        self.controller = None
        if adapter_type == "direct":
            if UNITREE_SDK_AVAILABLE:
                self.controller = DirectSportClientController(network_interface)
            else:
                print("错误: unitree_sdk2_python 不可用，无法使用 direct 模式")
                sys.exit(1)
        elif adapter_type == "unitree_b2":
            if BOTDOG_ADAPTER_AVAILABLE:
                try:
                    self.controller = create_adapter("unitree_b2", network_interface=network_interface)
                    print("使用 UnitreeB2Adapter")
                except Exception as e:
                    print(f"创建 UnitreeB2Adapter 失败: {e}")
                    sys.exit(1)
            else:
                print("错误: BotDog 适配器不可用")
                sys.exit(1)
        elif adapter_type == "simulation":
            self.controller = SimulationController(network_interface)
            print("使用模拟模式")
        else:
            print(f"错误: 不支持的适配器类型: {adapter_type}")
            sys.exit(1)
        
        # 创建订阅者
        self.subscription = self.create_subscription(
            Twist,
            'cmd_vel',
            self.cmd_vel_callback,
            10
        )
        
        # 超时检查定时器
        self.timer = self.create_timer(0.1, self.timeout_check_callback)
        
        print(f"ROS2 cmd_vel 桥接器已启动，适配器类型: {adapter_type}")
        print("等待 cmd_vel 消息...")
    
    def cmd_vel_callback(self, msg):
        """处理 cmd_vel 消息"""
        vx = msg.linear.x
        vy = msg.linear.y
        vyaw = msg.angular.z
        
        print(f"收到速度命令: vx={vx:.2f}, vy={vy:.2f}, vyaw={vyaw:.2f}")
        
        if self.adapter_type == "direct":
            # 直接使用 SportClient
            self.controller.send_velocity(vx, vy, vyaw)
        elif self.adapter_type == "unitree_b2":
            # 使用 BotDog 适配器
            if hasattr(self.controller, 'send_velocity'):
                # 适配器有 send_velocity 方法
                # 创建异步任务来发送速度命令
                import asyncio
                
                # 检查是否已经有事件循环在运行
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    # 如果没有事件循环，创建一个新的
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                
                # 创建异步任务
                async def send_velocity_async():
                    try:
                        await self.controller.send_velocity(vx, vy, vyaw)
                    except Exception as e:
                        print(f"发送速度命令失败: {e}")
                
                # 在事件循环中运行任务
                if loop.is_running():
                    # 如果事件循环已经在运行，创建任务
                    asyncio.create_task(send_velocity_async())
                else:
                    # 否则运行直到完成
                    loop.run_until_complete(send_velocity_async())
            else:
                # 回退到直接控制
                print("警告: UnitreeB2Adapter 不支持速度控制，使用直接控制")
                if UNITREE_SDK_AVAILABLE:
                    # 临时创建直接控制器
                    if not hasattr(self, '_direct_controller'):
                        self._direct_controller = DirectSportClientController(self.network_interface)
                    self._direct_controller.send_velocity(vx, vy, vyaw)
        elif self.adapter_type == "simulation":
            # 模拟模式
            self.controller.send_velocity(vx, vy, vyaw)
    
    def timeout_check_callback(self):
        """超时检查回调"""
        if self.controller:
            self.controller.check_timeout()


def main():
    parser = argparse.ArgumentParser(description='ROS2 cmd_vel 桥接器')
    parser.add_argument('--adapter', type=str, default='direct',
                       choices=['direct', 'unitree_b2', 'simulation'],
                       metavar='{direct,unitree_b2,simulation}',
                       help='适配器类型: direct (直接 SportClient), unitree_b2 (BotDog 适配器), 或 simulation (模拟模式)')
    parser.add_argument('--network-interface', type=str, default='eno1',
                       help='网络接口名称 (默认: eno1)')
    parser.add_argument('--use-dds-direct', action='store_true',
                       help='使用 DDS 直接订阅 (非 ROS2)')
    
    args = parser.parse_args()
    
    if args.use_dds_direct:
        # 使用 DDS 直接订阅模式 (非 ROS2)
        if not UNITREE_SDK_AVAILABLE:
            print("错误: unitree_sdk2_python 不可用")
            sys.exit(1)
        
        print(f"使用 DDS 直接订阅模式，网络接口: {args.network_interface}")
        run_dds_direct(args.network_interface)
    else:
        # 使用 ROS2 模式
        if not ROS2_AVAILABLE:
            print("错误: ROS2 (rclpy) 不可用")
            print("请安装 ROS2 或使用 --use-dds-direct 选项")
            sys.exit(1)
        
        print(f"使用 ROS2 模式，适配器: {args.adapter}，网络接口: {args.network_interface}")
        run_ros2_bridge(args.adapter, args.network_interface)


def run_dds_direct(network_interface):
    """运行 DDS 直接订阅模式"""
    from unitree_sdk2py.core.channel import ChannelSubscriber
    
    # 根据网络接口选择控制器
    controller = DirectSportClientController(network_interface)
    if not controller.initialized:
        print("控制器初始化失败，使用模拟模式")
        controller = SimulationController(network_interface)
    
    # 创建 DDS 订阅者
    try:
        sub = ChannelSubscriber("cmd_vel", Twist_)
        sub.Init()
        print("已订阅 DDS 话题: cmd_vel")
    except Exception as e:
        print(f"创建 DDS 订阅者失败: {e}")
        return
    
    print("开始接收速度命令，按 Ctrl+C 退出")
    try:
        while True:
            msg = sub.Read()
            if msg is not None:
                vx = msg.linear.x
                vy = msg.linear.y
                vyaw = msg.angular.z
                print(f"收到速度命令: vx={vx:.2f}, vy={vy:.2f}, vyaw={vyaw:.2f}")
                controller.send_velocity(vx, vy, vyaw)
            else:
                controller.check_timeout()
            
            time.sleep(0.01)
    except KeyboardInterrupt:
        print("正在退出...")
    finally:
        controller.stop()
        sub.Close()
        print("资源已释放")


def run_ros2_bridge(adapter_type, network_interface):
    """运行 ROS2 桥接模式"""
    rclpy.init()
    
    try:
        node = ROS2CmdVelBridge(adapter_type, network_interface)
        rclpy.spin(node)
    except KeyboardInterrupt:
        print("正在退出...")
    except Exception as e:
        print(f"运行桥接器时发生错误: {e}")
    finally:
        # 停止机器人
        try:
            if node and node.controller:
                node.controller.stop()
        except:
            pass
        
        try:
            node.destroy_node()
        except:
            pass
        
        try:
            rclpy.shutdown()
        except:
            pass
        
        print("ROS2 节点已关闭")


if __name__ == '__main__':
    main()
