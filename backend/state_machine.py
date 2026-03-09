"""
系统状态机模块。

职责边界：
- 定义系统状态枚举与状态转换逻辑
- 管理心跳超时检测
- 提供状态查询接口
- 状态与控制指令的联动（如 E_STOP_TRIGGERED 时拒绝移动指令）

状态定义：
- DISCONNECTED: MAVLink 链路断开，无心跳数据
- STANDBY: 链路正常，电机未解锁（Disarmed）
- IN_MISSION: 巡检任务执行中
- E_STOP_TRIGGERED: 紧急制动生效中
"""

import asyncio
import time
from enum import Enum
from typing import Callable, Optional

from backend.logging_config import logger


class SystemState(str, Enum):
    """系统状态枚举。"""

    DISCONNECTED = "DISCONNECTED"  # 链路断开
    STANDBY = "STANDBY"  # 待机（已连接，未解锁）
    IN_MISSION = "IN_MISSION"  # 任务执行中
    E_STOP_TRIGGERED = "E_STOP_TRIGGERED"  # 紧急制动


class StateMachine:
    """
    系统状态机。

    功能：
    - 维护当前状态
    - 处理状态转换条件检查
    - 触发状态变化回调
    - 管理心跳超时检测
    """

    def __init__(
        self,
        heartbeat_timeout: float = 3.0,
        on_state_change: Optional[Callable[[SystemState, SystemState], None]] = None,
    ):
        """
        初始化状态机。

        Args:
            heartbeat_timeout: 心跳超时时间（秒），超过则判定为失联
            on_state_change: 状态变化回调函数，参数为 (旧状态, 新状态)
        """
        self._state = SystemState.DISCONNECTED
        self._heartbeat_timeout = heartbeat_timeout
        self._on_state_change = on_state_change
        self._last_heartbeat_time: float = 0.0
        self._is_armed = False  # 电机是否解锁
        self._is_mission_active = False  # 任务是否激活

    @property
    def state(self) -> SystemState:
        """获取当前状态。"""
        return self._state

    @property
    def is_connected(self) -> bool:
        """判断 MAVLink 链路是否连通。"""
        return self._state != SystemState.DISCONNECTED

    @property
    def can_accept_control(self) -> bool:
        """
        判断是否可以接受控制指令。

        规则：
        - DISCONNECTED: 不接受
        - E_STOP_TRIGGERED: 不接受（紧急制动中）
        - STANDBY: 接受
        - IN_MISSION: 接受
        """
        return self._state in (SystemState.STANDBY, SystemState.IN_MISSION)

    def update_heartbeat(self, timestamp: float) -> None:
        """
        更新心跳时间戳。

        Args:
            timestamp: 当前 Unix 时间戳（秒）
        """
        self._last_heartbeat_time = timestamp
        self._evaluate_state()

    def update_armed_status(self, armed: bool) -> None:
        """
        更新电机解锁状态。

        Args:
            armed: True=已解锁，False=未解锁
        """
        old_armed = self._is_armed
        self._is_armed = armed

        # 解锁状态变化时，重新评估状态
        if old_armed != armed:
            self._evaluate_state()

    def update_mission_status(self, is_active: bool) -> None:
        """
        更新任务激活状态。

        Args:
            is_active: True=任务执行中，False=无任务
        """
        old_active = self._is_mission_active
        self._is_mission_active = is_active

        if old_active != is_active:
            self._evaluate_state()

    def trigger_emergency_stop(self) -> None:
        """触发紧急制动。"""
        if self._state != SystemState.E_STOP_TRIGGERED:
            old_state = self._state
            self._state = SystemState.E_STOP_TRIGGERED
            logger.warning(f"状态机触发紧急制动: {old_state} -> {self._state}")

            if self._on_state_change:
                self._on_state_change(old_state, self._state)

    def reset_emergency_stop(self) -> None:
        """重置紧急制动状态（仅限管理员操作）。"""
        if self._state == SystemState.E_STOP_TRIGGERED:
            old_state = self._state
            self._evaluate_state()  # 重新评估正常状态
            logger.info(f"状态机重置紧急制动: {old_state} -> {self._state}")

    def _evaluate_state(self) -> None:
        """
        评估并更新系统状态。

        状态转换逻辑：
        1. 如果处于 E_STOP_TRIGGERED，保持不变（需显式重置）
        2. 如果心跳超时，转为 DISCONNECTED
        3. 如果未收到过心跳，保持 DISCONNECTED
        4. 如果任务激活，转为 IN_MISSION
        5. 如果已解锁，转为 IN_MISSION（兼容未使用任务系统的情况）
        6. 否则转为 STANDBY
        """
        # 如果处于紧急制动状态，保持不变
        if self._state == SystemState.E_STOP_TRIGGERED:
            return

        # 与 update_heartbeat 使用同一时间基准（Unix 时间戳）
        current_time = time.time()
        heartbeat_age = current_time - self._last_heartbeat_time

        # 检查心跳超时
        if self._last_heartbeat_time == 0.0 or heartbeat_age > self._heartbeat_timeout:
            new_state = SystemState.DISCONNECTED
        elif self._is_mission_active:
            new_state = SystemState.IN_MISSION
        elif self._is_armed:
            new_state = SystemState.IN_MISSION  # 已解锁视为任务中
        else:
            new_state = SystemState.STANDBY

        # 状态变化时触发回调
        if new_state != self._state:
            old_state = self._state
            self._state = new_state
            logger.info(f"状态机状态转换: {old_state} -> {self._state}")

            if self._on_state_change:
                self._on_state_change(old_state, self._state)

    async def start_heartbeat_monitor(self) -> None:
        """
        启动心跳监控协程。

        该协程会定期检查心跳超时，并在超时时更新状态。
        """
        logger.info("心跳监控协程已启动")

        while True:
            try:
                self._evaluate_state()
                await asyncio.sleep(0.5)  # 每 0.5 秒检查一次
            except asyncio.CancelledError:
                logger.info("心跳监控协程已停止")
                break
            except Exception as exc:  # noqa: BLE001
                logger.exception("心跳监控协程异常: {}", exc)
                await asyncio.sleep(1.0)
