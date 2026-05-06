import time

from backend.safety_supervisor import SafetySupervisor
from backend.state_machine import StateMachine
from backend.state_machine_state import set_state_machine


def _set_ready_state_machine() -> StateMachine:
    state_machine = StateMachine()
    state_machine.update_heartbeat(time.time())
    set_state_machine(state_machine)
    return state_machine


def teardown_function():
    set_state_machine(None)


def test_stop_always_allowed():
    set_state_machine(None)
    decision = SafetySupervisor().evaluate_command("stop", adapter_status={"ready": False})
    assert decision.allowed is True
    assert decision.reasons == []


def test_forward_blocked_when_adapter_not_ready():
    _set_ready_state_machine()
    decision = SafetySupervisor().evaluate_command("forward", adapter_status={"ready": False})
    assert decision.allowed is False
    assert "控制适配器未就绪" in decision.reasons


def test_non_motion_command_not_blocked():
    set_state_machine(None)
    decision = SafetySupervisor().evaluate_command("sit", adapter_status={"ready": False})
    assert decision.allowed is True
    assert decision.reasons == []


def test_forward_allowed_when_state_normal_and_adapter_ready():
    _set_ready_state_machine()
    decision = SafetySupervisor().evaluate_command("forward", adapter_status={"ready": True})
    assert decision.allowed is True
    assert decision.reasons == []
