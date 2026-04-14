"""
宇树 B2 遥测 Worker。

订阅 DDS 话题 rt/sportmodestate，获取 B2 的位置、速度、姿态等状态，
并转换为项目内部 TelemetrySnapshotDTO 推送至遥测队列。

话题频率：500Hz（rt/sportmodestate）或 50Hz（rt/lf/sportmodestate）
Worker 内部以 50Hz 采样（实际使用低频话题）。
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional, TYPE_CHECKING

from .logging_config import logger
from .mavlink_dto import (
    AttitudeDTO,
    BatteryDTO,
    PositionDTO,
    SystemStatusDTO,
    TelemetrySnapshotDTO,
)

if TYPE_CHECKING:
    from .telemetry_queue import TelemetryQueueManager
    from .state_machine import StateMachine

# DDS 话题（低频 50Hz 版本，减少 CPU 占用）
TOPIC_SPORT_STATE = "rt/lf/sportmodestate"


class UnitreeTelemetryWorker:
    """
    宇树 B2 遥测数据 Worker。

    通过 unitree_sdk2py 订阅 DDS sportmodestate 话题，
    将机器人状态实时推送到遥测队列管理器。
    """

    def __init__(
        self,
        queue_manager: "TelemetryQueueManager",
        state_machine: "StateMachine",
        network_interface: str = "ens37",
    ) -> None:
        self._queue_manager = queue_manager
        self._state_machine = state_machine
        self._network_interface = network_interface
        self._latest_state: Optional[dict] = None
        self._last_update_time: float = 0.0
        self._initialized: bool = False

    async def start(self, stop_event: asyncio.Event) -> None:
        """启动遥测 Worker。"""
        try:
            from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
            from unitree_sdk2py.idl.unitree_go.msg.dds_ import SportModeState_

            logger.info(f"[UnitreeTelemetry] 初始化 DDS，网卡={self._network_interface}")

            # 初始化 DDS 频道（不重复初始化，B2Adapter 可能已初始化）
            try:
                ChannelFactoryInitialize(0, self._network_interface)
            except Exception as e:
                logger.debug(f"[UnitreeTelemetry] ChannelFactoryInitialize 跳过（已初始化）: {e}")

            # 创建订阅者（含重试逻辑）
            # UnitreeB2Adapter 在后台线程同时初始化 DDS，两者并发时 Topic 创建会失败。
            # 通过重试 + 等待解决竞态：B2Adapter 初始化约需 5~10s，最多等 15s。
            subscriber = None
            for _retry in range(5):
                try:
                    subscriber = ChannelSubscriber(TOPIC_SPORT_STATE, SportModeState_)
                    break
                except Exception as e_sub:
                    if _retry < 4:
                        logger.warning(
                            f"[UnitreeTelemetry] DDS subscriber 创建失败（attempt {_retry + 1}/5），"
                            f"等待 3s 重试（可能与 B2Adapter 初始化竞态）: {e_sub}"
                        )
                        await asyncio.sleep(3.0)
                    else:
                        raise  # 全部重试耗尽，抛出异常触发 fallback

            def on_state_message(msg: SportModeState_) -> None:
                """DDS 回调：接收到新状态时更新缓存。SportModeState_ 是 dataclass，字段直接访问。"""
                try:
                    self._latest_state = {
                        # IMUState_ 也是 dataclass，rpy 是 float32[3] 数组
                        "roll":  float(msg.imu_state.rpy[0]),
                        "pitch": float(msg.imu_state.rpy[1]),
                        "yaw":   float(msg.imu_state.rpy[2]),
                        # position: float32[3]，[0]=x(前), [1]=y(左), [2]=z(上)
                        "pos_x": float(msg.position[0]),
                        "pos_y": float(msg.position[1]),
                        "pos_z": float(msg.position[2]),
                        # velocity: float32[3]
                        "vel_x": float(msg.velocity[0]),
                        "vel_y": float(msg.velocity[1]),
                        "vel_z": float(msg.velocity[2]),
                        "body_height": float(msg.body_height),
                        "mode": int(msg.mode),
                    }
                    self._last_update_time = time.time()
                except Exception as exc:
                    logger.debug(f"[UnitreeTelemetry] 状态解析异常: {exc}")

            subscriber.Init(on_state_message, 1)  # Python SDK 用 .Init() 而非 .InitChannel()
            self._initialized = True
            logger.info("[UnitreeTelemetry] DDS 订阅者已启动，等待 B2 状态数据...")

            # 主循环：以 20Hz 将最新状态推送到遥测队列
            _last_warn_time: float = 0.0  # 断连警告限速（30s 冷却）
            while not stop_event.is_set():
                try:
                    await asyncio.sleep(0.05)  # 20Hz

                    state = self._latest_state
                    if state is None:
                        continue

                    # 超过 2 秒无更新，认为断连（警告限速：每 30s 最多输出一次）
                    if time.time() - self._last_update_time > 2.0:
                        now = time.time()
                        if now - _last_warn_time >= 30.0:
                            logger.warning("[UnitreeTelemetry] 超过 2s 无数据，可能断连")
                            _last_warn_time = now
                        self._state_machine.update_heartbeat(0)  # 触发断连检测
                        continue

                    # 构造遥测快照
                    snapshot = TelemetrySnapshotDTO(
                        attitude=AttitudeDTO(
                            roll=state["roll"],
                            pitch=state["pitch"],
                            yaw=state["yaw"],
                        ),
                        position=PositionDTO(
                            # B2 里程计位置（相对坐标，非 GPS）
                            lat=state["pos_x"],   # 前进方向（m）
                            lon=state["pos_y"],   # 横向（m）
                            alt=state["pos_z"],   # 高度（m）
                            hdg=state["yaw"],     # 朝向（rad）
                        ),
                        battery=BatteryDTO(
                            voltage=0.0,          # 单独从 robot_state 获取
                            remaining_pct=100,
                        ),
                        system_status=SystemStatusDTO(
                            armed=state["mode"] not in (0, 7),  # 非 idle/damping 视为激活
                            mode=f"B2_MODE_{state['mode']}",
                            mavlink_connected=True,
                        ),
                    )

                    self._queue_manager.add_telemetry(snapshot)
                    self._state_machine.update_heartbeat(time.time())
                    self._state_machine.update_armed_status(snapshot.system_status.armed)

                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    logger.exception(f"[UnitreeTelemetry] 主循环异常: {exc}")
                    await asyncio.sleep(1.0)

        except ImportError:
            logger.error("[UnitreeTelemetry] unitree_sdk2py 未安装，回退到模拟数据")
            await self._fallback_simulation(stop_event)
        except Exception as exc:
            logger.exception(f"[UnitreeTelemetry] 初始化失败: {exc}，回退到模拟数据")
            await self._fallback_simulation(stop_event)
        finally:
            logger.info("[UnitreeTelemetry] Worker 已停止")

    async def _fallback_simulation(self, stop_event: asyncio.Event) -> None:
        """回退到模拟数据（SDK 不可用时）。"""
        from .services_telemetry import generate_fake_sample
        seq = 0
        while not stop_event.is_set():
            try:
                seq += 1
                sample = generate_fake_sample(seq)
                snapshot = TelemetrySnapshotDTO(
                    attitude=AttitudeDTO(pitch=sample.pitch, roll=sample.roll, yaw=sample.yaw),
                    position=PositionDTO(lat=sample.lat, lon=sample.lon, alt=sample.alt, hdg=sample.hdg),
                    battery=BatteryDTO(voltage=sample.voltage, remaining_pct=sample.remaining_pct),
                    system_status=SystemStatusDTO(armed=True, mode="SIMULATION", mavlink_connected=False),
                )
                self._queue_manager.add_telemetry(snapshot)
                self._state_machine.update_heartbeat(time.time())
                await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                break
