import time

from backend.state_machine import StateMachine, SystemState


def test_reset_emergency_stop_releases_to_disconnected_without_heartbeat() -> None:
    transitions: list[tuple[SystemState, SystemState]] = []
    state_machine = StateMachine(on_state_change=lambda old, new: transitions.append((old, new)))

    state_machine.trigger_emergency_stop()
    state_machine.reset_emergency_stop()

    assert state_machine.state == SystemState.DISCONNECTED
    assert transitions[-1] == (
        SystemState.E_STOP_TRIGGERED,
        SystemState.DISCONNECTED,
    )


def test_reset_emergency_stop_recomputes_connected_state() -> None:
    state_machine = StateMachine(heartbeat_timeout=3.0)
    state_machine.update_heartbeat(time.time())
    assert state_machine.state == SystemState.STANDBY

    state_machine.trigger_emergency_stop()
    state_machine.reset_emergency_stop()

    assert state_machine.state == SystemState.STANDBY


def test_reset_emergency_stop_recomputes_active_mission_state() -> None:
    state_machine = StateMachine(heartbeat_timeout=3.0)
    state_machine.update_heartbeat(time.time())
    state_machine.update_mission_status(True)
    assert state_machine.state == SystemState.IN_MISSION

    state_machine.trigger_emergency_stop()
    state_machine.reset_emergency_stop()

    assert state_machine.state == SystemState.IN_MISSION
