from __future__ import annotations

import pytest

from backend.services_nav_goal import planner_goal_z, waypoint_with_planner_goal_z


def test_planner_goal_z_uses_stored_ground_z_by_default():
    assert planner_goal_z(-1.69) == pytest.approx(-1.69)


def test_waypoint_with_planner_goal_z_keeps_ground_z_for_diagnostics():
    waypoint = {
        "id": "wp_001",
        "name": "巡检点2",
        "x": -32.68,
        "y": 8.03,
        "z": -1.69,
        "yaw": 1.46,
        "frame_id": "map",
    }

    result = waypoint_with_planner_goal_z(waypoint)

    assert result["z"] == pytest.approx(-1.69)
    assert result["ground_z"] == -1.69
    assert result["planner_goal_z"] == pytest.approx(-1.69)
    assert result["planner_goal_z_offset_m"] == 0.0
    assert waypoint["z"] == -1.69
