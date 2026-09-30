import numpy as np
import pytest
from backend.pcd_intensity_stats import intensity_percentiles

@pytest.mark.parametrize('values', [
    [0, 2, 28, 114, 255], [-100, -4, -.1, 0, 1, 1.25, 10],
    [4] * 103, [0] * 98 + [255] * 2, [], [1, float('nan'), float('inf'), 3],
])
def test_streamed_percentiles_match_numpy(tmp_path, values):
    path = tmp_path / 'octree.bin'
    records = np.zeros((len(values), 4), dtype='<f4')
    records[:, 3] = values
    records.tofile(path)
    finite = records[:, 3][np.isfinite(records[:, 3])]
    expected = np.percentile(finite, [2, 98]) if len(finite) else [0, 0]
    assert intensity_percentiles(path, chunk_points=3) == pytest.approx(expected)


def test_rank_quantiles_for_skewed_distribution(tmp_path):
    path = tmp_path / 'octree.bin'
    records = np.zeros((10003, 4), dtype='<f4')
    records[:, 3] = np.random.default_rng(42).exponential(20, len(records))
    records.tofile(path)
    assert intensity_percentiles(path, chunk_points=79, percentiles=range(0, 101, 5)) == pytest.approx(
        np.percentile(records[:, 3], range(0, 101, 5)))
