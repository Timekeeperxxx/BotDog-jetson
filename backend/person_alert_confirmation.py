from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .lightweight_tracker import calc_iou
from .stranger_policy import is_authorized_person


@dataclass
class _Confirmation:
    bbox: tuple | None = None
    hits: int = 0
    last_frame: int = 0
    pose_batch: int = -1


class PersonAlertConfirmation:
    """Count fresh, consecutive unauthorized observations before personnel alerts."""

    def __init__(self, *, max_missing_frames: int = 20) -> None:
        self.max_missing_frames = max(1, max_missing_frames)
        self._tracks: dict[int, _Confirmation] = {}

    def clear(self) -> None:
        self._tracks.clear()

    def update(
        self, persons: list[Any], *, frame: int, required_hits: int,
        pose_batch: int, fresh_pose_ids: set[int],
    ) -> set[int]:
        required = max(1, int(required_hits))
        present = {int(person.track_id) for person in persons if int(person.track_id) >= 0}
        for track_id, state in list(self._tracks.items()):
            if frame - state.last_frame >= self.max_missing_frames:
                del self._tracks[track_id]
        confirmed: set[int] = set()
        seen: set[int] = set()
        for person in persons:
            track_id = int(person.track_id)
            if track_id < 0 or track_id in seen:
                continue
            seen.add(track_id)
            raw_bbox = getattr(person, 'bbox', None)
            bbox = tuple(raw_bbox) if raw_bbox is not None and len(raw_bbox) == 4 else None
            state = self._tracks.get(track_id)
            if state is None and bbox is not None:
                candidates = [
                    (calc_iou(bbox, prior.bbox), prior_id)
                    for prior_id, prior in self._tracks.items()
                    if prior_id not in present and prior.last_frame == frame - 1
                    and prior.bbox is not None
                ]
                if candidates:
                    score, prior_id = max(candidates, key=lambda item: item[0])
                    if score >= .3:
                        state = self._tracks.pop(prior_id)
            if state is None:
                state = _Confirmation()
            self._tracks[track_id] = state
            if state.last_frame != frame - 1:
                state.hits = 0
            fresh = not getattr(person, 'is_pose_fallback', False) or (
                pose_batch > 0 and pose_batch != state.pose_batch and track_id in fresh_pose_ids
            )
            state.last_frame = frame
            state.bbox = bbox
            state.pose_batch = pose_batch
            # Identity confirmation must finish before an unauthorized streak can start.
            # A recognized frame immediately cancels a prior unauthorized streak.
            if is_authorized_person(person) or getattr(person, 'face_status', None) == 'pending':
                state.hits = 0
                continue
            if not fresh:
                continue
            state.hits = min(required, state.hits + 1)
            if state.hits >= required:
                confirmed.add(track_id)
        for track_id, state in self._tracks.items():
            if track_id not in present:
                state.hits = 0
        return confirmed
