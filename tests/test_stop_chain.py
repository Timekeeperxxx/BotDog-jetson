"""Real worker/Pipe protocol with a fake Unitree SDK. No robot SDK is imported."""

import asyncio
import logging
import multiprocessing
import queue
import sys
import threading
import time
from types import ModuleType, SimpleNamespace

import pytest

from backend import robot_adapter, unitree_b2_sidecar as sidecar
from backend.control_service import ControlService, RESULT_ACCEPTED, RESULT_REJECTED_ADAPTER_ERROR
from backend.robot_adapter import UnitreeB2Adapter


def install_fake_sdk(client, monkeypatch=None):
    modules = {}
    for name in ["unitree_sdk2py", "unitree_sdk2py.b2", "unitree_sdk2py.b2.sport",
                 "unitree_sdk2py.b2.sport.sport_client", "unitree_sdk2py.core", "unitree_sdk2py.core.channel"]:
        modules[name] = ModuleType(name)
    modules["unitree_sdk2py.b2.sport.sport_client"].SportClient = lambda: client
    modules["unitree_sdk2py.core.channel"].ChannelFactoryInitialize = lambda *args: None
    for name, module in modules.items():
        if monkeypatch is None:
            sys.modules[name] = module
        else:
            monkeypatch.setitem(sys.modules, name, module)


class FakeSDK:
    def __init__(self):
        self.calls = []
        self.posture_entered = threading.Event()
        self.posture_release = threading.Event()
        self.posture_release.set()
        self.zero_entered = threading.Event()
        self.zero_release = threading.Event()
        self.zero_release.set()
        self.zero_result = 0
        self.terminal_result = 0

    def SetTimeout(self, timeout):
        pass

    def Init(self):
        pass

    def Move(self, vx, vy, vyaw):
        self.calls.append(("Move", vx, vy, vyaw))
        if (vx, vy, vyaw) == (0.0, 0.0, 0.0):
            self.zero_entered.set()
            assert self.zero_release.wait(4), "Test did not release fake stop SDK call"
            if isinstance(self.zero_result, Exception):
                raise self.zero_result
            return self.zero_result
        return 0

    def _posture(self, name):
        self.calls.append((name,))
        self.posture_entered.set()
        assert self.posture_release.wait(4), "Test did not release fake posture SDK call"
        return 0

    def BalanceStand(self):
        return self._posture("BalanceStand")

    def StandDown(self):
        return self._posture("StandDown")

    def StopMove(self):
        self.calls.append(("StopMove",))
        if isinstance(self.terminal_result, Exception):
            raise self.terminal_result
        return self.terminal_result


class ThreadProcess:
    """Process API for the in-process fake-SDK child thread."""
    def __init__(self, thread):
        self.thread = thread

    def is_alive(self):
        return self.thread.is_alive()

    def join(self, timeout=None):
        self.thread.join(timeout)

    def terminate(self):
        raise AssertionError("Fake child must stop normally, without termination")


@pytest.fixture
def link(monkeypatch):
    sdk = FakeSDK()
    install_fake_sdk(sdk, monkeypatch)
    monkeypatch.setattr(sidecar, "_clean_ros_environment", lambda: None)
    parent, child = multiprocessing.Pipe()
    child_thread = threading.Thread(target=sidecar.run_unitree_b2_sidecar,
                                    args=(child, "FAKE_NO_NETWORK", 0.3, 0.25, 0.5), daemon=True)
    child_thread.start()
    assert parent.poll(2)
    assert parent.recv()["ready"] is True
    adapter = UnitreeB2Adapter.__new__(UnitreeB2Adapter)
    adapter._initialized = True
    adapter._sport_client = object()
    adapter._sidecar_conn = parent
    adapter._sidecar_process = ThreadProcess(child_thread)
    adapter._sidecar_pid = None
    adapter._busy_with_posture = False
    adapter._motion_mode_enabled = False
    adapter._last_motion_prepare_result = None
    adapter._last_worker_error = None
    adapter._last_velocity = adapter._last_velocity_at = adapter._last_move_return = None
    adapter._executed_velocity_count = adapter._executed_nonzero_velocity_count = 0
    adapter._last_nonzero_velocity = adapter._last_nonzero_velocity_at = None
    adapter._vx, adapter._vy, adapter._vyaw = 0.3, 0.25, 0.5
    adapter._cmd_queue = queue.Queue(maxsize=1)
    adapter._command_lock = threading.Lock()
    adapter._stop_request = None
    adapter._close_lock = threading.Lock()
    adapter._closed = False
    adapter._worker_thread = threading.Thread(target=adapter._command_worker, daemon=True)
    yield SimpleNamespace(adapter=adapter, sdk=sdk, parent=parent, child=child,
                         child_thread=child_thread, start=adapter._worker_thread.start)
    sdk.posture_release.set()
    sdk.zero_release.set()
    adapter.close()
    child_thread.join(3)
    assert not child_thread.is_alive()
    assert not adapter._worker_thread.is_alive()


async def entered(event):
    assert await asyncio.to_thread(event.wait, 2), "Fake SDK call was not reached"


async def request_latched(adapter):
    for _ in range(100):
        if adapter._stop_request is not None:
            return
        await asyncio.sleep(0.001)
    pytest.fail("Stop was discarded rather than latched")


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["force_stop", "command", "zero_velocity"])
async def test_stop_not_dropped_while_posture_is_busy(link, path):
    adapter, sdk = link.adapter, link.sdk
    adapter._busy_with_posture = True
    sdk.zero_release.clear()
    link.start()
    service = ControlService(adapter)
    if path == "force_stop":
        task = asyncio.create_task(service.force_stop())
    elif path == "command":
        task = asyncio.create_task(service.handle_command("stop"))
    else:
        task = asyncio.create_task(service.send_navigation_velocity(0, 0, 0))
    await entered(sdk.zero_entered)
    assert not task.done(), "Must not acknowledge stop before the SDK reply"
    sdk.zero_release.set()
    result = await asyncio.wait_for(task, 2)
    if path == "zero_velocity":
        assert result is True
    else:
        assert result.result == RESULT_ACCEPTED
    assert sdk.calls == [("Move", 0.0, 0.0, 0.0)]


@pytest.mark.asyncio
@pytest.mark.parametrize("posture,call", [("stand", "BalanceStand"), ("sit", "StandDown")])
async def test_inflight_posture_finishes_then_priority_stop_executes(link, posture, call):
    adapter, sdk = link.adapter, link.sdk
    sdk.posture_release.clear()
    link.start()
    await adapter.send_command(posture)
    await entered(sdk.posture_entered)
    task = asyncio.create_task(ControlService(adapter).force_stop())
    await request_latched(adapter)
    assert not task.done()
    sdk.posture_release.set()
    assert (await asyncio.wait_for(task, 2)).result == RESULT_ACCEPTED
    assert sdk.calls[-2:] == [(call,), ("Move", 0.0, 0.0, 0.0)]


@pytest.mark.asyncio
async def test_stop_cancels_queued_posture_before_it_reaches_sdk(link):
    await link.adapter.send_command("stand")
    task = asyncio.create_task(link.adapter.stop())
    await request_latched(link.adapter)
    link.start()
    await asyncio.wait_for(task, 2)
    assert link.sdk.calls == [("Move", 0.0, 0.0, 0.0)]


@pytest.mark.asyncio
async def test_stop_cancels_pending_navigation_and_wakes_its_caller(link):
    prepared = asyncio.create_task(link.adapter.prepare_navigation_motion())
    await asyncio.sleep(0)
    task = asyncio.create_task(link.adapter.stop())
    await request_latched(link.adapter)
    with pytest.raises(RuntimeError, match="停止请求取消"):
        await prepared
    link.start()
    await asyncio.wait_for(task, 2)
    assert link.sdk.calls == [("Move", 0.0, 0.0, 0.0)]


@pytest.mark.asyncio
async def test_latched_stop_cannot_be_overwritten_and_concurrent_stops_share_ack(link):
    adapter, sdk = link.adapter, link.sdk
    sdk.zero_release.clear()
    link.start()
    first = asyncio.create_task(adapter.stop())
    await entered(sdk.zero_entered)
    second = asyncio.create_task(adapter.send_command("stop"))
    await asyncio.sleep(0)
    for command in ["forward", "stand", "sit"]:
        with pytest.raises(RuntimeError, match="停止请求尚未完成"):
            await adapter.send_command(command)
    with pytest.raises(RuntimeError, match="停止请求尚未完成"):
        await adapter.send_velocity(0.2, 0, 0)
    with pytest.raises(RuntimeError, match="停止请求尚未完成"):
        await adapter.prepare_navigation_motion()
    assert not first.done() and not second.done()
    sdk.zero_release.set()
    await asyncio.wait_for(asyncio.gather(first, second), 2)
    assert sdk.calls == [("Move", 0.0, 0.0, 0.0)]


@pytest.mark.asyncio
async def test_worker_does_not_replay_command_taken_just_before_stop(link):
    taken, release = threading.Event(), threading.Event()

    class HandoffQueue(queue.Queue):
        def get(self, *args, **kwargs):
            item = super().get(*args, **kwargs)
            if item == "forward":
                taken.set()
                assert release.wait(2)
            return item

    link.adapter._cmd_queue = HandoffQueue(maxsize=1)
    link.start()
    await link.adapter.send_command("forward")
    await entered(taken)
    task = asyncio.create_task(link.adapter.stop())
    await request_latched(link.adapter)
    release.set()
    await asyncio.wait_for(task, 2)
    assert link.sdk.calls == [("Move", 0.0, 0.0, 0.0)]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [3104, RuntimeError("fake SDK stop failure")])
async def test_stop_sdk_failure_is_rejected_not_reported_as_success(link, failure):
    link.sdk.zero_result = failure
    link.start()
    result = await ControlService(link.adapter).force_stop()
    assert result.result == RESULT_REJECTED_ADAPTER_ERROR
    assert not link.adapter.is_ready()
    link.child_thread.join(2)
    assert ("StopMove",) in link.sdk.calls
    with pytest.raises(RuntimeError, match="未就绪"):
        await link.adapter.send_command("forward")


@pytest.mark.asyncio
async def test_wait_timeout_keeps_stop_latched_until_sdk_reply(link, monkeypatch):
    monkeypatch.setattr(robot_adapter, "UNITREE_STOP_TIMEOUT_S", 0.05)
    link.sdk.zero_release.clear()
    link.start()
    result = await ControlService(link.adapter).force_stop()
    assert result.result == RESULT_REJECTED_ADAPTER_ERROR
    completed = link.adapter._stop_request[0]
    with pytest.raises(RuntimeError, match="停止请求尚未完成"):
        await link.adapter.send_command("forward")
    link.sdk.zero_release.set()
    await entered(completed)
    assert link.adapter._stop_request is None


@pytest.mark.asyncio
@pytest.mark.parametrize("sdk_return,expected", [(0, RESULT_ACCEPTED), (3104, RESULT_REJECTED_ADAPTER_ERROR)])
async def test_stop_route_waits_for_fake_sdk_confirmation(link, monkeypatch, sdk_return, expected):
    import httpx
    from fastapi import FastAPI
    from backend.api.routes import control
    from backend.auth.dependencies import require_operator
    from backend.auth.schemas import AuthUserInternal
    from backend.database import get_db
    from backend import control_arbiter

    app = FastAPI()
    app.include_router(control.router)
    app.dependency_overrides[require_operator] = lambda: AuthUserInternal(id=1, username="fake-operator", role="operator", token_version=0)

    async def no_db():
        yield None

    app.dependency_overrides[get_db] = no_db
    monkeypatch.setattr(control, "get_control_service", lambda: ControlService(link.adapter))
    monkeypatch.setattr(control_arbiter, "get_control_arbiter", lambda: None)
    link.sdk.zero_release.clear()
    link.sdk.zero_result = sdk_return
    link.start()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        request = asyncio.create_task(client.post("/api/v1/control/stop"))
        await entered(link.sdk.zero_entered)
        assert not request.done()
        link.sdk.zero_release.set()
        response = await asyncio.wait_for(request, 2)
        assert response.status_code == 200
        assert response.json()["result"] == expected


@pytest.mark.asyncio
async def test_watchdog_can_stop_during_posture_work(link):
    adapter = link.adapter
    adapter._busy_with_posture = True
    link.sdk.zero_release.clear()
    link.start()
    service = ControlService(adapter, watchdog_timeout_ms=50)
    service._watchdog_active = True
    service._watchdog_last_reset = time.monotonic() - 1
    stop_event = asyncio.Event()
    task = asyncio.create_task(service.run_watchdog(stop_event))
    try:
        await entered(link.sdk.zero_entered)
        completed = adapter._stop_request[0]
        link.sdk.zero_release.set()
        await entered(completed)
        assert link.sdk.calls == [("Move", 0.0, 0.0, 0.0)]
    finally:
        link.sdk.zero_release.set()
        stop_event.set()
        await asyncio.wait_for(task, 2)


@pytest.mark.asyncio
async def test_close_cancels_pending_stop_and_wakes_waiter(link):
    task = asyncio.create_task(link.adapter.stop())
    await request_latched(link.adapter)
    link.adapter.close()
    with pytest.raises(RuntimeError, match="适配器正在关闭"):
        await asyncio.wait_for(task, 1)
    assert link.sdk.calls == [("StopMove",)]


class ScriptedConnection:
    def __init__(self, commands=(), recv_error=None, fail_send_at=None):
        self.commands = iter(commands)
        self.recv_error = recv_error or EOFError()
        self.fail_send_at = fail_send_at
        self.sent = []
        self.send_count = 0
        self.closed = False

    def recv(self):
        try:
            return next(self.commands)
        except StopIteration:
            raise self.recv_error

    def send(self, message):
        self.send_count += 1
        if self.send_count == self.fail_send_at:
            raise BrokenPipeError("fake parent disconnected")
        self.sent.append(message)

    def close(self):
        self.closed = True


@pytest.fixture
def scripted_sdk(monkeypatch):
    sdk = FakeSDK()
    install_fake_sdk(sdk, monkeypatch)
    monkeypatch.setattr(sidecar, "_clean_ros_environment", lambda: None)
    return sdk


@pytest.mark.parametrize("error", [EOFError(), OSError("fake read failure"), ValueError("unexpected loop failure")])
def test_sidecar_stops_on_read_failure(scripted_sdk, error):
    connection = ScriptedConnection([("velocity", 0.2, 0.0, 0.0)], recv_error=error)
    sidecar.run_unitree_b2_sidecar(connection, "FAKE_NO_NETWORK", 0.3, 0.25, 0.5)
    assert scripted_sdk.calls == [("Move", 0.2, 0.0, 0.0), ("StopMove",)]
    assert connection.closed


@pytest.mark.parametrize("fail_send_at", [1, 2])
def test_sidecar_stops_on_failed_ready_or_command_reply(scripted_sdk, fail_send_at):
    connection = ScriptedConnection([("velocity", 0.2, 0, 0), "forward"], fail_send_at=fail_send_at)
    sidecar.run_unitree_b2_sidecar(connection, "FAKE_NO_NETWORK", 0.3, 0.25, 0.5)
    assert scripted_sdk.calls[-1] == ("StopMove",)
    assert ("Move", 0.3, 0.0, 0.0) not in scripted_sdk.calls
    assert connection.closed


def test_normal_sidecar_shutdown_stops_once_and_acknowledges(scripted_sdk):
    connection = ScriptedConnection([("_STOP_AND_QUIT_",)])
    sidecar.run_unitree_b2_sidecar(connection, "FAKE_NO_NETWORK", 0.3, 0.25, 0.5)
    assert scripted_sdk.calls == [("StopMove",)]
    assert connection.sent[-1] == {"ok": True, "return": 0}


@pytest.mark.parametrize("failure", [3104, RuntimeError("fake terminal stop failure")])
def test_terminal_stop_failure_is_observable_and_channel_still_closes(scripted_sdk, caplog, failure):
    scripted_sdk.terminal_result = failure
    connection = ScriptedConnection([("_STOP_AND_QUIT_",)])
    with caplog.at_level(logging.ERROR, logger=sidecar.__name__):
        sidecar.run_unitree_b2_sidecar(connection, "FAKE_NO_NETWORK", 0.3, 0.25, 0.5)
    assert scripted_sdk.calls == [("StopMove",)]
    assert connection.sent[-1]["ok"] is False
    assert "StopMove" in caplog.text
    assert connection.closed


def test_initialization_failure_does_not_call_uninitialized_sdk(scripted_sdk):
    def fail_init():
        raise RuntimeError("fake initialization failure")
    scripted_sdk.Init = fail_init
    connection = ScriptedConnection()
    sidecar.run_unitree_b2_sidecar(connection, "FAKE_NO_NETWORK", 0.3, 0.25, 0.5)
    assert connection.sent[0]["ready"] is False
    assert scripted_sdk.calls == []
    assert connection.closed


def test_ipc_timeout_closes_channel_instead_of_accepting_a_late_reply(link):
    class TimedOutConnection:
        closed = False
        def send(self, command):
            pass
        def poll(self, timeout):
            return False
        def recv(self):
            pytest.fail("A timed-out reply cannot confirm a later stop")
        def close(self):
            self.closed = True

    real_connection = link.adapter._sidecar_conn
    connection = TimedOutConnection()
    link.adapter._sidecar_conn = connection
    try:
        with pytest.raises(RuntimeError, match="响应超时"):
            link.adapter._execute_sidecar_command("stand")
        assert connection.closed
        assert not link.adapter.is_ready()
    finally:
        link.adapter._sidecar_conn = real_connection


def fake_sidecar_process(connection, reports):
    """Spawn target that installs fake modules before the real sidecar imports SDK."""
    class ProcessSDK(FakeSDK):
        def Move(self, vx, vy, vyaw):
            reports.put(("Move", vx, vy, vyaw))
            return 0
        def StopMove(self):
            reports.put(("StopMove",))
            return 0
    install_fake_sdk(ProcessSDK())
    sidecar.run_unitree_b2_sidecar(connection, "FAKE_NO_NETWORK", 0.3, 0.25, 0.5)


def test_real_spawned_process_stops_when_parent_pipe_closes():
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    reports = context.Queue()
    process = context.Process(target=fake_sidecar_process, args=(child, reports))
    process.start()
    child.close()
    try:
        assert parent.poll(5)
        assert parent.recv()["ready"] is True
        parent.send(("velocity", 0.2, 0.0, 0.0))
        assert parent.poll(2)
        assert parent.recv()["ok"] is True
        assert reports.get(timeout=2) == ("Move", 0.2, 0.0, 0.0)
        parent.close()
        assert reports.get(timeout=3) == ("StopMove",)
        process.join(3)
        assert process.exitcode == 0
    finally:
        parent.close()
        process.join(3)
        if process.is_alive():
            process.terminate()
            process.join(2)
        reports.close()
        reports.join_thread()
