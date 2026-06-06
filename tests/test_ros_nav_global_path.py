from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from backend.services_ros_nav import RosNavBridge


def test_extract_global_path_uses_path_points_and_map_frame():
    msg = SimpleNamespace(
        header=SimpleNamespace(
            frame_id="map",
            stamp=SimpleNamespace(sec=123, nanosec=456_000_000),
        ),
        poses=[
            SimpleNamespace(
                pose=SimpleNamespace(
                    position=SimpleNamespace(x=1.0, y=2.0, z=0.0),
                )
            ),
            SimpleNamespace(
                pose=SimpleNamespace(
                    position=SimpleNamespace(x=3.5, y=4.5, z=0.0),
                )
            ),
        ],
    )

    bridge = RosNavBridge.__new__(RosNavBridge)
    path = bridge._extract_global_path(msg)

    assert path["frame_id"] == "map"
    assert path["timestamp"] == pytest.approx(123.456)
    assert path["points"] == [
        {"x": 1.0, "y": 2.0, "z": 0.0},
        {"x": 3.5, "y": 4.5, "z": 0.0},
    ]


def test_global_path_broadcast_skips_duplicate_paths(monkeypatch):
    times = iter([10.0, 11.5])
    monkeypatch.setattr("backend.services_ros_nav.time.monotonic", lambda: next(times))

    bridge = RosNavBridge.__new__(RosNavBridge)
    bridge._last_global_path_broadcast_at = 0.0
    bridge._last_global_path_signature = None

    path = {
        "frame_id": "map",
        "timestamp": 123.0,
        "points": [
            {"x": 1.0, "y": 2.0, "z": 0.0},
            {"x": 3.0, "y": 4.0, "z": 0.0},
        ],
    }

    assert bridge._should_broadcast_global_path(path) is True
    assert bridge._should_broadcast_global_path({**path, "timestamp": 124.0}) is False


def test_global_path_broadcast_throttles_changed_paths(monkeypatch):
    times = iter([10.0, 10.4, 11.2])
    monkeypatch.setattr("backend.services_ros_nav.time.monotonic", lambda: next(times))

    bridge = RosNavBridge.__new__(RosNavBridge)
    bridge._last_global_path_broadcast_at = 0.0
    bridge._last_global_path_signature = None

    first_path = {
        "frame_id": "map",
        "timestamp": 123.0,
        "points": [{"x": 1.0, "y": 2.0, "z": 0.0}],
    }
    changed_path = {
        "frame_id": "map",
        "timestamp": 124.0,
        "points": [{"x": 1.5, "y": 2.5, "z": 0.0}],
    }

    assert bridge._should_broadcast_global_path(first_path) is True
    assert bridge._should_broadcast_global_path(changed_path) is False
    assert bridge._should_broadcast_global_path(changed_path) is True


def test_mapping_cloud_points_are_limited():
    points = np.arange(30, dtype=np.float32).reshape((10, 3))

    limited = RosNavBridge._limit_cloud_points(points, 3)

    assert limited.shape == (3, 3)
    assert limited.tolist() == [
        [0.0, 1.0, 2.0],
        [12.0, 13.0, 14.0],
        [24.0, 25.0, 26.0],
    ]


def test_mapping_cloud_points_under_limit_are_unchanged():
    points = np.arange(9, dtype=np.float32).reshape((3, 3))

    limited = RosNavBridge._limit_cloud_points(points, 3)

    assert limited is points
