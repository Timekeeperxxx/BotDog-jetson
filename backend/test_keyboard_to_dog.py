import sys
import termios
import tty
import time
import threading
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
    def __init__(self, net_iface="eth0"):
        self.sport_client = None
        self.dog_ready = False
        self.net_iface = net_iface
        
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
                ChannelFactoryInitialize(0, self.net_iface)
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
        print("控制说明：按住键不动，松开键自动停止")
        print("  W : 向前进")
        print("  S : 向后退")
        print("  A : 向左平移")
        print("  D : 向右平移")
        print("  Q : 原地左转")
        print("  E : 原地右转")
        print("  空格: 紧急停止 (StopMove)")
        print("  X / Ctrl+C : 退出并让狗坐下")
        print("="*40)
        print("请保持终端处于激活状态，然后直接按键盘：\n")

        # 共享状态
        current_vx = 0.0
        current_vy = 0.0
        current_vyaw = 0.0
        last_key_time = time.time()
        stop_flag = threading.Event()
        lock = threading.Lock()

        # 看门狗线程：超过 150ms 没有按键信号，自动发出停走指令
        def watchdog():
            nonlocal current_vx, current_vy, current_vyaw, last_key_time
            KEY_TIMEOUT = 0.15  # 150ms 没有按键就停走
            was_moving = False
            while not stop_flag.is_set():
                with lock:
                    idle = time.time() - last_key_time
                    moving = (current_vx != 0 or current_vy != 0 or current_vyaw != 0)
                if idle > KEY_TIMEOUT and moving:
                    if self.dog_ready:
                        self.sport_client.Move(0.0, 0.0, 0.0)
                    with lock:
                        current_vx = 0.0
                        current_vy = 0.0
                        current_vyaw = 0.0
                    if not was_moving:
                        print("\r[暂停] 松键，狗已停止", end="", flush=True)
                    was_moving = False
                else:
                    was_moving = moving
                time.sleep(0.05)

        wd_thread = threading.Thread(target=watchdog, daemon=True)
        wd_thread.start()

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
                    vyaw, action = self.VYAW_SPEED, "左转"
                elif ch == 'e':
                    vyaw, action = -self.VYAW_SPEED, "右转"
                elif ch == ' ':
                    action = "急停"
                    with lock:
                        current_vx = 0.0
                        current_vy = 0.0
                        current_vyaw = 0.0
                        last_key_time = time.time()
                    if self.dog_ready:
                        self.sport_client.StopMove()
                        time.sleep(0.05)
                        self.sport_client.SwitchMoveMode(True)
                    print(f"\r[{time.strftime('%H:%M:%S')}] 空格 -> 急停", flush=True)
                    continue
                elif ch in ('x', '\x03'):  # X 或 Ctrl+C
                    print("\n正在停止并退出...")
                    stop_flag.set()
                    if self.dog_ready:
                        self.sport_client.StopMove()
                        time.sleep(0.5)
                        self.sport_client.StandDown()
                    break
                else:
                    continue

                # 更新共享状态并发送指令
                with lock:
                    current_vx = vx
                    current_vy = vy
                    current_vyaw = vyaw
                    last_key_time = time.time()

                print(f"\r[{time.strftime('%H:%M:%S')}] {ch.upper()} -> {action}  [vx={vx:+.2f} vy={vy:+.2f} vyaw={vyaw:+.2f}]", end="", flush=True)
                if self.dog_ready:
                    self.sport_client.Move(vx, vy, vyaw)
                        
        except KeyboardInterrupt:
            stop_flag.set()
            print("\n强制退出。")
            if self.dog_ready:
                self.sport_client.StopMove()

if __name__ == "__main__":
    import os
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
        
    default_iface = os.getenv("UNITREE_NETWORK_IFACE", "enP4p65s0")
    iface = sys.argv[1] if len(sys.argv) > 1 else default_iface
    print(f"尝试使用网卡: {iface}")
    controller = B2KeyboardController(net_iface=iface)
    controller.run()
