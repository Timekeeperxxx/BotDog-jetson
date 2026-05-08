from __future__ import annotations

import asyncio

from backend.api.routes import nav as nav_routes
from backend.auth.schemas import AuthUserInternal


def test_nav_go_to_waypoint_uses_goal_xyz_and_goal_yaw(monkeypatch):
    waypoint = {
        "id": "wp_001",
        "map_id": "ground.pcd",
        "name": "巡检点1",
        "x": 1.0,
        "y": 2.0,
        "z": -0.83,
        "yaw": 1.57,
        "frame_id": "map",
    }
    audit_messages: list[str] = []
    nav_status_updates: list[dict[str, object]] = []
    publish_order: list[str] = []

    class DummyBridge:
        def publish_navigation_start(self) -> dict[str, object]:
            publish_order.append("nav_start")
            return {
                "success": True,
                "topic": "/nav_start",
                "data": True,
            }

        def publish_goal_xyz_yaw(self, payload: dict[str, object]) -> dict[str, object]:
            publish_order.append("goal")
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

    async def fake_audit_log(*args, **kwargs):
        audit_messages.append(kwargs["message"])

    def fake_update_navigation_status(payload: dict[str, object]) -> dict[str, object]:
        nav_status_updates.append(payload)
        return payload

    monkeypatch.setattr(nav_routes, "get_ros_nav_bridge", lambda: DummyBridge())
    monkeypatch.setattr("backend.services_nav_waypoints.get_waypoint", lambda map_id, waypoint_id: waypoint)
    monkeypatch.setattr(nav_routes, "safe_write_audit_log", fake_audit_log)
    monkeypatch.setattr("backend.services_nav_state.update_navigation_status", fake_update_navigation_status)

    result = asyncio.run(
        nav_routes.nav_go_to_waypoint(
            "ground.pcd",
            "wp_001",
            user=AuthUserInternal(id=1, username="admin", role="operator", token_version=1),
            db=object(),
        )
    )

    assert result["success"] is True
    assert result["topic"] == "/clicked_point"
    assert result["nav_start_topic"] == "/nav_start"
    assert result["nav_start"]["topic"] == "/nav_start"
    assert result["xyz_topic"] == "/clicked_point"
    assert result["yaw_topic"] == "goal_yaw"
    assert result["goal"]["waypoint_id"] == "wp_001"
    assert publish_order == ["nav_start", "goal"]
    assert audit_messages
    assert "nav_start_topic=/nav_start" in audit_messages[0]
    assert "clicked_point_topic=/clicked_point" in audit_messages[0]
    assert "yaw_topic=goal_yaw" in audit_messages[0]
    assert nav_status_updates
    assert nav_status_updates[0]["status"] == "navigating"
    assert "已发布 nav_start，随后发布 clicked_point 和 goal_yaw" in nav_status_updates[0]["message"]
