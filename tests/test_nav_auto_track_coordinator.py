from __future__ import annotations

import asyncio

import pytest

from backend.api.routes import nav as nav_routes
from backend.auth.schemas import AuthUserInternal
from backend.config import settings
from backend.control_arbiter import ControlArbiter, set_control_arbiter
from backend.nav_auto_track_coordinator import NavAutoTrackCoordinator
from backend.services_nav_state import clear_robot_pose, get_nav_state, set_navigation_idle, update_navigation_status, update_robot_pose
from backend.tracking_types import ControlOwner
from backend.api.routes.nav_auto_track_helpers import ensure_auto_track_enabled_for_navigation


class DummyBridge:
    def __init__(self) -> None:
        self.nav_start_calls: list[bool] = []

    def publish_navigation_start(self, enabled: bool = True) -> dict[str, object]:
        self.nav_start_calls.append(enabled)
        return {"success": True, "topic": "/nav_start", "data": enabled}


def setup_function() -> None:
    set_navigation_idle("测试初始化")
    set_control_arbiter(None)
    settings.NAV_AUTO_TRACK_RESUME_TIMEOUT_S = 0
    settings.NAV_AUTO_TRACK_REQUIRE_FRESH_TF = True


def teardown_function() -> None:
    set_navigation_idle("测试结束")
    set_control_arbiter(None)
    clear_robot_pose()
    settings.NAV_AUTO_TRACK_DURING_NAV_ENABLED = False
    settings.NAV_AUTO_TRACK_AUTO_ENABLE = False
    settings.NAV_AUTO_TRACK_RESUME_TIMEOUT_S = 3.0
    settings.NAV_AUTO_TRACK_REQUIRE_FRESH_TF = True


def test_control_arbiter_auto_track_preempts_navigation() -> None:
    arbiter = ControlArbiter()

    assert arbiter.request_control(ControlOwner.NAVIGATION) is True
    assert arbiter.owner == ControlOwner.NAVIGATION
    assert arbiter.can_navigation_send() is True

    assert arbiter.request_control(ControlOwner.AUTO_TRACK) is True
    assert arbiter.owner == ControlOwner.AUTO_TRACK
    assert arbiter.can_auto_track_send() is True
    assert arbiter.can_navigation_send() is False

    arbiter.release_control(ControlOwner.AUTO_TRACK)
    assert arbiter.owner == ControlOwner.NAVIGATION


def test_coordinator_pauses_and_resumes_navigation(monkeypatch) -> None:
    bridge = DummyBridge()
    monkeypatch.setattr("backend.nav_bridge_state.get_ros_nav_bridge", lambda: bridge)
    arbiter = ControlArbiter()
    set_control_arbiter(arbiter)

    update_robot_pose({"x": 1.0, "y": 2.0, "z": 0.0, "yaw": 0.0, "timestamp": 9999999999.0})
    update_navigation_status(
        {
            "status": "navigating",
            "task_id": "task_001",
            "target_waypoint_id": "wp_001",
            "target_name": "巡检点1",
            "message": "导航中",
        }
    )

    coordinator = NavAutoTrackCoordinator()
    pause_result = asyncio.run(coordinator.pause_navigation_for_tracking(track_id=7))

    assert pause_result["success"] is True
    assert bridge.nav_start_calls == [False]
    assert arbiter.owner == ControlOwner.AUTO_TRACK
    nav_status = get_nav_state()["navigation_status"]
    assert nav_status["status"] == "paused"
    assert nav_status["task_id"] == "task_001"
    assert "自动跟踪陌生人" in nav_status["message"]

    resume_result = asyncio.run(coordinator.resume_navigation_after_tracking(reason="TARGET_LOST"))

    assert resume_result["success"] is True
    assert bridge.nav_start_calls == [False, True]
    assert arbiter.owner == ControlOwner.NAVIGATION
    nav_status = get_nav_state()["navigation_status"]
    assert nav_status["status"] == "navigating"
    assert nav_status["task_id"] == "task_001"
    assert "当前 TF" in nav_status["message"]


def test_coordinator_does_not_resume_after_user_intervention(monkeypatch) -> None:
    bridge = DummyBridge()
    monkeypatch.setattr("backend.nav_bridge_state.get_ros_nav_bridge", lambda: bridge)
    arbiter = ControlArbiter()
    set_control_arbiter(arbiter)

    update_robot_pose({"x": 1.0, "y": 2.0, "z": 0.0, "yaw": 0.0, "timestamp": 9999999999.0})
    update_navigation_status(
        {
            "status": "navigating",
            "task_id": "task_001",
            "target_waypoint_id": "wp_001",
            "target_name": "巡检点1",
            "message": "导航中",
        }
    )

    coordinator = NavAutoTrackCoordinator()
    asyncio.run(coordinator.pause_navigation_for_tracking(track_id=7))
    coordinator.cancel_pending_resume("nav_task_stop")
    resume_result = asyncio.run(coordinator.resume_navigation_after_tracking(reason="TARGET_LOST"))

    assert resume_result["skipped"] is True
    assert bridge.nav_start_calls == [False]


@pytest.mark.asyncio
async def test_coordinator_keeps_interrupted_navigation_when_tf_temporarily_unavailable(monkeypatch) -> None:
    bridge = DummyBridge()
    monkeypatch.setattr("backend.nav_bridge_state.get_ros_nav_bridge", lambda: bridge)
    arbiter = ControlArbiter()
    set_control_arbiter(arbiter)

    update_navigation_status(
        {
            "status": "navigating",
            "task_id": "task_001",
            "target_waypoint_id": "wp_001",
            "target_name": "巡检点1",
            "message": "导航中",
        }
    )

    coordinator = NavAutoTrackCoordinator()
    pause_result = await coordinator.pause_navigation_for_tracking(track_id=7)
    assert pause_result["success"] is True
    assert bridge.nav_start_calls == [False]

    clear_robot_pose()
    resume_result = await coordinator.resume_navigation_after_tracking(reason="TARGET_LOST")

    assert resume_result["success"] is False
    assert resume_result["reason"] == "robot_pose_unavailable"
    assert resume_result["retry_scheduled"] is True
    assert bridge.nav_start_calls == [False]
    status = coordinator.get_status()
    assert status["interrupted_task_id"] == "task_001"
    assert status["resume_retry_scheduled"] is True

    update_robot_pose({"x": 1.0, "y": 2.0, "z": 0.0, "yaw": 0.0, "timestamp": 9999999999.0})
    retry_result = await coordinator.resume_navigation_after_tracking(
        reason="TARGET_LOST:robot_pose_unavailable",
        apply_delay=False,
    )

    assert retry_result["success"] is True
    assert bridge.nav_start_calls == [False, True]
    assert arbiter.owner == ControlOwner.NAVIGATION
    status = coordinator.get_status()
    assert status["interrupted_task_id"] is None
    assert status["resume_retry_scheduled"] is False


def test_nav_auto_track_mode_endpoint_enables_tracking_during_active_navigation(monkeypatch) -> None:
    calls: list[str] = []

    class DummyAutoTrack:
        def __init__(self) -> None:
            self.enabled = False

        def get_status(self) -> dict[str, object]:
            return {"enabled": self.enabled, "state": "IDLE" if self.enabled else "DISABLED"}

        def enable(self) -> None:
            self.enabled = True
            calls.append("enable")

        def disable(self) -> None:
            self.enabled = False
            calls.append("disable")

    async def fake_audit_log(*args, **kwargs):
        calls.append("audit")

    dummy = DummyAutoTrack()
    monkeypatch.setattr("backend.auto_track_service.get_auto_track_service", lambda: dummy)
    monkeypatch.setattr("backend.guard_mission_service.get_guard_mission_service", lambda: None)
    monkeypatch.setattr(nav_routes, "safe_write_audit_log", fake_audit_log)
    update_navigation_status({"status": "navigating", "task_id": "task_001", "message": "导航中"})

    result = asyncio.run(
        nav_routes.nav_set_auto_track_mode(
            nav_routes.NavAutoTrackModeRequest(enabled=True),
            user=AuthUserInternal(id=1, username="admin", role="operator", token_version=1),
            db=object(),
        )
    )

    assert result["enabled"] is True
    assert result["auto_track_enabled"] is True
    assert settings.NAV_AUTO_TRACK_DURING_NAV_ENABLED is True
    assert settings.NAV_AUTO_TRACK_AUTO_ENABLE is True
    assert calls == ["enable", "audit"]

    result = asyncio.run(
        nav_routes.nav_set_auto_track_mode(
            nav_routes.NavAutoTrackModeRequest(enabled=False),
            user=AuthUserInternal(id=1, username="admin", role="operator", token_version=1),
            db=object(),
        )
    )

    assert result["enabled"] is False
    assert result["auto_track_enabled"] is False
    assert settings.NAV_AUTO_TRACK_DURING_NAV_ENABLED is False
    assert settings.NAV_AUTO_TRACK_AUTO_ENABLE is False
    assert calls == ["enable", "audit", "disable", "audit"]


def test_explicit_auto_track_workflow_starts_disabled_until_control_step(monkeypatch) -> None:
    calls: list[str] = []

    class DummyAutoTrack:
        enabled = True

        def disable(self) -> None:
            self.enabled = False
            calls.append("disable")

        def get_status(self) -> dict[str, object]:
            return {
                "enabled": self.enabled,
                "state": "IDLE" if self.enabled else "DISABLED",
            }

    dummy = DummyAutoTrack()
    monkeypatch.setattr("backend.auto_track_service.get_auto_track_service", lambda: dummy)

    result = ensure_auto_track_enabled_for_navigation(
        {
            "id": "task_001",
            "steps": [
                {"type": "navigate_waypoint", "waypointId": "wp-a"},
                {"type": "auto_track_control", "enabled": True},
            ],
        }
    )

    assert calls == ["disable"]
    assert result["requested"] is False
    assert result["enabled"] is False
    assert "任务流程控制" in result["message"]
