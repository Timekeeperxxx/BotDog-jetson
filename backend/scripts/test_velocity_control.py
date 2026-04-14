#!/usr/bin/env python3
"""
测试速度控制脚本。

测试 UnitreeB2Adapter 的 send_velocity 方法。
"""

import asyncio
import time
import sys
import os

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from BotDog.backend.robot_adapter import create_adapter


async def test_velocity_control():
    """测试速度控制"""
    print("测试速度控制...")
    print("注意：确保机器狗已开机并处于安全位置")
    
    try:
        # 创建适配器
        adapter = create_adapter("unitree_b2", network_interface="eno1")
        
        # 等待适配器初始化
        await asyncio.sleep(2)
        
        print("\n1. 向前移动 (vx=0.2 m/s)")
        await adapter.send_velocity(0.2, 0.0, 0.0)
        await asyncio.sleep(2)
        
        print("停止")
        await adapter.send_velocity(0.0, 0.0, 0.0)
        await asyncio.sleep(1)
        
        print("\n2. 旋转 (vyaw=0.3 rad/s)")
        await adapter.send_velocity(0.0, 0.0, 0.3)
        await asyncio.sleep(2)
        
        print("停止")
        await adapter.send_velocity(0.0, 0.0, 0.0)
        await asyncio.sleep(1)
        
        print("\n3. 向后移动 (vx=-0.15 m/s)")
        await adapter.send_velocity(-0.15, 0.0, 0.0)
        await asyncio.sleep(2)
        
        print("停止")
        await adapter.send_velocity(0.0, 0.0, 0.0)
        await asyncio.sleep(1)
        
        print("\n4. 横向移动 (vy=0.2 m/s)")
        await adapter.send_velocity(0.0, 0.2, 0.0)
        await asyncio.sleep(2)
        
        print("停止")
        await adapter.send_velocity(0.0, 0.0, 0.0)
        await asyncio.sleep(1)
        
        print("\n5. 组合运动 (vx=0.1, vy=0.1, vyaw=0.2)")
        await adapter.send_velocity(0.1, 0.1, 0.2)
        await asyncio.sleep(2)
        
        print("停止")
        await adapter.send_velocity(0.0, 0.0, 0.0)
        
        print("\n测试完成！")
        
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_velocity_control())
