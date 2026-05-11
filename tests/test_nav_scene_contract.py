from __future__ import annotations

from pathlib import Path

import pytest

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


def test_scene_id_contract_and_navigation_flags(monkeypatch, tmp_path):
    scene_root = tmp_path / "MAPS"
    scene_root.mkdir()

    valid_scene = scene_root / "Scene1_实验室一楼"
    valid_scene.mkdir()
    write_ascii_pcd(valid_scene / "map.pcd", [(0.0, 0.0, 0.0)])
    write_ascii_pcd(valid_scene / "ground.pcd", [(1.0, 1.0, 1.0)])

    missing_map_scene = scene_root / "Scene2_缺少地图"
    missing_map_scene.mkdir()
    write_ascii_pcd(missing_map_scene / "ground.pcd", [(2.0, 2.0, 2.0)])

    missing_ground_scene = scene_root / "Scene3_缺少地面"
    missing_ground_scene.mkdir()
    write_ascii_pcd(missing_ground_scene / "map.pcd", [(3.0, 3.0, 3.0)])

    stray_scene = scene_root / "demo"
    stray_scene.mkdir()

    monkeypatch.setattr(pcd_services.settings, "SCENE_MAP_ROOT", str(scene_root))

    assert pcd_services.resolve_scene_path("Scene1_实验室一楼") == valid_scene.resolve()
    with pytest.raises(pcd_services.PcdMapError):
        pcd_services.validate_scene_id("demo")

    result = pcd_services.list_pcd_scenes()
    items = {item["id"]: item for item in result["items"]}

    assert "demo" not in items
    assert items["Scene1_实验室一楼"]["ready"] is True
    assert items["Scene1_实验室一楼"]["navigable"] is True
    assert items["Scene3_缺少地面"]["ready"] is False
    assert items["Scene3_缺少地面"]["navigable"] is False
    assert items["Scene2_缺少地图"]["ready"] is False
    assert items["Scene2_缺少地图"]["navigable"] is True
    assert "缺少 map.pcd" in str(items["Scene2_缺少地图"]["message"])
