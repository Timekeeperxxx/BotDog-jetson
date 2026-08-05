from __future__ import annotations

import math
from pathlib import Path

import pytest

from backend import services_nav_localization
from backend import services_nav_localization_process
from backend.navigation_velocity_protocol import (
    NAVIGATION_VELOCITY_PACKET,
    NAVIGATION_VELOCITY_UDP_HOST,
    NAVIGATION_VELOCITY_UDP_PORT,
    pack_navigation_velocity,
)
from backend.navigation_velocity_heartbeat import NavigationVelocityHeartbeat


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SENDER_SCRIPT = PROJECT_ROOT / "scripts" / "cmd_vel_ros2_udp_sender.py"
START_SCRIPT = PROJECT_ROOT / "scripts" / "start_cmd_vel_udp_sender.sh"


def test_navigation_velocity_protocol_is_loopback_and_three_doubles():
    payload = pack_navigation_velocity(0.25, -0.08, 0.3)

    assert NAVIGATION_VELOCITY_UDP_HOST == "127.0.0.1"
    assert NAVIGATION_VELOCITY_UDP_PORT == 52345
    assert len(payload) == 24
    assert NAVIGATION_VELOCITY_PACKET.unpack(payload) == pytest.approx((0.25, -0.08, 0.3))


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_navigation_velocity_protocol_rejects_non_finite_values(value):
    with pytest.raises(ValueError, match="non-finite"):
        pack_navigation_velocity(value, 0.0, 0.0)


def test_cmd_vel_sender_uses_ros_safe_topic_and_shared_udp_protocol():
    sender_source = SENDER_SCRIPT.read_text(encoding="utf-8")
    start_source = START_SCRIPT.read_text(encoding="utf-8")

    assert 'DEFAULT_TOPIC = "/cmd_vel_safe"' in sender_source
    assert "NavigationVelocityHeartbeat" in sender_source
    assert "create_timer" in sender_source
    assert "pack_navigation_velocity" in sender_source
    assert "unitree_sdk" not in sender_source.lower()
    assert 'exec /usr/bin/python3 "$SCRIPT_DIR/cmd_vel_ros2_udp_sender.py"' in start_source
    assert "rmw_fastrtps_cpp" in start_source


class ManualClock:
    def __init__(self) -> None:
        self.now = 10.0

    def __call__(self) -> float:
        return self.now


def test_velocity_heartbeat_repeats_fresh_filtered_command_then_fails_closed():
    clock = ManualClock()
    heartbeat = NavigationVelocityHeartbeat(command_timeout_s=0.25, clock=clock)

    assert heartbeat.sample().reason == "awaiting_command"
    heartbeat.update(0.25, -0.08, 0.3)
    first = heartbeat.sample()
    assert (first.vx, first.vy, first.vyaw) == pytest.approx((0.25, -0.08, 0.3))
    assert first.reason == "active"

    clock.now += 0.249
    assert heartbeat.sample().reason == "active"
    clock.now += 0.001
    stale = heartbeat.sample()
    assert (stale.vx, stale.vy, stale.vyaw) == (0.0, 0.0, 0.0)
    assert stale.reason == "command_stale"


def test_velocity_heartbeat_recovers_only_after_a_new_valid_command():
    clock = ManualClock()
    heartbeat = NavigationVelocityHeartbeat(command_timeout_s=0.25, clock=clock)
    heartbeat.update(0.2, 0.0, 0.0)
    clock.now += 0.3
    assert heartbeat.sample().reason == "command_stale"

    heartbeat.update(0.0, 0.0, -0.4)
    recovered = heartbeat.sample()
    assert recovered.reason == "active"
    assert recovered.vyaw == pytest.approx(-0.4)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_velocity_heartbeat_rejects_non_finite_commands(value):
    heartbeat = NavigationVelocityHeartbeat()
    with pytest.raises(ValueError, match="non-finite"):
        heartbeat.update(value, 0.0, 0.0)


def test_cmd_vel_script_path_points_to_existing_udp_sender_launcher():
    assert services_nav_localization._cmd_vel_script_path() == START_SCRIPT
    assert START_SCRIPT.is_file()
    assert SENDER_SCRIPT.is_file()


def test_start_cmd_vel_script_waits_for_sender_ready_file(monkeypatch, tmp_path):
    calls: dict[str, object] = {}

    class FakeProcess:
        pid = 4321

        @staticmethod
        def poll():
            return None

    def fake_popen(command, **kwargs):
        calls["command"] = command
        calls["kwargs"] = kwargs
        ready_file = Path(kwargs["env"]["BOTDOG_CMD_VEL_READY_FILE"])
        ready_file.write_text("4321\n", encoding="utf-8")
        return FakeProcess()

    monkeypatch.setattr(services_nav_localization.settings, "NAV_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(services_nav_localization.settings, "CONTROL_ADAPTER_TYPE", "test")
    monkeypatch.setattr(services_nav_localization, "_read_cmd_vel_pid", lambda: None)
    monkeypatch.setattr(services_nav_localization, "_find_cmd_vel_pids", lambda: [])
    monkeypatch.setattr(services_nav_localization.subprocess, "Popen", fake_popen)

    result = services_nav_localization.start_cmd_vel_script()

    assert result["success"] is True
    assert result["ready"] is True
    assert result["pid"] == 4321
    assert calls["command"] == ["bash", str(START_SCRIPT)]
    assert calls["kwargs"]["cwd"] == str(PROJECT_ROOT)
    assert Path(result["pid_file"]).read_text(encoding="utf-8").strip() == "4321"


def test_cmd_vel_process_discovery_includes_current_sender(monkeypatch):
    captured: list[str] = []

    def fake_find(needles):
        captured.extend(needles)
        return [123]

    monkeypatch.setattr(services_nav_localization_process, "_find_pids_by_needles", fake_find)

    assert services_nav_localization_process._find_cmd_vel_pids() == [123]
    assert str(START_SCRIPT) in captured
    assert str(SENDER_SCRIPT) in captured
