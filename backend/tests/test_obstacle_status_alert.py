"""持续阻断告警：/nav/obstacle_status 兜底逻辑的单元测试。"""

import json
import threading
from types import SimpleNamespace

from backend import services_ros_nav as module_under_test
from backend.services_nav_state import (
    get_nav_state,
    set_navigation_idle,
    update_navigation_status,
)
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
        self._goal_submission_lock = threading.RLock()
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


def test_no_regoal_while_replacement_goal_is_still_planning(monkeypatch) -> None:
    _regoal_settings(monkeypatch)

    for planning_status in ("queued", "planning"):
        harness = Harness()
        harness._last_goal_waypoint = {"x": 1.0, "y": 2.0, "z": -0.5}
        harness._latest_planning_status = planning_status

        _at(monkeypatch, 1000.0)
        harness._handle_obstacle_status_message(_msg("blocked"))
        _at(monkeypatch, 1030.0)
        harness._handle_obstacle_status_message(_msg("replan_requested"))

        assert harness.regoals == []
        assert harness._regoal_attempts == 0


def test_no_regoal_while_goal_generation_is_submitted(monkeypatch) -> None:
    harness = Harness()
    harness._last_goal_waypoint = {"x": 1.0, "y": 2.0, "z": -0.5}
    harness._planning_status_awaiting_new_generation = True
    _regoal_settings(monkeypatch)

    _at(monkeypatch, 1000.0)
    harness._handle_obstacle_status_message(_msg("blocked"))
    _at(monkeypatch, 1030.0)
    harness._handle_obstacle_status_message(_msg("replan_requested"))

    assert harness.regoals == []
    assert harness._regoal_attempts == 0


def test_auto_regoal_rechecks_planning_state_after_submission_lock(
    monkeypatch,
) -> None:
    class Gate:
        def __init__(self) -> None:
            self.entered = threading.Event()
            self.release = threading.Event()

        def __enter__(self):
            self.entered.set()
            if not self.release.wait(2.0):
                raise TimeoutError("test did not release goal submission lock")
            return self

        def __exit__(self, *_args) -> None:
            return None

    harness = Harness()
    old_waypoint = {"id": "old", "x": 1.0, "y": 2.0, "z": -0.5}
    new_waypoint = {"id": "new", "x": 3.0, "y": 4.0, "z": -0.5}
    harness._last_goal_waypoint = old_waypoint
    harness._latest_planning_status = "failed"
    gate = Gate()
    harness._goal_submission_lock = gate
    _regoal_settings(monkeypatch)

    errors = []

    def auto_regoal() -> None:
        try:
            harness._maybe_auto_regoal(1030.0, 30.0, "blocked")
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    worker = threading.Thread(target=auto_regoal, daemon=True)
    worker.start()
    assert gate.entered.wait(1.0)

    # Simulate a web goal completing its protected state hand-off while the
    # old automatic retry is waiting for the same submission lock.
    harness._last_goal_waypoint = new_waypoint
    harness._planning_status_awaiting_new_generation = True
    gate.release.set()
    worker.join(1.0)

    assert not worker.is_alive()
    assert errors == []
    assert harness.regoals == []
    assert harness._regoal_attempts == 0


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


def test_obstacle_status_is_broadcast_as_blocked_and_restored(monkeypatch) -> None:
    set_navigation_idle()
    update_navigation_status(
        {
            "status": "path_ready",
            "target_waypoint_id": "wp-1",
            "target_name": "目标",
            "message": "路径已生成",
        }
    )
    bridge = RosNavBridge.__new__(RosNavBridge)
    bridge._last_goal_waypoint = {"id": "wp-1"}
    bridge._navigation_task_active = False
    bridge._navigation_status_before_blocked = None
    bridge._obstacle_blocked_since = None
    bridge._obstacle_alert_sent = False
    bridge._regoal_attempts = 0
    bridge._last_regoal_at = 0.0
    bridge._submit_alert = lambda **_kwargs: None
    broadcasts = []
    bridge._submit_broadcast = lambda event_type, payload: broadcasts.append(
        (event_type, payload)
    )
    monkeypatch.setattr(
        module_under_test.settings,
        "NAV_OBSTACLE_ALERT_SECONDS",
        15.0,
    )

    bridge._handle_obstacle_status_message(
        _msg(
            "replan_requested",
            message="轨迹离开同层 ground 可通行区域，已请求重规划",
        )
    )

    blocked = get_nav_state()["navigation_status"]
    assert blocked["status"] == "blocked"
    assert blocked["error_code"] == "NAV_PATH_BLOCKED"
    assert "同层 ground" in blocked["message"]

    bridge._handle_obstacle_status_message(_msg("clear"))

    restored = get_nav_state()["navigation_status"]
    assert restored["status"] == "path_ready"
    assert restored["error_code"] is None
    assert [
        payload["status"]
        for event, payload in broadcasts
        if event == "nav.navigation_status"
    ] == ["blocked", "path_ready"]
