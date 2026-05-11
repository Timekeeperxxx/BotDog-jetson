from __future__ import annotations

import asyncio

from backend.api.routes import nav as nav_routes
from backend.auth.schemas import AuthUserInternal
from backend.services_nav_state import (
    clear_global_path,
    get_nav_state,
    set_navigation_idle,
    update_global_path,
)


def test_nav_stop_task_publishes_nav_start_false_and_clears_state(monkeypatch):
    audit_messages: list[str] = []
    clear_calls: list[str] = []
    status_updates: list[dict[str, object]] = []
    publish_calls: list[bool] = []

    class DummyBridge:
        def publish_navigation_start(self, enabled: bool = True) -> dict[str, object]:
            publish_calls.append(enabled)
            assert enabled is False
            return {
                "success": True,
                "topic": "/nav_start",
                "data": False,
            }

    async def fake_audit_log(*args, **kwargs):
        audit_messages.append(kwargs["message"])

    def fake_clear_global_path() -> None:
        clear_calls.append("clear")

    def fake_update_navigation_status(payload: dict[str, object]) -> dict[str, object]:
        status_updates.append(payload)
        return payload

    monkeypatch.setattr(nav_routes, "get_ros_nav_bridge", lambda: DummyBridge())
    monkeypatch.setattr("backend.services_nav_tasks.get_nav_task", lambda task_id: {"id": task_id, "name": "任务1"})
    monkeypatch.setattr("backend.services_nav_state.clear_global_path", fake_clear_global_path)
    monkeypatch.setattr("backend.services_nav_state.update_navigation_status", fake_update_navigation_status)
    monkeypatch.setattr(nav_routes, "safe_write_audit_log", fake_audit_log)

    result = asyncio.run(
        nav_routes.nav_stop_task(
            "task_001",
            user=AuthUserInternal(id=1, username="admin", role="operator", token_version=1),
            db=object(),
        )
    )

    assert result["success"] is True
    assert result["topic"] == "/nav_start"
    assert result["data"] is False
    assert result["nav_start"]["data"] is False
    assert publish_calls == [False]
    assert clear_calls == ["clear"]
    assert status_updates
    assert status_updates[0]["status"] == "idle"
    assert "已发布导航停止信号" in status_updates[0]["message"]
    assert audit_messages
    assert "nav_start_topic" not in audit_messages[0]


def test_nav_emergency_stop_stops_processes_and_sets_idle(monkeypatch):
    audit_messages: list[str] = []
    clear_calls: list[str] = []
    idle_messages: list[str] = []

    class DummyControlResult:
        result = "ACCEPTED"
        ack_cmd = "force_stop"

    class DummyControlService:
        async def force_stop(self) -> DummyControlResult:
            return DummyControlResult()

    async def fake_audit_log(*args, **kwargs):
        audit_messages.append(kwargs["message"])

    def fake_stop_navigation_processes() -> dict[str, object]:
        return {
            "success": True,
            "running": False,
            "pids": [111, 222],
            "message": "已停止导航后台进程",
        }

    def fake_clear_global_path() -> None:
        clear_calls.append("clear")

    def fake_set_navigation_idle(message: str = "导航空闲") -> dict[str, object]:
        idle_messages.append(message)
        return {"status": "idle", "message": message}

    monkeypatch.setattr("backend.control_service.get_control_service", lambda: DummyControlService())
    monkeypatch.setattr("backend.services_nav_localization.stop_navigation_processes", fake_stop_navigation_processes)
    monkeypatch.setattr("backend.services_nav_state.clear_global_path", fake_clear_global_path)
    monkeypatch.setattr("backend.services_nav_state.set_navigation_idle", fake_set_navigation_idle)
    monkeypatch.setattr(nav_routes, "safe_write_audit_log", fake_audit_log)

    result = asyncio.run(
        nav_routes.nav_emergency_stop(
            user=AuthUserInternal(id=1, username="admin", role="operator", token_version=1),
            db=object(),
        )
    )

    assert result["success"] is True
    assert result["message"] == "已触发导航急停"
    assert result["topic"] is None
    assert result["control_stop"]["result"] == "ACCEPTED"
    assert result["control_stop"]["ack_cmd"] == "force_stop"
    assert result["nav_stop"]["pids"] == [111, 222]
    assert clear_calls == ["clear"]
    assert idle_messages == ["已触发导航急停"]
    assert audit_messages


def test_services_nav_state_clear_global_path_and_idle():
    update_global_path({"frame_id": "map", "points": [{"x": 1, "y": 2, "z": 0}]})
    state = get_nav_state()
    assert state["global_path"] is not None

    clear_global_path()
    state = get_nav_state()
    assert state["global_path"] is None

    set_navigation_idle("测试 idle")
    state = get_nav_state()
    assert state["navigation_status"]["status"] == "idle"
    assert state["navigation_status"]["message"] == "测试 idle"

