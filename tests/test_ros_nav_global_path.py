from __future__ import annotations

import struct
from types import SimpleNamespace

import numpy as np
import pytest

from backend.ros_nav_cloud import (
    extract_cloud_xyz_np,
    limit_cloud_points,
    mapping_cloud_voxel_preview,
    merge_mapping_cloud_voxels,
)
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


def test_execution_path_broadcast_tracks_live_path_without_duplicates(monkeypatch):
    times = iter([10.0, 10.05, 10.2, 10.4])
    monkeypatch.setattr("backend.services_ros_nav.time.monotonic", lambda: next(times))

    bridge = RosNavBridge.__new__(RosNavBridge)
    bridge._last_execution_path_broadcast_at = 0.0
    bridge._last_execution_path_signature = None

    first_path = {
        "frame_id": "map",
        "timestamp": 123.0,
        "points": [{"x": 2.0, "y": -1.0, "z": 0.0}],
    }
    changed_path = {
        "frame_id": "map",
        "timestamp": 123.0,
        "points": [{"x": 1.8, "y": -0.9, "z": 0.0}],
    }

    assert bridge._should_broadcast_execution_path(first_path) is True
    assert bridge._should_broadcast_execution_path(changed_path) is False
    assert bridge._should_broadcast_execution_path(changed_path) is True
    assert bridge._should_broadcast_execution_path(changed_path) is False


def test_mapping_cloud_points_are_limited():
    points = np.arange(30, dtype=np.float32).reshape((10, 3))

    limited = limit_cloud_points(points, 3)

    assert limited.shape == (3, 3)
    assert limited.tolist() == [
        [0.0, 1.0, 2.0],
        [12.0, 13.0, 14.0],
        [24.0, 25.0, 26.0],
    ]


def test_mapping_cloud_points_under_limit_are_unchanged():
    points = np.arange(9, dtype=np.float32).reshape((3, 3))

    limited = limit_cloud_points(points, 3)

    assert limited is points


def test_extract_cloud_xyz_np_filters_invalid_points():
    values = [
        (1.0, 2.0, 3.0),
        (float("nan"), 2.0, 3.0),
        (4.0, float("inf"), 6.0),
        (7.0, 8.0, 9.0),
    ]
    msg = SimpleNamespace(
        point_step=12,
        width=len(values),
        height=1,
        fields=[
            SimpleNamespace(name="x", offset=0),
            SimpleNamespace(name="y", offset=4),
            SimpleNamespace(name="z", offset=8),
        ],
        data=b"".join(struct.pack("<fff", *point) for point in values),
    )

    points = extract_cloud_xyz_np(msg)

    assert points is not None
    assert points.tolist() == [[1.0, 2.0, 3.0], [7.0, 8.0, 9.0]]


def test_mapping_cloud_voxel_preview_deduplicates_voxels():
    voxels = {}
    merge_mapping_cloud_voxels(
        voxels,
        np.array(
            [
                [0.01, 0.01, 0.01],
                [0.02, 0.02, 0.02],
                [0.20, 0.20, 0.20],
            ],
            dtype=np.float32,
        ),
    )

    preview = mapping_cloud_voxel_preview(voxels)

    assert preview.shape == (2, 3)
    assert preview == pytest.approx(np.array([[0.02, 0.02, 0.02], [0.20, 0.20, 0.20]], dtype=np.float32))


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

    monkeypatch.setattr("backend.ros_nav_cloud_bridge.time.monotonic", lambda: 100.0)
    monkeypatch.setattr("backend.ros_nav_cloud_bridge.time.time", lambda: 123.0)
    monkeypatch.setattr(RosNavBridge, "_is_navigation_active", staticmethod(lambda: False))

    bridge = RosNavBridge.__new__(RosNavBridge)
    bridge._last_cloud_broadcast_at = 0.0
    bridge._last_full_map_broadcast_at = 0.0
    bridge._accumulated_cloud = np.empty((0, 3), dtype=np.float32)
    bridge._accumulated_cloud_voxels = {}
    broadcasts = []
    bridge._submit_broadcast = lambda event_type, payload: broadcasts.append((event_type, payload))

    bridge._handle_cloud_message(msg)

    assert len(broadcasts) == 1
    event_type, payload = broadcasts[0]
    assert event_type == "nav.mapping_cloud"
    assert np.array(payload["live_points"]) == pytest.approx(np.array(points))
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


def test_mapping_cloud_broadcast_drops_frame_when_previous_send_is_pending(monkeypatch):
    class PendingFuture:
        def done(self):
            return False

        def add_done_callback(self, callback):
            return None

    class DummyBroadcaster:
        async def broadcast_event(self, event_type, data):
            return 1

    submitted = []

    def fake_run_coroutine_threadsafe(coro, loop):
        coro.close()
        submitted.append((coro, loop))
        return PendingFuture()

    monkeypatch.setattr(
        "backend.services_ros_nav.asyncio.run_coroutine_threadsafe",
        fake_run_coroutine_threadsafe,
    )

    bridge = RosNavBridge.__new__(RosNavBridge)
    bridge._loop = SimpleNamespace(is_closed=lambda: False)
    bridge._broadcaster = DummyBroadcaster()
    bridge._mapping_cloud_broadcaster = DummyBroadcaster()
    bridge._mapping_cloud_broadcast_future = None

    bridge._submit_broadcast("nav.mapping_cloud", {"live_points": [[0.0, 0.0, 0.0]]})
    bridge._submit_broadcast("nav.mapping_cloud", {"live_points": [[1.0, 1.0, 1.0]]})

    assert len(submitted) == 1
