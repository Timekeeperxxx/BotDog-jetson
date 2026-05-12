from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from backend.api.routes import nav as nav_routes
from backend.auth.schemas import AuthUserInternal
from backend.repositories.json_store import read_json
from backend.services_nav_tasks import save_nav_task
from backend.services_nav_waypoints import create_waypoint


ASCII_PCD_TEMPLATE = """# .PCD v0.7 - Point Cloud Data file format
VERSION 0.7
FIELDS x y z
SIZE 4 4 4
TYPE F F F
COUNT 1 1 1
WIDTH {width}
HEIGHT 1
VIEWPOINT 0 0 0 1 0 0 0
POINTS {width}
DATA ascii
{points}
"""


def write_ascii_pcd(path: Path, points: list[tuple[float, float, float]]) -> None:
    content = ASCII_PCD_TEMPLATE.format(
        width=len(points),
        points="\n".join(f"{x} {y} {z}" for x, y, z in points),
    )
    path.write_text(content, encoding="utf-8")


def test_nav_execute_task_materializes_runtime_json(monkeypatch, tmp_path):
    scene_root = tmp_path / "MAPS"
    task_root = tmp_path / "tasks"
    waypoint_root = tmp_path / "waypoints"
    runtime_root = tmp_path / "runtime"
    scene_root.mkdir()

    scene_id = "Scene1_实验室一楼"
    scene_path = scene_root / scene_id
    scene_path.mkdir()
    write_ascii_pcd(scene_path / "map.pcd", [(0.0, 0.0, 0.0)])
    write_ascii_pcd(scene_path / "ground.pcd", [(1.0, 2.0, 3.0)])

    monkeypatch.setattr("backend.services_pcd_maps.settings.SCENE_MAP_ROOT", str(scene_root))
    monkeypatch.setattr("backend.services_nav_tasks.settings.NAV_TASK_STORE_DIR", str(task_root))
    monkeypatch.setattr("backend.services_nav_waypoints.settings.NAV_WAYPOINT_STORE_DIR", str(waypoint_root))
    monkeypatch.setattr("backend.services_nav_localization.settings.NAV_RUNTIME_DIR", str(runtime_root))
    monkeypatch.setattr("backend.services_nav_task_runtime.settings.NAV_RUNTIME_DIR", str(runtime_root))

    waypoint = create_waypoint(
        scene_id,
        {
            "name": "巡检点1",
            "x": 1.0,
            "y": 2.0,
            "z": -0.83,
            "yaw": 1.57,
            "frame_id": "map",
        },
    )

    task = {
        "id": "task_001",
        "name": "场景任务",
        "mapId": scene_id,
        "sceneId": scene_id,
        "mapName": scene_id,
        "createdAt": "2026-05-11T10:00:00.000Z",
        "steps": [
            {
                "type": "navigate_waypoint",
                "waypointId": waypoint["id"],
            },
        ],
    }
    save_nav_task(task)

    class DummyBridge:
        def publish_navigation_start(self, enabled: bool = True) -> dict[str, object]:
            assert enabled is True
            return {"success": True, "topic": "/nav_start", "data": True}

    async def fake_audit_log(*args, **kwargs):
        return None

    monkeypatch.setattr(nav_routes, "get_ros_nav_bridge", lambda: DummyBridge())
    monkeypatch.setattr(nav_routes, "safe_write_audit_log", fake_audit_log)

    result = asyncio.run(
        nav_routes.nav_execute_task(
            "task_001",
            user=AuthUserInternal(id=1, username="admin", role="operator", token_version=1),
            db=object(),
        )
    )

    assert result["success"] is True
    assert result["nav_start"]["topic"] == "/nav_start"
    assert result["runtime_file"].endswith("current_task.json")
    assert Path(result["runtime_file"]).exists()

    runtime = read_json(Path(result["runtime_file"]), {})
    assert runtime["task_id"] == "task_001"
    assert runtime["scene_id"] == scene_id
    assert runtime["steps"] == [{"type": "navigate_waypoint", "waypoint_id": waypoint["id"]}]


def test_nav_execute_task_missing_waypoint_returns_404(monkeypatch, tmp_path):
    scene_root = tmp_path / "MAPS"
    task_root = tmp_path / "tasks"
    waypoint_root = tmp_path / "waypoints"
    runtime_root = tmp_path / "runtime"
    scene_root.mkdir()

    scene_id = "Scene2_测试"
    scene_path = scene_root / scene_id
    scene_path.mkdir()
    write_ascii_pcd(scene_path / "map.pcd", [(0.0, 0.0, 0.0)])
    write_ascii_pcd(scene_path / "ground.pcd", [(1.0, 2.0, 3.0)])

    monkeypatch.setattr("backend.services_pcd_maps.settings.SCENE_MAP_ROOT", str(scene_root))
    monkeypatch.setattr("backend.services_nav_tasks.settings.NAV_TASK_STORE_DIR", str(task_root))
    monkeypatch.setattr("backend.services_nav_waypoints.settings.NAV_WAYPOINT_STORE_DIR", str(waypoint_root))
    monkeypatch.setattr("backend.services_nav_localization.settings.NAV_RUNTIME_DIR", str(runtime_root))
    monkeypatch.setattr("backend.services_nav_task_runtime.settings.NAV_RUNTIME_DIR", str(runtime_root))

    save_nav_task(
        {
            "id": "task_002",
            "name": "缺少点位任务",
            "mapId": scene_id,
            "sceneId": scene_id,
            "mapName": scene_id,
            "createdAt": "2026-05-11T10:00:00.000Z",
            "steps": [
                {"type": "navigate_waypoint", "waypointId": "wp_missing"},
            ],
        }
    )

    class DummyBridge:
        def publish_navigation_start(self, enabled: bool = True) -> dict[str, object]:
            return {"success": True, "topic": "/nav_start", "data": True}

    async def fake_audit_log(*args, **kwargs):
        return None

    monkeypatch.setattr(nav_routes, "get_ros_nav_bridge", lambda: DummyBridge())
    monkeypatch.setattr(nav_routes, "safe_write_audit_log", fake_audit_log)

    with pytest.raises(nav_routes.HTTPException) as exc_info:
        asyncio.run(
            nav_routes.nav_execute_task(
                "task_002",
                user=AuthUserInternal(id=1, username="admin", role="operator", token_version=1),
                db=object(),
            )
        )

    assert exc_info.value.status_code == 404
