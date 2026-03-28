import sys
import asyncio
import time
from loguru import logger

# 导入项目中已有代码
from test_sbus_receiver import SBUSReceiver

import queue
import threading

def map_joystick(raw_val: int, max_speed: float, reverse: bool = False) -> float:
    """
    将 SBUS 原始值 (0-2047) 映射为实际速度
    中位假设为 1024，死区 100
    """
    center = 1024
    deadband = 100
    
    if abs(raw_val - center) < deadband:
        return 0.0
        
    if raw_val > center:
        # 上半区: mapped to 0 ~ 1.0
        pct = (raw_val - (center + deadband)) / (2047 - (center + deadband))
    else:
        # 下半区: mapped to -1.0 ~ 0
        pct = -((center - deadband) - raw_val) / (center - deadband)
        
    pct = max(-1.0, min(1.0, pct))
    if reverse:
        pct = -pct
    return round(pct * max_speed, 3)

class B2SbusController:
    def __init__(self, port: str):
        self.port = port
        self.receiver = SBUSReceiver(port=self.port, baudrate=100000, invert=False)
        self.sport_client = None
        self.dog_ready = False
        
        # 最大线速度和角速度（安全范围）
        self.MAX_VX = 0.5  # 前后 m/s
        self.MAX_VY = 0.3  # 左右横移 m/s
        self.MAX_VYAW = 0.8 # 旋转 rad/s

    def init_dog(self):
        """初始化宇树狗子 DDS"""
        try:
            from unitree_sdk2py.core.channel import ChannelFactoryInitialize
            from unitree_sdk2py.b2.sport.sport_client import SportClient
            from unitree_sdk2py.comm.motion_switcher.motion_switcher_client import MotionSwitcherClient
            
            logger.info("正在初始化 B2 SDK...")
            try:
                ChannelFactoryInitialize(0, "eth0")
            except Exception as e:
                logger.warning(f"DDS 可能已初始化: {e}")
                
            msc = MotionSwitcherClient()
            msc.SetTimeout(5.0)
            msc.Init()
            
            code, data = msc.CheckMode()
            if code == 0 and data and data.get("name") != "ai":
                logger.info("切换到 AI 运控模式...")
                msc.SelectMode("ai")
                time.sleep(2.0)
                
            self.sport_client = SportClient()
            self.sport_client.SetTimeout(1.5)
            self.sport_client.Init()
            
            logger.info("解锁机器人并站立...")
            self.sport_client.BalanceStand()
            time.sleep(0.5)
            self.sport_client.SwitchMoveMode(True)
            
            self.dog_ready = True
            logger.info("宇树 B2 初始化完成，等待遥控器信号...")
            
        except ImportError:
             logger.error("未安装 unitree_sdk2_python，将仅测试 SBUS 解析不发指令！")
        except Exception as e:
             logger.error(f"狗子初始化失败: {e}")

    async def run(self):
        if not self.receiver.connect():
            logger.error("无法连接 SBUS 接收器")
            return
            
        self.init_dog()
        
        try:
            logger.info(">> 开始接收 SBUS，按 Ctrl+C 停止 <<")
            
            # 定时打印，防止日志刷屏
            last_log_time = time.time()
            
            while True:
                result = self.receiver.read_frame()
                if result:
                    channels, flags, _ = result
                    
                    # 通道映射 (基于美国手标准，可能需要根据您的真实手感调整)
                    # CH1 (Index 0): 右摇杆 左右 (Roll)   -> 横移 VY
                    # CH2 (Index 1): 右摇杆 上下 (Pitch)  -> 前后 VX
                    # CH3 (Index 2): 左摇杆 上下 (Throt)  -> (预留)
                    # CH4 (Index 3): 左摇杆 左右 (Yaw)    -> 旋转 VYAW
                    
                    # 注意：有些遥控器推到底数值是反的，如果有反向，把对应通道 reverse 设为 True
                    vx = map_joystick(channels[1], self.MAX_VX, reverse=False)
                    vy = -map_joystick(channels[0], self.MAX_VY, reverse=False) # 通常右摇向左是负值
                    vyaw = -map_joystick(channels[3], self.MAX_VYAW, reverse=False)

                    if time.time() - last_log_time > 0.5:
                        logger.info(f"SBUS -> [VX(前后): {vx: .2f}] [VY(横移): {vy: .2f}] [VYAW(转向): {vyaw: .2f}]")
                        last_log_time = time.time()

                    if self.dog_ready and self.sport_client:
                        # 持续将速度发给 B2
                        self.sport_client.Move(vx, vy, vyaw)
                        
                # 稍微让出 CPU
                await asyncio.sleep(0.001)

        except KeyboardInterrupt:
            logger.info("测试结束，停止指令")
            if self.dog_ready and self.sport_client:
                self.sport_client.StopMove()
        finally:
            self.receiver.disconnect()

async def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyS2"
    logger.info(f"使用串口: {port}")
    controller = B2SbusController(port=port)
    await controller.run()

if __name__ == "__main__":
    asyncio.run(main())
