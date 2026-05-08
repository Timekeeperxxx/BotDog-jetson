from __future__ import annotations

from types import SimpleNamespace

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
