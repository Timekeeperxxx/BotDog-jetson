from __future__ import annotations

import threading

import pytest

from backend.ros_nav_publishers import euler_to_quaternion, wait_for_initial_pose_subscribers
from backend.services_ros_nav import RosNavBridge


def test_euler_to_quaternion_identity():
    quaternion = euler_to_quaternion(0.0, 0.0, 0.0)

    assert quaternion["w"] == pytest.approx(1.0)
    assert quaternion["x"] == pytest.approx(0.0)
    assert quaternion["y"] == pytest.approx(0.0)
    assert quaternion["z"] == pytest.approx(0.0)


def test_wait_for_initial_pose_subscribers_reports_ready():
    result = wait_for_initial_pose_subscribers(
        topic="/initialpose",
        timeout_s=0.1,
        subscription_counts=lambda: {
            "graph_count": 1,
            "matched_count": 0,
            "subscriber_count": 1,
        },
        backend_publisher_count=lambda: 1,
    )

    assert result["ready"] is True
    assert result["topic"] == "/initialpose"
    assert result["subscriber_count"] == 1
    assert result["backend_publisher_count"] == 1


def test_task_start_rejects_missing_task_navigator(monkeypatch):
    class PublisherWithoutSubscribers:
        def get_subscription_count(self) -> int:
            return 0

    bridge = RosNavBridge.__new__(RosNavBridge)
    bridge._node = object()
    bridge._nav_task_start_publisher = PublisherWithoutSubscribers()
    bridge._publisher_lock = threading.RLock()

    timestamps = iter([0.0, 3.0])
    monkeypatch.setattr("backend.services_ros_nav.time.monotonic", lambda: next(timestamps))

    with pytest.raises(RuntimeError, match="nav_task_start 没有订阅者"):
        bridge.publish_navigation_task_start(True)
