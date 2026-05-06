import json
from pathlib import Path

from backend.config import settings
from backend.services_nav_runtime import (
    PROJECT_ROOT,
    build_current_goal_payload,
    get_current_goal_path,
    read_current_goal,
    write_current_goal,
)


def test_build_current_goal_payload():
    payload = build_current_goal_payload(
        {
            "id": "wp_001",
            "map_id": "ground.pcd",
            "name": "巡检点1",
            "x": 1.0,
            "y": 2.0,
            "z": -0.83,
            "yaw": 1.57,
            "frame_id": "map",
        }
    )

    assert payload["schema_version"] == 1
    assert payload["event"] == "nav_goal"
    assert payload["waypoint_id"] == "wp_001"
    assert payload["waypoint_name"] == "巡检点1"
    assert payload["map_id"] == "ground.pcd"
    assert payload["x"] == 1.0
    assert payload["y"] == 2.0
    assert payload["z"] == -0.83
    assert payload["yaw"] == 1.57
    assert "selected_at" in payload
    assert "created_at" not in payload
    assert payload["source"] == "botdog-backend"


def test_write_current_goal(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "NAV_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "NAV_CURRENT_GOAL_FILE", "current_goal.json")

    payload = write_current_goal(
        {
            "id": "wp_001",
            "map_id": "ground.pcd",
            "name": "巡检点1",
            "x": 1.0,
            "y": 2.0,
            "z": -0.83,
            "yaw": 1.57,
            "frame_id": "map",
        }
    )

    path = get_current_goal_path()
    assert path.exists()
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["schema_version"] == 1
    assert "selected_at" in data
    assert "created_at" not in data
    assert data["waypoint_id"] == "wp_001"
    assert payload["waypoint_id"] == "wp_001"


def test_read_current_goal(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "NAV_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "NAV_CURRENT_GOAL_FILE", "current_goal.json")

    assert read_current_goal() is None

    write_current_goal(
        {
            "id": "wp_001",
            "map_id": "ground.pcd",
            "name": "巡检点1",
            "x": 1.0,
            "y": 2.0,
            "z": -0.83,
            "yaw": 1.57,
            "frame_id": "map",
        }
    )

    data = read_current_goal()
    assert data is not None
    assert data["waypoint_id"] == "wp_001"


def test_write_current_goal_resolves_relative_path_from_project_root(monkeypatch, tmp_path):
    relative_dir = tmp_path.relative_to(PROJECT_ROOT) if str(tmp_path).startswith(str(PROJECT_ROOT)) else None
    if relative_dir is None:
        relative_dir = Path("tmp") / "nav_runtime_test_relative"

    monkeypatch.setattr(settings, "NAV_RUNTIME_DIR", str(relative_dir))
    monkeypatch.setattr(settings, "NAV_CURRENT_GOAL_FILE", "current_goal.json")

    payload = write_current_goal(
        {
            "id": "wp_001",
            "map_id": "ground.pcd",
            "name": "巡检点1",
            "x": 1.0,
            "y": 2.0,
            "z": -0.83,
            "yaw": 1.57,
            "frame_id": "map",
        }
    )

    path = get_current_goal_path()
    assert path == (PROJECT_ROOT / relative_dir).resolve() / "current_goal.json"
    assert payload["waypoint_id"] == "wp_001"
