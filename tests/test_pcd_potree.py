import json
import struct
from collections import Counter

import numpy as np
import pytest

from backend import pcd_potree as potree


def write_pcd(path, points):
    with path.open('wb') as f:
        f.write(('VERSION .7\nFIELDS x y z intensity\nSIZE 4 4 4 4\nTYPE F F F F\nCOUNT 1 1 1 1\n'
                 f'WIDTH {len(points)}\nHEIGHT 1\nPOINTS {len(points)}\nDATA binary\n').encode())
        np.asarray(points, dtype='<f4').tofile(f)


def test_additive_tree_keeps_all_points_and_intensity_once_with_paged_hierarchy(tmp_path, monkeypatch):
    monkeypatch.setattr(potree, 'LEAF_POINTS', 32)
    monkeypatch.setattr(potree, 'BRANCH_POINTS', 8)
    monkeypatch.setattr(potree, 'CHUNK_POINTS', 73)
    rng = np.random.default_rng(42)
    points = np.column_stack((rng.integers(-12, 12, (700, 3)), np.arange(700))).astype('<f4')
    points[1] = points[0]  # exact duplicates must survive
    points[-1, 0] = np.nan
    source = tmp_path / 'source.pcd'
    output = tmp_path / 'tree'
    write_pcd(source, points)
    info = potree.build_layer(source, output)
    meta = json.loads((output / 'metadata.json').read_text())
    hierarchy = (output / 'hierarchy.bin').read_bytes()
    data = (output / 'octree.bin').read_bytes()
    collected, ranges, pages = [], [], set()

    def visit(offset, size):
        assert size <= 9 * 22
        assert offset not in pages
        pages.add(offset)
        records = list(struct.iter_unpack('<BBIqq', hierarchy[offset:offset + size]))
        kind, mask, count, start, length = records[0]
        assert kind in (0, 1)
        assert len(records) == 1 + mask.bit_count()
        assert length == count * 16
        ranges.append((start, start + length))
        values = np.frombuffer(data[start:start + length], dtype=[('xyz', '<i4', (3,)), ('i', '<f4')])
        xyz = values['xyz'] * meta['scale'] + meta['offset']
        for pos, intensity in zip(xyz, values['i']):
            collected.append((*np.round(pos, 4), float(intensity)))
        for kind, _, _, off, length in records[1:]:
            assert kind == 2
            visit(off, length)

    visit(0, meta['hierarchy']['firstChunkSize'])
    expected = [(float(x), float(z), float(-y), float(i)) for x, y, z, i in points[:-1]]
    assert Counter(collected) == Counter(expected)
    assert meta['points'] == info['points'] == 699
    assert len(pages) == info['nodes']
    assert sorted(ranges)[0][0] == 0
    for left, right in zip(sorted(ranges), sorted(ranges)[1:]):
        assert left[1] == right[0]
    assert not list(output.glob('*.part'))


def test_scene_manifest_is_small_and_assets_are_scene_scoped(tmp_path, monkeypatch):
    scene = tmp_path / 'Scene1_test'
    scene.mkdir()
    write_pcd(scene / 'map.pcd', [[1, 2, 3, 4], [1, 2, 3, 4]])
    monkeypatch.setattr(potree.settings, 'SCENE_MAP_ROOT', str(tmp_path))
    monkeypatch.setattr(potree.settings, 'PCD_SCENE_TILE_CACHE_DIR', str(tmp_path / 'cache'))
    cache, files = potree.scene_cache(scene.name)
    potree.build_scene(scene.name, cache, files)
    manifest = potree.request_scene(scene.name)
    assert manifest['nodes'] == []
    assert manifest['potree']['layers'][0]['point_count'] == 2
    assert potree.resolve_asset(scene.name, cache.name, 'wall', 'octree.bin').stat().st_size == 32
    for role, file in [('..', 'metadata.json'), ('wall', '../manifest.json')]:
        with pytest.raises(FileNotFoundError):
            potree.resolve_asset(scene.name, cache.name, role, file)


def test_coincident_points_do_not_require_a_whole_partition_in_memory(tmp_path, monkeypatch):
    monkeypatch.setattr(potree, 'LEAF_POINTS', 8)
    monkeypatch.setattr(potree, 'BRANCH_POINTS', 4)
    monkeypatch.setattr(potree, 'CHUNK_POINTS', 17)
    source = tmp_path / 'coincident.pcd'
    write_pcd(source, [[1, 2, 3, 4]] * 1100)
    info = potree.build_layer(source, tmp_path / 'tree')
    assert info['points'] == 1100
    assert (tmp_path / 'tree' / 'octree.bin').stat().st_size == 1100 * 16
