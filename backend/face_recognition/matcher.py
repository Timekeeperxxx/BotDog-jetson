from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

import numpy as np


@dataclass(frozen=True)
class FaceTemplateRecord:
    template_id: int
    identity_id: int
    display_name: str
    embedding: np.ndarray


@dataclass(frozen=True)
class FaceMatch:
    identity_id: int | None
    display_name: str | None
    score: float
    matched: bool


class FaceMatcher:
    """线程安全的内存向量矩阵，API 修改人员库后可原子替换。"""

    def __init__(self, threshold: float = 0.45) -> None:
        self.threshold = float(threshold)
        self._records: tuple[FaceTemplateRecord, ...] = ()
        self._matrix = np.empty((0, 0), dtype=np.float32)
        self._lock = RLock()

    @property
    def template_count(self) -> int:
        with self._lock:
            return len(self._records)

    @property
    def identity_count(self) -> int:
        with self._lock:
            return len({record.identity_id for record in self._records})

    def replace(self, records: list[FaceTemplateRecord]) -> None:
        normalized: list[FaceTemplateRecord] = []
        dimension: int | None = None
        for record in records:
            vector = np.asarray(record.embedding, dtype=np.float32).reshape(-1)
            norm = float(np.linalg.norm(vector))
            if not np.isfinite(norm) or norm <= 1e-8:
                continue
            if dimension is None:
                dimension = vector.size
            if vector.size != dimension:
                continue
            normalized.append(
                FaceTemplateRecord(
                    template_id=record.template_id,
                    identity_id=record.identity_id,
                    display_name=record.display_name,
                    embedding=np.ascontiguousarray(vector / norm, dtype=np.float32),
                )
            )
        matrix = (
            np.stack([record.embedding for record in normalized]).astype(np.float32)
            if normalized
            else np.empty((0, 0), dtype=np.float32)
        )
        with self._lock:
            self._records = tuple(normalized)
            self._matrix = matrix

    def match(self, embedding: np.ndarray) -> FaceMatch:
        vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(vector))
        if not np.isfinite(norm) or norm <= 1e-8:
            return FaceMatch(None, None, 0.0, False)
        with self._lock:
            records = self._records
            matrix = self._matrix
        if not records or matrix.shape[1] != vector.size:
            return FaceMatch(None, None, 0.0, False)
        scores = matrix @ (vector / norm)
        best_index = int(np.argmax(scores))
        score = max(-1.0, min(1.0, float(scores[best_index])))
        record = records[best_index]
        if score < self.threshold:
            return FaceMatch(None, None, score, False)
        return FaceMatch(record.identity_id, record.display_name, score, True)
