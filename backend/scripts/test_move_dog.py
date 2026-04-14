#!/usr/bin/env python3
"""
测试机器狗移动脚本
发送简单的速度命令让机器狗移动
"""

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
import time

def test_move_dog():
    """测试移动机器狗"""
    rclpy.init()
    
    # 创建节点
    node = Node('test_move_dog')
    publisher = node.create_publisher(Twist, '/cmd_vel', 10)
    
    print("测试机器狗移动...")
    print("注意：确保机器狗已开机并处于安全位置")
    
    # 等待发布者建立连接
    time.sleep(1)
    
    try:
        # 测试1：向前移动
        print("\n1. 向前移动 (0.2 m/s, 2秒)")
        twist = Twist()
        twist.linear.x = 0.2
        twist.linear.y = 0.0
        twist.angular.z = 0.0
        
        for i in range(20):  # 2秒
            publisher.publish(twist)
            time.sleep(0.1)
        
        # 停止
        print("停止")
        twist.linear.x = 0.0
        publisher.publish(twist)
        time.sleep(1)
        
        # 测试2：旋转
        print("\n2. 旋转 (0.3 rad/s, 2秒)")
        twist.angular.z = 0.3
        
        for i in range(20):  # 2秒
            publisher.publish(twist)
            time.sleep(0.1)
        
        # 停止
        print("停止")
        twist.angular.z = 0.0
        publisher.publish(twist)
        time.sleep(1)
        
        # 测试3：向后移动
        print("\n3. 向后移动 (-0.15 m/s, 2秒)")
        twist.linear.x = -0.15
        
        for i in range(20):  # 2秒
            publisher.publish(twist)
            time.sleep(0.1)
        
        # 停止
        print("停止")
        twist.linear.x = 0.0
        publisher.publish(twist)
        time.sleep(1)
        
        print("\n测试完成！")
        
    except KeyboardInterrupt:
        print("\n测试被中断")
    finally:
        # 确保停止
        twist = Twist()
        publisher.publish(twist)
        time.sleep(0.5)
        
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    test_move_dog()
