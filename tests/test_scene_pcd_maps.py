from __future__ import annotations

import os
import struct
from pathlib import Path

import pytest

from backend import services_pcd_maps as pcd_services
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


def write_binary_pcd_with_histogram(
    path: Path,
    points: list[tuple[float, float, float, tuple[float, float, float]]],
) -> None:
    header = f"""# .PCD v0.7 - Point Cloud Data file format
VERSION 0.7
FIELDS x y z histogram
SIZE 4 4 4 4
TYPE F F F F
COUNT 1 1 1 3
WIDTH {len(points)}
HEIGHT 1
VIEWPOINT 0 0 0 1 0 0 0
POINTS {len(points)}
DATA binary
"""
    with path.open("wb") as f:
        f.write(header.encode("utf-8"))
        for x, y, z, histogram in points:
            f.write(struct.pack("<ffffff", x, y, z, *histogram))


def test_list_pcd_scenes_and_find_layer_files(monkeypatch, tmp_path):
    scene_root = tmp_path / "MAPS"
    scene_root.mkdir()
    scene_a = scene_root / "Scene1_实验室一楼"
    scene_a.mkdir()
    scene_b = scene_root / "demo"
    scene_b.mkdir()

    wall = scene_a / "abcmap.pcd"
    ground = scene_a / "abcground.pcd"
    footprint_fill = scene_a / "abc_footprint_fill.pcd"
    write_ascii_pcd(wall, [(0.0, 0.0, 0.0)])
    write_ascii_pcd(ground, [(1.0, 2.0, 3.0)])
    write_ascii_pcd(footprint_fill, [(2.0, 3.0, 4.0)])

    monkeypatch.setattr(pcd_services.settings, "SCENE_MAP_ROOT", str(scene_root))

    result = pcd_services.list_pcd_scenes()

    assert result["root"] == str(scene_root.resolve())
    assert [item["id"] for item in result["items"]] == ["Scene1_实验室一楼"]
    item = result["items"][0]
    assert item["ready"] is True
    assert item["navigable"] is True
    assert item["wall"]["name"] == "abcmap.pcd"
    assert item["ground"]["name"] == "abcground.pcd"
    assert item["footprint_fill"]["name"] == "abc_footprint_fill.pcd"


def test_find_scene_pcd_files_prefers_exact_names(monkeypatch, tmp_path):
    scene_root = tmp_path / "MAPS"
    scene_root.mkdir()
    scene = scene_root / "Scene3_大厅"
    scene.mkdir()

    prefixed_wall = scene / "Scene3_half_map.pcd"
    exact_wall = scene / "map.pcd"
    prefixed_ground = scene / "Scene3_half_ground.pcd"
    exact_ground = scene / "ground.pcd"

    write_ascii_pcd(prefixed_wall, [(0.0, 0.0, 0.0)])
    write_ascii_pcd(exact_wall, [(1.0, 0.0, 0.0)])
    write_ascii_pcd(prefixed_ground, [(0.0, 1.0, 0.0)])
    write_ascii_pcd(exact_ground, [(1.0, 1.0, 0.0)])
    os.utime(prefixed_wall, (exact_wall.stat().st_atime + 10, exact_wall.stat().st_mtime + 10))
    os.utime(prefixed_ground, (exact_ground.stat().st_atime + 10, exact_ground.stat().st_mtime + 10))

    monkeypatch.setattr(pcd_services.settings, "SCENE_MAP_ROOT", str(scene_root))

    files = pcd_services.find_scene_pcd_files(scene)

    assert files["wall"] == exact_wall
    assert files["ground"] == exact_ground


def test_scene_metadata_and_preview_merge_bounds(monkeypatch, tmp_path):
    scene_root = tmp_path / "MAPS"
    scene_root.mkdir()
    scene = scene_root / "Scene2_走廊"
    scene.mkdir()

    wall = scene / "scene_wall_map.pcd"
    ground = scene / "scene_ground.pcd"
    footprint_fill = scene / "terrain_map_20260622_192856_base_footprint_fill.pcd"
    write_ascii_pcd(wall, [(-1.0, 0.0, 0.0), (2.0, 4.0, 1.0)])
    write_ascii_pcd(ground, [(3.0, -2.0, -1.0), (4.0, 1.0, 2.0)])
    write_ascii_pcd(footprint_fill, [(-2.0, -3.0, -0.5), (5.0, 2.0, 0.5)])

    monkeypatch.setattr(pcd_services.settings, "SCENE_MAP_ROOT", str(scene_root))

    metadata = pcd_services.get_scene_metadata("Scene2_走廊")
    assert metadata["supported"] is True
    assert metadata["message"] is None
    assert metadata["bounds"]["min_x"] == -2.0
    assert metadata["bounds"]["max_x"] == 5.0
    assert metadata["bounds"]["min_y"] == -3.0
    assert metadata["bounds"]["max_y"] == 4.0
    assert metadata["files"]["wall"]["point_count"] == 2
    assert metadata["files"]["ground"]["point_count"] == 2
    assert metadata["files"]["footprint_fill"]["point_count"] == 2

    preview = pcd_services.get_scene_preview("Scene2_走廊", max_points=1000)
    assert preview["layers"]["ground"] is not None
    assert preview["layers"]["wall"] is not None
    assert preview["layers"]["footprint_fill"] is not None
    assert len(preview["layers"]["ground"]["points"]) == 2
    assert len(preview["layers"]["wall"]["points"]) == 2
    assert len(preview["layers"]["footprint_fill"]["points"]) == 2
    assert preview["layers"]["footprint_fill"]["file_name"] == footprint_fill.name
    assert preview["bounds"]["min_x"] == -2.0
    assert preview["bounds"]["max_x"] == 5.0


def test_scene_preview_binary_pcd_with_count_fields_reads_xyz_correctly(monkeypatch, tmp_path):
    scene_root = tmp_path / "MAPS"
    scene_root.mkdir()
    scene = scene_root / "Scene4_二进制场景"
    scene.mkdir()

    wall = scene / "map.pcd"
    ground = scene / "ground.pcd"
    wall_points = [
        (1.0, 2.0, 3.0, (10.0, 11.0, 12.0)),
        (4.0, 5.0, 6.0, (13.0, 14.0, 15.0)),
    ]
    ground_points = [
        (-1.0, -2.0, -3.0, (20.0, 21.0, 22.0)),
        (7.0, 8.0, 9.0, (23.0, 24.0, 25.0)),
    ]
    write_binary_pcd_with_histogram(wall, wall_points)
    write_binary_pcd_with_histogram(ground, ground_points)

    monkeypatch.setattr(pcd_services.settings, "SCENE_MAP_ROOT", str(scene_root))

    preview = pcd_services.get_scene_preview("Scene4_二进制场景", max_points=1000)

    assert preview["layers"]["wall"] is not None
    assert preview["layers"]["ground"] is not None
    assert preview["layers"]["wall"]["points"] == [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
    assert preview["layers"]["ground"]["points"] == [[-1.0, -2.0, -3.0], [7.0, 8.0, 9.0]]
    assert preview["bounds"]["min_x"] == -1.0
    assert preview["bounds"]["max_x"] == 7.0
    assert preview["bounds"]["min_y"] == -2.0
    assert preview["bounds"]["max_y"] == 8.0
    assert preview["bounds"]["min_z"] == -3.0
    assert preview["bounds"]["max_z"] == 9.0


def test_snap_xy_to_ground_fits_local_ground_plane(monkeypatch, tmp_path):
    scene_root = tmp_path / "MAPS"
    scene_root.mkdir()
    scene = scene_root / "Scene5_地面吸附"
    scene.mkdir()

    write_ascii_pcd(scene / "map.pcd", [(0.0, 0.0, 0.0)])
    write_ascii_pcd(
        scene / "ground.pcd",
        [
            (0.0, 0.0, 1.0),
            (2.0, 0.0, 1.2),
            (0.0, 2.0, 1.4),
            (2.0, 2.0, 1.6),
        ],
    )
    monkeypatch.setattr(pcd_services.settings, "SCENE_MAP_ROOT", str(scene_root))

    snapped = pcd_services.snap_xy_to_ground("Scene5_地面吸附", 1.0, 1.0, max_distance_m=2.0)

    assert snapped["source_file"] == "ground.pcd"
    assert snapped["method"] == "plane"
    assert snapped["z"] == pytest.approx(1.3)


def test_snap_xy_to_ground_rejects_points_far_from_ground(monkeypatch, tmp_path):
    scene_root = tmp_path / "MAPS"
    scene_root.mkdir()
    scene = scene_root / "Scene6_远离地面"
    scene.mkdir()

    write_ascii_pcd(scene / "map.pcd", [(0.0, 0.0, 0.0)])
    write_ascii_pcd(scene / "ground.pcd", [(0.0, 0.0, 0.0)])
    monkeypatch.setattr(pcd_services.settings, "SCENE_MAP_ROOT", str(scene_root))

    with pytest.raises(pcd_services.PcdMapError, match="不在 ground.pcd 附近"):
        pcd_services.snap_xy_to_ground("Scene6_远离地面", 5.0, 5.0, max_distance_m=1.0)


def test_create_waypoint_uses_payload_z_from_3d_ground_preview(monkeypatch, tmp_path):
    scene_root = tmp_path / "MAPS"
    waypoint_root = tmp_path / "waypoints"
    scene_root.mkdir()
    scene = scene_root / "Scene7_点位吸附"
    scene.mkdir()

    write_ascii_pcd(scene / "map.pcd", [(0.0, 0.0, 0.0)])
    write_ascii_pcd(scene / "ground.pcd", [(1.0, 2.0, 0.42), (1.2, 2.0, 0.44), (1.0, 2.2, 0.46)])
    monkeypatch.setattr(pcd_services.settings, "SCENE_MAP_ROOT", str(scene_root))
    monkeypatch.setattr("backend.services_nav_waypoints.settings.NAV_WAYPOINT_STORE_DIR", str(waypoint_root))

    waypoint = create_waypoint(
        "Scene7_点位吸附",
        {
            "name": "测试点",
            "x": 1.0,
            "y": 2.0,
            "z": 99.0,
            "yaw": 0.5,
            "frame_id": "map",
        },
    )

    assert waypoint["x"] == 1.0
    assert waypoint["y"] == 2.0
    assert waypoint["z"] == pytest.approx(99.0)


def test_create_waypoint_uses_payload_z_without_scanning_ground_file(monkeypatch, tmp_path):
    scene_root = tmp_path / "MAPS"
    waypoint_root = tmp_path / "waypoints"
    scene_root.mkdir()
    scene = scene_root / "Scene8_超大地面"
    scene.mkdir()

    write_ascii_pcd(scene / "map.pcd", [(0.0, 0.0, 0.0)])
    write_ascii_pcd(scene / "ground.pcd", [(1.0, 2.0, 0.42)])
    monkeypatch.setattr(pcd_services.settings, "SCENE_MAP_ROOT", str(scene_root))
    monkeypatch.setattr("backend.services_nav_waypoints.settings.NAV_WAYPOINT_STORE_DIR", str(waypoint_root))
    waypoint = create_waypoint(
        "Scene8_超大地面",
        {
            "name": "快速点",
            "x": 1.0,
            "y": 2.0,
            "z": 9.87,
            "yaw": 0.5,
            "frame_id": "map",
        },
    )

    assert waypoint["x"] == 1.0
    assert waypoint["y"] == 2.0
    assert waypoint["z"] == pytest.approx(9.87)
