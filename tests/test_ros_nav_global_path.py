from __future__ import annotations

import struct
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


def test_mapping_cloud_accumulated_payload_keeps_all_points(monkeypatch):
    points = [
        (0.0, 0.0, 0.0),
        (0.1, 0.0, 0.0),
        (0.2, 0.0, 0.0),
        (0.3, 0.0, 0.0),
    ]
    msg = SimpleNamespace(
        point_step=12,
        width=len(points),
        height=1,
        fields=[
            SimpleNamespace(name="x", offset=0),
            SimpleNamespace(name="y", offset=4),
            SimpleNamespace(name="z", offset=8),
        ],
        data=b"".join(struct.pack("<fff", *point) for point in points),
    )

    monkeypatch.setattr("backend.services_ros_nav.time.monotonic", lambda: 100.0)
    monkeypatch.setattr("backend.services_ros_nav.time.time", lambda: 123.0)
    monkeypatch.setattr(RosNavBridge, "_is_navigation_active", staticmethod(lambda: False))

    bridge = RosNavBridge.__new__(RosNavBridge)
    bridge._last_cloud_broadcast_at = 0.0
    bridge._last_full_map_broadcast_at = 0.0
    bridge._accumulated_cloud = np.empty((0, 3), dtype=np.float32)
    bridge._accumulated_cloud_voxels = {}
    broadcasts = []
    bridge._submit_broadcast = lambda event_type, payload: broadcasts.append((event_type, payload))

    bridge._handle_cloud_message(msg)

    assert len(broadcasts) == 2
    event_type, payload = broadcasts[0]
    assert event_type == "nav.mapping_cloud"
    assert np.array(payload["live_points"]) == pytest.approx(np.array(points))
    assert "accumulated_points" not in payload

    event_type, payload = broadcasts[1]
    assert event_type == "nav.mapping_cloud"
    assert "live_points" not in payload
    assert np.array(payload["accumulated_points"]) == pytest.approx(np.array(points))
    assert np.array(payload["points"]) == pytest.approx(np.array(points))


def test_mapping_cloud_uses_dedicated_broadcaster():
    event_broadcaster = object()
    cloud_broadcaster = object()
    bridge = RosNavBridge.__new__(RosNavBridge)
    bridge._broadcaster = event_broadcaster
    bridge._mapping_cloud_broadcaster = cloud_broadcaster

    assert bridge._broadcaster_for_event("nav.mapping_cloud") is cloud_broadcaster
    assert bridge._broadcaster_for_event("nav.robot_pose") is event_broadcaster
