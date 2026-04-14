#!/usr/bin/env python3
"""
测试 ROS2 cmd_vel 消息发布器。

这个脚本发布测试速度命令到 cmd_vel 话题，用于测试桥接器。
"""

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
import time
import sys

class CmdVelPublisher(Node):
    def __init__(self):
        super().__init__('test_cmd_vel_publisher')
        self.publisher = self.create_publisher(Twist, 'cmd_vel', 10)
        self.timer = self.create_timer(0.5, self.timer_callback)
        self.count = 0
        
    def timer_callback(self):
        msg = Twist()
        
        # 发布不同的速度模式
        if self.count % 4 == 0:
            # 前进
            msg.linear.x = 0.1
            msg.linear.y = 0.0
            msg.angular.z = 0.0
            print(f"[{self.count}] 发布: 前进 vx=0.2")
        elif self.count % 4 == 1:
            # 后退
            msg.linear.x = -0.1
            msg.linear.y = 0.0
            msg.angular.z = 0.0
            print(f"[{self.count}] 发布: 后退 vx=-0.2")
        elif self.count % 4 == 2:
            # 左转
            msg.linear.x = 0.0
            msg.linear.y = 0.0
            msg.angular.z = 0.1
            print(f"[{self.count}] 发布: 左转 vyaw=0.3")
        else:
            # 右转
            msg.linear.x = 0.0
            msg.linear.y = 0.0
            msg.angular.z = -0.1
            print(f"[{self.count}] 发布: 右转 vyaw=-0.3")
        
        self.publisher.publish(msg)
        self.count += 1
        
        # 测试10次后停止
        if self.count >= 10:
            print("测试完成，发布停止命令")
            msg.linear.x = 0.0
            msg.linear.y = 0.0
            msg.angular.z = 0.0
            self.publisher.publish(msg)
            self.get_logger().info('测试完成')
            rclpy.shutdown()

def main():
    rclpy.init()
    
    try:
        node = CmdVelPublisher()
        print("开始发布测试速度命令到 cmd_vel 话题...")
        print("按 Ctrl+C 停止")
        rclpy.spin(node)
    except KeyboardInterrupt:
        print("用户中断")
    finally:
        if rclpy.ok():
            rclpy.shutdown()
        print("发布器已关闭")

if __name__ == '__main__':
    main()
