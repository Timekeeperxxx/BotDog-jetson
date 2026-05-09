from __future__ import annotations

from pathlib import Path

from backend import services_pcd_maps as pcd_services


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


def test_list_pcd_scenes_and_find_layer_files(monkeypatch, tmp_path):
    scene_root = tmp_path / "MAPS"
    scene_root.mkdir()
    scene_a = scene_root / "Scene1_实验室一楼"
    scene_a.mkdir()
    scene_b = scene_root / "demo"
    scene_b.mkdir()

    wall = scene_a / "abcmap.pcd"
    ground = scene_a / "abcground.pcd"
    write_ascii_pcd(wall, [(0.0, 0.0, 0.0)])
    write_ascii_pcd(ground, [(1.0, 2.0, 3.0)])

    monkeypatch.setattr(pcd_services.settings, "SCENE_MAP_ROOT", str(scene_root))

    result = pcd_services.list_pcd_scenes()

    assert result["root"] == str(scene_root.resolve())
    assert [item["id"] for item in result["items"]] == ["Scene1_实验室一楼"]
    item = result["items"][0]
    assert item["ready"] is True
    assert item["navigable"] is True
    assert item["wall"]["name"] == "abcmap.pcd"
    assert item["ground"]["name"] == "abcground.pcd"


def test_scene_metadata_and_preview_merge_bounds(monkeypatch, tmp_path):
    scene_root = tmp_path / "MAPS"
    scene_root.mkdir()
    scene = scene_root / "Scene2_走廊"
    scene.mkdir()

    wall = scene / "scene_wall_map.pcd"
    ground = scene / "scene_ground.pcd"
    write_ascii_pcd(wall, [(-1.0, 0.0, 0.0), (2.0, 4.0, 1.0)])
    write_ascii_pcd(ground, [(3.0, -2.0, -1.0), (4.0, 1.0, 2.0)])

    monkeypatch.setattr(pcd_services.settings, "SCENE_MAP_ROOT", str(scene_root))

    metadata = pcd_services.get_scene_metadata("Scene2_走廊")
    assert metadata["supported"] is True
    assert metadata["message"] is None
    assert metadata["bounds"]["min_x"] == -1.0
    assert metadata["bounds"]["max_x"] == 4.0
    assert metadata["bounds"]["min_y"] == -2.0
    assert metadata["bounds"]["max_y"] == 4.0
    assert metadata["files"]["wall"]["point_count"] == 2
    assert metadata["files"]["ground"]["point_count"] == 2

    preview = pcd_services.get_scene_preview("Scene2_走廊", max_points=1000)
    assert preview["layers"]["ground"] is not None
    assert preview["layers"]["wall"] is not None
    assert len(preview["layers"]["ground"]["points"]) == 2
    assert len(preview["layers"]["wall"]["points"]) == 2
    assert preview["bounds"]["min_x"] == -1.0
    assert preview["bounds"]["max_x"] == 4.0
