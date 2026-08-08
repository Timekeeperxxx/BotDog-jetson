from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from backend.config import settings
from backend.services_nav_state import get_nav_state, set_navigation_idle, update_navigation_status
from backend.services_ros_nav import RosNavBridge


@pytest.fixture(autouse=True)
def reset_navigation_state():
    set_navigation_idle("导航空闲")


def _make_bridge(monkeypatch, broadcast_calls: list[tuple[str, dict[str, object]]]) -> RosNavBridge:
    bridge = RosNavBridge.__new__(RosNavBridge)

    def fake_submit_broadcast(event_type: str, data: dict[str, object]) -> None:
        broadcast_calls.append((event_type, data))

    monkeypatch.setattr(bridge, "_submit_broadcast", fake_submit_broadcast)
    monkeypatch.setattr(bridge, "_diagnose_navigation_failure", lambda: None)
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


def test_nav_status_canceled_preserves_auto_track_paused_navigation(monkeypatch):
    broadcast_calls: list[tuple[str, dict[str, object]]] = []
    bridge = _make_bridge(monkeypatch, broadcast_calls)
    monkeypatch.setattr(
        bridge,
        "_auto_track_interrupted_navigation",
        lambda: {
            "task_id": "task_auto",
            "target_waypoint_id": "wp_auto",
            "target_name": "自动跟踪前目标",
        },
    )

    bridge._handle_nav_status_message(
        SimpleNamespace(
            data=json.dumps(
                {
                    "status": "canceled",
                    "task_id": "task_old",
                    "waypoint_id": "wp_old",
                    "message": "导航取消",
                    "timestamp": 1770000000.123,
                }
            )
        )
    )

    state = get_nav_state()["navigation_status"]
    assert state["status"] == "paused"
    assert state["ros_status"] == "canceled"
    assert state["task_id"] == "task_auto"
    assert state["target_waypoint_id"] == "wp_auto"
    assert state["target_name"] == "自动跟踪前目标"
    assert "自动跟踪陌生人" in state["message"]
    assert broadcast_calls[0][1]["status"] == "paused"


def test_nav_status_moving_without_task_id_preserves_active_task(monkeypatch):
    broadcast_calls: list[tuple[str, dict[str, object]]] = []
    bridge = _make_bridge(monkeypatch, broadcast_calls)
    update_navigation_status(
        {
            "status": "navigating",
            "task_id": "task_001",
            "target_waypoint_id": "wp_001",
            "target_name": "巡检任务",
            "message": "已发布导航启动信号",
        }
    )

    bridge._handle_nav_status_message(
        SimpleNamespace(
            data=json.dumps(
                {
                    "status": "moving",
                    "waypoint_id": "wp_002",
                    "message": "导航中",
                    "timestamp": 1770000000.456,
                }
            )
        )
    )

    state = get_nav_state()["navigation_status"]
    assert state["status"] == "navigating"
    assert state["task_id"] == "task_001"
    assert state["waypoint_id"] == "wp_002"
    assert broadcast_calls[0][1]["task_id"] == "task_001"


def test_nav_status_without_waypoint_context_preserves_latest_single_goal(monkeypatch):
    broadcast_calls: list[tuple[str, dict[str, object]]] = []
    bridge = _make_bridge(monkeypatch, broadcast_calls)
    update_navigation_status(
        {
            "status": "planning",
            "target_waypoint_id": "wp-lower-floor",
            "target_name": "下一层目标",
            "message": "正在规划",
        }
    )

    bridge._handle_nav_status_message(
        SimpleNamespace(
            data=json.dumps(
                {
                    "status": "accepted",
                    "message": "目标已接收",
                    "timestamp": 1770000000.789,
                }
            )
        )
    )

    state = get_nav_state()["navigation_status"]
    assert state["status"] == "navigating"
    assert state["target_waypoint_id"] == "wp-lower-floor"
    assert state["target_name"] == "下一层目标"


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


def test_nav_status_failed_uses_global_planner_diagnosis(monkeypatch):
    broadcast_calls: list[tuple[str, dict[str, object]]] = []
    bridge = _make_bridge(monkeypatch, broadcast_calls)
    monkeypatch.setattr(
        bridge,
        "_diagnose_navigation_failure",
        lambda: {
            "error_code": "GLOBAL_PLANNER_GOAL_NOT_ON_GROUND",
            "message": "目标点不在 global_planner 的地面点云附近",
            "evidence": "Goal is not found.",
        },
    )

    bridge._handle_nav_status_message(
        SimpleNamespace(
            data=json.dumps(
                {
                    "status": "failed",
                    "task_id": "task_002",
                    "waypoint_id": "wp_002",
                    "message": "路径规划失败",
                    "error_code": "PLAN_FAILED",
                    "timestamp": 1770000001.0,
                }
            )
        )
    )

    state = get_nav_state()["navigation_status"]
    assert state["status"] == "error"
    assert state["error_code"] == "GLOBAL_PLANNER_GOAL_NOT_ON_GROUND"
    assert state["message"] == "目标点不在 global_planner 的地面点云附近"
    assert broadcast_calls[0][1]["error_code"] == "GLOBAL_PLANNER_GOAL_NOT_ON_GROUND"


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


def test_nav_auto_track_workflow_message_applies_control_on_backend_loop(monkeypatch):
    broadcast_calls: list[tuple[str, dict[str, object]]] = []
    bridge = _make_bridge(monkeypatch, broadcast_calls)
    control_calls: list[bool] = []

    class ImmediateLoop:
        @staticmethod
        def call_soon_threadsafe(callback, *args):
            callback(*args)

    bridge._loop = ImmediateLoop()
    monkeypatch.setattr(
        "backend.api.routes.nav_auto_track_helpers.apply_auto_track_workflow_control",
        lambda enabled: (
            control_calls.append(enabled)
            or {
                "requested": True,
                "enabled": enabled,
                "state": "IDLE" if enabled else "DISABLED",
                "message": "ok",
            }
        ),
    )

    bridge._handle_auto_track_control_message(
        SimpleNamespace(
            data=json.dumps(
                {
                    "type": "auto_track_control",
                    "enabled": True,
                    "task_id": "task_001",
                    "step_index": 2,
                }
            )
        )
    )

    assert control_calls == [True]
    assert broadcast_calls == [
        (
            "nav.auto_track_control",
            {
                "task_id": "task_001",
                "step_index": 2,
                "enabled": True,
                "state": "IDLE",
                "success": True,
                "message": "ok",
            },
        )
    ]


@pytest.mark.parametrize(
    "payload",
    [
        "",
        "{not json",
        json.dumps({"enabled": "true"}),
        json.dumps([]),
    ],
)
def test_nav_auto_track_workflow_invalid_message_is_ignored(monkeypatch, payload):
    broadcast_calls: list[tuple[str, dict[str, object]]] = []
    bridge = _make_bridge(monkeypatch, broadcast_calls)
    scheduled_calls: list[object] = []
    bridge._loop = SimpleNamespace(
        call_soon_threadsafe=lambda *args: scheduled_calls.append(args)
    )

    bridge._handle_auto_track_control_message(SimpleNamespace(data=payload))

    assert scheduled_calls == []
    assert broadcast_calls == []


def test_stale_idle_after_new_nav_start_does_not_release_navigation(monkeypatch):
    broadcast_calls: list[tuple[str, dict[str, object]]] = []
    bridge = _make_bridge(monkeypatch, broadcast_calls)
    bridge._navigation_terminal_release_blocked_until = time.monotonic() + 2.0
    bridge._navigation_control_expected = True
    update_navigation_status(
        {
            "status": "navigating",
            "message": "新目标导航中",
        }
    )
    release_calls: list[str] = []

    class DummyCoordinator:
        def release_navigation_control(self) -> None:
            release_calls.append("release")

    monkeypatch.setattr(
        "backend.nav_auto_track_coordinator.get_nav_auto_track_coordinator",
        lambda: DummyCoordinator(),
    )

    bridge._handle_nav_status_message(
        SimpleNamespace(
            data=json.dumps(
                {
                    "status": "canceled",
                    "message": "上一轮导航取消",
                    "timestamp": 1770000003.0,
                }
            )
        )
    )

    assert release_calls == []
    assert get_nav_state()["navigation_status"]["status"] == "navigating"


def test_idle_after_nav_start_grace_releases_navigation(monkeypatch):
    broadcast_calls: list[tuple[str, dict[str, object]]] = []
    bridge = _make_bridge(monkeypatch, broadcast_calls)
    bridge._navigation_terminal_release_blocked_until = time.monotonic() - 1.0
    bridge._navigation_control_expected = True
    release_calls: list[str] = []

    class DummyCoordinator:
        def release_navigation_control(self) -> None:
            release_calls.append("release")

    monkeypatch.setattr(
        "backend.nav_auto_track_coordinator.get_nav_auto_track_coordinator",
        lambda: DummyCoordinator(),
    )

    bridge._handle_nav_status_message(
        SimpleNamespace(
            data=json.dumps(
                {
                    "status": "canceled",
                    "message": "导航取消",
                    "timestamp": 1770000004.0,
                }
            )
        )
    )

    assert release_calls == ["release"]
    assert bridge._navigation_control_expected is False


def test_stale_scan_failure_after_new_nav_start_does_not_release_or_replace_status(
    monkeypatch,
):
    broadcast_calls: list[tuple[str, dict[str, object]]] = []
    bridge = _make_bridge(monkeypatch, broadcast_calls)
    bridge._navigation_terminal_release_blocked_until = time.monotonic() + 2.0
    bridge._navigation_control_expected = True
    update_navigation_status(
        {
            "status": "navigating",
            "message": "新目标导航中",
        }
    )
    release_calls: list[str] = []

    class DummyCoordinator:
        def release_navigation_control(self) -> None:
            release_calls.append("release")

    monkeypatch.setattr(
        "backend.nav_auto_track_coordinator.get_nav_auto_track_coordinator",
        lambda: DummyCoordinator(),
    )

    bridge._handle_nav_status_message(
        SimpleNamespace(
            data=json.dumps(
                {
                    "status": "failed",
                    "message": "上一轮 SCAN 重规划失败",
                    "error_code": "SCAN_REPLAN_FAILED",
                    "timestamp": 1770000005.0,
                }
            )
        )
    )

    assert release_calls == []
    assert broadcast_calls == []
    state = get_nav_state()["navigation_status"]
    assert state["status"] == "navigating"
    assert state["message"] == "新目标导航中"


def test_moving_status_restores_expected_navigation_control(monkeypatch):
    broadcast_calls: list[tuple[str, dict[str, object]]] = []
    bridge = _make_bridge(monkeypatch, broadcast_calls)
    bridge._navigation_terminal_release_blocked_until = 0.0
    bridge._navigation_control_expected = True
    request_calls: list[str] = []

    class DummyCoordinator:
        def request_navigation_control(self) -> None:
            request_calls.append("request")

        def release_navigation_control(self) -> None:
            raise AssertionError("moving status must not release navigation")

    monkeypatch.setattr(
        "backend.nav_auto_track_coordinator.get_nav_auto_track_coordinator",
        lambda: DummyCoordinator(),
    )

    bridge._handle_nav_status_message(
        SimpleNamespace(
            data=json.dumps(
                {
                    "status": "moving",
                    "message": "局部规划已恢复",
                    "timestamp": 1770000006.0,
                }
            )
        )
    )

    assert request_calls == ["request"]
    assert get_nav_state()["navigation_status"]["status"] == "navigating"


def test_moving_status_after_explicit_stop_does_not_restore_navigation_control(
    monkeypatch,
):
    broadcast_calls: list[tuple[str, dict[str, object]]] = []
    bridge = _make_bridge(monkeypatch, broadcast_calls)
    bridge._navigation_terminal_release_blocked_until = 0.0
    bridge._navigation_control_expected = False
    request_calls: list[str] = []

    class DummyCoordinator:
        def request_navigation_control(self) -> None:
            request_calls.append("request")

        def release_navigation_control(self) -> None:
            raise AssertionError("moving status must not be terminal")

    monkeypatch.setattr(
        "backend.nav_auto_track_coordinator.get_nav_auto_track_coordinator",
        lambda: DummyCoordinator(),
    )

    bridge._handle_nav_status_message(
        SimpleNamespace(
            data=json.dumps(
                {
                    "status": "moving",
                    "message": "停止后的迟到消息",
                    "timestamp": 1770000007.0,
                }
            )
        )
    )

    assert request_calls == []


def test_tf_pose_uses_receive_time_for_freshness(monkeypatch):
    ros_now = time.time()
    bridge = RosNavBridge.__new__(RosNavBridge)
    bridge._tf_buffer = SimpleNamespace(
        lookup_transform=lambda _target, _source, _time: SimpleNamespace(
            header=SimpleNamespace(
                stamp=SimpleNamespace(
                    sec=int(ros_now),
                    nanosec=int((ros_now % 1.0) * 1_000_000_000),
                )
            ),
            transform=SimpleNamespace(
                translation=SimpleNamespace(x=1.0, y=2.0, z=0.0),
                rotation=SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0),
            ),
        )
    )
    bridge._rclpy = object()
    monkeypatch.setattr(settings, "ROS_NAV_FRAME_ID", "map")
    monkeypatch.setattr(settings, "ROS_NAV_BASE_FRAME_ID", "base_footprint")

    before = time.time()
    pose = bridge._lookup_tf_pose()
    after = time.time()

    assert pose["x"] == 1.0
    assert pose["source_frame"] == "base_footprint"
    assert before <= pose["timestamp"] <= after
    assert pose["ros_timestamp"] == pytest.approx(ros_now, abs=1e-6)


def test_tf_pose_accepts_latest_transform_available_in_local_buffer(monkeypatch):
    bridge = RosNavBridge.__new__(RosNavBridge)
    bridge._tf_buffer = SimpleNamespace(
        lookup_transform=lambda _target, _source, _time: SimpleNamespace(
            header=SimpleNamespace(stamp=SimpleNamespace(sec=1, nanosec=0)),
            transform=SimpleNamespace(
                translation=SimpleNamespace(x=1.0, y=2.0, z=0.0),
                rotation=SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0),
            ),
        )
    )
    bridge._rclpy = object()
    monkeypatch.setattr(settings, "ROS_NAV_FRAME_ID", "map")
    monkeypatch.setattr(settings, "ROS_NAV_BASE_FRAME_ID", "base_footprint")

    pose = bridge._lookup_tf_pose()

    assert pose["x"] == 1.0
    assert pose["source_frame"] == "base_footprint"
    assert pose["ros_timestamp"] == 1.0
