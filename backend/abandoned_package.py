"""Continuously visible backpacks with no overlapping person detection.

This produces an unattended candidate, not proof of ownership or abandonment.
Camera registration keeps track identities across patrol motion; bag stillness,
carrying, placement and a witnessed owner departure are not alarm conditions.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Sequence

import numpy as np

BBox = tuple[float, float, float, float]
PACKAGE_LABELS = frozenset({"backpack", "handbag", "suitcase", "luggage", "parcel"})


@dataclass(frozen=True)
class PackageConfig:
    confirm_seconds: float = 3.0
    max_gap_seconds: float = 0.8
    min_box_pixels: int = 12

    def __post_init__(self):
        values = (self.confirm_seconds, self.max_gap_seconds)
        if any(not math.isfinite(v) or v <= 0 for v in values):
            raise ValueError("包裹确认时间和观测间隔必须为有限正数")
        if self.min_box_pixels < 4:
            raise ValueError("包裹检测框的最小边长必须至少为4像素")


@dataclass(frozen=True)
class PackageEvent:
    track_id: int
    # Kept in the event schema for compatibility. This rule does not infer an owner.
    owner_id: int | None
    bbox: BBox
    confidence: float
    observed_at: float
    duration_seconds: float
    label: str = "backpack"


def _warp_point(point, matrix):
    value = matrix @ np.array([point[0], point[1], 1.0])
    return value[:2] / value[2]


def _warp_box(box, matrix) -> BBox:
    points = np.array([_warp_point(p, matrix) for p in
                       [(box[0], box[1]), (box[2], box[1]),
                        (box[2], box[3]), (box[0], box[3])]])
    return (float(points[:, 0].min()), float(points[:, 1].min()),
            float(points[:, 0].max()), float(points[:, 1].max()))


def _intersection(a, b):
    return max(0., min(a[2], b[2]) - max(a[0], b[0])) * max(
        0., min(a[3], b[3]) - max(a[1], b[1]))


def _iou(a, b):
    inter = _intersection(a, b)
    union = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - inter
    return inter / union if union > 0 else 0.


@dataclass
class _Track:
    id: int
    label: str
    box: BBox
    confidence: float
    seen_at: float
    unattended_since: float | None = None
    alerted: bool = False


class PackageEventEngine:
    """Track bags and time continuous visibility without current-frame overlap."""

    def __init__(self, config: PackageConfig | None = None):
        self.config = config or PackageConfig()
        self._next_id = 1
        self._tracks: dict[int, _Track] = {}
        self._last_at: float | None = None
        self.status: dict[str, Any] = {"state": "waiting", "tracks": []}

    def reset(self, reason: str = "reset"):
        self._tracks.clear()
        self._last_at = None
        self.status = {"state": reason, "tracks": []}

    def update(self, detections: Sequence[Any], now: float,
               motion: np.ndarray | None) -> tuple[list[PackageEvent], list[Any]]:
        if not math.isfinite(now):
            raise ValueError("观测时间必须为有限数值")
        previous_at = self._last_at
        gap = previous_at is None or not 0 < now-previous_at <= self.config.max_gap_seconds
        if motion is None or gap:
            self.reset("observing" if motion is not None else "motion_unavailable")
        self._last_at = now
        for detection in detections:
            if detection.label in PACKAGE_LABELS:
                detection.track_id = -1
        # Never accumulate across a cut, weak registration or missing video.
        if motion is None:
            return [], [d for d in detections if d.label in PACKAGE_LABELS]

        for track in self._tracks.values():
            track.box = _warp_box(track.box, motion)
        self._tracks = {i: t for i, t in self._tracks.items()
                        if now-t.seen_at <= self.config.max_gap_seconds}
        # Use every valid current person box, including small boxes or boxes
        # outside the tracking cap. Tracking filters must not invent absence.
        person_boxes = [d.bbox for d in detections if d.label == "person"
                        and d.bbox is not None and len(d.bbox) == 4
                        and all(math.isfinite(float(v)) for v in d.bbox)
                        and d.bbox[2] > d.bbox[0] and d.bbox[3] > d.bbox[1]]
        # A person may occlude a bag before its detection returns. Clear the
        # episode on every still-valid, motion-warped package track now; a missed
        # bag must not retain an old red latch through that overlap.
        overlap_cleared = set()
        for track in self._tracks.values():
            if (track.label in PACKAGE_LABELS
                    and any(_intersection(track.box, box) > 0. for box in person_boxes)):
                if track.alerted:
                    overlap_cleared.add(track.id)
                track.unattended_since = None
                track.alerted = False
        observed: dict[int, _Track] = {}
        output = []
        eligible = [d for d in detections if d.label in PACKAGE_LABELS or d.label == "person"]
        eligible = [d for d in eligible
                    if d.bbox is not None and len(d.bbox) == 4
                    and all(math.isfinite(float(v)) for v in d.bbox)
                    and min(d.bbox[2]-d.bbox[0], d.bbox[3]-d.bbox[1]) >= self.config.min_box_pixels]
        candidates = sorted(eligible, key=lambda d: d.confidence, reverse=True)[:128]
        confirmed_pairs = sorted(
            ((score, detection.confidence, index, track.id)
             for index, detection in enumerate(candidates) if detection.label in PACKAGE_LABELS
             for track in self._tracks.values() if track.label in PACKAGE_LABELS and track.alerted
             if (score := _iou(track.box, detection.bbox)) >= 0.15), reverse=True)
        reserved, reserved_ids = {}, set()
        for score, _, index, track_id in confirmed_pairs:
            if index not in reserved and track_id not in reserved_ids:
                reserved[index] = (self._tracks[track_id], score)
                reserved_ids.add(track_id)
        for index, detection in enumerate(candidates):
            box = tuple(float(v) for v in detection.bbox)
            choices = []
            for track in self._tracks.values():
                same_family = track.label in PACKAGE_LABELS and detection.label in PACKAGE_LABELS
                if ((track.label != detection.label and not same_family)
                        or track.id in observed or track.id in reserved_ids):
                    continue
                score = _iou(track.box, box)
                choices.append((track, score))
            # A nested tentative fragment must not steal an established alarm identity.
            best, score = reserved.get(index) or max(choices, key=lambda x: x[1], default=(None, 0.))
            if best is None or score < 0.15:
                best = _Track(self._next_id, detection.label, box, detection.confidence, now)
                self._next_id += 1
                self._tracks[best.id] = best
            elif best.seen_at != previous_at:
                # A missed bag breaks confirmation, even if its ID is recovered.
                best.unattended_since = None
            best.box, best.confidence, best.seen_at = box, detection.confidence, now
            best.label = detection.label
            observed[best.id] = best
            if best.label in PACKAGE_LABELS:
                detection.track_id = best.id
                output.append(detection)

        events, statuses = [], []
        for bag in [t for t in observed.values() if t.label in PACKAGE_LABELS]:
            area = (bag.box[2]-bag.box[0])*(bag.box[3]-bag.box[1])
            overlap = max((_intersection(bag.box, box)/area for box in person_boxes), default=0.)
            overlapping = overlap > 0.
            if overlapping:
                if bag.alerted:
                    overlap_cleared.add(bag.id)
                bag.unattended_since = None
                # A new episode may begin after an overlapping person leaves.
                bag.alerted = False
            elif bag.unattended_since is None:
                bag.unattended_since = now
            duration = 0. if bag.unattended_since is None else now-bag.unattended_since
            if (not overlapping and not bag.alerted
                    and duration >= self.config.confirm_seconds):
                bag.alerted = True
                events.append(PackageEvent(bag.id, None, bag.box,
                                           bag.confidence, now, duration, bag.label))
            statuses.append({
                "track_id": bag.id, "owner_id": None, "label": bag.label,
                "person_overlapping": overlapping,
                "state": "overlapping" if overlapping else "alerted" if bag.alerted else "unattended",
                "bbox": list(bag.box), "unattended_seconds": round(duration, 3),
                "person_overlap_ratio": round(overlap, 3),
            })
        for track in self._tracks.values():
            if track.label in PACKAGE_LABELS and track.id not in observed:
                track.unattended_since = None
        self._tracks = dict(sorted(self._tracks.items(), key=lambda x: x[1].seen_at,
                                   reverse=True)[:128])
        self.status = {"state": "observing", "policy": "no_person_overlap", "tracks": statuses,
                       "overlap_cleared_track_ids": sorted(overlap_cleared)}
        return events, output


class CameraMotionEstimator:
    """Sparse background flow; rejects cuts and weak registrations.

    A 2-D homography approximates scene motion. Parallax on nonplanar scenes
    remains a limitation and needs validation on the actual patrol camera.
    """
    def __init__(self):
        self.reset()

    def reset(self):
        self._gray = None
        self._mask = None
        self.status = {"state": "waiting", "inliers": 0}

    def estimate(self, frame: bytes, width: int, height: int,
                 detections: Sequence[Any]) -> np.ndarray | None:
        import cv2
        image = np.frombuffer(frame, dtype=np.uint8).reshape(height, width, 3)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        mask = np.full(gray.shape, 255, np.uint8)
        for d in detections:
            if d.bbox is None:
                continue
            x1, y1, x2, y2 = d.bbox
            pad = 8
            mask[max(0,int(y1)-pad):min(height,int(y2)+pad),
                 max(0,int(x1)-pad):min(width,int(x2)+pad)] = 0
        previous, previous_mask = self._gray, self._mask
        self._gray, self._mask = gray, mask
        self.status = {"state": "motion_unavailable", "inliers": 0}
        if previous is None:
            return None
        points = cv2.goodFeaturesToTrack(previous, maxCorners=300, qualityLevel=0.02,
                                        minDistance=10, mask=previous_mask)
        if points is None or len(points) < 20:
            return None
        targets, valid, _ = cv2.calcOpticalFlowPyrLK(previous, gray, points, None)
        if targets is None:
            return None
        returned, backward_valid, _ = cv2.calcOpticalFlowPyrLK(gray, previous, targets, None)
        if returned is None:
            return None
        ok = valid.reshape(-1).astype(bool) & backward_valid.reshape(-1).astype(bool)
        ok &= np.linalg.norm(returned-points, axis=2).reshape(-1) < 1.5
        src, dst = points.reshape(-1,2)[ok], targets.reshape(-1,2)[ok]
        if len(src) < 20:
            return None
        inside = (dst[:,0] >= 0) & (dst[:,0] < width) & (dst[:,1] >= 0) & (dst[:,1] < height)
        src, dst = src[inside], dst[inside]
        if len(src):
            visible = mask[dst[:,1].astype(int), dst[:,0].astype(int)] > 0
            src, dst = src[visible], dst[visible]
        if len(src) < 20:
            return None
        matrix, inliers = cv2.findHomography(src, dst, cv2.RANSAC, 2.5)
        if matrix is None or not np.isfinite(matrix).all() or inliers is None:
            return None
        good = inliers.reshape(-1).astype(bool)
        support = src[good]
        if len(support) < 16 or good.mean() < 0.65:
            return None
        # Well-spread support avoids estimating camera motion from one small
        # moving patch, or a single distant wall in an otherwise moving scene.
        if np.ptp(support[:,0]) < 0.35*width or np.ptp(support[:,1]) < 0.30*height:
            return None
        corners = np.array([_warp_point(p,matrix) for p in
                            [(0,0),(width,0),(width,height),(0,height)]],np.float32)
        area_ratio = abs(cv2.contourArea(corners))/(width*height)
        if not 0.65 < area_ratio < 1.5 or not cv2.isContourConvex(corners):
            return None
        original = np.array([(0,0),(width,0),(width,height),(0,height)])
        if np.linalg.norm(corners-original,axis=1).max() > 0.35*math.hypot(width,height):
            return None
        self.status = {"state": "registered", "inliers": int(good.sum()),
                       "inlier_ratio": round(float(good.mean()),3)}
        return matrix


class PackageObservationService:
    def __init__(self, config: PackageConfig, width: int, height: int):
        self.engine = PackageEventEngine(config)
        self.motion = CameraMotionEstimator()
        self.width, self.height = width, height

    def reset(self, reason="reset"):
        self.engine.reset(reason)
        self.motion.reset()

    def process_frame(self, frame, detections, now):
        if self.engine._last_at is not None and not 0 < now-self.engine._last_at <= self.engine.config.max_gap_seconds:
            self.reset("video_gap")
        matrix = self.motion.estimate(frame, self.width, self.height, detections)
        return self.engine.update(detections, now, matrix)

    def get_status(self):
        return {**self.engine.status, "motion": self.motion.status}
