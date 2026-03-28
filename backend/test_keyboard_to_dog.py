import sys
import termios
import tty
import time
from loguru import logger

def getch():
    """读取终端按键（跨平台兼容适配 Linux）"""
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(sys.stdin.fileno())
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    return ch

class B2KeyboardController:
    def __init__(self):
        self.sport_client = None
        self.dog_ready = False
        
        # 预设的基础速度
        self.VX_SPEED = 0.3   # 前后 m/s
        self.VY_SPEED = 0.2   # 左右侧滑 m/s
        self.VYAW_SPEED = 0.5 # 旋转 rad/s

    def init_dog(self):
        """初始化宇树 B2 底层 SDK"""
        try:
            from unitree_sdk2py.core.channel import ChannelFactoryInitialize
            from unitree_sdk2py.b2.sport.sport_client import SportClient
            from unitree_sdk2py.comm.motion_switcher.motion_switcher_client import MotionSwitcherClient
            
            logger.info("-> 正在初始化 B2 SDK...")
            try:
                ChannelFactoryInitialize(0, "eth0")
            except Exception as e:
                logger.debug(f"DDS 可能已初始化: {e}")
                
            msc = MotionSwitcherClient()
            msc.SetTimeout(5.0)
            msc.Init()
            
            code, data = msc.CheckMode()
            if code == 0 and data and data.get("name") != "ai":
                logger.info("-> 切换到 AI 运控模式...")
                msc.SelectMode("ai")
                time.sleep(2.0)
                
            self.sport_client = SportClient()
            self.sport_client.SetTimeout(1.5)
            self.sport_client.Init()
            
            logger.info("-> 解锁狗子并起立...")
            self.sport_client.BalanceStand()
            time.sleep(0.5)
            self.sport_client.SwitchMoveMode(True)
            
            self.dog_ready = True
            logger.info("✅ 宇树 B2 初始化完成！")
            
        except ImportError:
             logger.error("未找到 unitree_sdk2py，将只打印模拟按键日志。")
        except Exception as e:
             logger.error(f"狗子连接失败: {e}")

    def run(self):
        self.init_dog()
        
        print("\n" + "="*40)
        print("💻 键盘直控机器狗测试程序 🐶")
        print("="*40)
        print("控制说明：")
        print("  W : 向前进")
        print("  S : 向后退")
        print("  A : 向左平移")
        print("  D : 向右平移")
        print("  Q : 原地左转")
        print("  E : 原地右转")
        print("  空格: 紧急停止 (StopMove)")
        print("  X : 退出测试程序并让狗坐下")
        print("="*40)
        print("请在此时保持终端处于激活状态，然后直接按键盘：\n")

        try:
            while True:
                ch = getch().lower()
                
                vx, vy, vyaw = 0.0, 0.0, 0.0
                action = ""

                if ch == 'w':
                    vx, action = self.VX_SPEED, "前进"
                elif ch == 's':
                    vx, action = -self.VX_SPEED, "后退"
                elif ch == 'a':
                    vy, action = self.VY_SPEED, "左平移"
                elif ch == 'd':
                    vy, action = -self.VY_SPEED, "右平移"
                elif ch == 'q':
                    vyaw, action = self.VYAW_SPEED, "左旋转"
                elif ch == 'e':
                    vyaw, action = -self.VYAW_SPEED, "右旋转"
                elif ch == ' ':
                    action = "急停"
                elif ch == 'x':
                    print("\n正在停止并退出...")
                    if self.dog_ready:
                        self.sport_client.StopMove()
                        time.sleep(0.5)
                        self.sport_client.StandDown() # 让狗坐下休息
                    break
                else:
                    continue # 忽略其他按键
                    
                print(f"[{time.strftime('%H:%M:%S')}] 您按下了 '{ch.upper()}' -> {action} [vx={vx}, vy={vy}, vyaw={vyaw}]")

                if self.dog_ready:
                    # 将指令发给狗子
                    if action == "急停":
                        self.sport_client.StopMove()
                        time.sleep(0.1)
                        # 为了使其能立刻重新受控，再次开启 SwitchMoveMode
                        self.sport_client.SwitchMoveMode(True)
                    else:
                        self.sport_client.Move(vx, vy, vyaw)
                        
        except KeyboardInterrupt:
            print("\n强制退出。")
            if self.dog_ready:
                self.sport_client.StopMove()

if __name__ == "__main__":
    controller = B2KeyboardController()
    controller.run()
