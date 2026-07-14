from __future__ import annotations

import asyncio
import math
import socket
from types import SimpleNamespace

import pytest

from backend.control_arbiter import ControlArbiter
from backend.control_service import ControlService
from backend.navigation_velocity_udp import (
    DATAGRAM_ACCEPTED,
    DATAGRAM_REJECTED_CONTROL,
    DATAGRAM_REJECTED_OWNER,
    DATAGRAM_REJECTED_SIZE,
    DATAGRAM_REJECTED_SOURCE,
    DATAGRAM_REJECTED_VALUE,
    NAVIGATION_VELOCITY_PACKET,
    NavigationVelocityUdpService,
    get_navigation_velocity_udp_service,
    get_navigation_velocity_udp_status,
    is_navigation_velocity_udp_ready,
    set_navigation_velocity_udp_service,
)
from backend.robot_adapter import BaseRobotAdapter
from backend.state_machine import SystemState
from backend.state_machine_state import set_state_machine
from backend.tracking_types import ControlOwner


class ManualClock:
    def __init__(self) -> None:
        self.now = 10.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class RecordingAdapter(BaseRobotAdapter):
    def __init__(self) -> None:
        self.ready = True
        self.velocities: list[tuple[float, float, float]] = []
        self.commands: list[str] = []

    def is_ready(self) -> bool:
        return self.ready

    async def send_command(self, cmd: str, *, vx=None, vyaw=None) -> None:
        self.commands.append(cmd)

    async def send_velocity(self, vx: float, vy: float, vyaw: float) -> None:
        self.velocities.append((vx, vy, vyaw))


@pytest.fixture
def velocity_service():
    clock = ManualClock()
    adapter = RecordingAdapter()
    state_machine = SimpleNamespace(state=SystemState.STANDBY)
    control_service = ControlService(adapter=adapter, state_machine=state_machine)
    arbiter = ControlArbiter()
    service = NavigationVelocityUdpService(
        control_service=control_service,
        control_arbiter=arbiter,
        clock=clock,
    )
    set_state_machine(state_machine)
    yield service, clock, adapter, state_machine, arbiter
    service.close()
    set_state_machine(None)


def packet(vx: float, vy: float, vyaw: float) -> bytes:
    return NAVIGATION_VELOCITY_PACKET.pack(vx, vy, vyaw)


@pytest.mark.asyncio
async def test_udp_run_loop_stays_alive_and_receives_on_python310():
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()

    adapter = RecordingAdapter()
    state_machine = SimpleNamespace(state=SystemState.STANDBY)
    set_state_machine(state_machine)
    arbiter = ControlArbiter()
    arbiter.request_control(ControlOwner.NAVIGATION)
    service = NavigationVelocityUdpService(
        control_service=ControlService(adapter=adapter, state_machine=state_machine),
        control_arbiter=arbiter,
        port=port,
    )
    stop_event = asyncio.Event()
    service.bind()
    task = asyncio.create_task(service.run(stop_event))
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sender.sendto(packet(0.2, 0.0, -0.1), ("127.0.0.1", port))
        for _ in range(20):
            if adapter.velocities:
                break
            await asyncio.sleep(0.01)

        assert task.done() is False
        assert adapter.velocities == [(0.2, 0.0, -0.1)]
    finally:
        sender.close()
        stop_event.set()
        await asyncio.wait_for(task, timeout=1.0)
        set_state_machine(None)


@pytest.mark.asyncio
async def test_valid_navigation_velocity_is_clamped_and_forwarded(velocity_service):
    service, _, adapter, _, arbiter = velocity_service
    arbiter.request_control(ControlOwner.NAVIGATION)

    result = await service.handle_datagram(packet(2.0, -1.0, 1.5))

    assert result == DATAGRAM_ACCEPTED
    assert adapter.velocities == [(0.6, -0.4, 0.8)]
    assert service.get_status()["stream_active"] is True


@pytest.mark.asyncio
async def test_nonzero_navigation_velocity_is_rejected_when_link_disconnected(velocity_service):
    service, _, adapter, state_machine, arbiter = velocity_service
    arbiter.request_control(ControlOwner.NAVIGATION)
    state_machine.state = SystemState.DISCONNECTED

    result = await service.handle_datagram(packet(0.2, 0.0, 0.0))

    assert result == DATAGRAM_REJECTED_CONTROL
    assert adapter.velocities == []


@pytest.mark.asyncio
async def test_malformed_nonfinite_and_nonlocal_datagrams_are_rejected(velocity_service):
    service, _, adapter, _, arbiter = velocity_service
    arbiter.request_control(ControlOwner.NAVIGATION)

    assert await service.handle_datagram(b"short") == DATAGRAM_REJECTED_SIZE
    assert (
        await service.handle_datagram(packet(math.nan, 0.0, 0.0))
        == DATAGRAM_REJECTED_VALUE
    )
    assert (
        await service.handle_datagram(packet(0.0, math.inf, 0.0))
        == DATAGRAM_REJECTED_VALUE
    )
    assert (
        await service.handle_datagram(
            packet(0.1, 0.0, 0.0),
            source=("192.168.123.1", 40000),
        )
        == DATAGRAM_REJECTED_SOURCE
    )
    assert adapter.velocities == []


@pytest.mark.asyncio
async def test_owner_gate_discards_packets_outside_navigation(velocity_service):
    service, _, adapter, _, arbiter = velocity_service

    assert (
        await service.handle_datagram(packet(0.2, 0.0, 0.0))
        == DATAGRAM_REJECTED_OWNER
    )
    arbiter.request_control(ControlOwner.NAVIGATION)
    assert await service.handle_datagram(packet(0.2, 0.0, 0.0)) == DATAGRAM_ACCEPTED
    assert adapter.velocities == [(0.2, 0.0, 0.0)]


@pytest.mark.asyncio
async def test_adapter_ready_and_state_machine_estop_are_checked(velocity_service):
    service, _, adapter, state_machine, arbiter = velocity_service
    arbiter.request_control(ControlOwner.NAVIGATION)

    adapter.ready = False
    assert (
        await service.handle_datagram(packet(0.2, 0.0, 0.0))
        == DATAGRAM_REJECTED_CONTROL
    )

    adapter.ready = True
    state_machine.state = SystemState.E_STOP_TRIGGERED
    assert (
        await service.handle_datagram(packet(0.2, 0.0, 0.0))
        == DATAGRAM_REJECTED_CONTROL
    )
    assert adapter.velocities == []


@pytest.mark.asyncio
async def test_datagram_timeout_soft_stops_once_while_navigation_owns_control(velocity_service):
    service, clock, adapter, _, arbiter = velocity_service
    arbiter.request_control(ControlOwner.NAVIGATION)
    assert await service.handle_datagram(packet(0.2, 0.0, 0.0)) == DATAGRAM_ACCEPTED

    clock.advance(0.499)
    await service.poll_safety()
    assert adapter.commands == []
    assert adapter.velocities == [(0.2, 0.0, 0.0)]

    clock.advance(0.002)
    await service.poll_safety()
    await service.poll_safety()
    assert adapter.commands == []
    assert adapter.velocities == [(0.2, 0.0, 0.0), (0.0, 0.0, 0.0)]
    assert service.get_status()["stop_count"] == 1


@pytest.mark.asyncio
async def test_navigation_to_none_soft_stops_once_and_discards_later_zeroes(velocity_service):
    service, _, adapter, _, arbiter = velocity_service
    arbiter.request_control(ControlOwner.NAVIGATION)
    assert await service.handle_datagram(packet(0.2, 0.0, 0.0)) == DATAGRAM_ACCEPTED

    arbiter.release_control(ControlOwner.NAVIGATION)
    assert (
        await service.handle_datagram(packet(0.0, 0.0, 0.0))
        == DATAGRAM_REJECTED_OWNER
    )
    assert (
        await service.handle_datagram(packet(0.0, 0.0, 0.0))
        == DATAGRAM_REJECTED_OWNER
    )
    assert adapter.commands == []
    assert adapter.velocities == [(0.2, 0.0, 0.0), (0.0, 0.0, 0.0)]


@pytest.mark.asyncio
async def test_navigation_to_estop_owner_stops_once(velocity_service):
    service, _, adapter, _, arbiter = velocity_service
    arbiter.request_control(ControlOwner.NAVIGATION)
    assert await service.handle_datagram(packet(0.2, 0.0, 0.0)) == DATAGRAM_ACCEPTED

    arbiter.request_control(ControlOwner.E_STOP)
    await service.poll_safety()
    await service.poll_safety()
    assert adapter.commands == ["stop"]


@pytest.mark.asyncio
async def test_state_machine_estop_stops_active_navigation_stream_once(velocity_service):
    service, _, adapter, state_machine, arbiter = velocity_service
    arbiter.request_control(ControlOwner.NAVIGATION)
    assert await service.handle_datagram(packet(0.2, 0.0, 0.0)) == DATAGRAM_ACCEPTED

    state_machine.state = SystemState.E_STOP_TRIGGERED
    await service.poll_safety()
    await service.poll_safety()
    assert adapter.commands == ["stop"]


@pytest.mark.parametrize(
    "competing_owner",
    [
        ControlOwner.WEB_MANUAL,
        ControlOwner.AUTO_TRACK,
        ControlOwner.GUARD_MISSION,
        ControlOwner.REMOTE_CONTROLLER,
    ],
)
@pytest.mark.asyncio
async def test_competing_owner_transition_never_sends_delayed_stop(
    velocity_service,
    competing_owner,
):
    service, clock, adapter, _, arbiter = velocity_service
    arbiter.request_control(ControlOwner.NAVIGATION)
    assert await service.handle_datagram(packet(0.2, 0.0, 0.0)) == DATAGRAM_ACCEPTED

    arbiter.request_control(competing_owner)
    clock.advance(1.0)
    await service.poll_safety()
    assert (
        await service.handle_datagram(packet(0.0, 0.0, 0.0))
        == DATAGRAM_REJECTED_OWNER
    )
    assert adapter.commands == []


@pytest.mark.asyncio
async def test_pending_none_stop_is_cancelled_if_manual_takes_control(velocity_service):
    service, _, adapter, _, arbiter = velocity_service
    arbiter.request_control(ControlOwner.NAVIGATION)
    assert await service.handle_datagram(packet(0.2, 0.0, 0.0)) == DATAGRAM_ACCEPTED

    arbiter.release_control(ControlOwner.NAVIGATION)
    arbiter.request_control(ControlOwner.WEB_MANUAL)
    await service.poll_safety()
    assert adapter.commands == []


def test_module_status_accessors_do_not_require_a_socket(velocity_service):
    service, _, _, _, _ = velocity_service
    set_navigation_velocity_udp_service(service)
    try:
        assert get_navigation_velocity_udp_service() is service
        assert is_navigation_velocity_udp_ready() is False
        status = get_navigation_velocity_udp_status()
        assert status["host"] == "127.0.0.1"
        assert status["port"] == 52345
    finally:
        set_navigation_velocity_udp_service(None)


def test_bind_uses_fixed_loopback_endpoint_without_real_socket(
    velocity_service,
    monkeypatch,
):
    original_service, clock, adapter, state_machine, arbiter = velocity_service
    original_service.close()

    class FakeSocket:
        def __init__(self) -> None:
            self.blocking = True
            self.bound_to = None
            self.closed = False

        def setblocking(self, value: bool) -> None:
            self.blocking = value

        def bind(self, address) -> None:
            self.bound_to = address

        def close(self) -> None:
            self.closed = True

    fake_socket = FakeSocket()
    monkeypatch.setattr(
        "backend.navigation_velocity_udp.socket.socket",
        lambda *_args, **_kwargs: fake_socket,
    )
    service = NavigationVelocityUdpService(
        control_service=ControlService(adapter=adapter, state_machine=state_machine),
        control_arbiter=arbiter,
        clock=clock,
    )
    try:
        service.bind()
        assert fake_socket.bound_to == ("127.0.0.1", 52345)
        assert fake_socket.blocking is False
        assert service.is_ready is True
    finally:
        service.close()
    assert fake_socket.closed is True


def test_service_rejects_non_loopback_bind_address(velocity_service):
    _, clock, adapter, state_machine, arbiter = velocity_service
    control_service = ControlService(adapter=adapter, state_machine=state_machine)
    with pytest.raises(ValueError, match="127.0.0.1"):
        NavigationVelocityUdpService(
            control_service=control_service,
            control_arbiter=arbiter,
            host="0.0.0.0",
            clock=clock,
        )


def test_activate_estop_clears_stale_requesters_and_notifies_listener():
    arbiter = ControlArbiter()
    transitions: list[tuple[ControlOwner, ControlOwner]] = []
    arbiter.add_owner_change_listener(lambda old, new: transitions.append((old, new)))
    arbiter.request_control(ControlOwner.NAVIGATION)
    arbiter.request_control(ControlOwner.WEB_MANUAL)

    arbiter.activate_e_stop()
    assert arbiter.owner == ControlOwner.E_STOP
    assert arbiter.get_status()["active_requesters"] == [ControlOwner.E_STOP.value]
    assert transitions[-1] == (ControlOwner.WEB_MANUAL, ControlOwner.E_STOP)

    arbiter.release_control(ControlOwner.E_STOP)
    assert arbiter.owner == ControlOwner.NONE
