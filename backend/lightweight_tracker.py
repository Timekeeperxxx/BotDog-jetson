from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class IouTrack:
    track_id: int
    bbox: tuple[int, int, int, int]
    last_seen_frame: int


class LightweightIouTracker:
    """ByteTrack 关闭时共用的轻量 IOU/中心距离轨迹分配器。"""

    def __init__(
        self,
        *,
        frame_width: int,
        iou_threshold: float = 0.15,
        max_age_frames: int = 30,
    ) -> None:
        self.frame_width = max(1, int(frame_width))
        self.iou_threshold = float(iou_threshold)
        self.max_age_frames = max(1, int(max_age_frames))
        self.next_id = 0
        self.tracks: dict[int, IouTrack] = {}

    def remember(
        self,
        track_id: int,
        bbox: tuple[int, int, int, int],
        frame_index: int,
    ) -> None:
        self.next_id = max(self.next_id, int(track_id))
        self.tracks[int(track_id)] = IouTrack(int(track_id), bbox, int(frame_index))

    def update(self, detections: list[Any], frame_index: int) -> list[Any]:
        self._prune(frame_index)
        result = [item for item in detections if int(getattr(item, "track_id", -1)) >= 0]
        for item in result:
            self.remember(int(item.track_id), item.bbox, frame_index)
        without_id = [item for item in detections if int(getattr(item, "track_id", -1)) < 0]
        without_id.sort(
            key=lambda item: (
                float(getattr(item, "confidence", 0.0)),
                _bbox_area(item.bbox),
            ),
            reverse=True,
        )
        used_ids = {int(item.track_id) for item in result}
        for item in without_id:
            track_id = self._best_track(item.bbox, used_ids)
            if track_id is None:
                self.next_id += 1
                track_id = self.next_id
            item.track_id = track_id
            used_ids.add(track_id)
            self.remember(track_id, item.bbox, frame_index)
            result.append(item)
        return result

    def _prune(self, frame_index: int) -> None:
        for track_id in [
            key for key, track in self.tracks.items()
            if frame_index - track.last_seen_frame > self.max_age_frames
        ]:
            self.tracks.pop(track_id, None)

    def _best_track(
        self,
        bbox: tuple[int, int, int, int],
        used_ids: set[int],
    ) -> int | None:
        best_id: int | None = None
        best_score = -1.0
        for track_id, track in self.tracks.items():
            if track_id in used_ids:
                continue
            score = self.match_score(bbox, track.bbox)
            if score > best_score:
                best_id, best_score = track_id, score
        return best_id if best_score >= 0.0 else None

    def match_score(
        self,
        bbox: tuple[int, int, int, int],
        reference: tuple[int, int, int, int],
    ) -> float:
        iou = calc_iou(bbox, reference)
        distance = center_distance(bbox, reference)
        sizes = [
            max(1, bbox[2] - bbox[0]),
            max(1, bbox[3] - bbox[1]),
            max(1, reference[2] - reference[0]),
            max(1, reference[3] - reference[1]),
        ]
        gate = max(120.0, 0.08 * self.frame_width, 0.30 * max(sizes))
        if iou < self.iou_threshold and distance > gate:
            return -1.0
        return iou * 3.0 + max(0.0, 1.0 - distance / gate)


def calc_iou(
    bbox_a: tuple[int, int, int, int],
    bbox_b: tuple[int, int, int, int],
) -> float:
    ax1, ay1, ax2, ay2 = bbox_a
    bx1, by1, bx2, by2 = bbox_b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    intersection = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    union = _bbox_area(bbox_a) + _bbox_area(bbox_b) - intersection
    return intersection / union if union > 0 else 0.0


def center_distance(
    bbox_a: tuple[int, int, int, int],
    bbox_b: tuple[int, int, int, int],
) -> float:
    acx, acy = (bbox_a[0] + bbox_a[2]) / 2.0, (bbox_a[1] + bbox_a[3]) / 2.0
    bcx, bcy = (bbox_b[0] + bbox_b[2]) / 2.0, (bbox_b[1] + bbox_b[3]) / 2.0
    return ((acx - bcx) ** 2 + (acy - bcy) ** 2) ** 0.5


def _bbox_area(bbox: tuple[int, int, int, int]) -> int:
    return max(0, bbox[2] - bbox[0]) * max(0, bbox[3] - bbox[1])
