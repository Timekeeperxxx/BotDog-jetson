from __future__ import annotations

import json
import sys
from types import ModuleType, SimpleNamespace

import pytest

from backend.config import settings
from backend.services_nav_state import (
    get_nav_state,
    set_navigation_idle,
    update_navigation_status,
)
from backend.services_ros_nav import RosNavBridge


@pytest.fixture(autouse=True)
def reset_navigation_state():
    set_navigation_idle("导航空闲")


def _bridge() -> tuple[RosNavBridge, list[tuple[str, dict[str, object]]]]:
    bridge = RosNavBridge.__new__(RosNavBridge)
    bridge._latest_planning_generation = None
    bridge._latest_planning_status = None
    bridge._planning_status_seen = False
    bridge._planning_status_accept_generation_reset = False
    bridge._planning_status_awaiting_new_generation = False
    bridge._planning_generation_floor = None
    bridge._planning_status_publisher_gid = None
    bridge._retired_planning_status_publisher_gids = set()
    bridge._navigation_status_before_blocked = None
    broadcasts: list[tuple[str, dict[str, object]]] = []
    bridge._submit_broadcast = lambda event, payload: broadcasts.append(
        (event, payload)
    )
    return bridge, broadcasts


def _message(
    status: str,
    generation: int,
    *,
    elapsed_seconds: float = 0.0,
    message: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        data=json.dumps(
            {
                "status": status,
                "message": message or status,
                "generation": generation,
                "elapsed_seconds": elapsed_seconds,
            }
        )
    )


def test_planning_status_maps_lifecycle_and_elapsed_time_to_navigation_status():
    bridge, broadcasts = _bridge()

    bridge._handle_planning_status_message(_message("queued", 7))
    assert get_nav_state()["navigation_status"]["status"] == "planning"

    bridge._handle_planning_status_message(_message("planning", 7))
    planning = get_nav_state()["navigation_status"]
    assert planning["status"] == "planning"
    assert planning["planning_status"] == "planning"
    assert planning["planning_generation"] == 7
    assert planning["source"] == "/nav/planning_status"

    bridge._handle_planning_status_message(
        _message("path_ready", 7, elapsed_seconds=12.345)
    )
    ready = get_nav_state()["navigation_status"]
    assert ready["status"] == "path_ready"
    assert ready["planning_status"] == "path_ready"
    assert ready["planning_elapsed_seconds"] == pytest.approx(12.345)
    assert "12.345 秒" in ready["message"]
    assert broadcasts[-1][0] == "nav.navigation_status"


@pytest.mark.parametrize(
    ("planner_status", "error_code"),
    [
        ("failed", "GLOBAL_PLANNER_FAILED"),
        ("rejected", "GLOBAL_PLANNER_GOAL_REJECTED"),
    ],
)
def test_planning_failure_and_rejection_end_planning_state(
    planner_status: str,
    error_code: str,
):
    bridge, _ = _bridge()
    update_navigation_status({"status": "planning", "message": "正在规划"})

    bridge._handle_planning_status_message(
        _message(planner_status, 4, elapsed_seconds=8.25)
    )

    status = get_nav_state()["navigation_status"]
    assert status["status"] == "error"
    assert status["planning_status"] == planner_status
    assert status["error_code"] == error_code


def test_path_ready_does_not_overwrite_blocked_status():
    bridge, _ = _bridge()
    bridge._handle_planning_status_message(_message("planning", 3))
    update_navigation_status(
        {
            "status": "blocked",
            "message": "局部路径受阻",
            "error_code": "NAV_PATH_BLOCKED",
        }
    )

    bridge._handle_planning_status_message(_message("path_ready", 3))

    status = get_nav_state()["navigation_status"]
    assert status["status"] == "blocked"
    assert status["message"] == "局部路径受阻"
    assert status["planning_status"] == "path_ready"
    assert bridge._navigation_status_before_blocked == "path_ready"


def test_new_goal_generation_barrier_ignores_old_terminal_status():
    bridge, _ = _bridge()
    bridge._handle_planning_status_message(_message("planning", 10))
    bridge._begin_planning_goal_submission()
    update_navigation_status(
        {
            "status": "planning",
            "target_waypoint_id": "new-goal",
            "message": "正在规划新目标",
        }
    )

    bridge._handle_planning_status_message(_message("failed", 10))
    assert get_nav_state()["navigation_status"]["status"] == "planning"

    bridge._handle_planning_status_message(_message("queued", 11))
    bridge._handle_planning_status_message(_message("failed", 10))
    assert get_nav_state()["navigation_status"]["status"] == "planning"

    bridge._handle_planning_status_message(_message("path_ready", 11))
    status = get_nav_state()["navigation_status"]
    assert status["status"] == "path_ready"
    assert status["target_waypoint_id"] == "new-goal"
    assert status["planning_generation"] == 11


def test_new_planner_publisher_can_restart_generation_and_retires_old_writer():
    bridge, _ = _bridge()
    writer_a = SimpleNamespace(publisher_gid=b"planner-a")
    writer_b = SimpleNamespace(publisher_gid=b"planner-b")

    bridge._handle_planning_status_message(_message("queued", 9), writer_a)
    bridge._handle_planning_status_message(_message("queued", 1), writer_b)
    assert get_nav_state()["navigation_status"]["planning_generation"] == 1

    bridge._handle_planning_status_message(_message("failed", 10), writer_a)
    status = get_nav_state()["navigation_status"]
    assert status["status"] == "planning"
    assert status["planning_generation"] == 1


def test_elapsed_time_never_creates_a_botdog_planning_timeout():
    bridge, _ = _bridge()

    bridge._handle_planning_status_message(
        _message("planning", 2, elapsed_seconds=3600.0)
    )

    status = get_nav_state()["navigation_status"]
    assert status["status"] == "planning"
    assert status["error_code"] is None
    assert status["planning_elapsed_seconds"] == pytest.approx(3600.0)


def test_generationless_moving_heartbeat_does_not_hide_planner_failure():
    bridge, _ = _bridge()
    bridge._handle_planning_status_message(_message("failed", 2))
    bridge._navigation_task_active = False
    bridge._normalize_nav_status = lambda _payload: {
        "status": "navigating",
        "ros_status": "moving",
        "message": "旧执行链仍在上报 moving",
    }
    bridge._ignore_terminal_status_during_navigation_handoff = (
        lambda _status: False
    )
    bridge._restore_navigation_control_on_active_status = lambda _status: None
    bridge._release_navigation_control_on_terminal_status = (
        lambda *_args, **_kwargs: None
    )

    bridge._handle_nav_status_message(
        SimpleNamespace(data=json.dumps({"status": "moving"}))
    )

    status = get_nav_state()["navigation_status"]
    assert status["status"] == "error"
    assert status["planning_status"] == "failed"


@pytest.mark.parametrize(
    "payload",
    [
        "{not-json",
        "[]",
        json.dumps(
            {
                "status": "unknown",
                "generation": 1,
                "elapsed_seconds": 0,
            }
        ),
        json.dumps(
            {
                "status": "planning",
                "generation": True,
                "elapsed_seconds": 0,
            }
        ),
        json.dumps(
            {
                "status": "planning",
                "generation": 1,
                "elapsed_seconds": -1,
            }
        ),
    ],
)
def test_invalid_planning_status_messages_are_ignored(payload: str):
    bridge, broadcasts = _bridge()

    bridge._handle_planning_status_message(SimpleNamespace(data=payload))

    assert get_nav_state()["navigation_status"]["status"] == "idle"
    assert broadcasts == []


def test_planning_status_subscription_uses_configured_transient_reliable_qos(
    monkeypatch,
):
    class String:
        pass

    class ReliabilityPolicy:
        RELIABLE = "reliable"

    class DurabilityPolicy:
        TRANSIENT_LOCAL = "transient_local"

    class QoSProfile:
        def __init__(self, *, depth, reliability, durability):
            self.depth = depth
            self.reliability = reliability
            self.durability = durability

    std_msgs = ModuleType("std_msgs")
    std_msgs_msg = ModuleType("std_msgs.msg")
    std_msgs_msg.String = String
    rclpy = ModuleType("rclpy")
    rclpy_qos = ModuleType("rclpy.qos")
    rclpy_qos.DurabilityPolicy = DurabilityPolicy
    rclpy_qos.QoSProfile = QoSProfile
    rclpy_qos.ReliabilityPolicy = ReliabilityPolicy
    monkeypatch.setitem(sys.modules, "std_msgs", std_msgs)
    monkeypatch.setitem(sys.modules, "std_msgs.msg", std_msgs_msg)
    monkeypatch.setitem(sys.modules, "rclpy", rclpy)
    monkeypatch.setitem(sys.modules, "rclpy.qos", rclpy_qos)

    subscriptions = []

    class Node:
        def create_subscription(self, msg_type, topic, callback, qos):
            subscriptions.append((msg_type, topic, callback, qos))
            return object()

    bridge, _ = _bridge()
    bridge._node = Node()
    bridge._setup_planning_status_subscription()

    msg_type, topic, _, qos = subscriptions[0]
    assert msg_type is String
    assert topic == settings.ROS_NAV_PLANNING_STATUS_TOPIC
    assert qos.depth == 10
    assert qos.reliability == ReliabilityPolicy.RELIABLE
    assert qos.durability == DurabilityPolicy.TRANSIENT_LOCAL
