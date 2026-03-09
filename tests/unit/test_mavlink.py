"""
MAVLink 网关与状态机单元测试。

测试覆盖：
- 状态机状态转换逻辑
- 心跳超时检测
- 遥测队列管理器
- WebSocket 客户端连接池管理
"""

import asyncio
import contextlib
import time

import pytest

from backend.mavlink_dto import (
    AttitudeDTO,
    BatteryDTO,
    PositionDTO,
    SystemStatusDTO,
    TelemetrySnapshotDTO,
)
from backend.state_machine import StateMachine, SystemState
from backend.telemetry_queue import TelemetryQueueManager


class TestStateMachine:
    """状态机单元测试。"""

    def test_initial_state(self) -> None:
        """状态机初始状态应为 DISCONNECTED。"""
        state_machine = StateMachine()
        assert state_machine.state == SystemState.DISCONNECTED

    def test_heartbeat_timeout(self) -> None:
        """心跳超时后应转为 DISCONNECTED 状态。"""
        state_machine = StateMachine(heartbeat_timeout=0.5)  # 使用较短的超时时间

        # 模拟收到心跳
        state_machine.update_heartbeat(time.time())

        # 此时应该是 STANDBY（未解锁，无任务）
        assert state_machine.state == SystemState.STANDBY

        # 等待超时（0.6 秒）
        time.sleep(0.6)
        state_machine._evaluate_state()

        # 应转为 DISCONNECTED
        assert state_machine.state == SystemState.DISCONNECTED

    def test_armed_status_transition(self) -> None:
        """解锁状态变化应触发状态转换。"""
        state_machine = StateMachine()

        # 先有心跳
        state_machine.update_heartbeat(time.time())

        # 初始状态：未解锁，应为 STANDBY
        assert state_machine.state == SystemState.STANDBY

        # 解锁后：应为 IN_MISSION
        state_machine.update_armed_status(True)
        assert state_machine.state == SystemState.IN_MISSION

    def test_mission_status_transition(self) -> None:
        """任务激活状态变化应触发状态转换。"""
        state_machine = StateMachine()

        # 先有心跳
        state_machine.update_heartbeat(time.time())

        # 初始状态：无任务，应为 STANDBY
        assert state_machine.state == SystemState.STANDBY

        # 激活任务：应为 IN_MISSION
        state_machine.update_mission_status(True)
        assert state_machine.state == SystemState.IN_MISSION

    def test_emergency_stop(self) -> None:
        """触发紧急制动后应转为 E_STOP_TRIGGERED 状态。"""
        state_machine = StateMachine()

        # 先进入正常状态
        state_machine.update_heartbeat(time.time())
        state_machine.update_mission_status(True)
        assert state_machine.state == SystemState.IN_MISSION

        # 触发紧急制动
        state_machine.trigger_emergency_stop()
        assert state_machine.state == SystemState.E_STOP_TRIGGERED

        # 紧急制动期间不应接受控制
        assert not state_machine.can_accept_control

    def test_control_permission(self) -> None:
        """测试控制指令权限判断。"""
        state_machine = StateMachine()

        # DISCONNECTED 不接受控制
        assert not state_machine.can_accept_control

        # STANDBY 接受控制
        state_machine.update_heartbeat(time.time())
        assert state_machine.can_accept_control

        # E_STOP_TRIGGERED 不接受控制
        state_machine.trigger_emergency_stop()
        assert not state_machine.can_accept_control


@pytest.mark.asyncio
class TestTelemetryQueueManager:
    """遥测队列管理器单元测试。"""

    async def test_add_telemetry(self) -> None:
        """测试添加遥测数据到缓冲区。"""
        manager = TelemetryQueueManager()

        snapshot = TelemetrySnapshotDTO(
            attitude=AttitudeDTO(pitch=0.1, roll=0.2, yaw=1.5),
            battery=BatteryDTO(voltage=84.0, remaining_pct=80),
            system_status=SystemStatusDTO(
                armed=False,
                mode="STABILIZE",
                mavlink_connected=True,
            ),
        )

        manager.add_telemetry(snapshot)

        # 数据应在缓冲区中
        assert len(manager._snapshot_buffer) > 0

    async def test_broadcast_queue(self) -> None:
        """测试广播队列数据获取。"""
        manager = TelemetryQueueManager()

        snapshot = TelemetrySnapshotDTO(
            attitude=AttitudeDTO(pitch=0.1, roll=0.2, yaw=1.5),
            battery=BatteryDTO(voltage=84.0, remaining_pct=80),
            system_status=SystemStatusDTO(
                armed=False,
                mode="STABILIZE",
                mavlink_connected=True,
            ),
        )

        # 添加数据
        manager.add_telemetry(snapshot)

        # 启动采样任务
        stop_event = asyncio.Event()
        sampling_task = asyncio.create_task(manager.start_sampling_task(stop_event))

        # 等待采样完成
        await asyncio.sleep(0.2)

        # 从广播队列获取数据
        received = await asyncio.wait_for(
            manager.get_next_broadcast_snapshot(), timeout=1.0
        )

        assert received is not None
        assert received.attitude is not None

        # 清理
        stop_event.set()
        sampling_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sampling_task

    async def test_ws_client_management(self) -> None:
        """测试 WebSocket 客户端连接池管理。"""
        manager = TelemetryQueueManager()

        # 模拟客户端
        client1 = "ws_client_1"
        client2 = "ws_client_2"

        manager.add_ws_client(client1)
        manager.add_ws_client(client2)

        clients = manager.get_ws_clients()
        assert len(clients) == 2
        assert client1 in clients
        assert client2 in clients

        # 移除一个客户端
        manager.remove_ws_client(client1)

        clients = manager.get_ws_clients()
        assert len(clients) == 1
        assert client1 not in clients
        assert client2 in clients


@pytest.mark.asyncio
class TestIntegration:
    """集成测试：状态机 + 队列管理器。"""

    async def test_telemetry_flow(self) -> None:
        """测试遥测数据完整流程。"""
        # 创建组件
        state_machine = StateMachine()
        queue_manager = TelemetryQueueManager()

        # 模拟遥测快照
        snapshot = TelemetrySnapshotDTO(
            attitude=AttitudeDTO(pitch=0.1, roll=0.2, yaw=1.5),
            position=PositionDTO(lat=39.9, lon=116.4, alt=1.2, hdg=180.0),
            battery=BatteryDTO(voltage=84.0, remaining_pct=80),
            system_status=SystemStatusDTO(
                armed=True,
                mode="AUTO",
                mavlink_connected=True,
            ),
        )

        # 添加到队列
        queue_manager.add_telemetry(snapshot)

        # 更新状态机
        state_machine.update_heartbeat(time.time())
        state_machine.update_armed_status(True)

        # 验证状态
        assert state_machine.state == SystemState.IN_MISSION
        assert len(queue_manager._snapshot_buffer) > 0
