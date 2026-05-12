from __future__ import annotations

import json
from types import SimpleNamespace

from backend.services_nav_state import get_nav_state, set_navigation_idle
from backend.services_ros_nav import RosNavBridge


def test_nav_status_moving_updates_navigation_state_and_broadcasts(monkeypatch):
    broadcast_calls: list[tuple[str, dict[str, object]]] = []

    bridge = RosNavBridge.__new__(RosNavBridge)

    def fake_submit_broadcast(event_type: str, data: dict[str, object]) -> None:
        broadcast_calls.append((event_type, data))

    monkeypatch.setattr(bridge, "_submit_broadcast", fake_submit_broadcast)

    bridge._handle_nav_status_message(
        SimpleNamespace(
            data=json.dumps(
                {
                    "status": "moving",
                    "task_id": "task_001",
                    "waypoint_id": "wp_001",
                    "message": "导航中",
                    "distance_to_goal": 1.25,
                    "error_code": None,
                    "timestamp": 1770000000.123,
                }
            )
        )
    )

    state = get_nav_state()["navigation_status"]
    assert state["status"] == "navigating"
    assert state["ros_status"] == "moving"
    assert state["task_id"] == "task_001"
    assert state["waypoint_id"] == "wp_001"
    assert state["distance_to_goal"] == 1.25
    assert state["message"] == "导航中"
    assert state["source"] == "/nav_status"
    assert broadcast_calls
    assert broadcast_calls[0][0] == "nav.navigation_status"
    assert broadcast_calls[0][1]["status"] == "navigating"


def test_nav_status_failed_preserves_error_fields(monkeypatch):
    broadcast_calls: list[tuple[str, dict[str, object]]] = []

    bridge = RosNavBridge.__new__(RosNavBridge)

    def fake_submit_broadcast(event_type: str, data: dict[str, object]) -> None:
        broadcast_calls.append((event_type, data))

    monkeypatch.setattr(bridge, "_submit_broadcast", fake_submit_broadcast)

    bridge._handle_nav_status_message(
        SimpleNamespace(
            data=json.dumps(
                {
                    "status": "failed",
                    "task_id": "task_002",
                    "waypoint_id": "wp_002",
                    "message": "路径规划失败",
                    "distance_to_goal": 0.33,
                    "error_code": "PLAN_FAILED",
                    "timestamp": 1770000001.0,
                }
            )
        )
    )

    state = get_nav_state()["navigation_status"]
    assert state["status"] == "error"
    assert state["ros_status"] == "failed"
    assert state["error_code"] == "PLAN_FAILED"
    assert state["message"] == "路径规划失败"
    assert broadcast_calls[0][0] == "nav.navigation_status"
    assert broadcast_calls[0][1]["status"] == "error"
    assert broadcast_calls[0][1]["error_code"] == "PLAN_FAILED"


def test_nav_status_invalid_json_is_ignored(monkeypatch):
    broadcast_calls: list[tuple[str, dict[str, object]]] = []

    bridge = RosNavBridge.__new__(RosNavBridge)

    def fake_submit_broadcast(event_type: str, data: dict[str, object]) -> None:
        broadcast_calls.append((event_type, data))

    monkeypatch.setattr(bridge, "_submit_broadcast", fake_submit_broadcast)

    set_navigation_idle("保持原样")
    before = get_nav_state()["navigation_status"]

    bridge._handle_nav_status_message(SimpleNamespace(data="{not json"))

    after = get_nav_state()["navigation_status"]
    assert after["status"] == before["status"]
    assert after["message"] == before["message"]
    assert broadcast_calls == []
