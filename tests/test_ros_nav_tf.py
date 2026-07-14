from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.ros_nav_tf import base_frame_candidates, lookup_tf_pose, use_tf_pose


def test_base_frame_candidates_deduplicates_and_adds_defaults():
    assert base_frame_candidates("base_link, base_custom, base_link") == [
        "base_link",
        "base_custom",
        "base_footprint",
    ]


def test_use_tf_pose_accepts_tf_aliases():
    assert use_tf_pose("tf") is True
    assert use_tf_pose("TransformStamped") is True
    assert use_tf_pose("odometry") is False


def test_lookup_tf_pose_converts_transform_to_robot_pose():
    tf_buffer = SimpleNamespace(
        lookup_transform=lambda _target, _source, _time: SimpleNamespace(
            header=SimpleNamespace(stamp=SimpleNamespace(sec=1, nanosec=500_000_000)),
            transform=SimpleNamespace(
                translation=SimpleNamespace(x=1.0, y=2.0, z=0.0),
                rotation=SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0),
            ),
        )
    )

    pose = lookup_tf_pose(
        tf_buffer=tf_buffer,
        rclpy_time_cls=lambda: object(),
        target_frame="map",
        source_frames=["base_footprint"],
    )

    assert pose["x"] == 1.0
    assert pose["source"] == "tf:map->base_footprint"
    assert pose["source_frame"] == "base_footprint"
    assert pose["ros_timestamp"] == pytest.approx(1.5)
