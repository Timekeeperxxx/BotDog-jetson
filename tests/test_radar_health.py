import pytest

from backend import services_radar_health as radar_health


def _command_result(*, stdout: str = "", returncode: int = 0, timed_out: bool = False):
    return radar_health.CommandResult(
        returncode=returncode,
        stdout=stdout,
        stderr="",
        timed_out=timed_out,
    )


@pytest.fixture(autouse=True)
def reset_preflight_cache():
    with radar_health._radar_preflight_cache_lock:
        radar_health._radar_preflight_success_cache = None
    yield
    with radar_health._radar_preflight_cache_lock:
        radar_health._radar_preflight_success_cache = None


def test_radar_preflight_fails_immediately_when_topic_is_missing(monkeypatch):
    monkeypatch.setattr(radar_health.shutil, "which", lambda _name: "/opt/ros/bin/ros2")
    monkeypatch.setattr(
        radar_health,
        "_list_topics",
        lambda timeout: (_command_result(), {"/rosout": "rcl_interfaces/msg/Log"}),
    )

    result = radar_health.check_radar_preflight(allow_cached_success=False)

    assert result["ok"] is False
    assert result["level"] == "error"
    assert "雷达未连接" in result["message"]
    assert result["topic"] is None


def test_radar_preflight_rejects_topic_without_live_data(monkeypatch):
    monkeypatch.setattr(radar_health.shutil, "which", lambda _name: "/opt/ros/bin/ros2")
    monkeypatch.setattr(
        radar_health,
        "_list_topics",
        lambda timeout: (
            _command_result(),
            {"/livox/lidar": "livox_ros_driver2/msg/CustomMsg"},
        ),
    )
    monkeypatch.setattr(
        radar_health,
        "_run_ros2",
        lambda _args, timeout: _command_result(
            stdout="Type: livox_ros_driver2/msg/CustomMsg\nPublisher count: 1\nSubscription count: 0\n"
        ),
    )
    monkeypatch.setattr(
        radar_health,
        "_measure_topic_hz_quick",
        lambda _topic: (_command_result(returncode=124, timed_out=True), None),
    )

    result = radar_health.check_radar_preflight(allow_cached_success=False)

    assert result["ok"] is False
    assert "无有效数据" in result["message"]
    assert result["publisher_count"] == 1


def test_radar_preflight_accepts_live_radar_data(monkeypatch):
    monkeypatch.setattr(radar_health.shutil, "which", lambda _name: "/opt/ros/bin/ros2")
    monkeypatch.setattr(
        radar_health,
        "_list_topics",
        lambda timeout: (
            _command_result(),
            {"/livox/lidar": "livox_ros_driver2/msg/CustomMsg"},
        ),
    )
    monkeypatch.setattr(
        radar_health,
        "_run_ros2",
        lambda _args, timeout: _command_result(
            stdout="Type: livox_ros_driver2/msg/CustomMsg\nPublisher count: 1\nSubscription count: 2\n"
        ),
    )
    monkeypatch.setattr(
        radar_health,
        "_measure_topic_hz_quick",
        lambda _topic: (_command_result(returncode=124, timed_out=True), 10.0),
    )

    result = radar_health.check_radar_preflight(allow_cached_success=False)

    assert result["ok"] is True
    assert result["level"] == "normal"
    assert result["frequency_hz"] == 10.0
    assert result["message"] == "雷达连接正常"


def test_quick_frequency_check_uses_humble_compatible_arguments(monkeypatch):
    calls: list[tuple[list[str], float]] = []

    def fake_run_ros2(args, timeout):
        calls.append((args, timeout))
        return _command_result(stdout="average rate: 10.000\n", timed_out=True)

    monkeypatch.setattr(radar_health, "_run_ros2", fake_run_ros2)

    _result, frequency = radar_health._measure_topic_hz_quick("/livox/lidar")

    assert frequency == 10.0
    assert calls == [
        (["topic", "hz", "/livox/lidar", "--window", "2"], radar_health.RADAR_PREFLIGHT_DATA_TIMEOUT_S)
    ]


def test_radar_preflight_reuses_recent_success_to_avoid_duplicate_startup_delay(monkeypatch):
    topic_list_calls = 0

    def fake_list_topics(timeout):
        nonlocal topic_list_calls
        topic_list_calls += 1
        return (
            _command_result(),
            {"/livox/lidar": "livox_ros_driver2/msg/CustomMsg"},
        )

    monkeypatch.setattr(radar_health.shutil, "which", lambda _name: "/opt/ros/bin/ros2")
    monkeypatch.setattr(radar_health, "_list_topics", fake_list_topics)
    monkeypatch.setattr(
        radar_health,
        "_run_ros2",
        lambda _args, timeout: _command_result(
            stdout="Type: livox_ros_driver2/msg/CustomMsg\nPublisher count: 1\nSubscription count: 2\n"
        ),
    )
    monkeypatch.setattr(
        radar_health,
        "_measure_topic_hz_quick",
        lambda _topic: (_command_result(returncode=124, timed_out=True), 10.0),
    )

    first = radar_health.check_radar_preflight()
    second = radar_health.check_radar_preflight()

    assert first["ok"] is True
    assert second == first
    assert topic_list_calls == 1


def test_livox_network_preflight_rejects_disconnected_ethernet(monkeypatch):
    monkeypatch.setattr(radar_health.shutil, "which", lambda _name: "/usr/sbin/ip")
    monkeypatch.setattr(
        radar_health,
        "_run_system_command",
        lambda _args, timeout: _command_result(
            stdout="192.168.123.179 dev eno1 src 192.168.123.222 uid 1000\n"
        ),
    )
    monkeypatch.setattr(
        radar_health,
        "_read_network_attribute",
        lambda _interface, attribute: {"operstate": "down", "carrier": "0"}[attribute],
    )

    result = radar_health.check_livox_network_preflight()

    assert result["ok"] is False
    assert "网卡 eno1 未建立物理链路" in result["message"]


def test_livox_network_preflight_accepts_live_ethernet_link(monkeypatch):
    monkeypatch.setattr(radar_health.shutil, "which", lambda _name: "/usr/sbin/ip")
    monkeypatch.setattr(
        radar_health,
        "_run_system_command",
        lambda _args, timeout: _command_result(
            stdout="192.168.123.179 dev eno1 src 192.168.123.222 uid 1000\n"
        ),
    )
    monkeypatch.setattr(
        radar_health,
        "_read_network_attribute",
        lambda _interface, attribute: {"operstate": "up", "carrier": "1"}[attribute],
    )

    result = radar_health.check_livox_network_preflight()

    assert result["ok"] is True
    assert "eno1" in result["message"]
