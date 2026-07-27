from __future__ import annotations

from backend.ros_nav_messages import global_path_signature, normalize_nav_status


def test_global_path_signature_ignores_timestamp_and_rounds_points():
    first = {
        "frame_id": "map",
        "timestamp": 123.0,
        "points": [{"x": 1.0004, "y": 2.0004, "z": 0.0}],
    }
    second = {
        "frame_id": "map",
        "timestamp": 124.0,
        "points": [{"x": 1.00049, "y": 2.00049, "z": 0.0}],
    }

    assert global_path_signature(first) == global_path_signature(second)


def test_normalize_nav_status_preserves_active_task_when_payload_omits_task_id():
    status = normalize_nav_status(
        {
            "status": "moving",
            "waypoint_id": "wp_002",
            "timestamp": 1770000000.0,
        },
        status_topic="/nav_status",
        current_navigation_status=lambda: {
            "status": "navigating",
            "task_id": "task_001",
        },
        diagnose_navigation_failure=lambda: None,
        interrupted_navigation=lambda: None,
    )

    assert status["status"] == "navigating"
    assert status["task_id"] == "task_001"
    assert status["waypoint_id"] == "wp_002"
    assert status["source"] == "/nav_status"


def test_normalize_nav_status_uses_failure_diagnosis():
    status = normalize_nav_status(
        {
            "status": "failed",
            "message": "路径规划失败",
            "error_code": "PLAN_FAILED",
            "timestamp": 1770000001.0,
        },
        status_topic="/nav_status",
        current_navigation_status=lambda: {},
        diagnose_navigation_failure=lambda: {
            "error_code": "GLOBAL_PLANNER_GOAL_NOT_ON_GROUND",
            "message": "目标点不在 global_planner 的地面点云附近",
        },
        interrupted_navigation=lambda: None,
    )

    assert status["status"] == "error"
    assert status["error_code"] == "GLOBAL_PLANNER_GOAL_NOT_ON_GROUND"
    assert status["message"] == "目标点不在 global_planner 的地面点云附近"


def test_normalize_nav_status_preserves_scan_emergency_diagnosis():
    status = normalize_nav_status(
        {
            "status": "failed",
            "message": "SCAN 起点或局部路径位于障碍物内，已安全停车",
            "error_code": "SCAN_REPLAN_FAILED",
        },
        status_topic="/nav_status",
        current_navigation_status=lambda: {},
        diagnose_navigation_failure=lambda: {
            "error_code": "GLOBAL_PLANNER_GOAL_NOT_ON_GROUND",
            "message": "stale diagnosis",
        },
        interrupted_navigation=lambda: None,
    )

    assert status["status"] == "error"
    assert status["error_code"] == "SCAN_REPLAN_FAILED"
    assert status["message"] == "SCAN 起点或局部路径位于障碍物内，已安全停车"
