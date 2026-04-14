"""
机器狗适配器模块。

职责边界：
- 定义适配器抽象接口，屏蔽底层设备差异
- SimulatedRobotAdapter：无真实硬件时打印日志（开发 / CI 阶段使用）
- MAVLinkRobotAdapter：预留骨架，真实硬件接入时实现
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Optional

from .logging_config import logger


# 合法的动作名集合
VALID_COMMANDS = frozenset({
    "forward",
    "backward",
    "left",
    "right",
    "strafe_left",
    "strafe_right",
    "sit",
    "stand",
    "stop",
})


class BaseRobotAdapter(ABC):
    """
    机器狗适配器基类。

    所有具体适配器必须继承此类并实现 send_command 方法。
    """

    @abstractmethod
    async def send_command(self, cmd: str) -> None:
        """
        向机器狗发送控制命令。

        Args:
            cmd: 动作名（forward/backward/left/right/sit/stand/stop）
        """
        ...

    async def stop(self) -> None:
        """快捷停止方法，供 Watchdog 调用。"""
        await self.send_command("stop")


class SimulatedRobotAdapter(BaseRobotAdapter):
    """
    模拟适配器（无真实硬件时使用）。

    仅打印日志，不发送真实指令。
    后续换真实硬件时，替换为 MAVLinkRobotAdapter，其余代码不变。
    """

    async def send_command(self, cmd: str) -> None:
        """
        模拟执行命令，仅打印日志。

        Args:
            cmd: 动作名
        """
        logger.info(f"[SimulatedAdapter] 执行命令: {cmd}")
        # 模拟指令执行延迟（约 5ms）
        await asyncio.sleep(0.005)


class MAVLinkRobotAdapter(BaseRobotAdapter):
    """
    MAVLink 真实硬件适配器（预留骨架）。

    TODO: 真实硬件接入时实现此类。
    需要注入 MAVLink 连接对象，通过发送相应的 MAVLink 消息控制机器狗。
    """

    def __init__(self, mavlink_connection=None):
        """
        初始化 MAVLink 适配器。

        Args:
            mavlink_connection: pymavlink 连接对象（可选，接入真实硬件时必填）
        """
        self._connection = mavlink_connection

    async def send_command(self, cmd: str) -> None:
        """
        通过 MAVLink 发送控制命令（待实现）。

        Args:
            cmd: 动作名
        """
        # TODO: 实现具体的 MAVLink 命令映射
        # 例如：forward -> SET_POSITION_TARGET_LOCAL_NED with vx=1.0
        logger.warning(f"[MAVLinkAdapter] send_command({cmd}) 尚未实现，已忽略")


class UnitreeB2Adapter(BaseRobotAdapter):
    """
    宇树 B2 真实硬件适配器。

    使用 unitree_sdk2_python（CycloneDDS）的 SportClient 高层运动接口，
    将项目内部命令映射为 B2 能接受的速度控制指令。

    依赖：
    - pip install unitree_sdk2_python    (或从源码 pip install -e .)
    - 网线连接 B2（默认 IP 192.168.123.161）
    - 运行环境必须是 Linux（官方不支持 Windows/Mac）

    官方速度范围（来自 AI 运控服务接口文档）：
        vx:   [-0.6 ~ 0.6]  m/s
        vy:   [-0.4 ~ 0.4]  m/s
        vyaw: [-0.8 ~ 0.8]  rad/s

    初始化序列（必须按顺序）：
        ChannelFactoryInitialize → Init() → BalanceStand()（解锁）
        → ClassicWalk(True)（进入经典步态）→ SwitchMoveMode(True)（持续响应）

    命令映射：
        forward      → Move(vx, 0, 0)
        backward     → Move(-vx, 0, 0)
        left         → Move(0, 0, +vyaw)     # 偏航正值 = 逆时针 = 向左转
        right        → Move(0, 0, -vyaw)
        strafe_left  → Move(0, +vy, 0)       # 正值 = 向左平移
        strafe_right → Move(0, -vy, 0)
        stop         → StopMove() + BalanceStand()（停止但保持解锁）
        stand        → StandUp()（从蹲下起立）/ RecoveryStand()（倒地紧急恢复，作兜底）
        sit          → StandDown()
    """

    def __init__(
        self,
        network_interface: str = "eth0",  # 占位默认值，实际由 .env UNITREE_NETWORK_IFACE 覆盖
        vx: float = 0.3,
        vy: float = 0.25,
        vyaw: float = 0.5,
    ) -> None:
        """
        初始化宇树 B2 适配器。

        Args:
            network_interface: 连接 B2 的网卡名（eth0 / enp2s0）
            vx: 前进/后退速度（m/s），范围 0~0.6，默认 0.3
            vy: 横向平移速度（m/s），范围 0~0.4，默认 0.25
            vyaw: 偏航转速（rad/s），范围 0~0.8，默认 0.5
        """
        import queue
        import threading
        self._vx = vx
        self._vy = vy
        self._vyaw = vyaw
        self._network_interface = network_interface
        self._sport_client = None
        self._initialized = False

        # 姿态命令（stand/sit）执行期间置 True，防止被后续命令从队列挤掉
        self._busy_with_posture = False
        # 当前姿态状态："stand"=站立/运动中，"sit"=蹲坐，"unknown"=未知
        # stop 命令只在 stand 状态下调用 BalanceStand()，sit 状态跳过，防止 watchdog 把蹲下的狗强制站起来
        self._current_posture: str = "unknown"

        # 启动单独的工作线程处理阻塞的 SDK 调用，防止耗尽 FastAPI 的线程池
        self._cmd_queue = queue.Queue(maxsize=1)
        self._worker_thread = threading.Thread(target=self._command_worker, daemon=True)
        self._worker_thread.start()

        try:
            from unitree_sdk2py.core.channel import ChannelFactoryInitialize
            from unitree_sdk2py.b2.sport.sport_client import SportClient
            from unitree_sdk2py.comm.motion_switcher.motion_switcher_client import MotionSwitcherClient

            # 初始化 DDS 频道
            # 正常情况：首次调用成功；已有实例时抛 "channel factory init error."（可忽略）
            # 异常情况：DDS 端口被占用等导致 "create domain error"（致命，需中止）
            try:
                ChannelFactoryInitialize(0, network_interface)
            except Exception as _dds_e:
                err_msg = str(_dds_e).lower()
                if "create domain error" in err_msg or "domain" in err_msg:
                    # 真实的 DDS domain 初始化失败（通常是端口被占用或网卡不可用）
                    raise RuntimeError(
                        f"[UnitreeB2] CycloneDDS domain 初始化失败，"
                        f"可能存在其他后端进程占用 DDS 端口，请先 pkill -f run_backend.py: {_dds_e}"
                    )
                # 其他异常视为"已由其他组件初始化"，安全跳过
                logger.debug(f"[UnitreeB2] ChannelFactoryInitialize 跳过（已初始化）: {_dds_e}")

            # Step 1: 通过 MotionSwitcher 切换到 AI 运控模式（必须在 SportClient 之前）
            import time
            msc = MotionSwitcherClient()
            msc.SetTimeout(5.0)
            msc.Init()

            # 查询当前模式
            code, data = msc.CheckMode()
            current_mode = data.get("name", "unknown") if data else "unknown"
            logger.info(f"[UnitreeB2] 当前运控模式: {current_mode} (code={code})")

            # 如果不是 ai 模式，切换过去
            if code == 0 and current_mode != "ai":
                logger.info("[UnitreeB2] 切换到 AI 运控模式...")
                sel_code, _ = msc.SelectMode("ai")
                if sel_code == 0:
                    logger.info("[UnitreeB2] 已切换到 ai 模式")
                    time.sleep(2.0)  # 等待模式切换完成
                else:
                    logger.warning(f"[UnitreeB2] 模式切换失败 code={sel_code}，尝试继续")

            # Step 2: 初始化 SportClient
            self._sport_client = SportClient()
            self._sport_client.SetTimeout(1.5)  # RPC 超时：1.5s（原 5s，减少界面卡顿）
            self._sport_client.Init()

            # Step 3: 解锁运动模式（必须，否则 Move() 命令被硬件层忽略）
            # BalanceStand() → 切换到平衡站立（解除阻尼/静止锁定）
            # SwitchMoveMode(True) → 进入持续响应 Move 的运动模式
            import time as _time
            _ret_bs = self._sport_client.BalanceStand()
            logger.info(f"[UnitreeB2] BalanceStand ret={_ret_bs}")
            _time.sleep(0.5)
            _ret_mm = self._sport_client.SwitchMoveMode(True)
            logger.info(f"[UnitreeB2] SwitchMoveMode(True) ret={_ret_mm}")

            self._initialized = True
            logger.info(
                f"[UnitreeB2] 初始化成功（网卡={network_interface}, "
                f"vx={vx} m/s, vyaw={vyaw} rad/s）"
            )
        except ImportError:
            logger.error(
                "[UnitreeB2] unitree_sdk2_python 未安装！"
                "请运行: pip install unitree_sdk2_python"
            )
        except Exception as e:
            logger.error(f"[UnitreeB2] 初始化失败: {e}")

    def _command_worker(self):
        """后台专用的工作线程：消费队列并调用阻断的 SDK。"""
        import queue
        while True:
            try:
                cmd = self._cmd_queue.get()
                if cmd == "_QUIT_":
                    break
                if not self._initialized or self._sport_client is None:
                    continue

                client = self._sport_client
                logger.debug(f"[UnitreeB2 Worker] 执行命令: {cmd}")
                
                if cmd == "forward":
                    client.Move(self._vx, 0.0, 0.0)
                elif cmd == "backward":
                    client.Move(-self._vx, 0.0, 0.0)
                elif cmd == "left":
                    client.Move(0.0, 0.0, self._vyaw)
                elif cmd == "right":
                    client.Move(0.0, 0.0, -self._vyaw)
                elif cmd == "strafe_left":
                    client.Move(0.0, self._vy, 0.0)
                elif cmd == "strafe_right":
                    client.Move(0.0, -self._vy, 0.0)

                elif cmd == "stop":
                    ret = client.StopMove()
                    logger.debug(f"[UnitreeB2 Worker] StopMove ret={ret}")
                    if ret != 0:
                        client.Move(0.0, 0.0, 0.0)
                        logger.debug(f"[UnitreeB2 Worker] StopMove失败，备用 Move(0,0,0)")
                    # 退出持续运动模式（SwitchMoveMode(True)），回到稳定站立。
                    # 仅在站立/运动状态下调用；蹲坐（sit）状态下跳过，防止 watchdog 把狗强制站起来。
                    if self._current_posture != "sit":
                        import time as _t
                        _t.sleep(0.1)
                        ret_bs = client.BalanceStand()
                        logger.debug(f"[UnitreeB2 Worker] stop→BalanceStand ret={ret_bs}")
                    else:
                        logger.debug("[UnitreeB2 Worker] stop：当前蹲坐状态，跳过 BalanceStand")
                elif cmd == "stand":
                    self._busy_with_posture = True
                    try:
                        import time
                        # 直接 BalanceStand，跳过 StandUp（StandUp 是专门从坐姿起立，但会破坏模式状态）
                        ret_bs = client.BalanceStand()
                        logger.info(f"[UnitreeB2 Worker] BalanceStand ret={ret_bs}")
                        time.sleep(2.0)  # 等待起立稳定
                        for attempt in range(5):
                            ret_mm = client.SwitchMoveMode(True)
                            logger.info(f"[UnitreeB2 Worker] SwitchMoveMode(True) ret={ret_mm} (attempt {attempt+1})")
                            if ret_mm == 0:
                                break
                            time.sleep(0.5)
                    except Exception as e_stand:
                        logger.error(f"[UnitreeB2 Worker] stand 失败: {e_stand}")
                    else:
                        self._current_posture = "stand"
                    finally:
                        self._busy_with_posture = False
                elif cmd == "sit":
                    self._busy_with_posture = True
                    try:
                        import time
                        # 先停步态，再坐下
                        client.StopMove()
                        time.sleep(0.3)
                        ret_sd = client.StandDown()
                        logger.info(f"[UnitreeB2 Worker] StandDown ret={ret_sd}")
                        # StandDown 物理过程长于 1.5s，经常超时返回 3104。但硬件已在执行蹲下
                        # 所以无论返回值是什么，都认为已进入坐下状态
                        self._current_posture = "sit"
                    finally:
                        self._busy_with_posture = False

                logger.debug(f"[UnitreeB2 Worker] 执行完成: {cmd}")
            except Exception as e:
                self._busy_with_posture = False
                logger.error(f"[UnitreeB2 Worker] 执行异常 ({cmd}): {e}")

    async def send_command(self, cmd: str) -> None:
        """
        通过 SportClient 发送控制命令。

        Args:
            cmd: 动作名（forward/backward/left/right/stop/stand/sit）
        """
        if not self._initialized or self._sport_client is None:
            logger.warning(f"[UnitreeB2] 适配器未就绪，忽略命令: {cmd}")
            return

        import queue

        if cmd in ("stand", "sit"):
            # ── 姿态命令：特殊处理 ─────────────────────────────────────
            # 若正在执行另一个姿态命令，忽略
            if self._busy_with_posture:
                logger.debug(f"[UnitreeB2] 正在执行姿态命令，忽略: {cmd}")
                return
            # 提前占位标志，消灭 race window
            self._busy_with_posture = True
            # 清空队列中积压的运动命令，确保姿态命令能顺利入队
            try:
                while not self._cmd_queue.empty():
                    self._cmd_queue.get_nowait()
            except queue.Empty:
                pass
            # 阻塞入队（maxsize=1，已清空，一定成功）
            try:
                self._cmd_queue.put_nowait(cmd)
                logger.info(f"[UnitreeB2] 姿态命令已入队: {cmd}")
            except queue.Full:
                # 意外：重置标志防止死锁
                self._busy_with_posture = False
                logger.warning(f"[UnitreeB2] 姿态命令入队失败，队列仍满: {cmd}")
        else:
            # ── 运动/停止命令：若姿态命令执行中则忽略 ──────────────────
            if self._busy_with_posture:
                logger.debug(f"[UnitreeB2] 正在执行姿态命令，忽略运动命令: {cmd}")
                return
            try:
                # 清空积压，始终只执行最新命令
                while not self._cmd_queue.empty():
                    self._cmd_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._cmd_queue.put_nowait(cmd)
                logger.debug(f"[UnitreeB2] 已放入后台队列: {cmd}")
            except queue.Full:
                logger.warning(f"[UnitreeB2] 队列已满，丢弃命令: {cmd}")



# ─── 工厂函数 ────────────────────────────────────────────────────────────────

_adapter: Optional[BaseRobotAdapter] = None


def create_adapter(adapter_type: str = "simulation", **kwargs) -> BaseRobotAdapter:
    """
    创建适配器实例。

    Args:
        adapter_type: 适配器类型（"simulation" | "mavlink" | "unitree_b2"）
        **kwargs: 传递给适配器构造函数的额外参数

    Returns:
        适配器实例
    """
    if adapter_type == "mavlink":
        logger.info("使用 MAVLink 适配器（真实硬件模式）")
        return MAVLinkRobotAdapter()
    elif adapter_type == "unitree_b2":
        logger.info("使用 UnitreeB2Adapter（宇树 B2 真实硬件）")
        return UnitreeB2Adapter(**kwargs)
    else:
        logger.info("使用 SimulatedRobotAdapter（模拟模式）")
        return SimulatedRobotAdapter()


def get_robot_adapter() -> BaseRobotAdapter:
    """获取当前适配器实例（单例）。"""
    global _adapter
    if _adapter is None:
        _adapter = create_adapter("simulation")
    return _adapter


def set_robot_adapter(adapter: BaseRobotAdapter) -> None:
    """注入适配器实例（供测试和初始化时使用）。"""
    global _adapter
    _adapter = adapter
