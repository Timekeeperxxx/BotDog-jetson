from __future__ import annotations

import asyncio
import threading

import pytest
from fastapi import HTTPException

from backend.api.routes import nav as nav_routes
from backend.auth.schemas import AuthUserInternal


def test_nav_go_to_waypoint_replaces_goal_without_nav_start(monkeypatch):
    waypoint = {
        "id": "wp_001",
        "map_id": "Scene1_实验室一楼",
        "name": "巡检点1",
        "x": 1.0,
        "y": 2.0,
        "z": -0.83,
        "yaw": 1.57,
        "frame_id": "map",
    }
    audit_messages: list[str] = []
    publish_order: list[str] = []
    publish_thread_ids: list[int] = []
    task_start_calls: list[bool] = []
    request_thread_id = threading.get_ident()

    class DummyBridge:
        def publish_navigation_task_start(self, enabled: bool = True) -> dict[str, object]:
            publish_order.append("task_start")
            task_start_calls.append(enabled)
            return {
                "success": True,
                "topic": "/nav_task_start",
                "data": enabled,
            }

        def publish_navigation_start(self, enabled: bool = True) -> dict[str, object]:
            raise AssertionError("single-point go-to must not publish /nav_start")

        def publish_goal_xyz_yaw(self, payload: dict[str, object]) -> dict[str, object]:
            publish_order.append("goal")
            publish_thread_ids.append(threading.get_ident())
            assert payload == waypoint
            return {
                "success": True,
                "xyz_topic": "/clicked_point",
                "yaw_topic": "goal_yaw",
                "waypoint_id": payload["id"],
                "x": float(payload["x"]),
                "y": float(payload["y"]),
                "z": float(payload["z"]),
                "yaw": float(payload["yaw"]),
                "frame_id": str(payload["frame_id"]),
            }

    class DummyControlService:
        async def prepare_navigation_motion(self) -> dict[str, object]:
            return {"success": True, "switch_move_mode_return": 0}

    async def fake_audit_log(*args, **kwargs):
        audit_messages.append(kwargs["message"])

    monkeypatch.setattr(nav_routes, "get_ros_nav_bridge", lambda: DummyBridge())
    monkeypatch.setattr(
        "backend.control_service.get_control_service",
        lambda: DummyControlService(),
    )
    monkeypatch.setattr("backend.services_nav_waypoints.get_waypoint", lambda map_id, waypoint_id: waypoint)
    monkeypatch.setattr(
        "backend.services_nav_localization.start_cmd_vel_script",
        lambda: {"success": True, "running": True, "pid": 1234},
    )
    monkeypatch.setattr(
        "backend.services_nav_localization.wait_navigation_runtime_ready",
        lambda: {"navigation_ready": True},
    )
    monkeypatch.setattr(
        "backend.services_nav_state.get_nav_state",
        lambda: {
            "robot_pose": {
                "x": 0.0,
                "y": 0.0,
                "z": 0.0,
                "yaw": 0.0,
                "frame_id": "map",
                "source": "test",
                "timestamp": 1.0,
            },
            "localization_status": {"status": "ok", "message": "定位正常"},
        },
    )
    monkeypatch.setattr(nav_routes, "safe_write_audit_log", fake_audit_log)
    result = asyncio.run(
        nav_routes.nav_go_to_waypoint(
            "Scene1_实验室一楼",
            "wp_001",
            user=AuthUserInternal(id=1, username="admin", role="operator", token_version=1),
            db=object(),
        )
    )

    assert result["success"] is True
    assert result["topic"] == "/clicked_point"
    assert result["xyz_topic"] == "/clicked_point"
    assert result["yaw_topic"] == "goal_yaw"
    assert result["goal"]["waypoint_id"] == "wp_001"
    assert result["stop_task"]["data"] is False
    assert "stop_task_nav" not in result
    assert "nav_start" not in result
    assert result["motion_prepare"]["switch_move_mode_return"] == 0
    assert publish_order == ["task_start", "goal"]
    assert publish_thread_ids
    assert publish_thread_ids[0] != request_thread_id
    assert task_start_calls == [False]
    assert audit_messages
    assert "clicked_point_topic=/clicked_point" in audit_messages[0]
    assert "yaw_topic=goal_yaw" in audit_messages[0]
    assert "nav_start=not_published" in audit_messages[0]
    assert result["message"] == "新单点目标已替换旧目标，正在规划路径"


def _install_concurrent_go_to_dependencies(
    monkeypatch,
    *,
    bridge,
    control_service,
    waypoints: dict[tuple[str, str], dict[str, object]],
) -> None:
    async def fake_audit_log(*args, **kwargs):
        return None

    monkeypatch.setattr(nav_routes, "_go_to_waypoint_lock", asyncio.Lock())
    monkeypatch.setattr(nav_routes, "_go_to_waypoint_inflight", set())
    monkeypatch.setattr(nav_routes, "get_ros_nav_bridge", lambda: bridge)
    monkeypatch.setattr(
        "backend.control_service.get_control_service",
        lambda: control_service,
    )
    monkeypatch.setattr(
        "backend.services_nav_waypoints.get_waypoint",
        lambda map_id, waypoint_id: waypoints[(map_id, waypoint_id)],
    )
    monkeypatch.setattr(
        "backend.services_nav_localization.start_cmd_vel_script",
        lambda: {"success": True, "running": True, "pid": 1234},
    )
    monkeypatch.setattr(
        "backend.services_nav_localization.stop_cmd_vel_script",
        lambda: {"success": True, "running": False},
    )
    monkeypatch.setattr(
        "backend.services_nav_localization.wait_navigation_runtime_ready",
        lambda: {"navigation_ready": True},
    )
    monkeypatch.setattr(
        "backend.services_nav_state.get_nav_state",
        lambda: {
            "robot_pose": {
                "x": 0.0,
                "y": 0.0,
                "z": 0.0,
                "yaw": 0.0,
                "frame_id": "map",
                "source": "test",
                "timestamp": 1.0,
            },
            "localization_status": {"status": "ok", "message": "定位正常"},
        },
    )
    monkeypatch.setattr(nav_routes, "_request_navigation_control", lambda: None)
    monkeypatch.setattr(nav_routes, "_release_navigation_control", lambda: None)
    monkeypatch.setattr(nav_routes, "safe_write_audit_log", fake_audit_log)


def _goal_publish_result(waypoint: dict[str, object]) -> dict[str, object]:
    return {
        "success": True,
        "xyz_topic": "/clicked_point",
        "yaw_topic": "goal_yaw",
        "waypoint_id": waypoint["id"],
        "x": float(waypoint["x"]),
        "y": float(waypoint["y"]),
        "z": float(waypoint["z"]),
        "yaw": float(waypoint["yaw"]),
        "frame_id": str(waypoint["frame_id"]),
    }


def _operator() -> AuthUserInternal:
    return AuthUserInternal(
        id=1,
        username="admin",
        role="operator",
        token_version=1,
    )


@pytest.mark.asyncio
async def test_nav_go_to_rejects_same_inflight_target_immediately(monkeypatch):
    map_id = "Scene5"
    waypoint_id = "wp_001"
    waypoint = {
        "id": waypoint_id,
        "map_id": map_id,
        "name": "目标一",
        "x": 1.0,
        "y": 2.0,
        "z": -0.83,
        "yaw": 0.0,
        "frame_id": "map",
    }
    prepare_started = asyncio.Event()
    release_prepare = asyncio.Event()
    prepare_calls = 0

    class DummyControlService:
        async def prepare_navigation_motion(self) -> dict[str, object]:
            nonlocal prepare_calls
            prepare_calls += 1
            prepare_started.set()
            await release_prepare.wait()
            return {"success": True, "switch_move_mode_return": 0}

    class DummyBridge:
        def publish_navigation_task_start(self, enabled: bool = True) -> dict[str, object]:
            return {"success": True, "topic": "/nav_task_start", "data": enabled}

        def publish_goal_xyz_yaw(self, payload: dict[str, object]) -> dict[str, object]:
            return _goal_publish_result(payload)

    _install_concurrent_go_to_dependencies(
        monkeypatch,
        bridge=DummyBridge(),
        control_service=DummyControlService(),
        waypoints={(map_id, waypoint_id): waypoint},
    )

    first_request = asyncio.create_task(
        nav_routes.nav_go_to_waypoint(
            map_id,
            waypoint_id,
            user=_operator(),
            db=object(),
        )
    )
    await asyncio.wait_for(prepare_started.wait(), timeout=1.0)

    try:
        with pytest.raises(HTTPException) as exc_info:
            await asyncio.wait_for(
                nav_routes.nav_go_to_waypoint(
                    map_id,
                    waypoint_id,
                    user=_operator(),
                    db=object(),
                ),
                timeout=0.1,
            )
        assert exc_info.value.status_code == 409
        assert "正在处理中" in str(exc_info.value.detail)
        assert prepare_calls == 1
        assert not first_request.done()
    finally:
        release_prepare.set()

    result = await asyncio.wait_for(first_request, timeout=1.0)
    assert result["waypoint_id"] == waypoint_id
    assert nav_routes._go_to_waypoint_inflight == set()


@pytest.mark.asyncio
async def test_nav_go_to_serializes_distinct_targets_in_arrival_order(monkeypatch):
    map_id = "Scene5"
    first_waypoint = {
        "id": "wp_001",
        "map_id": map_id,
        "name": "目标一",
        "x": 1.0,
        "y": 2.0,
        "z": -0.83,
        "yaw": 0.0,
        "frame_id": "map",
    }
    second_waypoint = {
        "id": "wp_002",
        "map_id": map_id,
        "name": "目标二",
        "x": 4.0,
        "y": 5.0,
        "z": -0.83,
        "yaw": 1.0,
        "frame_id": "map",
    }
    first_prepare_started = asyncio.Event()
    release_first_prepare = asyncio.Event()
    prepare_order: list[str] = []
    prepare_calls = 0
    publish_order: list[str] = []
    publish_thread_ids: list[int] = []
    last_published_goal: dict[str, object] | None = None
    request_thread_id = threading.get_ident()

    class DummyControlService:
        async def prepare_navigation_motion(self) -> dict[str, object]:
            nonlocal prepare_calls
            prepare_calls += 1
            call_number = prepare_calls
            prepare_order.append(f"start-{call_number}")
            if call_number == 1:
                first_prepare_started.set()
                await release_first_prepare.wait()
            prepare_order.append(f"end-{call_number}")
            return {"success": True, "switch_move_mode_return": 0}

    class DummyBridge:
        def publish_navigation_task_start(self, enabled: bool = True) -> dict[str, object]:
            return {"success": True, "topic": "/nav_task_start", "data": enabled}

        def publish_goal_xyz_yaw(self, payload: dict[str, object]) -> dict[str, object]:
            nonlocal last_published_goal
            publish_order.append(str(payload["id"]))
            publish_thread_ids.append(threading.get_ident())
            last_published_goal = payload
            return _goal_publish_result(payload)

    _install_concurrent_go_to_dependencies(
        monkeypatch,
        bridge=DummyBridge(),
        control_service=DummyControlService(),
        waypoints={
            (map_id, "wp_001"): first_waypoint,
            (map_id, "wp_002"): second_waypoint,
        },
    )

    first_request = asyncio.create_task(
        nav_routes.nav_go_to_waypoint(
            map_id,
            "wp_001",
            user=_operator(),
            db=object(),
        )
    )
    await asyncio.wait_for(first_prepare_started.wait(), timeout=1.0)
    second_request = asyncio.create_task(
        nav_routes.nav_go_to_waypoint(
            map_id,
            "wp_002",
            user=_operator(),
            db=object(),
        )
    )
    await asyncio.sleep(0)

    assert nav_routes._go_to_waypoint_inflight == {
        (map_id, "wp_001"),
        (map_id, "wp_002"),
    }
    assert prepare_order == ["start-1"]

    release_first_prepare.set()
    first_result, second_result = await asyncio.wait_for(
        asyncio.gather(first_request, second_request),
        timeout=2.0,
    )

    assert first_result["waypoint_id"] == "wp_001"
    assert second_result["waypoint_id"] == "wp_002"
    assert prepare_order == ["start-1", "end-1", "start-2", "end-2"]
    assert publish_order == ["wp_001", "wp_002"]
    assert last_published_goal == second_waypoint
    assert publish_thread_ids
    assert all(thread_id != request_thread_id for thread_id in publish_thread_ids)
    assert nav_routes._go_to_waypoint_inflight == set()
