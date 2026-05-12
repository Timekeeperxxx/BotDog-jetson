from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from backend.services_nav_state import get_nav_state, set_navigation_idle
from backend.services_ros_nav import RosNavBridge


@pytest.fixture(autouse=True)
def reset_navigation_state():
    set_navigation_idle("导航空闲")


def _make_bridge(monkeypatch, broadcast_calls: list[tuple[str, dict[str, object]]]) -> RosNavBridge:
    bridge = RosNavBridge.__new__(RosNavBridge)

    def fake_submit_broadcast(event_type: str, data: dict[str, object]) -> None:
        broadcast_calls.append((event_type, data))

    monkeypatch.setattr(bridge, "_submit_broadcast", fake_submit_broadcast)
    return bridge


@pytest.mark.parametrize(
    "ros_status,mapped_status",
    [
        ("accepted", "navigating"),
        ("moving", "navigating"),
        ("reached", "reached"),
        ("failed", "error"),
        ("canceled", "idle"),
        ("estop", "estop"),
    ],
)
def test_nav_status_mappings_update_navigation_state_and_broadcast(monkeypatch, ros_status, mapped_status):
    broadcast_calls: list[tuple[str, dict[str, object]]] = []
    bridge = _make_bridge(monkeypatch, broadcast_calls)

    bridge._handle_nav_status_message(
        SimpleNamespace(
            data=json.dumps(
                {
                    "status": ros_status,
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
    assert state["status"] == mapped_status
    assert state["ros_status"] == ros_status
    assert state["task_id"] == "task_001"
    assert state["waypoint_id"] == "wp_001"
    assert state["distance_to_goal"] == 1.25
    assert state["message"] == "导航中"
    assert state["source"] == "/nav_status"
    assert broadcast_calls
    assert broadcast_calls[0][0] == "nav.navigation_status"
    assert broadcast_calls[0][1]["status"] == mapped_status


def test_nav_status_failed_preserves_error_fields(monkeypatch):
    broadcast_calls: list[tuple[str, dict[str, object]]] = []
    bridge = _make_bridge(monkeypatch, broadcast_calls)

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


def test_nav_status_unknown_status_maps_to_error_and_preserves_raw_status(monkeypatch):
    broadcast_calls: list[tuple[str, dict[str, object]]] = []
    bridge = _make_bridge(monkeypatch, broadcast_calls)

    bridge._handle_nav_status_message(
        SimpleNamespace(
            data=json.dumps(
                {
                    "status": "paused",
                    "task_id": "task_003",
                    "waypoint_id": "wp_003",
                    "message": "未知状态",
                    "timestamp": 1770000002.0,
                }
            )
        )
    )

    state = get_nav_state()["navigation_status"]
    assert state["status"] == "error"
    assert state["ros_status"] == "paused"
    assert state["task_id"] == "task_003"
    assert state["waypoint_id"] == "wp_003"
    assert broadcast_calls[0][0] == "nav.navigation_status"
    assert broadcast_calls[0][1]["status"] == "error"
    assert broadcast_calls[0][1]["ros_status"] == "paused"


def test_nav_status_invalid_json_is_ignored(monkeypatch):
    broadcast_calls: list[tuple[str, dict[str, object]]] = []
    bridge = _make_bridge(monkeypatch, broadcast_calls)

    before = get_nav_state()["navigation_status"]

    bridge._handle_nav_status_message(SimpleNamespace(data="{not json"))

    after = get_nav_state()["navigation_status"]
    assert after["status"] == before["status"]
    assert after["message"] == before["message"]
    assert broadcast_calls == []
