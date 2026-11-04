"""Obstacle state regressions with in-memory state and fake event sinks."""
import json
import threading
from types import SimpleNamespace

import pytest

from backend import services_ros_nav as module
from backend.services_ros_nav import RosNavBridge


@pytest.fixture
def harness(monkeypatch):
    state = {"navigation_status": {"status": "navigating"}, "global_path": {"points": [1, 2]}}
    bridge = RosNavBridge.__new__(RosNavBridge)
    bridge._navigation_status_before_blocked = None
    bridge._last_goal_waypoint = {"x": 1, "y": 2}
    bridge._navigation_task_active = False
    bridge._obstacle_blocked_since = None
    bridge._obstacle_alert_sent = False
    bridge._regoal_attempts = 0
    bridge._last_regoal_at = 0.0
    bridge._goal_submission_lock = threading.RLock()
    bridge._planning_status_awaiting_new_generation = False
    bridge._latest_planning_status = "path_ready"
    alerts, updates, goals = [], [], []
    bridge._submit_alert = lambda **payload: alerts.append(payload)
    bridge.publish_goal_xyz_yaw = lambda payload: goals.append(payload)

    def update(payload):
        updates.append(payload)
        state["navigation_status"] = payload

    bridge._update_live_navigation_status = update
    monkeypatch.setattr(module, "get_nav_state", lambda: state)
    monkeypatch.setattr(module.settings, "NAV_OBSTACLE_ALERT_SECONDS", 15)
    monkeypatch.setattr(module.settings, "NAV_OBSTACLE_AUTO_REGOAL_ENABLED", False)

    def send(status, now, **payload):
        monkeypatch.setattr(module.time, "time", lambda: now)
        bridge._handle_obstacle_status_message(SimpleNamespace(data=json.dumps({"status": status, **payload})))

    return SimpleNamespace(bridge=bridge, state=state, alerts=alerts, updates=updates, goals=goals, send=send)


@pytest.mark.parametrize("status", ["deviated", "waiting_tf"])
def test_stop_status_keeps_block_and_timer_until_explicit_recovery(harness, status):
    h = harness
    h.send("blocked", 1000, action="stop")
    h.send(status, 1010, action="stop", message="等待定位恢复")
    assert h.state["navigation_status"]["status"] == "blocked"
    assert h.state["navigation_status"]["obstacle_status"] == status
    assert h.bridge._obstacle_blocked_since == 1000
    h.send(status, 1016, action="stop", message="等待定位恢复")
    assert len(h.alerts) == 1
    assert h.alerts[0]["event_code"] == ("NAV_SENSOR_LOST" if status == "waiting_tf" else "NAV_PATH_BLOCKED")
    h.send("clear", 1020, action="pass")
    assert h.state["navigation_status"]["status"] == "navigating"
    assert h.bridge._obstacle_blocked_since is None
    assert [a["event_code"] for a in h.alerts][-1] == "NAV_BLOCK_CLEARED"


@pytest.mark.parametrize("status", ["idle", "no_path", "disabled", "unknown", "", "future_state"])
def test_non_recovery_status_does_not_fabricate_clear(harness, status):
    h = harness
    h.send("blocked", 1000, action="stop")
    h.send("blocked", 1016, action="stop")
    h.send(status, 1020)
    assert h.state["navigation_status"]["status"] == "blocked"
    assert h.bridge._obstacle_alert_sent is True
    assert h.bridge._obstacle_blocked_since == 1000
    assert len(h.alerts) == 1


@pytest.mark.parametrize("status", ["clear", "caution", "future_state"])
def test_explicit_stop_wins_over_status_name(harness, status):
    h = harness
    h.send(status, 1000, action="stop", message="安全停车")
    assert h.state["navigation_status"]["status"] == "blocked"
    assert h.state["navigation_status"]["message"] == "安全停车"
    h.send(status, 1016, action="stop")
    assert all(a["event_code"] != "NAV_BLOCK_CLEARED" for a in h.alerts)


@pytest.mark.parametrize("status,action", [("clear", "pass"), ("caution", "slow"), ("clear", None)])
def test_confirmed_recovery_preserves_previous_navigation_state(harness, status, action):
    h = harness
    h.state["navigation_status"]["status"] = "path_ready"
    h.send("deviated", 1000, action="stop")
    h.send(status, 1020, **({"action": action} if action is not None else {}))
    assert h.state["navigation_status"]["status"] == "path_ready"


@pytest.mark.parametrize("action", [None, [], {}, "unknown"])
def test_invalid_recovery_action_preserves_block(harness, action):
    h = harness
    h.send("blocked", 1000, action="stop")
    h.send("clear", 1016, action=action)
    assert h.state["navigation_status"]["status"] == "blocked"
    assert h.bridge._obstacle_blocked_since == 1000


@pytest.mark.parametrize("status", ["deviated", "waiting_tf", "future_state"])
def test_localization_or_unknown_stop_does_not_auto_resubmit_goal(harness, monkeypatch, status):
    h = harness
    monkeypatch.setattr(module.settings, "NAV_OBSTACLE_AUTO_REGOAL_ENABLED", True)
    monkeypatch.setattr(module.settings, "NAV_OBSTACLE_REGOAL_SECONDS", 25)
    monkeypatch.setattr(module.settings, "NAV_OBSTACLE_REGOAL_COOLDOWN_SECONDS", 0)
    h.send(status, 1000, action="stop")
    h.send(status, 1040, action="stop")
    assert h.goals == []
