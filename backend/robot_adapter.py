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
        forward  → Move(vx, 0, 0)
        backward → Move(-vx, 0, 0)
        left     → Move(0, 0, +vyaw)     # 偏航正值 = 逆时针 = 向左转
        right    → Move(0, 0, -vyaw)
        stop     → StopMove() + BalanceStand()（停止但保持解锁）
        stand    → RecoveryStand()
        sit      → StandDown()
    """

    def __init__(
        self,
        network_interface: str = "eth0",
        vx: float = 0.3,
        vyaw: float = 0.5,
    ) -> None:
        """
        初始化宇树 B2 适配器。

        Args:
            network_interface: 连接 B2 的网卡名（eth0 / enp2s0）
            vx: 前进/后退速度（m/s），范围 0~0.6，默认 0.3
            vyaw: 偏航转速（rad/s），范围 0~0.8，默认 0.5
        """
        import queue
        import threading
        self._vx = vx
        self._vyaw = vyaw
        self._network_interface = network_interface
        self._sport_client = None
        self._initialized = False

        # 启动单独的工作线程处理阻塞的 SDK 调用，防止耗尽 FastAPI 的线程池
        self._cmd_queue = queue.Queue(maxsize=1)
        self._worker_thread = threading.Thread(target=self._command_worker, daemon=True)
        self._worker_thread.start()

        try:
            from unitree_sdk2py.core.channel import ChannelFactoryInitialize
            from unitree_sdk2py.b2.sport.sport_client import SportClient
            from unitree_sdk2py.comm.motion_switcher.motion_switcher_client import MotionSwitcherClient

            ChannelFactoryInitialize(0, network_interface)

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
            self._sport_client.SetTimeout(5.0)
            self._sport_client.Init()

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
                elif cmd == "stop":
                    client.StopMove()
                elif cmd == "stand":
                    # 起立前先解锁关节+切步态（初始化未自动起立时必须）
                    import time
                    client.BalanceStand()
                    time.sleep(1.0)
                    client.ClassicWalk(True)
                    time.sleep(0.5)
                    client.RecoveryStand()
                elif cmd == "sit":
                    client.StandDown()

                logger.debug(f"[UnitreeB2 Worker] 执行完成: {cmd}")
            except Exception as e:
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
        try:
            # 清空队列，确保始终只运行最新的命令，防止阻塞导致堆积
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
