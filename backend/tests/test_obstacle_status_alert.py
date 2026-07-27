"""持续阻断告警：/nav/obstacle_status 兜底逻辑的单元测试。"""

import json
from types import SimpleNamespace

from backend import services_ros_nav as module_under_test
from backend.services_ros_nav import RosNavBridge


class Harness:
    """只绑定告警相关方法，避免在测试机上启动 ROS 节点。"""

    _OBSTACLE_STUCK_STATUSES = RosNavBridge._OBSTACLE_STUCK_STATUSES
    _handle_obstacle_status_message = (
        RosNavBridge._handle_obstacle_status_message
    )
    _maybe_auto_regoal = RosNavBridge._maybe_auto_regoal

    _navigation_task_active = False

    def __init__(self) -> None:
        self._obstacle_blocked_since = None
        self._obstacle_alert_sent = False
        self._last_goal_waypoint = None
        self._regoal_attempts = 0
        self._last_regoal_at = 0.0
        self.alerts: list[dict] = []
        self.regoals: list[dict] = []

    def _submit_alert(self, **kwargs) -> None:
        self.alerts.append(kwargs)

    def publish_goal_xyz_yaw(self, waypoint: dict) -> dict:
        self.regoals.append(waypoint)
        return {"success": True}


def _msg(status: str, **extra) -> SimpleNamespace:
    return SimpleNamespace(data=json.dumps({"status": status, **extra}))


def _at(monkeypatch, timestamp: float) -> None:
    monkeypatch.setattr(module_under_test.time, "time", lambda: timestamp)


def test_short_block_does_not_alert(monkeypatch) -> None:
    harness = Harness()
    monkeypatch.setattr(
        module_under_test.settings, "NAV_OBSTACLE_ALERT_SECONDS", 15.0
    )

    _at(monkeypatch, 1000.0)
    harness._handle_obstacle_status_message(_msg("blocked"))
    _at(monkeypatch, 1010.0)
    harness._handle_obstacle_status_message(_msg("replan_requested"))

    assert harness.alerts == []


def test_persistent_block_alerts_once(monkeypatch) -> None:
    harness = Harness()
    monkeypatch.setattr(
        module_under_test.settings, "NAV_OBSTACLE_ALERT_SECONDS", 15.0
    )

    _at(monkeypatch, 1000.0)
    harness._handle_obstacle_status_message(_msg("blocked"))
    _at(monkeypatch, 1016.0)
    harness._handle_obstacle_status_message(
        _msg("replan_requested", nearest_obstacle_distance=0.8)
    )
    _at(monkeypatch, 1020.0)
    harness._handle_obstacle_status_message(_msg("replan_requested"))

    assert len(harness.alerts) == 1
    alert = harness.alerts[0]
    assert alert["event_code"] == "NAV_PATH_BLOCKED"
    assert alert["severity"] == "warning"
    assert alert["obstacle_status"] == "replan_requested"
    assert alert["nearest_obstacle_distance"] == 0.8


def test_status_flicker_within_stuck_set_keeps_timer(monkeypatch) -> None:
    # blocked -> replan_requested -> waiting_replan -> clearing 都属于
    # “没有前进”，计时不能被状态抖动清零。
    harness = Harness()
    monkeypatch.setattr(
        module_under_test.settings, "NAV_OBSTACLE_ALERT_SECONDS", 15.0
    )

    _at(monkeypatch, 1000.0)
    harness._handle_obstacle_status_message(_msg("blocked"))
    _at(monkeypatch, 1006.0)
    harness._handle_obstacle_status_message(_msg("waiting_replan"))
    _at(monkeypatch, 1012.0)
    harness._handle_obstacle_status_message(_msg("clearing"))
    _at(monkeypatch, 1016.0)
    harness._handle_obstacle_status_message(_msg("replan_requested"))

    assert len(harness.alerts) == 1


def test_clear_after_alert_sends_resolution_and_rearms(monkeypatch) -> None:
    harness = Harness()
    monkeypatch.setattr(
        module_under_test.settings, "NAV_OBSTACLE_ALERT_SECONDS", 15.0
    )

    _at(monkeypatch, 1000.0)
    harness._handle_obstacle_status_message(_msg("blocked"))
    _at(monkeypatch, 1016.0)
    harness._handle_obstacle_status_message(_msg("blocked"))
    _at(monkeypatch, 1020.0)
    harness._handle_obstacle_status_message(_msg("clear"))

    assert [a["event_code"] for a in harness.alerts] == [
        "NAV_PATH_BLOCKED",
        "NAV_BLOCK_CLEARED",
    ]
    assert harness.alerts[1]["severity"] == "info"
    assert harness._obstacle_blocked_since is None
    assert harness._obstacle_alert_sent is False

    # 解除后再次阻断，应重新计时并可再次告警。
    _at(monkeypatch, 2000.0)
    harness._handle_obstacle_status_message(_msg("blocked"))
    _at(monkeypatch, 2016.0)
    harness._handle_obstacle_status_message(_msg("blocked"))
    assert len(harness.alerts) == 3


def test_clear_without_alert_stays_silent(monkeypatch) -> None:
    harness = Harness()
    monkeypatch.setattr(
        module_under_test.settings, "NAV_OBSTACLE_ALERT_SECONDS", 15.0
    )

    _at(monkeypatch, 1000.0)
    harness._handle_obstacle_status_message(_msg("blocked"))
    _at(monkeypatch, 1005.0)
    harness._handle_obstacle_status_message(_msg("clear"))

    assert harness.alerts == []


def test_persistent_sensor_lost_uses_dedicated_code(monkeypatch) -> None:
    harness = Harness()
    monkeypatch.setattr(
        module_under_test.settings, "NAV_OBSTACLE_ALERT_SECONDS", 15.0
    )

    _at(monkeypatch, 1000.0)
    harness._handle_obstacle_status_message(_msg("sensor_lost"))
    _at(monkeypatch, 1016.0)
    harness._handle_obstacle_status_message(_msg("sensor_lost"))

    assert len(harness.alerts) == 1
    assert harness.alerts[0]["event_code"] == "NAV_SENSOR_LOST"


def _regoal_settings(monkeypatch) -> None:
    s = module_under_test.settings
    monkeypatch.setattr(s, "NAV_OBSTACLE_ALERT_SECONDS", 15.0)
    monkeypatch.setattr(s, "NAV_OBSTACLE_AUTO_REGOAL_ENABLED", True)
    monkeypatch.setattr(s, "NAV_OBSTACLE_REGOAL_SECONDS", 25.0)
    monkeypatch.setattr(s, "NAV_OBSTACLE_REGOAL_COOLDOWN_SECONDS", 30.0)
    monkeypatch.setattr(s, "NAV_OBSTACLE_REGOAL_MAX_ATTEMPTS", 3)


def test_auto_regoal_fires_with_cooldown_and_cap(monkeypatch) -> None:
    harness = Harness()
    harness._last_goal_waypoint = {"x": 1.0, "y": 2.0, "yaw": 0.0}
    _regoal_settings(monkeypatch)

    _at(monkeypatch, 1000.0)
    harness._handle_obstacle_status_message(_msg("blocked"))
    _at(monkeypatch, 1016.0)  # 告警阈值已过，重发阈值未到
    harness._handle_obstacle_status_message(_msg("replan_requested"))
    assert harness.regoals == []

    _at(monkeypatch, 1026.0)  # 26s >= 25s：第 1 次重发
    harness._handle_obstacle_status_message(_msg("replan_requested"))
    assert len(harness.regoals) == 1

    _at(monkeypatch, 1040.0)  # 冷却 30s 未过
    harness._handle_obstacle_status_message(_msg("replan_requested"))
    assert len(harness.regoals) == 1

    _at(monkeypatch, 1057.0)  # 第 2 次
    harness._handle_obstacle_status_message(_msg("replan_requested"))
    _at(monkeypatch, 1090.0)  # 第 3 次
    harness._handle_obstacle_status_message(_msg("replan_requested"))
    _at(monkeypatch, 1130.0)  # 已达上限，不再重发
    harness._handle_obstacle_status_message(_msg("replan_requested"))
    assert len(harness.regoals) == 3

    regoal_alerts = [a for a in harness.alerts if a["event_code"] == "NAV_AUTO_REGOAL"]
    assert len(regoal_alerts) == 3
    assert all(a["severity"] == "info" for a in regoal_alerts)


def test_no_regoal_in_task_mode(monkeypatch) -> None:
    harness = Harness()
    harness._navigation_task_active = True
    harness._last_goal_waypoint = {"x": 1.0, "y": 2.0}
    _regoal_settings(monkeypatch)

    _at(monkeypatch, 1000.0)
    harness._handle_obstacle_status_message(_msg("blocked"))
    _at(monkeypatch, 1030.0)
    harness._handle_obstacle_status_message(_msg("blocked"))

    assert harness.regoals == []


def test_no_regoal_without_stored_goal(monkeypatch) -> None:
    harness = Harness()
    _regoal_settings(monkeypatch)

    _at(monkeypatch, 1000.0)
    harness._handle_obstacle_status_message(_msg("blocked"))
    _at(monkeypatch, 1030.0)
    harness._handle_obstacle_status_message(_msg("blocked"))

    assert harness.regoals == []


def test_no_regoal_on_sensor_lost(monkeypatch) -> None:
    harness = Harness()
    harness._last_goal_waypoint = {"x": 1.0, "y": 2.0}
    _regoal_settings(monkeypatch)

    _at(monkeypatch, 1000.0)
    harness._handle_obstacle_status_message(_msg("sensor_lost"))
    _at(monkeypatch, 1030.0)
    harness._handle_obstacle_status_message(_msg("sensor_lost"))

    assert harness.regoals == []


def test_clear_resets_regoal_attempts(monkeypatch) -> None:
    harness = Harness()
    harness._last_goal_waypoint = {"x": 1.0, "y": 2.0}
    _regoal_settings(monkeypatch)

    _at(monkeypatch, 1000.0)
    harness._handle_obstacle_status_message(_msg("blocked"))
    _at(monkeypatch, 1026.0)
    harness._handle_obstacle_status_message(_msg("blocked"))
    assert harness._regoal_attempts == 1

    _at(monkeypatch, 1030.0)
    harness._handle_obstacle_status_message(_msg("clear"))
    assert harness._regoal_attempts == 0


def test_regoal_disabled_by_config(monkeypatch) -> None:
    harness = Harness()
    harness._last_goal_waypoint = {"x": 1.0, "y": 2.0}
    _regoal_settings(monkeypatch)
    monkeypatch.setattr(
        module_under_test.settings, "NAV_OBSTACLE_AUTO_REGOAL_ENABLED", False
    )

    _at(monkeypatch, 1000.0)
    harness._handle_obstacle_status_message(_msg("blocked"))
    _at(monkeypatch, 1030.0)
    harness._handle_obstacle_status_message(_msg("blocked"))

    assert harness.regoals == []


def test_malformed_payload_is_ignored(monkeypatch) -> None:
    harness = Harness()

    harness._handle_obstacle_status_message(SimpleNamespace(data="not json"))
    harness._handle_obstacle_status_message(SimpleNamespace(data=""))
    harness._handle_obstacle_status_message(SimpleNamespace(data="[1,2]"))

    assert harness.alerts == []
    assert harness._obstacle_blocked_since is None
