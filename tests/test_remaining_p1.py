"""Emergency-stop and readiness regressions; every actuator/network is mocked."""
import asyncio
import json
import subprocess
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import services_readiness, video_probe, workers_ai
from backend.api.routes import control, system
from backend.config import settings
from backend.control_arbiter import ControlArbiter
from backend.schemas import ControlAckDTO
from backend.services_nav_state import clear_robot_pose, get_nav_freshness, update_robot_pose
from backend.state_machine import StateMachine, SystemState
from backend.workers_ai import AIWorker


@pytest.fixture
def emergency(monkeypatch):
    state = StateMachine()
    state.update_heartbeat(time.time())
    arbiter = ControlArbiter()
    calls = []
    service = SimpleNamespace(force_stop=AsyncMock(return_value=ControlAckDTO(ack_cmd="stop", result="ACCEPTED", latency_ms=10)))
    bridge = SimpleNamespace(**{name: Mock(side_effect=lambda *a, _name=name, **kw: calls.append(_name)) for name in [
        "publish_navigation_task_start", "publish_navigation_start", "publish_navigation_stop", "publish_zero_cmd_vel"]})
    monkeypatch.setattr(control, "get_state_machine", lambda: state)
    monkeypatch.setattr(control, "get_ros_nav_bridge", lambda: bridge)
    monkeypatch.setattr(control, "set_cmd_vel_estop", Mock())
    monkeypatch.setattr(control, "stop_cmd_vel_script", Mock())
    monkeypatch.setattr(control, "safe_write_audit_log", AsyncMock())
    monkeypatch.setattr("backend.control_arbiter.get_control_arbiter", lambda: arbiter)
    monkeypatch.setattr("backend.control_service.get_control_service", lambda: service)
    return SimpleNamespace(state=state, arbiter=arbiter, service=service, bridge=bridge, calls=calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("sdk_result", ["ACCEPTED", "REJECTED_ADAPTER_ERROR", "REJECTED_ADAPTER_NOT_READY"])
async def test_emergency_stop_separates_latching_from_sdk_confirmation(emergency, sdk_result):
    emergency.service.force_stop.return_value = ControlAckDTO(ack_cmd="stop", result=sdk_result, latency_ms=20)
    result = await control.emergency_stop(db=None)
    assert result.e_stop_latched is True
    assert emergency.state.state == SystemState.E_STOP_TRIGGERED
    assert result.stop_confirmed is (sdk_result == "ACCEPTED")
    assert result.success is (sdk_result == "ACCEPTED")
    assert result.control_ack.result == sdk_result
    assert emergency.arbiter.owner.value == "E_STOP"


@pytest.mark.asyncio
async def test_missing_control_service_never_reports_confirmed_stop(emergency, monkeypatch):
    monkeypatch.setattr("backend.control_service.get_control_service", lambda: None)
    result = await control.emergency_stop(db=None)
    assert result.e_stop_latched and not result.stop_confirmed and not result.success
    assert result.control_ack is None and result.errors


@pytest.mark.asyncio
async def test_unexpected_sdk_error_remains_visible_and_latched(emergency):
    emergency.service.force_stop.side_effect = RuntimeError("fake SDK error")
    result = await control.emergency_stop(db=None)
    assert not result.success and not result.stop_confirmed
    assert result.e_stop_latched and "fake SDK error" in str(result.errors)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["clamp", "publisher", "sender"])
async def test_navigation_failure_does_not_prevent_sdk_stop(emergency, monkeypatch, failure):
    if failure == "clamp":
        monkeypatch.setattr(control, "set_cmd_vel_estop", Mock(side_effect=OSError("fake write failure")))
    elif failure == "publisher":
        emergency.bridge.publish_navigation_task_start.side_effect = RuntimeError("fake ROS failure")
    else:
        monkeypatch.setattr(control, "stop_cmd_vel_script", Mock(side_effect=OSError("fake sender failure")))
    result = await control.emergency_stop(db=None)
    emergency.service.force_stop.assert_awaited_once()
    assert result.e_stop_latched and result.stop_confirmed and not result.success
    assert result.errors
    assert "publish_zero_cmd_vel" in emergency.calls


@pytest.mark.asyncio
async def test_slow_navigation_cleanup_does_not_delay_sdk_stop(emergency, monkeypatch):
    release = threading.Event()
    sdk_started = asyncio.Event()
    monkeypatch.setattr(control, "stop_cmd_vel_script", lambda: release.wait(2))

    async def sdk_stop():
        sdk_started.set()
        return ControlAckDTO(ack_cmd="stop", result="ACCEPTED", latency_ms=0)

    emergency.service.force_stop = sdk_stop
    task = asyncio.create_task(control.emergency_stop(db=None))
    try:
        await asyncio.wait_for(sdk_started.wait(), 0.5)
        assert not task.done()
    finally:
        release.set()
    assert (await task).success


@pytest.fixture
def readiness(monkeypatch):
    state = StateMachine()
    state.update_heartbeat(time.time())
    service = SimpleNamespace(get_adapter_status=lambda: {"ready": True})
    ai = SimpleNamespace(get_runtime_status=lambda: {"required": True, "ready": True, "status": "ready", "message": "fake fresh video"})
    monkeypatch.setattr(services_readiness, "get_state_machine", lambda: state)
    monkeypatch.setattr(services_readiness, "get_control_service", lambda: service)
    monkeypatch.setattr(settings, "AI_ENABLED", True)
    monkeypatch.setattr(settings, "ROS_NAV_ENABLED", True)
    update_robot_pose({"x": 0, "y": 0, "timestamp": time.time()})
    yield SimpleNamespace(state=state, service=service, ai=ai)
    clear_robot_pose()


def test_readiness_checks_current_data_not_startup_summary(readiness):
    assert services_readiness.collect_readiness(readiness.ai)["ready"] is True
    readiness.state._last_heartbeat_time = time.time() - 10
    result = services_readiness.collect_readiness(readiness.ai)
    assert not result["ready"] and result["status"] == "standby"
    assert result["components"]["control"]["heartbeat_age_s"] >= 10


def test_estop_does_not_make_stale_telemetry_appear_connected(readiness):
    readiness.state.trigger_emergency_stop()
    readiness.state._last_heartbeat_time = time.time() - 10
    assert readiness.state.state == SystemState.E_STOP_TRIGGERED
    assert readiness.state.is_connected is False
    assert services_readiness.collect_readiness(readiness.ai)["status"] == "degraded"


@pytest.mark.parametrize("offset", [-10, 10])
def test_stale_or_future_navigation_pose_is_not_ready(readiness, offset):
    update_robot_pose({"timestamp": time.time() + offset})
    assert get_nav_freshness()["ready"] is False
    assert services_readiness.collect_readiness(readiness.ai)["ready"] is False


def test_disabled_or_idle_optional_video_is_not_reported_as_healthy(readiness, monkeypatch):
    readiness.ai.get_runtime_status = lambda: {"required": False, "ready": False, "status": "standby", "message": "idle video"}
    result = services_readiness.collect_readiness(readiness.ai)
    assert result["ready"] and result["components"]["video_ai"]["status"] == "standby"
    monkeypatch.setattr(settings, "AI_ENABLED", False)
    monkeypatch.setattr(settings, "ROS_NAV_ENABLED", False)
    result = services_readiness.collect_readiness(None)
    assert result["ready"] and result["components"]["video_ai"]["status"] == "disabled"


def test_liveness_200_readiness_503_and_recovery_200(monkeypatch):
    app = FastAPI()
    app.include_router(system.router)
    snapshot = {"ready": False, "status": "standby", "checked_at": "test", "reasons": ["offline"], "components": {}}
    monkeypatch.setattr(system, "_current_readiness", lambda: snapshot)
    client = TestClient(app)
    for path in ["/health", "/healthz"]:
        response = client.get(path)
        assert response.status_code == 200 and response.json()["status"] == "alive"
    response = client.get("/readyz")
    assert response.status_code == 503 and response.json()["ready"] is False
    snapshot.update(ready=True, status="ready", reasons=[])
    assert client.get("/readyz").status_code == 200
    assert client.get("/api/v1/system/readiness").status_code == 401
    client.close()


def test_carrier_down_skips_ffprobe_and_maintenance_connect(tmp_path, monkeypatch):
    (tmp_path / "fake0").mkdir()
    (tmp_path / "fake0/carrier").write_text("0")
    run = Mock(return_value=subprocess.CompletedProcess([], 0, stdout='[{"dev":"fake0"}]', stderr=""))
    monkeypatch.setattr(video_probe.subprocess, "run", run)
    original = video_probe.inspect_source_network
    monkeypatch.setattr(video_probe, "inspect_source_network", lambda url: original(url, sysfs_root=tmp_path))
    connect = Mock(side_effect=AssertionError("offline must not connect to camera"))
    monkeypatch.setattr(video_probe.socket, "create_connection", connect)
    result = video_probe.probe_rtsp_video("rtsp://192.0.2.1/cam", timeout_seconds=1)
    assert not result.ready and not result.network_available
    assert "no carrier" in result.detail
    assert all(call.args[0][0] == "ip" for call in run.call_args_list)
    assert not video_probe.probe_recovery_access("rtsp://192.0.2.1/cam", port=23, timeout_seconds=1).ready
    connect.assert_not_called()


@pytest.mark.parametrize("route", ['{}', '[]', '{invalid'])
def test_unknown_camera_route_is_visible_not_default_success(monkeypatch, route):
    monkeypatch.setattr(video_probe.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess([], 0, stdout=route, stderr=""))
    result = video_probe.inspect_source_network("rtsp://192.0.2.1/cam")
    assert not result.ready and result.detail


def test_no_route_does_not_attempt_video_probe(monkeypatch):
    run = Mock(return_value=subprocess.CompletedProcess([], 2, stdout="", stderr="no route"))
    monkeypatch.setattr(video_probe.subprocess, "run", run)
    result = video_probe.probe_rtsp_video("rtsp://192.0.2.1/cam", timeout_seconds=1)
    assert not result.ready and not result.network_available and run.call_count == 1


def test_closed_maintenance_port_disables_recovery(monkeypatch):
    monkeypatch.setattr(video_probe, "inspect_source_network", lambda url: video_probe.NetworkResult(True, "fake up"))
    monkeypatch.setattr(video_probe.socket, "create_connection", Mock(side_effect=OSError("unreachable")))
    assert not video_probe.probe_recovery_access("rtsp://192.0.2.1/", port=23, timeout_seconds=1).ready


def fake_worker():
    worker = AIWorker.__new__(AIWorker)
    worker._frame_width, worker._frame_height = 640, 360
    worker._last_video_frame_at = None
    worker._last_frame_completed_at = 0.0
    worker._frame_process_timeout_s = 15
    worker._detector = object()
    worker._ffmpeg_frame_timeout_s = 5
    worker._ffmpeg_stream_unavailable = False
    worker._source_detail = "no video source"
    worker._source_network_available = None
    worker._startup_status = "waiting"
    worker._is_mission_active = lambda: True
    worker._notify_auto_track_video_lost = AsyncMock()
    worker._maybe_broadcast_status = AsyncMock()
    worker._rtsp_urls = ["rtsp://127.0.0.1:8554/cam"]
    worker._rtsp_url_index = 0
    return worker


def test_ai_readiness_expires_without_new_frames():
    worker = fake_worker()
    assert not worker.get_runtime_status()["ready"]
    worker._last_video_frame_at = time.monotonic()
    worker._last_frame_completed_at = time.monotonic()
    assert worker.get_runtime_status()["ready"]
    worker._last_video_frame_at -= 10
    assert not worker.get_runtime_status()["ready"]
    worker._is_mission_active = lambda: False
    assert worker.get_runtime_status()["status"] == "standby"


def test_fresh_video_does_not_hide_missing_or_stalled_inference():
    worker = fake_worker()
    worker._last_video_frame_at = time.monotonic()
    assert worker.get_runtime_status()["status"] == "waiting"
    worker._last_frame_completed_at = time.monotonic() - 20
    assert not worker.get_runtime_status()["ready"]
    assert "AI 分析未持续完成" in worker.get_runtime_status()["message"]
    worker._last_frame_completed_at = time.monotonic()
    assert worker.get_runtime_status()["ready"]


def test_unavailable_model_is_not_reported_as_idle_or_healthy():
    worker = fake_worker()
    worker._is_mission_active = lambda: False
    worker._detector = workers_ai._NullDetector()
    assert worker.get_runtime_status()["status"] == "failed"
    assert worker.get_runtime_status()["required"]
    assert not worker.get_runtime_status()["ready"]


@pytest.mark.asyncio
async def test_failed_ai_preflight_notifies_once_and_skips_decoder(monkeypatch):
    worker = fake_worker()
    monkeypatch.setattr(workers_ai, "probe_rtsp_video", lambda *a, **kw: video_probe.ProbeResult(False, "no carrier", False))
    assert not await worker._check_video_source()
    assert not await worker._check_video_source()
    worker._notify_auto_track_video_lost.assert_awaited_once()
    assert worker._startup_status == "waiting" and not worker._source_network_available


@pytest.mark.asyncio
@pytest.mark.parametrize("restore", [False, True])
async def test_ai_backoff_grows_and_resets_only_after_real_frame(monkeypatch, restore):
    worker = fake_worker()
    worker._pose_status = worker._weapon_status = "disabled"
    worker._weather_service = SimpleNamespace(available=False, get_status=lambda: {"state": "disabled"})
    worker._patrol_skip = worker._weapon_frame_skip = 1
    worker._parallel_inference_enabled = False
    worker._update_current_task_id = AsyncMock()
    worker._warmup_models = AsyncMock()
    worker._rotate_rtsp_url_after_failure = Mock()
    worker._log_retry_scheduled = Mock()
    worker._check_video_source = AsyncMock(side_effect=[False, False, True] if restore else [False] * 6)
    delays = []
    stop = asyncio.Event()

    async def wait(event, delay):
        delays.append(delay)
        if len(delays) == (3 if restore else 6):
            stop.set()

    async def stream(event):
        worker._last_video_frame_at = time.monotonic()

    worker._wait_before_reconnect = wait
    worker._run_ffmpeg_loop = AsyncMock(side_effect=stream)
    monkeypatch.setattr(settings, "AI_FFMPEG_RETRY_MIN_SECONDS", 1)
    monkeypatch.setattr(settings, "AI_FFMPEG_RETRY_MAX_SECONDS", 30)
    await worker.start(stop)
    assert delays == ([2, 4, 1] if restore else [2, 4, 8, 16, 30, 30])
    if not restore:
        worker._run_ffmpeg_loop.assert_not_awaited()
        worker._warmup_models.assert_not_awaited()


@pytest.mark.asyncio
async def test_offline_wait_is_interruptible_for_shutdown():
    stop = asyncio.Event()
    stop.set()
    await asyncio.wait_for(AIWorker._wait_before_reconnect(stop, 30), timeout=0.1)
