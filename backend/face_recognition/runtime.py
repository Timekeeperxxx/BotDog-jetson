from __future__ import annotations

from dataclasses import dataclass
import time
from threading import RLock
from typing import Any

import numpy as np

from .engine import FaceEngineError, FaceRecognitionEngine
from .matcher import FaceMatch, FaceMatcher


@dataclass
class _TrackState:
    candidate_identity_id: int | None = None
    candidate_name: str | None = None
    hits: int = 0
    status: str = "pending"
    score: float | None = None
    last_seen: float = 0.0


class FaceRecognitionRuntime:
    """按轨迹缓存人名并做连续帧确认；不修改任何安全/控制字段。"""

    def __init__(
        self,
        engine: FaceRecognitionEngine,
        matcher: FaceMatcher,
        *,
        frame_skip: int = 2,
        confirm_hits: int = 3,
        track_ttl_seconds: float = 2.0,
        enabled: bool = True,
    ) -> None:
        self.engine = engine
        self.matcher = matcher
        self.frame_skip = max(1, int(frame_skip))
        self.confirm_hits = max(1, int(confirm_hits))
        self.track_ttl_seconds = max(0.1, float(track_ttl_seconds))
        self.enabled = bool(enabled)
        self._tracks: dict[int, _TrackState] = {}
        self._lock = RLock()

    def clear(self) -> None:
        with self._lock:
            self._tracks.clear()

    def process(
        self,
        frame_bgr: np.ndarray,
        detections: list[Any],
        frame_index: int,
        *,
        now: float | None = None,
    ) -> None:
        with self._lock:
            self._process_locked(frame_bgr, detections, frame_index, now=now)

    def _process_locked(
        self,
        frame_bgr: np.ndarray,
        detections: list[Any],
        frame_index: int,
        *,
        now: float | None = None,
    ) -> None:
        timestamp = time.monotonic() if now is None else float(now)
        self._prune(timestamp)
        persons = [
            item for item in detections
            if getattr(item, "label", getattr(item, "class_name", "")) == "person"
            and getattr(item, "bbox", None) is not None
            and int(getattr(item, "track_id", -1)) >= 0
        ]
        if not self.enabled:
            for person in persons:
                self._set_result(person, "unavailable", None, None, None)
            return

        due = frame_index % self.frame_skip == 0
        face_matches: dict[int, FaceMatch] = {}
        if due and persons:
            try:
                for face in self.engine.detect(frame_bgr):
                    person = self._person_for_face(face, persons)
                    if person is None:
                        continue
                    try:
                        extraction = self.engine.extract_from_face(frame_bgr, face)
                    except FaceEngineError:
                        continue
                    face_matches[int(person.track_id)] = self.matcher.match(extraction.embedding)
            except FaceEngineError:
                for person in persons:
                    self._set_result(person, "unavailable", None, None, None)
                return

        for person in persons:
            track_id = int(person.track_id)
            state = self._tracks.setdefault(track_id, _TrackState())
            state.last_seen = timestamp
            match = face_matches.get(track_id)
            if match is not None:
                self._update_state(state, match)
            self._set_result(
                person,
                state.status,
                state.candidate_identity_id if state.status == "recognized" else None,
                state.candidate_name if state.status == "recognized" else None,
                state.score,
            )

    def _update_state(self, state: _TrackState, match: FaceMatch) -> None:
        identity_id = match.identity_id if match.matched else None
        if identity_id == state.candidate_identity_id:
            state.hits += 1
        else:
            state.candidate_identity_id = identity_id
            state.candidate_name = match.display_name if match.matched else None
            state.hits = 1
        state.score = match.score
        if state.hits < self.confirm_hits:
            state.status = "pending"
        elif match.matched:
            state.status = "recognized"
        else:
            state.status = "unknown"

    def _prune(self, now: float) -> None:
        for track_id in [
            key for key, state in self._tracks.items()
            if now - state.last_seen > self.track_ttl_seconds
        ]:
            self._tracks.pop(track_id, None)

    @staticmethod
    def _person_for_face(face: np.ndarray, persons: list[Any]) -> Any | None:
        x, y, width, height = (float(value) for value in face[:4])
        cx = x + width / 2.0
        cy = y + height / 2.0
        candidates = []
        for person in persons:
            x1, y1, x2, y2 = person.bbox
            if x1 <= cx <= x2 and y1 <= cy <= y2:
                candidates.append(person)
        if not candidates:
            return None
        return min(candidates, key=lambda item: (item.bbox[2] - item.bbox[0]) * (item.bbox[3] - item.bbox[1]))

    @staticmethod
    def _set_result(
        detection: Any,
        status: str,
        identity_id: int | None,
        display_name: str | None,
        score: float | None,
    ) -> None:
        detection.face_status = status
        detection.identity_id = identity_id
        detection.display_name = display_name
        detection.face_score = score
