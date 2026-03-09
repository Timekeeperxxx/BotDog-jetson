"""
MAVLink 网关模块。

职责边界：
- 监听 UDP/Serial 端口接收 MAVLink 报文
- 解析 HEARTBEAT、ATTITUDE、GLOBAL_POSITION_INT、SYS_STATUS 等报文
- 将解析结果转换为内部 DTO
- 支持模拟数据源（用于开发和测试）
- 与遥测队列管理器对接

数据源切换：
- 通过配置项 MAVLINK_SOURCE 控制（mavlink|simulation）
- mavlink: 从真实 UDP 端口读取
- simulation: 使用模拟数据生成器
"""

import asyncio
import time
from typing import Any, Optional

from backend.config import settings
from backend.logging_config import logger
from backend.mavlink_dto import (
    AttitudeDTO,
    BatteryDTO,
    PositionDTO,
    SystemStatusDTO,
    TelemetrySnapshotDTO,
    ThermalExtDTO,
)
from backend.state_machine import StateMachine
from backend.telemetry_queue import TelemetryQueueManager
from backend.temperature_monitor import TemperatureMonitor, TemperatureAlert
from backend.alert_service import get_alert_service


class MAVLinkGateway:
    """
    MAVLink 网关。

    功能：
    - 监听 MAVLink UDP 端口
    - 解析 MAVLink 报文
    - 生成遥测快照
    - 更新系统状态机
    - 推送数据到队列管理器
    """

    def __init__(
        self,
        queue_manager: TelemetryQueueManager,
        state_machine: StateMachine,
        mavlink_endpoint: Optional[str] = None,
    ):
        """
        初始化 MAVLink 网关。

        Args:
            queue_manager: 遥测队列管理器
            state_machine: 系统状态机
            mavlink_endpoint: MAVLink UDP 端口（如 "udp:127.0.0.1:14550"）
                            如果为 None，从配置读取
        """
        self.queue_manager = queue_manager
        self.state_machine = state_machine
        self.mavlink_endpoint = mavlink_endpoint or str(settings.MAVLINK_ENDPOINT)

        # 数据源类型
        self._source_type = getattr(settings, "MAVLINK_SOURCE", "simulation")

        # 内部缓存（用于组装完整快照）
        self._cached_attitude: Optional[AttitudeDTO] = None
        self._cached_position: Optional[PositionDTO] = None
        self._cached_battery: Optional[BatteryDTO] = None

        # MAVLink 连接对象
        self._mavlink_connection: Optional[Any] = None

        # 温度监控器
        self._temperature_monitor: Optional[TemperatureMonitor] = None

    async def start(self, stop_event: asyncio.Event) -> None:
        """
        启动 MAVLink 网关。

        Args:
            stop_event: 停止事件
        """
        logger.info(f"MAVLink 网关启动，数据源: {self._source_type}")

        if self._source_type == "mavlink":
            await self._start_real_mavlink(stop_event)
        else:
            await self._start_simulation_mode(stop_event)

    async def _start_real_mavlink(self, stop_event: asyncio.Event) -> None:
        """
        启动真实 MAVLink 数据接收。

        Args:
            stop_event: 停止事件
        """
        try:
            # 动态导入 pymavlink（避免硬依赖）
            from pymavlink import mavutil

            logger.info(f"连接到 MAVLink 端口: {self.mavlink_endpoint}")
            self._mavlink_connection = mavutil.mavlink_connection(self.mavlink_endpoint)

            # 等待心跳包
            logger.info("等待 MAVLink 心跳...")
            self._mavlink_connection.wait_heartbeat()
            logger.info("MAVLink 心跳已接收，链路建立")

            # 初始化温度监控
            self._init_temperature_monitor()

            # 启动消息接收循环
            await self._message_loop(stop_event)

        except ImportError:
            logger.error("pymavlink 未安装，无法使用真实 MAVLink 数据源")
            logger.info("回退到模拟数据源")
            await self._start_simulation_mode(stop_event)
        except Exception as exc:  # noqa: BLE001
            logger.exception(f"MAVLink 连接失败: {exc}，回退到模拟数据源")
            await self._start_simulation_mode(stop_event)

    def _init_temperature_monitor(self) -> None:
        """初始化温度监控器。"""
        self._temperature_monitor = TemperatureMonitor(
            threshold=settings.THERMAL_THRESHOLD,
            on_alert=self._on_temperature_alert,
        )
        logger.info("温度监控器已初始化")

    async def _on_temperature_alert(self, alert: TemperatureAlert) -> None:
        """温度告警回调。"""
        logger.warning(f"收到温度告警: {alert.temperature:.1f}°C")

        alert_service = get_alert_service()

        # 获取当前位置
        position = self._cached_position

        await alert_service.handle_temperature_alert(
            alert=alert,
            position={
                "lat": position.lat if position else None,
                "lon": position.lon if position else None,
            } if position else None,
            task_id=None,  # TODO: 获取当前任务 ID
        )

        async def _start_simulation_mode(self, stop_event: asyncio.Event) -> None:
            """
            启动模拟数据模式。

            Args:
                stop_event: 停止事件
            """
            logger.info("使用模拟数据源")

        # 初始化温度监控
        self._init_temperature_monitor()

        # 导入模拟数据生成器
        from backend.services_telemetry import generate_fake_sample

        seq = 0

        while not stop_event.is_set():
            try:
                seq += 1
                sample = generate_fake_sample(seq)

                # 构造遥测快照
                snapshot = TelemetrySnapshotDTO(
                    attitude=AttitudeDTO(
                        pitch=sample.pitch,
                        roll=sample.roll,
                        yaw=sample.yaw,
                    ),
                    position=PositionDTO(
                        lat=sample.lat,
                        lon=sample.lon,
                        alt=sample.alt,
                        hdg=sample.hdg,
                    ),
                    battery=BatteryDTO(
                        voltage=sample.voltage,
                        remaining_pct=sample.remaining_pct,
                    ),
                    system_status=SystemStatusDTO(
                        armed=True,
                        mode="AUTO",
                        mavlink_connected=True,
                    ),
                    thermal=ThermalExtDTO(
                        core_temp=40.0 + (seq % 20),  # 模拟温度 40-60°C
                        t_max=65.0 if (seq % 50) == 0 else 45.0,  # 每50次触发告警
                    ),
                )

                # 更新温度监控
                if self._temperature_monitor and snapshot.thermal:
                    self._temperature_monitor.update_temperature(
                        "T_MAX",
                        snapshot.thermal.t_max,
                    )

                # 推送到队列
                self.queue_manager.add_telemetry(snapshot)

                # 更新状态机
                self.state_machine.update_heartbeat(time.time())
                self.state_machine.update_armed_status(True)

                # 模拟 10Hz 数据更新
                await asyncio.sleep(0.1)

            except asyncio.CancelledError:
                logger.info("模拟数据源已停止")
                break
            except Exception as exc:  # noqa: BLE001
                logger.exception(f"模拟数据源异常: {exc}")
                await asyncio.sleep(1.0)

    async def _message_loop(self, stop_event: asyncio.Event) -> None:
        """
        MAVLink 消息接收循环。

        Args:
            stop_event: 停止事件
        """
        logger.info("MAVLink 消息循环已启动")

        while not stop_event.is_set():
            try:
                # 非阻塞读取消息
                msg = self._mavlink_connection.recv_match(blocking=False, timeout=0.1)

                if msg is None:
                    await asyncio.sleep(0.01)
                    continue

                # 处理消息
                await self._process_message(msg)

            except asyncio.CancelledError:
                logger.info("MAVLink 消息循环已停止")
                break
            except Exception as exc:  # noqa: BLE001
                logger.exception(f"MAVLink 消息处理异常: {exc}")
                await asyncio.sleep(0.1)

    async def _process_message(self, msg: Any) -> None:
        """
        处理单个 MAVLink 消息。

        Args:
            msg: MAVLink 消息对象
        """
        msg_type = msg.get_type()

        # 过滤心跳包（用于状态机）
        if msg_type == "HEARTBEAT":
            self._process_heartbeat(msg)
            return

        # 解析姿态数据
        if msg_type == "ATTITUDE":
            self._cached_attitude = AttitudeDTO(
                pitch=float(msg.pitch),
                roll=float(msg.roll),
                yaw=float(msg.yaw),
            )

        # 解析位置数据
        elif msg_type == "GLOBAL_POSITION_INT":
            self._cached_position = PositionDTO(
                lat=msg.lat / 1e7,  # 转换为度
                lon=msg.lon / 1e7,  # 转换为度
                alt=msg.alt / 1e3,  # 转换为米
                hdg=msg.hdg / 100,  # 转换为度
            )

        # 解析电池数据
        elif msg_type in ("SYS_STATUS", "BATTERY_STATUS"):
            self._cached_battery = BatteryDTO(
                voltage=msg.voltage_battery / 1000 if msg_type == "SYS_STATUS" else 0.0,
                remaining_pct=int(msg.battery_remaining),
            )

        # 检查是否需要生成快照
        if self._is_snapshot_ready():
            snapshot = TelemetrySnapshotDTO(
                attitude=self._cached_attitude,
                position=self._cached_position,
                battery=self._cached_battery,
                system_status=SystemStatusDTO(
                    armed=self._is_armed(),
                    mode=self._get_flight_mode(),
                    mavlink_connected=True,
                ),
            )

            self.queue_manager.add_telemetry(snapshot)

            # 清空缓存（避免重复数据）
            self._cached_attitude = None
            self._cached_position = None
            # 电池数据不清空，可能不需要每次更新

    def _process_heartbeat(self, msg: Any) -> None:
        """
        处理心跳包。

        Args:
            msg: HEARTBEAT 消息
        """
        current_time = time.time()
        self.state_machine.update_heartbeat(current_time)
        self.state_machine.update_armed_status(self._is_armed_from_heartbeat(msg))

    def _is_snapshot_ready(self) -> bool:
        """
        判断是否准备好生成遥测快照。

        规则：
        - 至少有姿态或位置数据之一
        """
        return (
            self._cached_attitude is not None or self._cached_position is not None
        ) and self._cached_battery is not None

    def _is_armed(self) -> bool:
        """判断电机是否解锁（从缓存推断）。"""
        # 简化实现，实际应从 HEARTBEAT 消息读取
        return False

    def _is_armed_from_heartbeat(self, msg: Any) -> bool:
        """
        从心跳包判断电机是否解锁。

        Args:
            msg: HEARTBEAT 消息
        """
        # base_mode 的第 7 位表示 ARMED 状态
        return bool(msg.base_mode & 0b10000000)

    def _get_flight_mode(self) -> str:
        """获取飞行模式（简化实现）。"""
        return "STABILIZE"
