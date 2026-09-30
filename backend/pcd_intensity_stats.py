"""Exact percentiles of finite float32 intensities in 16-byte XYZ/I records.

Two streaming radix-histogram passes; memory is independent of point count.
Works on both conversion spool records and packed Potree octree records.
"""
from pathlib import Path

import numpy as np


def intensity_percentiles(path: Path, chunk_points: int = 131072, percentiles=(2, 98)) -> list[float]:
    def keys():
        with path.open('rb') as stream:
            while True:
                records = np.fromfile(stream, dtype='<f4', count=chunk_points * 4)
                if not records.size:
                    return
                values = records.reshape(-1, 4)[:, 3].copy()
                values = values[np.isfinite(values)]
                bits = values.view(np.uint32)
                yield np.where(bits & 0x80000000, ~bits, bits ^ 0x80000000).astype(np.uint32)

    high_counts = np.zeros(65536, dtype=np.int64)
    for values in keys():
        high_counts += np.bincount(values >> 16, minlength=65536)
    count = int(high_counts.sum())
    if not count:
        return [0.0] * len(percentiles)
    positions = (np.asarray(percentiles) / 100) * (count - 1)
    ranks = np.unique(np.concatenate((np.floor(positions), np.ceil(positions))).astype(np.int64))
    cumulative = high_counts.cumsum()
    buckets = np.searchsorted(cumulative, ranks, side='right')
    low_counts = {int(bucket): np.zeros(65536, dtype=np.int64) for bucket in buckets}
    for values in keys():
        high = values >> 16
        for bucket, histogram in low_counts.items():
            histogram += np.bincount(values[high == bucket] & 65535, minlength=65536)
    selected = {}
    for rank, bucket in zip(ranks, buckets):
        before = cumulative[bucket - 1] if bucket else 0
        low = int(np.searchsorted(low_counts[int(bucket)].cumsum(), rank - before, side='right'))
        key = (int(bucket) << 16) | low
        bits = key ^ 0x80000000 if key & 0x80000000 else (~key & 0xffffffff)
        selected[int(rank)] = float(np.array([bits], dtype=np.uint32).view(np.float32)[0])
    return [selected[int(np.floor(p))] * (1 - (p % 1)) + selected[int(np.ceil(p))] * (p % 1) for p in positions]
