from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .logging_config import logger
from .tracking_types import ActiveTarget, DetectionResult


@dataclass
class _FallbackTrack:
    track_id: int
    bbox: tuple[int, int, int, int]
    last_seen_frame: int


class AutoTrackDetectionMixin:
    def _filter_no_helmet_persons(
        self,
        detections: list[DetectionResult],
    ) -> list[DetectionResult]:
        persons = [d for d in detections if d.class_name == "person"]
        heads = [d for d in detections if d.class_name == "head"]
        helmets = [d for d in detections if d.class_name == "helmet"]

        result: list[DetectionResult] = []
        for person in persons:
            has_head = any(self._part_belongs_to_person(head.bbox, person.bbox) for head in heads)
            if not has_head:
                continue

            has_helmet = any(self._part_belongs_to_person(helmet.bbox, person.bbox) for helmet in helmets)
            if has_helmet:
                continue

            result.append(person)

        return result

    def _filter_helmet_person_ids(
        self,
        detections: list[DetectionResult],
        persons: list[DetectionResult],
    ) -> set[int]:
        helmets = [d for d in detections if d.class_name == "helmet"]
        if not helmets:
            return set()

        result: set[int] = set()
        for person in persons:
            if person.track_id < 0:
                continue
            if any(self._part_belongs_to_person(helmet.bbox, person.bbox) for helmet in helmets):
                result.add(person.track_id)
        return result

    @staticmethod
    def _part_belongs_to_person(
        part_bbox: tuple[int, int, int, int],
        person_bbox: tuple[int, int, int, int],
    ) -> bool:
        px1, py1, px2, py2 = person_bbox
        part_x1, part_y1, part_x2, part_y2 = part_bbox
        person_w = max(1, px2 - px1)
        person_h = max(1, py2 - py1)
        part_area = max(1, part_x2 - part_x1) * max(1, part_y2 - part_y1)

        cx = (part_x1 + part_x2) / 2.0
        cy = (part_y1 + part_y2) / 2.0
        upper_limit = py1 + person_h * 0.65
        horizontal_margin = person_w * 0.12

        center_in_upper_person = (
            px1 - horizontal_margin <= cx <= px2 + horizontal_margin
            and py1 <= cy <= upper_limit
        )

        ix1 = max(part_x1, px1)
        iy1 = max(part_y1, py1)
        ix2 = min(part_x2, px2)
        iy2 = min(part_y2, py2)
        intersection = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        overlap_ratio = intersection / float(part_area)

        return center_in_upper_person and overlap_ratio >= 0.35

    def _assign_fallback_ids(
        self,
        persons: list[DetectionResult],
        frame_index: int,
    ) -> list[DetectionResult]:
        """
        为 track_id == -1 的检测结果分配降级 IOU ID，保持帧间连续性。
        YOLO track 模式正常工作时此函数基本是空操作。
        """
        self._prune_fallback_tracks(frame_index)

        # 若已有锁定目标，把它作为最高优先级轨迹保留下来。
        if self._active_target is not None:
            self._fallback_tracks[self._active_target.track_id] = _FallbackTrack(
                track_id=self._active_target.track_id,
                bbox=self._active_target.bbox,
                last_seen_frame=frame_index,
            )

        no_id = [d for d in persons if d.track_id == -1]
        if not no_id:
            return persons

        result = [d for d in persons if d.track_id != -1]
        used_track_ids = {d.track_id for d in result if d.track_id >= 0}

        # 优先处理高置信度/大框，减少多人场景下小框抢占主目标 ID。
        no_id.sort(
            key=lambda d: (
                d.confidence,
                max(0, d.bbox[2] - d.bbox[0]) * max(0, d.bbox[3] - d.bbox[1]),
            ),
            reverse=True,
        )

        for det in no_id:
            track_id = self._match_fallback_track(det.bbox, used_track_ids)
            if track_id is None:
                self._iou_id_counter += 1
                track_id = self._iou_id_counter

            det.track_id = track_id
            used_track_ids.add(track_id)
            self._last_iou_bbox = det.bbox
            self._fallback_tracks[track_id] = _FallbackTrack(
                track_id=track_id,
                bbox=det.bbox,
                last_seen_frame=frame_index,
            )
            result.append(det)

        return result

    def _prune_fallback_tracks(self, frame_index: int) -> None:
        stale_ids = [
            track_id
            for track_id, track in self._fallback_tracks.items()
            if frame_index - track.last_seen_frame > self._fallback_max_age_frames
        ]
        for track_id in stale_ids:
            self._fallback_tracks.pop(track_id, None)

    def _match_fallback_track(
        self,
        bbox: tuple[int, int, int, int],
        used_track_ids: set[int],
    ) -> Optional[int]:
        best_id: Optional[int] = None
        best_score = -1.0

        for track_id, track in self._fallback_tracks.items():
            if track_id in used_track_ids:
                continue

            score = self._bbox_match_score(bbox, track.bbox, track_id=track_id)
            if score > best_score:
                best_score = score
                best_id = track_id

        return best_id if best_score >= 0.0 else None

    def _find_target_match(
        self,
        persons: list[DetectionResult],
        target: ActiveTarget,
    ) -> Optional[DetectionResult]:
        matched = self._find_by_track_id(persons, target.track_id)
        if matched is not None:
            return matched

        best: Optional[DetectionResult] = None
        best_score = -1.0
        for det in persons:
            score = self._bbox_match_score(det.bbox, target.bbox, track_id=target.track_id)
            if score > best_score:
                best_score = score
                best = det

        if best is None or best_score < 0.0:
            return None

        previous_id = best.track_id
        best.track_id = target.track_id
        self._fallback_tracks[target.track_id] = _FallbackTrack(
            track_id=target.track_id,
            bbox=best.bbox,
            last_seen_frame=self._frames_processed,
        )
        logger.debug(
            "[AutoTrackService] 通过 bbox 重关联目标：old_track_id={} -> active_track_id={} score={:.3f}",
            previous_id,
            target.track_id,
            best_score,
        )
        return best

    def _bbox_match_score(
        self,
        bbox: tuple[int, int, int, int],
        ref_bbox: tuple[int, int, int, int],
        *,
        track_id: int,
    ) -> float:
        iou = _calc_iou(bbox, ref_bbox)
        center_distance = _center_distance(bbox, ref_bbox)
        bw = max(1, bbox[2] - bbox[0])
        bh = max(1, bbox[3] - bbox[1])
        rw = max(1, ref_bbox[2] - ref_bbox[0])
        rh = max(1, ref_bbox[3] - ref_bbox[1])
        gate = max(
            120.0,
            0.08 * float(self._frame_width),
            0.30 * float(max(bw, bh, rw, rh)),
        )

        if iou < self._fallback_iou_threshold and center_distance > gate:
            return -1.0

        center_score = max(0.0, 1.0 - center_distance / gate)
        active_bonus = 0.35 if self._active_target is not None and track_id == self._active_target.track_id else 0.0
        return iou * 3.0 + center_score + active_bonus

    def _find_by_track_id(
        self,
        persons: list[DetectionResult],
        track_id: int,
    ) -> Optional[DetectionResult]:
        """在检测结果中精确查找指定 track_id。"""
        for det in persons:
            if det.track_id == track_id:
                return det
        return None


def _calc_iou(
    bbox_a: tuple[int, int, int, int],
    bbox_b: tuple[int, int, int, int],
) -> float:
    ax1, ay1, ax2, ay2 = bbox_a
    bx1, by1, bx2, by2 = bbox_b
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    if inter == 0:
        return 0.0
    area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    area_b = max(0, bx2 - bx1) * max(0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _center_distance(
    bbox_a: tuple[int, int, int, int],
    bbox_b: tuple[int, int, int, int],
) -> float:
    ax1, ay1, ax2, ay2 = bbox_a
    bx1, by1, bx2, by2 = bbox_b
    acx = (ax1 + ax2) / 2.0
    acy = (ay1 + ay2) / 2.0
    bcx = (bx1 + bx2) / 2.0
    bcy = (by1 + by2) / 2.0
    return ((acx - bcx) ** 2 + (acy - bcy) ** 2) ** 0.5
