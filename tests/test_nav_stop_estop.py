from __future__ import annotations

import asyncio

from backend.api.routes import control as control_routes
from backend.api.routes import nav as nav_routes
from backend.auth.schemas import AuthUserInternal
from backend.services_nav_state import (
    clear_global_path,
    get_nav_state,
    set_navigation_idle,
    update_execution_path,
    update_global_path,
)


def test_nav_stop_task_publishes_nav_start_false_and_clears_state(monkeypatch):
    audit_messages: list[str] = []
    clear_calls: list[str] = []
    status_updates: list[dict[str, object]] = []
    publish_calls: list[bool] = []
    task_publish_calls: list[bool] = []

    class DummyBridge:
        def publish_navigation_task_start(self, enabled: bool = True) -> dict[str, object]:
            task_publish_calls.append(enabled)
            return {
                "success": True,
                "topic": "/nav_task_start",
                "data": enabled,
            }

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
    monkeypatch.setattr(
        "backend.services_nav_localization.stop_cmd_vel_script",
        lambda: {"success": True, "running": False, "pid": 1234},
    )
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
    assert result["task_start"]["data"] is False
    assert publish_calls == [False]
    assert task_publish_calls == [False]
    assert clear_calls == ["clear"]
    assert status_updates
    assert status_updates[0]["status"] == "idle"
    assert "已发布导航停止信号" in status_updates[0]["message"]
    assert audit_messages
    assert "nav_start_topic" not in audit_messages[0]


def test_nav_emergency_stop_soft_stops_without_killing_navigation(monkeypatch):
    audit_messages: list[str] = []
    clear_calls: list[str] = []
    idle_messages: list[str] = []
    zero_cmd_vel_calls: list[tuple[int, float]] = []
    nav_start_calls: list[bool] = []

    class DummyControlService:
        async def send_navigation_velocity(self, vx: float, vy: float, vyaw: float) -> bool:
            assert (vx, vy, vyaw) == (0.0, 0.0, 0.0)
            return True

    class DummyBridge:
        def publish_navigation_task_start(self, enabled: bool = True) -> dict[str, object]:
            return {"success": True, "topic": "/nav_task_start", "data": enabled}

        def publish_navigation_start(self, enabled: bool = True) -> dict[str, object]:
            nav_start_calls.append(enabled)
            return {"success": True, "topic": "/nav_start", "data": enabled}

        def publish_zero_cmd_vel(self, publish_count: int = 10, interval_s: float = 0.03) -> dict[str, object]:
            zero_cmd_vel_calls.append((publish_count, interval_s))
            return {"success": True, "topic": "/cmd_vel", "publish_count": publish_count}

    async def fake_audit_log(*args, **kwargs):
        audit_messages.append(kwargs["message"])

    def fake_clear_global_path() -> None:
        clear_calls.append("clear")

    def fake_set_navigation_idle(message: str = "导航空闲") -> dict[str, object]:
        idle_messages.append(message)
        return {"status": "idle", "message": message}

    monkeypatch.setattr("backend.control_service.get_control_service", lambda: DummyControlService())
    monkeypatch.setattr(
        "backend.services_nav_localization.set_cmd_vel_estop",
        lambda active, reason="": {"success": True, "active": active, "reason": reason},
    )
    monkeypatch.setattr(
        "backend.services_nav_localization.stop_cmd_vel_script",
        lambda: (_ for _ in ()).throw(AssertionError("软停不应停止 cmd_vel 桥接")),
    )
    monkeypatch.setattr(
        "backend.services_nav_localization.stop_navigation_processes",
        lambda: (_ for _ in ()).throw(AssertionError("软停不应杀死导航进程")),
    )
    monkeypatch.setattr(nav_routes, "get_ros_nav_bridge", lambda: DummyBridge())
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
    assert result["message"] == "导航已软停：全速度为 0，导航定位进程保持运行"
    assert result["topic"] == "/cmd_vel"
    assert result["control_zero"]["sent"] is True
    assert result["control_zero"]["linear"] == {"x": 0.0, "y": 0.0, "z": 0.0}
    assert result["cmd_vel_estop"]["active"] is True
    assert result["cmd_vel_zero"]["topic"] == "/cmd_vel"
    assert result["navigation_processes_preserved"] is True
    assert zero_cmd_vel_calls == [(20, 0.02)]
    assert nav_start_calls == [False]
    assert clear_calls == ["clear"]
    assert idle_messages == ["导航已软停：速度已归零，导航定位进程保持运行"]
    assert "soft_stop=true" in audit_messages[0]
    assert "navigation_processes_preserved=true" in audit_messages[0]
    assert audit_messages


def test_restart_localization_clears_all_estop_layers_before_restart(monkeypatch):
    calls: list[object] = []
    audit_messages: list[str] = []

    class DummyStateMachine:
        def reset_emergency_stop(self) -> None:
            calls.append("reset_state_machine")

    class DummyArbiter:
        def release_control(self, owner) -> None:
            calls.append(("release_control", owner.value))

    async def fake_audit_log(*args, **kwargs):
        audit_messages.append(kwargs["message"])

    monkeypatch.setattr(
        "backend.services_nav_localization.set_cmd_vel_estop",
        lambda active, reason="": calls.append(("cmd_vel_estop", active, reason))
        or {"success": True, "active": active, "reason": reason},
    )
    monkeypatch.setattr(
        "backend.services_radar_health.check_livox_network_preflight",
        lambda: {"ok": True, "message": "雷达物理链路正常"},
    )
    monkeypatch.setattr("backend.state_machine_state.get_state_machine", lambda: DummyStateMachine())
    monkeypatch.setattr("backend.control_arbiter.get_control_arbiter", lambda: DummyArbiter())
    monkeypatch.setattr(nav_routes, "_cancel_pending_auto_track_resume", lambda reason: calls.append(("cancel_resume", reason)))
    monkeypatch.setattr(nav_routes, "_release_navigation_control", lambda: calls.append("release_navigation"))
    monkeypatch.setattr("backend.services_nav_task_runtime.clear_nav_task_runtime", lambda: calls.append("clear_task"))
    monkeypatch.setattr("backend.services_nav_state.reset_localization_tracking", lambda message: calls.append(("reset_tracking", message)))
    monkeypatch.setattr(
        "backend.services_nav_localization.restart_navigation_localization",
        lambda: calls.append("restart_navigation") or {"success": True, "pid": 4321, "message": "已重启"},
    )
    monkeypatch.setattr(nav_routes, "safe_write_audit_log", fake_audit_log)

    result = asyncio.run(
        nav_routes.nav_restart_localization(
            user=AuthUserInternal(id=1, username="operator", role="operator", token_version=1),
            db=object(),
        )
    )

    assert result["pid"] == 4321
    assert ("cmd_vel_estop", False, "nav_localization_restart") in calls
    assert "reset_state_machine" in calls
    assert ("release_control", "E_STOP") in calls
    assert calls.index(("cmd_vel_estop", False, "nav_localization_restart")) < calls.index("restart_navigation")
    assert calls.index("reset_state_machine") < calls.index("restart_navigation")
    assert calls.index(("release_control", "E_STOP")) < calls.index("restart_navigation")
    assert "自动解除急停=True" in audit_messages[0]
    assert get_nav_state()["navigation_status"]["status"] == "idle"


def test_services_nav_state_clear_global_path_and_idle():
    update_global_path({"frame_id": "map", "points": [{"x": 1, "y": 2, "z": 0}]})
    update_execution_path({"frame_id": "map", "points": [{"x": 1, "y": 2, "z": 0}]})
    state = get_nav_state()
    assert state["global_path"] is not None
    assert state["execution_path"] is not None

    clear_global_path()
    state = get_nav_state()
    assert state["global_path"] is None
    assert state["execution_path"] is None

    set_navigation_idle("测试 idle")
    state = get_nav_state()
    assert state["navigation_status"]["status"] == "idle"
    assert state["navigation_status"]["message"] == "测试 idle"


def test_control_emergency_stop_clamps_both_navigation_and_direct_adapter(monkeypatch):
    calls: list[object] = []

    class DummyStateMachine:
        def trigger_emergency_stop(self) -> None:
            calls.append("state_e_stop")

    class DummyArbiter:
        def activate_e_stop(self) -> None:
            calls.append("owner_e_stop")

    class DummyBridge:
        def publish_navigation_task_start(self, enabled: bool = True):
            calls.append(("task_start", enabled))

        def publish_navigation_start(self, enabled: bool = True):
            calls.append(("nav_start", enabled))

        def publish_zero_cmd_vel(self, publish_count: int, interval_s: float):
            calls.append(("zero", publish_count, interval_s))

    class DummyControlService:
        async def force_stop(self):
            calls.append("force_stop")

    async def fake_audit_log(*args, **kwargs):
        calls.append("audit")

    monkeypatch.setattr(control_routes, "get_state_machine", lambda: DummyStateMachine())
    monkeypatch.setattr(control_routes, "get_ros_nav_bridge", lambda: DummyBridge())
    monkeypatch.setattr(control_routes, "set_cmd_vel_estop", lambda active, reason="": calls.append(("clamp", active, reason)))
    monkeypatch.setattr(control_routes, "stop_cmd_vel_script", lambda: calls.append("stop_sender"))
    monkeypatch.setattr(control_routes, "safe_write_audit_log", fake_audit_log)
    monkeypatch.setattr("backend.control_arbiter.get_control_arbiter", lambda: DummyArbiter())
    monkeypatch.setattr("backend.control_service.get_control_service", lambda: DummyControlService())

    response = asyncio.run(control_routes.emergency_stop(db=object()))

    assert response.success is True
    assert "state_e_stop" in calls
    assert ("clamp", True, "control_e_stop") in calls
    assert "owner_e_stop" in calls
    assert ("nav_start", False) in calls
    assert ("task_start", False) in calls
    assert ("zero", 20, 0.02) in calls
    assert "stop_sender" in calls
    assert "force_stop" in calls
