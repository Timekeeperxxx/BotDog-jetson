import pytest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock
from backend.config import settings
from backend.control_service import (
    ControlService,
    RESULT_ACCEPTED,
    RESULT_REJECTED_INVALID_CMD,
    RESULT_REJECTED_E_STOP,
    RESULT_RATE_LIMITED,
    RESULT_REJECTED_ADAPTER_NOT_READY,
    RESULT_REJECTED_ADAPTER_ERROR,
    RESULT_REJECTED_SAFETY_BLOCKED,
)
from backend.robot_adapter import BaseRobotAdapter
from backend.state_machine import StateMachine, SystemState
from backend.state_machine_state import set_state_machine

class MockAdapter(BaseRobotAdapter):
    def is_ready(self):
        return True

    async def send_command(self, cmd, vx=None, vyaw=None):
        pass

@pytest.fixture
def adapter():
    return MockAdapter()

@pytest.fixture
def control_service(adapter):
    return ControlService(adapter=adapter, cmd_rate_limit_ms=0)


@pytest.fixture(autouse=True)
def state_machine_context():
    sm = StateMachine()
    sm.update_heartbeat(time.time())
    set_state_machine(sm)
    yield sm
    set_state_machine(None)
    settings.SAFETY_BLOCK_MOTION_WHEN_DISCONNECTED = True

@pytest.mark.asyncio
async def test_handle_command_accepted(control_service, adapter):
    adapter.send_command = AsyncMock()
    res = await control_service.handle_command("forward")
    assert res.result == RESULT_ACCEPTED
    adapter.send_command.assert_called_once_with("forward", vx=None, vyaw=None)

@pytest.mark.asyncio
async def test_handle_command_invalid(control_service):
    res = await control_service.handle_command("invalid_cmd")
    assert res.result == RESULT_REJECTED_INVALID_CMD

@pytest.mark.asyncio
async def test_handle_command_not_ready(control_service, adapter):
    adapter.is_ready = MagicMock(return_value=False)
    res = await control_service.handle_command("forward")
    assert res.result == RESULT_REJECTED_SAFETY_BLOCKED
    assert res.safety_reason == "控制适配器未就绪"
    assert res.safety_reasons == ["控制适配器未就绪"]

@pytest.mark.asyncio
async def test_handle_command_adapter_error(control_service, adapter):
    adapter.send_command = AsyncMock(side_effect=RuntimeError("SDK Error"))
    res = await control_service.handle_command("forward")
    assert res.result == RESULT_REJECTED_ADAPTER_ERROR


@pytest.mark.asyncio
async def test_handle_command_blocked_when_disconnected(adapter, state_machine_context):
    state_machine_context._state = SystemState.DISCONNECTED
    cs = ControlService(adapter=adapter, cmd_rate_limit_ms=0)
    res = await cs.handle_command("forward")
    assert res.result == RESULT_REJECTED_SAFETY_BLOCKED
    assert res.safety_reason == "底层链路断开"
    assert res.safety_reasons == ["底层链路断开"]


@pytest.mark.asyncio
async def test_handle_command_allows_disconnected_when_config_disabled(adapter, state_machine_context):
    settings.SAFETY_BLOCK_MOTION_WHEN_DISCONNECTED = False
    state_machine_context._state = SystemState.DISCONNECTED
    adapter.send_command = AsyncMock()
    cs = ControlService(adapter=adapter, cmd_rate_limit_ms=0)
    res = await cs.handle_command("forward")
    assert res.result == RESULT_ACCEPTED
    assert res.safety_reason is None
    assert res.safety_reasons == []

@pytest.mark.asyncio
async def test_handle_command_rate_limit(adapter):
    # Set rate limit to 1 second
    cs = ControlService(adapter=adapter, cmd_rate_limit_ms=1000)
    res1 = await cs.handle_command("forward")
    assert res1.result == RESULT_ACCEPTED

    res2 = await cs.handle_command("forward")
    assert res2.result == RESULT_RATE_LIMITED

@pytest.mark.asyncio
async def test_handle_command_stop_ignores_rate_limit(adapter):
    cs = ControlService(adapter=adapter, cmd_rate_limit_ms=1000)
    res1 = await cs.handle_command("forward")
    assert res1.result == RESULT_ACCEPTED

    res2 = await cs.handle_command("stop")
    assert res2.result == RESULT_ACCEPTED

# ── adapter=None 语义测试 ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_command_adapter_none():
    """adapter=None 时，所有控制命令应返回 REJECTED_ADAPTER_NOT_READY。"""
    cs = ControlService(adapter=None, cmd_rate_limit_ms=0)
    motion_cmds = ("forward", "backward", "left", "right", "strafe_left", "strafe_right")
    for cmd in motion_cmds:
        res = await cs.handle_command(cmd)
        assert res.result == RESULT_REJECTED_SAFETY_BLOCKED, f"cmd={cmd!r} 应被安全监督拒绝"

    for cmd in ("stop", "stand", "sit"):
        res = await cs.handle_command(cmd)
        assert res.result == RESULT_REJECTED_ADAPTER_NOT_READY, f"cmd={cmd!r} 应因适配器未就绪被拒绝"

@pytest.mark.asyncio
async def test_set_adapter_none_rejects_commands(adapter):
    """set_adapter(None) 后，命令应被拒绝。"""
    cs = ControlService(adapter=adapter, cmd_rate_limit_ms=0)
    # 初始时应接受
    res = await cs.handle_command("forward")
    assert res.result == RESULT_ACCEPTED

    cs.set_adapter(None)
    res = await cs.handle_command("forward")
    assert res.result == RESULT_REJECTED_SAFETY_BLOCKED

@pytest.mark.asyncio
async def test_set_adapter_replaces_correctly(adapter):
    """set_adapter(new_adapter) 后，命令应由新适配器处理。"""
    cs = ControlService(adapter=None, cmd_rate_limit_ms=0)
    res = await cs.handle_command("forward")
    assert res.result == RESULT_REJECTED_SAFETY_BLOCKED

    cs.set_adapter(adapter)
    res = await cs.handle_command("forward")
    assert res.result == RESULT_ACCEPTED

def test_get_adapter_status_none():
    """adapter=None 时 get_adapter_status 返回 ready=False 且 type=None。"""
    cs = ControlService(adapter=None)
    status = cs.get_adapter_status()
    assert status["type"] is None
    assert status["ready"] is False

def test_get_adapter_status_ready(adapter):
    """适配器就绪时 get_adapter_status 返回正确类型和 ready=True。"""
    cs = ControlService(adapter=adapter)
    status = cs.get_adapter_status()
    assert status["type"] == "MockAdapter"
    assert status["ready"] is True
