#!/usr/bin/env python3
"""
订阅 /cmd_vel 话题，通过 unitree_sdk2py 的 SportClient 直接控制机器狗行走。

使用方式：
    source /opt/ros/humble/setup.bash
    cd /home/jetson/Project/BOTDOG/BotDog/backend
    python3 cmd_vel_controller.py

依赖：
    - ROS2 Humble (rclpy)
    - unitree_sdk2_python (pip install unitree_sdk2_python)
    - 网线连接 B2 机器狗（默认 IP 192.168.123.161，网卡 eno1）
"""

import rclpy
import sys
import time
import signal
from geometry_msgs.msg import Twist


class UnitreeB2DirectController:
    """
    直接使用 unitree_sdk2py 的 SportClient 控制宇树 B2 机器狗。
    不依赖 robot_adapter.py，避免相对导入问题。
    """

    def __init__(self, network_interface: str = "eno1"):
        self._sport_client = None
        self._initialized = False
        self._network_interface = network_interface

    def init(self):
        """初始化 DDS 通道和 SportClient"""
        try:
            from unitree_sdk2py.core.channel import ChannelFactoryInitialize
            from unitree_sdk2py.b2.sport.sport_client import SportClient
            from unitree_sdk2py.comm.motion_switcher.motion_switcher_client import MotionSwitcherClient

            # 初始化 DDS 频道
            try:
                ChannelFactoryInitialize(0, self._network_interface)
                print(f"[UnitreeB2] DDS 频道初始化成功 (网卡: {self._network_interface})")
            except Exception as e:
                err_msg = str(e).lower()
                if "create domain error" in err_msg:
                    print(f"[UnitreeB2] 错误: DDS domain 初始化失败 - {e}")
                    print("可能原因: 有其他进程占用 DDS 端口，请先 pkill -f run_backend.py")
                    return False
                print(f"[UnitreeB2] DDS 频道初始化跳过: {e}")

            # Step 1: 切换到 AI 运控模式
            try:
                msc = MotionSwitcherClient()
                msc.SetTimeout(5.0)
                msc.Init()
                code, data = msc.CheckMode()
                current_mode = data.get("name", "unknown") if data else "unknown"
                print(f"[UnitreeB2] 当前运控模式: {current_mode} (code={code})")
                if code == 0 and current_mode != "ai":
                    print("[UnitreeB2] 正在切换到 AI 运控模式...")
                    sel_code, _ = msc.SelectMode("ai")
                    if sel_code == 0:
                        print("[UnitreeB2] 已切换到 AI 运控模式")
                        time.sleep(2.0)
                    else:
                        print(f"[UnitreeB2] AI 模式切换失败: code={sel_code}")
            except Exception as e:
                print(f"[UnitreeB2] MotionSwitcher 初始化跳过: {e}")

            # Step 2: 初始化 SportClient
            self._sport_client = SportClient()
            self._sport_client.SetTimeout(1.5)
            self._sport_client.Init()
            self._initialized = True
            print("[UnitreeB2] SportClient 初始化成功")
            return True

        except ImportError:
            print("[UnitreeB2] 错误: unitree_sdk2_python 未安装")
            print("请运行: pip install unitree_sdk2_python")
            return False
        except Exception as e:
            print(f"[UnitreeB2] 初始化失败: {e}")
            return False

    def is_ready(self):
        return self._initialized

    def stand_up(self):
        """让机器狗站立"""
        if not self._initialized or self._sport_client is None:
            print("[UnitreeB2] 适配器未就绪，无法站立")
            return False
        try:
            print("[UnitreeB2] 正在让机器狗站立...")
            ret = self._sport_client.BalanceStand()
            print(f"[UnitreeB2] BalanceStand ret={ret}")
            time.sleep(2.0)
            # 切换到运动模式
            for attempt in range(5):
                ret_mm = self._sport_client.SwitchMoveMode(True)
                print(f"[UnitreeB2] SwitchMoveMode(True) ret={ret_mm} (attempt {attempt+1})")
                if ret_mm == 0:
                    break
                time.sleep(0.5)
            print("[UnitreeB2] 机器狗已站立")
            return True
        except Exception as e:
            print(f"[UnitreeB2] 站立失败: {e}")
            return False

    def stand_down(self):
        """让机器狗坐下"""
        if not self._initialized or self._sport_client is None:
            return
        try:
            print("[UnitreeB2] 正在让机器狗坐下...")
            self._sport_client.StopMove()
            time.sleep(0.3)
            ret = self._sport_client.StandDown()
            print(f"[UnitreeB2] StandDown ret={ret}")
            time.sleep(1.0)
        except Exception as e:
            print(f"[UnitreeB2] 坐下失败: {e}")

    def move(self, vx: float, vy: float, vyaw: float):
        """发送速度命令"""
        if not self._initialized or self._sport_client is None:
            return
        try:
            # 限制速度范围
            vx = max(-0.6, min(0.6, vx))
            vy = max(-0.4, min(0.4, vy))
            vyaw = max(-0.8, min(0.8, vyaw))
            self._sport_client.Move(vx, vy, vyaw)
        except Exception as e:
            print(f"[UnitreeB2] 速度命令失败: {e}")

    def stop(self):
        """停止运动"""
        if not self._initialized or self._sport_client is None:
            return
        try:
            ret = self._sport_client.StopMove()
            if ret != 0:
                self._sport_client.Move(0.0, 0.0, 0.0)
        except Exception as e:
            print(f"[UnitreeB2] 停止失败: {e}")

    def close(self):
        """释放资源"""
        self._initialized = False
        self._sport_client = None
        print("[UnitreeB2] 资源已释放")


def cmd_vel_callback(dog, last_cmd_time, msg):
    """收到 /cmd_vel 消息时调用"""
    vx = msg.linear.x
    vy = msg.linear.y
    vyaw = msg.angular.z

    print(f"收到 cmd_vel: vx={vx:.2f}, vy={vy:.2f}, vyaw={vyaw:.2f}")

    last_cmd_time[0] = time.time()
    dog.move(vx, vy, vyaw)


def main():
    # 先初始化 rclpy
    rclpy.init()
    node = rclpy.create_node('cmd_vel_controller')

    # 再初始化机器狗控制器（在 rclpy 之后初始化 DDS，避免冲突）
    dog = UnitreeB2DirectController(network_interface="eno1")
    if not dog.init():
        node.get_logger().error("机器狗控制器初始化失败")
        rclpy.shutdown()
        sys.exit(1)

    # 让机器狗站立
    node.get_logger().info("正在让机器狗站立...")
    dog.stand_up()
    node.get_logger().info("机器狗已站立，准备接收速度指令")

    # 订阅 /cmd_vel
    last_cmd_time = [time.time()]

    def callback(msg):
        cmd_vel_callback(dog, last_cmd_time, msg)

    sub = node.create_subscription(
        Twist,
        '/cmd_vel',
        callback,
        10
    )

    # 超时检测
    def check_timeout():
        if time.time() - last_cmd_time[0] > 1.0:
            dog.stop()

    timer = node.create_timer(0.5, check_timeout)

    node.get_logger().info("=" * 50)
    node.get_logger().info("cmd_vel_controller 已启动")
    node.get_logger().info("等待 /cmd_vel 消息...")
    node.get_logger().info("=" * 50)

    # 处理 Ctrl+C
    shutdown_requested = False

    def signal_handler(sig, frame):
        nonlocal shutdown_requested
        shutdown_requested = True

    signal.signal(signal.SIGINT, signal_handler)

    try:
        while rclpy.ok() and not shutdown_requested:
            rclpy.spin_once(node, timeout_sec=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        node.get_logger().info("正在停止机器狗...")
        dog.stop()
        time.sleep(0.5)
        dog.stand_down()
        dog.close()
        node.destroy_node()
        rclpy.shutdown()
        node.get_logger().info("已退出")


if __name__ == '__main__':
    main()
