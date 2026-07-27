from __future__ import annotations

import os
import json
import struct
from pathlib import Path

import pytest

from backend import pcd_reader
from backend import pcd_ground
from backend import pcd_tiles
from backend import services_pcd_maps as pcd_services
from backend.services_nav_localization import save_localization_pose
from backend.services_nav_tasks import list_nav_tasks, save_nav_task
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


def write_binary_pcd(
    path: Path,
    points: list[tuple[float, float, float, float]],
) -> None:
    header = f"""# .PCD v0.7 - Point Cloud Data file format
VERSION 0.7
FIELDS x y z intensity
SIZE 4 4 4 4
TYPE F F F F
COUNT 1 1 1 1
WIDTH {len(points)}
HEIGHT 1
VIEWPOINT 0 0 0 1 0 0 0
POINTS {len(points)}
DATA binary
"""
    with path.open("wb") as f:
        f.write(header.encode("utf-8"))
        for point in points:
            f.write(struct.pack("<ffff", *point))


def test_pcd_reader_handles_binary_count_fields_and_bounds(tmp_path):
    pcd_path = tmp_path / "histogram.pcd"
    write_binary_pcd_with_histogram(
        pcd_path,
        [
            (1.0, 2.0, 3.0, (10.0, 11.0, 12.0)),
            (-4.0, 5.0, -6.0, (13.0, 14.0, 15.0)),
        ],
    )

    header, data_start_offset = pcd_reader.parse_pcd_header(pcd_path)
    normalized = pcd_reader.normalize_pcd_header(header)
    point_struct, value_offsets = pcd_reader.binary_layout(header)
    points, bounds = pcd_reader.read_pcd_preview(pcd_path, header, data_start_offset, max_points=1000)

    assert normalized["data_type"] == "binary"
    assert normalized["point_count"] == 2
    assert point_struct.size == 24
    assert value_offsets == {"x": 0, "y": 1, "z": 2, "histogram": 3}
    assert points == [[1.0, 2.0, 3.0], [-4.0, 5.0, -6.0]]
    assert bounds == {
        "min_x": -4.0,
        "max_x": 1.0,
        "min_y": 2.0,
        "max_y": 5.0,
        "min_z": -6.0,
        "max_z": 3.0,
    }
    assert pcd_reader.merge_bounds([None, bounds]) == bounds


def test_pcd_ground_snaps_binary_count_fields_to_local_plane(tmp_path):
    pcd_path = tmp_path / "ground.pcd"
    write_binary_pcd_with_histogram(
        pcd_path,
        [
            (0.0, 0.0, 1.0, (10.0, 11.0, 12.0)),
            (2.0, 0.0, 1.2, (13.0, 14.0, 15.0)),
            (0.0, 2.0, 1.4, (16.0, 17.0, 18.0)),
            (2.0, 2.0, 1.6, (19.0, 20.0, 21.0)),
        ],
    )

    snapped = pcd_ground.snap_xy_to_ground_file(
        pcd_path,
        1.0,
        1.0,
        max_distance_m=2.0,
        neighbor_count=4,
    )

    assert snapped["source_file"] == "ground.pcd"
    assert snapped["method"] == "plane"
    assert snapped["z"] == pytest.approx(1.3)


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


def test_scene_binary_wire_format_preserves_all_preview_points(monkeypatch, tmp_path):
    scene_root = tmp_path / "MAPS"
    scene_root.mkdir()
    scene = scene_root / "Scene9_二进制传输"
    scene.mkdir()

    write_ascii_pcd(scene / "map.pcd", [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)])
    write_ascii_pcd(scene / "ground.pcd", [(-1.0, -2.0, -3.0), (7.0, 8.0, 9.0)])
    monkeypatch.setattr(pcd_services.settings, "SCENE_MAP_ROOT", str(scene_root))

    preview = pcd_services.get_scene_preview("Scene9_二进制传输", max_points=1000)
    payload = pcd_services.get_scene_preview_binary("Scene9_二进制传输", max_points=1000)
    header_size = struct.unpack_from("<I", payload, len(pcd_services.PCD_SCENE_BINARY_MAGIC))[0]
    header_start = len(pcd_services.PCD_SCENE_BINARY_MAGIC) + 4
    header = json.loads(payload[header_start:header_start + header_size])

    assert payload.startswith(pcd_services.PCD_SCENE_BINARY_MAGIC)
    assert (header_start + header_size) % 4 == 0
    assert header["layers"]["wall"]["point_count"] == len(preview["layers"]["wall"]["points"])
    assert header["layers"]["ground"]["point_count"] == len(preview["layers"]["ground"]["points"])
    assert header["layers"]["footprint_fill"] is None
    assert sum(
        layer["byte_length"] for layer in header["layers"].values() if layer is not None
    ) == 4 * 3 * 4


def test_scene_binary_without_global_limit_preserves_sparse_points(monkeypatch, tmp_path):
    scene_root = tmp_path / "MAPS"
    scene_root.mkdir()
    scene = scene_root / "Scene10_全量点云"
    scene.mkdir()
    source_points = [
        (float(index), float(index + 1), float(index + 2), float(index + 3))
        for index in range(7)
    ]
    write_binary_pcd(scene / "map.pcd", source_points)
    write_binary_pcd(scene / "ground.pcd", source_points)
    monkeypatch.setattr(pcd_services.settings, "SCENE_MAP_ROOT", str(scene_root))
    monkeypatch.setattr(pcd_services.settings, "PCD_PREVIEW_DEFAULT_POINTS", 2)
    monkeypatch.setattr(pcd_services.settings, "PCD_PREVIEW_MAX_POINTS", 2)
    monkeypatch.setattr(pcd_services.settings, "PCD_SCENE_PREVIEW_VOXEL_SIZE_M", 0.15)
    monkeypatch.setattr(pcd_services.settings, "PCD_SCENE_PREVIEW_POINTS_PER_VOXEL", 2)

    payload = pcd_services.get_scene_preview_binary("Scene10_全量点云")
    header_size = struct.unpack_from("<I", payload, len(pcd_services.PCD_SCENE_BINARY_MAGIC))[0]
    header_start = len(pcd_services.PCD_SCENE_BINARY_MAGIC) + 4
    header = json.loads(payload[header_start:header_start + header_size])

    assert header["layers"]["wall"]["point_count"] == len(source_points)
    assert header["layers"]["ground"]["point_count"] == len(source_points)
    assert header["layers"]["wall"]["byte_length"] == len(source_points) * 3 * 4
    assert header["layers"]["ground"]["byte_length"] == len(source_points) * 3 * 4


def test_scene_binary_limits_density_per_voxel(monkeypatch, tmp_path):
    scene_root = tmp_path / "MAPS"
    scene_root.mkdir()
    scene = scene_root / "Scene11_空间密度"
    scene.mkdir()
    clustered_points = [
        (0.01, 0.01, 0.01, 1.0),
        (0.02, 0.02, 0.02, 2.0),
        (0.03, 0.03, 0.03, 3.0),
        (0.04, 0.04, 0.04, 4.0),
        (0.05, 0.05, 0.05, 5.0),
        (1.00, 1.00, 1.00, 6.0),
        (2.00, 2.00, 2.00, 7.0),
    ]
    write_binary_pcd(scene / "map.pcd", clustered_points)
    write_binary_pcd(scene / "ground.pcd", clustered_points)
    monkeypatch.setattr(pcd_services.settings, "SCENE_MAP_ROOT", str(scene_root))
    monkeypatch.setattr(pcd_services.settings, "PCD_SCENE_PREVIEW_VOXEL_SIZE_M", 0.15)
    monkeypatch.setattr(pcd_services.settings, "PCD_SCENE_PREVIEW_POINTS_PER_VOXEL", 2)

    payload = pcd_services.get_scene_preview_binary("Scene11_空间密度")
    header_size = struct.unpack_from("<I", payload, len(pcd_services.PCD_SCENE_BINARY_MAGIC))[0]
    header_start = len(pcd_services.PCD_SCENE_BINARY_MAGIC) + 4
    header = json.loads(payload[header_start:header_start + header_size])

    assert header["layers"]["wall"]["point_count"] == 4
    assert header["layers"]["ground"]["point_count"] == 4
    wall_header = header["layers"]["wall"]
    assert wall_header["intensity_encoding"] == "uint8_percentile_2_98"
    assert wall_header["intensity_byte_length"] == wall_header["point_count"]
    point_data_offset = header_start + header_size
    intensity_start = point_data_offset + wall_header["intensity_byte_offset"]
    intensity = payload[intensity_start:intensity_start + wall_header["intensity_byte_length"]]
    assert len(intensity) == 4
    assert list(intensity) == sorted(intensity)


def test_scene_binary_cache_key_tracks_source_version(monkeypatch, tmp_path):
    scene_root = tmp_path / "MAPS"
    cache_root = tmp_path / "preview-cache"
    scene_root.mkdir()
    scene = scene_root / "Scene12_缓存"
    scene.mkdir()
    map_path = scene / "map.pcd"
    ground_path = scene / "ground.pcd"
    write_ascii_pcd(map_path, [(0.0, 0.0, 0.0)])
    write_ascii_pcd(ground_path, [(0.0, 0.0, 0.0)])
    monkeypatch.setattr(pcd_services.settings, "SCENE_MAP_ROOT", str(scene_root))
    monkeypatch.setattr(pcd_services.settings, "PCD_SCENE_PREVIEW_CACHE_DIR", str(cache_root))
    monkeypatch.setattr(pcd_services.settings, "PCD_SCENE_PREVIEW_CACHE_MAX_ENTRIES", 4)
    monkeypatch.setattr(pcd_services.settings, "PCD_SCENE_PREVIEW_VOXEL_SIZE_M", 0.15)
    monkeypatch.setattr(pcd_services.settings, "PCD_SCENE_PREVIEW_POINTS_PER_VOXEL", 2)

    first_path = pcd_services.prepare_scene_preview_binary("Scene12_缓存")
    same_path = pcd_services.prepare_scene_preview_binary("Scene12_缓存")
    write_ascii_pcd(ground_path, [(0.0, 0.0, 0.0), (1.0, 1.0, 1.0)])
    next_path = pcd_services.prepare_scene_preview_binary("Scene12_缓存")

    assert first_path == same_path
    assert first_path.is_file()
    assert next_path.is_file()
    assert next_path != first_path


def test_iter_pcd_chunks_keeps_xyz_and_raw_intensity(tmp_path):
    pcd_path = tmp_path / "chunked.pcd"
    source_points = [
        (float(index), float(index + 1), float(index + 2), float(index * 10))
        for index in range(7)
    ]
    write_binary_pcd(pcd_path, source_points)
    header, data_start_offset = pcd_reader.parse_pcd_header(pcd_path)

    chunks = list(pcd_reader.iter_pcd_xyz_intensity_float32(
        pcd_path,
        header,
        data_start_offset,
        chunk_points=3,
    ))

    assert [len(points) for points, _ in chunks] == [3, 3, 1]
    assert [float(value) for _, intensity in chunks for value in intensity] == [
        point[3] for point in source_points
    ]
    assert [float(value) for points, _ in chunks for value in points[:, 0]] == [
        point[0] for point in source_points
    ]


def test_scene_tile_manifest_builds_progressive_payloads(monkeypatch, tmp_path):
    scene_root = tmp_path / "MAPS"
    cache_root = tmp_path / "tile-cache"
    scene_root.mkdir()
    scene = scene_root / "Scene13_分层瓦片"
    scene.mkdir()
    wall_points = [
        (0.01, 0.02, 0.03, 10.0),
        (0.10, 0.20, 0.30, 20.0),
        (1.10, 0.20, 0.40, 30.0),
        (2.10, 0.20, 0.50, 40.0),
        (4.10, 0.20, 0.60, 50.0),
    ]
    ground_points = [
        (0.0, 0.0, -0.8, 1.0),
        (2.0, 0.0, -0.8, 2.0),
        (4.0, 0.0, -0.8, 3.0),
    ]
    write_binary_pcd(scene / "map.pcd", wall_points)
    write_binary_pcd(scene / "ground.pcd", ground_points)
    monkeypatch.setattr(pcd_services.settings, "SCENE_MAP_ROOT", str(scene_root))
    monkeypatch.setattr(pcd_tiles.settings, "SCENE_MAP_ROOT", str(scene_root))
    monkeypatch.setattr(pcd_tiles.settings, "PCD_SCENE_TILE_CACHE_DIR", str(cache_root))
    monkeypatch.setattr(pcd_tiles.settings, "PCD_SCENE_TILE_SIZE_M", 2.0)
    monkeypatch.setattr(pcd_tiles.settings, "PCD_SCENE_TILE_BALANCED_VOXEL_SIZE_M", 0.07)
    monkeypatch.setattr(pcd_tiles.settings, "PCD_SCENE_TILE_BALANCED_POINTS_PER_VOXEL", 1)
    monkeypatch.setattr(pcd_tiles.settings, "PCD_SCENE_TILE_PERFORMANCE_VOXEL_SIZE_M", 0.10)
    monkeypatch.setattr(pcd_tiles.settings, "PCD_SCENE_TILE_PERFORMANCE_POINTS_PER_VOXEL", 1)
    monkeypatch.setattr(pcd_tiles.settings, "PCD_SCENE_TILE_MAX_POINTS", 4096)
    monkeypatch.setattr(pcd_tiles.settings, "PCD_SCENE_TILE_ROOT_POINTS", 10000)
    monkeypatch.setattr(pcd_tiles.settings, "PCD_SCENE_TILE_BUILD_CHUNK_POINTS", 3)

    manifest_path = pcd_tiles.prepare_scene_tile_manifest("Scene13_分层瓦片")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["version"] == pcd_tiles.PCD_TILE_CACHE_VERSION
    assert manifest["scene_id"] == "Scene13_分层瓦片"
    assert {item["role"] for item in manifest["root_tiles"]} == {"ground", "wall"}
    assert {item["role"] for item in manifest["nodes"]} == {"ground", "wall"}
    wall_node = next(item for item in manifest["nodes"] if item["role"] == "wall")
    assert wall_node["performance"]["has_intensity"] is True
    assert wall_node["balanced"]["has_intensity"] is True
    assert wall_node["original"]["byte_length"] == wall_node["original"]["point_count"] * 13
    wall_stats = manifest["stats"]["wall"]
    assert wall_stats["original_points"] == len(wall_points)
    assert wall_stats["performance_points"] <= wall_stats["balanced_points"] <= wall_stats["original_points"]

    tile_path = pcd_tiles.resolve_scene_tile_file(
        "Scene13_分层瓦片",
        wall_node["original"]["file"],
    )
    payload = tile_path.read_bytes()
    point_count = wall_node["original"]["point_count"]
    first_three_point = struct.unpack_from("<fff", payload, 0)
    # Payload is already transformed to Three.js coordinates: (x, z, -y).
    assert first_three_point == pytest.approx((0.01, 0.03, -0.02))
    assert len(payload) == point_count * 13


def test_scene_tile_cache_key_tracks_source_version(monkeypatch, tmp_path):
    scene_root = tmp_path / "MAPS"
    cache_root = tmp_path / "tile-cache"
    scene_root.mkdir()
    scene = scene_root / "Scene14_瓦片缓存"
    scene.mkdir()
    map_path = scene / "map.pcd"
    ground_path = scene / "ground.pcd"
    write_binary_pcd(map_path, [(0.0, 0.0, 0.0, 1.0)])
    write_binary_pcd(ground_path, [(0.0, 0.0, 0.0, 1.0)])
    monkeypatch.setattr(pcd_services.settings, "SCENE_MAP_ROOT", str(scene_root))
    monkeypatch.setattr(pcd_tiles.settings, "SCENE_MAP_ROOT", str(scene_root))
    monkeypatch.setattr(pcd_tiles.settings, "PCD_SCENE_TILE_CACHE_DIR", str(cache_root))
    monkeypatch.setattr(pcd_tiles.settings, "PCD_SCENE_TILE_BUILD_CHUNK_POINTS", 1000)

    first = pcd_tiles.prepare_scene_tile_manifest("Scene14_瓦片缓存")
    same = pcd_tiles.prepare_scene_tile_manifest("Scene14_瓦片缓存")
    write_binary_pcd(ground_path, [
        (0.0, 0.0, 0.0, 1.0),
        (1.0, 1.0, 1.0, 2.0),
    ])
    changed = pcd_tiles.prepare_scene_tile_manifest("Scene14_瓦片缓存")

    assert first == same
    assert changed != first
    assert changed.is_file()


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


def test_delete_scene_removes_related_json_without_deleting_collided_waypoints(monkeypatch, tmp_path):
    scene_root = tmp_path / "MAPS"
    waypoint_root = tmp_path / "waypoints"
    localization_root = tmp_path / "localization"
    task_root = tmp_path / "tasks"
    runtime_root = tmp_path / "runtime"
    scene_root.mkdir()

    scene_id = "Scene20_楚峰国际"
    other_scene_id = "Scene20_办公楼建图"
    scene = scene_root / scene_id
    scene.mkdir()
    write_ascii_pcd(scene / "map.pcd", [(0.0, 0.0, 0.0)])
    write_ascii_pcd(scene / "ground.pcd", [(0.0, 0.0, -0.8)])

    monkeypatch.setattr(pcd_services.settings, "SCENE_MAP_ROOT", str(scene_root))
    monkeypatch.setattr(pcd_services.settings, "NAV_RUNTIME_DIR", str(runtime_root))
    monkeypatch.setattr("backend.services_nav_waypoints.settings.SCENE_MAP_ROOT", str(scene_root))
    monkeypatch.setattr("backend.services_nav_waypoints.settings.NAV_WAYPOINT_STORE_DIR", str(waypoint_root))
    monkeypatch.setattr("backend.services_nav_localization.settings.SCENE_MAP_ROOT", str(scene_root))
    monkeypatch.setattr("backend.services_nav_localization.settings.NAV_LOCALIZATION_STORE_DIR", str(localization_root))
    monkeypatch.setattr("backend.services_nav_tasks.settings.NAV_TASK_STORE_DIR", str(task_root))

    created_waypoint = create_waypoint(
        scene_id,
        {"name": "巡检点1", "x": 0.0, "y": 0.0, "z": -0.8, "yaw": 0.0, "frame_id": "map"},
    )
    save_localization_pose({"map_id": scene_id, "x": 0.0, "y": 0.0, "z": -0.8, "yaw": 0.0, "frame_id": "map"})
    save_nav_task({
        "id": "task-scene20-target",
        "name": "目标场景任务",
        "mapId": scene_id,
        "sceneId": scene_id,
        "mapName": scene_id,
        "createdAt": "2026-06-25T00:00:00.000Z",
        "steps": [{"type": "navigate_waypoint", "waypointId": created_waypoint["id"]}],
    })
    save_nav_task({
        "id": "task-scene20-other",
        "name": "其他场景任务",
        "mapId": other_scene_id,
        "sceneId": other_scene_id,
        "mapName": other_scene_id,
        "createdAt": "2026-06-25T00:00:00.000Z",
        "steps": [],
    })

    waypoint_root.mkdir(parents=True, exist_ok=True)
    legacy_waypoint_file = waypoint_root / "Scene20.json"
    legacy_waypoint_file.write_text(json.dumps({
        "map_id": scene_id,
        "items": [
            {"id": "legacy-target", "map_id": scene_id, "name": "旧目标点"},
            {"id": "legacy-other", "map_id": other_scene_id, "name": "旧其他点"},
        ],
    }, ensure_ascii=False), encoding="utf-8")

    runtime_root.mkdir(parents=True, exist_ok=True)
    (runtime_root / "current_scene.json").write_text(json.dumps({"scene_id": scene_id}), encoding="utf-8")
    (runtime_root / "current_goal.json").write_text(json.dumps({"map_id": scene_id}), encoding="utf-8")

    result = pcd_services.delete_pcd_scene(scene_id)

    assert result["success"] is True
    assert not scene.exists()
    assert result["cleanup"]["waypoints"]["removed_items"] == 2
    assert result["cleanup"]["tasks"]["deleted_task_ids"] == ["task-scene20-target"]
    assert len(result["cleanup"]["localization"]["deleted_files"]) == 1
    assert sorted(Path(path).name for path in result["cleanup"]["runtime"]["deleted_files"]) == [
        "current_goal.json",
        "current_scene.json",
    ]

    legacy_data = json.loads(legacy_waypoint_file.read_text(encoding="utf-8"))
    assert legacy_data["items"] == [{"id": "legacy-other", "map_id": other_scene_id, "name": "旧其他点"}]
    assert [task["id"] for task in list_nav_tasks()["items"]] == ["task-scene20-other"]


def test_delete_incomplete_scene_without_ground_pcd(monkeypatch, tmp_path):
    scene_root = tmp_path / "MAPS"
    waypoint_root = tmp_path / "waypoints"
    localization_root = tmp_path / "localization"
    task_root = tmp_path / "tasks"
    runtime_root = tmp_path / "runtime"
    scene_root.mkdir()

    scene_id = "Scene21_失败建图"
    scene = scene_root / scene_id
    scene.mkdir()

    monkeypatch.setattr(pcd_services.settings, "SCENE_MAP_ROOT", str(scene_root))
    monkeypatch.setattr(pcd_services.settings, "NAV_RUNTIME_DIR", str(runtime_root))
    monkeypatch.setattr("backend.services_nav_waypoints.settings.NAV_WAYPOINT_STORE_DIR", str(waypoint_root))
    monkeypatch.setattr(
        "backend.services_nav_localization.settings.NAV_LOCALIZATION_STORE_DIR",
        str(localization_root),
    )
    monkeypatch.setattr("backend.services_nav_tasks.settings.NAV_TASK_STORE_DIR", str(task_root))

    result = pcd_services.delete_pcd_scene(scene_id)

    assert result["success"] is True
    assert result["scene_id"] == scene_id
    assert not scene.exists()
    assert result["cleanup"]["waypoints"]["removed_items"] == 0
    assert result["cleanup"]["localization"]["deleted_files"] == []
    assert result["cleanup"]["tasks"]["removed_count"] == 0
