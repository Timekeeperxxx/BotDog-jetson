"""人体姿态推理、轻量跟踪与时序事件判定。

第一阶段只使用 COCO 17 点人体骨架，不在单帧上直接宣称发生了复杂行为。
攀爬、蹲伏、倒地和徘徊事件都需要连续帧确认。攀爬和倒地属于全画面安全
事件；重点区只用于限制持续蹲伏和徘徊，减少普通活动造成的误报。
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol


class ZoneGate(Protocol):
    def is_inside_zone(self, anchor_point: tuple[int, int]) -> bool: ...


class Posture(str, Enum):
    UNKNOWN = "unknown"
    STANDING = "standing"
    CROUCHING = "crouching"
    LYING = "lying"
    CLIMBING = "climbing_suspected"


@dataclass(frozen=True)
class PoseKeypoint:
    x: float
    y: float
    confidence: float


@dataclass(frozen=True)
class RawPose:
    bbox: tuple[int, int, int, int]
    confidence: float
    keypoints: tuple[PoseKeypoint, ...]


@dataclass(frozen=True)
class PoseObservation:
    track_id: int
    bbox: tuple[int, int, int, int]
    confidence: float
    keypoints: tuple[PoseKeypoint, ...]
    posture: Posture
    posture_confidence: float
    inside_zone: bool
    dwell_seconds: float

    def as_overlay(self) -> dict[str, object]:
        return {
            "track_id": self.track_id,
            "bbox": list(self.bbox),
            "confidence": round(self.confidence, 4),
            "posture": self.posture.value,
            "posture_confidence": round(self.posture_confidence, 4),
            "inside_zone": self.inside_zone,
            "dwell_seconds": round(self.dwell_seconds, 1),
            "keypoints": [
                [round(point.x, 1), round(point.y, 1), round(point.confidence, 4)]
                for point in self.keypoints
            ],
        }


@dataclass(frozen=True)
class PoseEvent:
    event_type: str
    track_id: int
    confidence: float
    bbox: tuple[int, int, int, int]
    posture: Posture
    duration_seconds: float


@dataclass
class _TrackState:
    track_id: int
    bbox: tuple[int, int, int, int]
    first_seen_at: float
    last_seen_at: float
    inside_since: float | None = None
    posture: Posture = Posture.UNKNOWN
    posture_since: float = 0.0
    # 最近若干帧的 (时间, 姿态) 采样，用滑动窗口投票替代连续帧确认，
    # 避免攀爬等剧烈动作在帧间跳变时确认计数被反复清零。
    posture_window: deque[tuple[float, Posture]] = field(default_factory=deque)
    # 各姿态在窗口内首次出现的时间；只要窗口内仍有该姿态样本就不重置，
    # 用于计算容忍闪断的持续时长。
    posture_present_since: dict[Posture, float] = field(default_factory=dict)
    # 最近的 (时间, 脚部y, 框高, 是否有手高于肩) 采样，用于攀升轨迹判定。
    motion_history: deque[tuple[float, float, float, bool]] = field(
        default_factory=deque
    )
    last_events: dict[str, float] = field(default_factory=dict)


COCO_KEYPOINT_NAMES = (
    "nose",
    "left_eye",
    "right_eye",
    "left_ear",
    "right_ear",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
)

LEFT_SHOULDER = 5
RIGHT_SHOULDER = 6
LEFT_ELBOW = 7
RIGHT_ELBOW = 8
LEFT_WRIST = 9
RIGHT_WRIST = 10
LEFT_HIP = 11
RIGHT_HIP = 12
LEFT_KNEE = 13
RIGHT_KNEE = 14
LEFT_ANKLE = 15
RIGHT_ANKLE = 16


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _point(
    keypoints: tuple[PoseKeypoint, ...],
    index: int,
    min_confidence: float,
) -> PoseKeypoint | None:
    if index >= len(keypoints):
        return None
    point = keypoints[index]
    return point if point.confidence >= min_confidence else None


def _midpoint(
    keypoints: tuple[PoseKeypoint, ...],
    left_index: int,
    right_index: int,
    min_confidence: float,
) -> PoseKeypoint | None:
    left = _point(keypoints, left_index, min_confidence)
    right = _point(keypoints, right_index, min_confidence)
    if left is None or right is None:
        return None
    return PoseKeypoint(
        x=(left.x + right.x) / 2.0,
        y=(left.y + right.y) / 2.0,
        confidence=min(left.confidence, right.confidence),
    )


def _joint_angle(a: PoseKeypoint, b: PoseKeypoint, c: PoseKeypoint) -> float:
    """Return angle ABC in degrees."""
    ab = (a.x - b.x, a.y - b.y)
    cb = (c.x - b.x, c.y - b.y)
    denominator = math.hypot(*ab) * math.hypot(*cb)
    if denominator <= 1e-6:
        return 180.0
    cosine = _clamp((ab[0] * cb[0] + ab[1] * cb[1]) / denominator, -1.0, 1.0)
    return math.degrees(math.acos(cosine))


def count_raised_wrists(
    keypoints: tuple[PoseKeypoint, ...],
    height: float,
    keypoint_confidence: float,
) -> int:
    """Count wrists visibly above their shoulder line."""
    raised = 0
    for wrist_index, shoulder_index in (
        (LEFT_WRIST, LEFT_SHOULDER),
        (RIGHT_WRIST, RIGHT_SHOULDER),
    ):
        wrist = _point(keypoints, wrist_index, keypoint_confidence)
        shoulder = _point(keypoints, shoulder_index, keypoint_confidence)
        if wrist is not None and shoulder is not None and wrist.y < shoulder.y - height * 0.04:
            raised += 1
    return raised


def classify_posture(
    pose: RawPose,
    *,
    keypoint_confidence: float = 0.35,
    min_visible_keypoints: int = 5,
) -> tuple[Posture, float]:
    """Classify a single skeleton into a conservative coarse posture."""
    visible_keypoints = sum(
        point.confidence >= keypoint_confidence for point in pose.keypoints
    )
    if visible_keypoints < max(1, min_visible_keypoints):
        return Posture.UNKNOWN, 0.0

    x1, y1, x2, y2 = pose.bbox
    width = max(1.0, float(x2 - x1))
    height = max(1.0, float(y2 - y1))
    aspect_ratio = width / height

    shoulders = _midpoint(
        pose.keypoints,
        LEFT_SHOULDER,
        RIGHT_SHOULDER,
        keypoint_confidence,
    )
    hips = _midpoint(
        pose.keypoints,
        LEFT_HIP,
        RIGHT_HIP,
        keypoint_confidence,
    )

    torso_horizontal_score = 0.0
    if shoulders is not None and hips is not None:
        torso_dx = abs(hips.x - shoulders.x)
        torso_dy = abs(hips.y - shoulders.y)
        torso_horizontal_score = _clamp((torso_dx - torso_dy * 0.65) / (height * 0.25))

    lying_score = max(
        _clamp((aspect_ratio - 0.95) / 0.55),
        torso_horizontal_score,
    )
    visible_lower_body = sum(
        _point(pose.keypoints, index, keypoint_confidence) is not None
        for index in (LEFT_KNEE, RIGHT_KNEE, LEFT_ANKLE, RIGHT_ANKLE)
    )
    # A wide box alone is not enough evidence of lying down: people leaning over
    # a desk or cut off by the image edge also produce short, wide boxes.
    # Require an observable horizontal torso plus lower-body evidence.
    if (
        shoulders is not None
        and hips is not None
        and visible_lower_body >= 2
        and aspect_ratio >= 1.05
        and torso_horizontal_score >= 0.45
        and lying_score >= 0.62
    ):
        return Posture.LYING, max(0.62, lying_score)

    raised_wrists = count_raised_wrists(
        pose.keypoints,
        height,
        keypoint_confidence,
    )

    raised_legs = 0
    for knee_index, hip_index, ankle_index in (
        (LEFT_KNEE, LEFT_HIP, LEFT_ANKLE),
        (RIGHT_KNEE, RIGHT_HIP, RIGHT_ANKLE),
    ):
        knee = _point(pose.keypoints, knee_index, keypoint_confidence)
        hip = _point(pose.keypoints, hip_index, keypoint_confidence)
        ankle = _point(pose.keypoints, ankle_index, keypoint_confidence)
        if knee is not None and hip is not None and knee.y <= hip.y + height * 0.12:
            raised_legs += 1
        elif ankle is not None and knee is not None and ankle.y < knee.y - height * 0.08:
            raised_legs += 1

    if raised_wrists >= 1 and raised_legs >= 1:
        climb_score = _clamp(0.58 + 0.12 * raised_wrists + 0.12 * raised_legs)
        return Posture.CLIMBING, climb_score

    # 吊挂阶段：双腕过顶、双肘高于肩，此时双腿通常是伸直下垂的，
    # 上面"手+腿同时抬起"的规则覆盖不到。
    overhead_wrists = 0
    for wrist_index, elbow_index, shoulder_index in (
        (LEFT_WRIST, LEFT_ELBOW, LEFT_SHOULDER),
        (RIGHT_WRIST, RIGHT_ELBOW, RIGHT_SHOULDER),
    ):
        wrist = _point(pose.keypoints, wrist_index, keypoint_confidence)
        elbow = _point(pose.keypoints, elbow_index, keypoint_confidence)
        shoulder = _point(pose.keypoints, shoulder_index, keypoint_confidence)
        if (
            wrist is not None
            and elbow is not None
            and shoulder is not None
            and wrist.y < elbow.y
            and elbow.y < shoulder.y - height * 0.02
            and wrist.y < shoulder.y - height * 0.12
        ):
            overhead_wrists += 1
    if overhead_wrists >= 2:
        return Posture.CLIMBING, 0.62

    leg_angles: list[float] = []
    for hip_index, knee_index, ankle_index in (
        (LEFT_HIP, LEFT_KNEE, LEFT_ANKLE),
        (RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE),
    ):
        hip = _point(pose.keypoints, hip_index, keypoint_confidence)
        knee = _point(pose.keypoints, knee_index, keypoint_confidence)
        ankle = _point(pose.keypoints, ankle_index, keypoint_confidence)
        if hip is not None and knee is not None and ankle is not None:
            leg_angles.append(_joint_angle(hip, knee, ankle))

    if leg_angles:
        most_bent_angle = min(leg_angles)
        crouch_score = _clamp((145.0 - most_bent_angle) / 65.0)
        if crouch_score >= 0.38:
            return Posture.CROUCHING, max(0.55, crouch_score)

    if shoulders is not None and hips is not None and aspect_ratio < 0.95:
        return Posture.STANDING, 0.7
    return Posture.UNKNOWN, 0.35


def bbox_iou(
    first: tuple[int, int, int, int],
    second: tuple[int, int, int, int],
) -> float:
    ax1, ay1, ax2, ay2 = first
    bx1, by1, bx2, by2 = second
    intersection_w = max(0, min(ax2, bx2) - max(ax1, bx1))
    intersection_h = max(0, min(ay2, by2) - max(ay1, by1))
    intersection = intersection_w * intersection_h
    if intersection <= 0:
        return 0.0
    first_area = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    second_area = max(0, bx2 - bx1) * max(0, by2 - by1)
    union = first_area + second_area - intersection
    return intersection / union if union > 0 else 0.0


def _bbox_center_distance(
    first: tuple[int, int, int, int],
    second: tuple[int, int, int, int],
) -> float:
    first_x = (first[0] + first[2]) / 2.0
    first_y = (first[1] + first[3]) / 2.0
    second_x = (second[0] + second[2]) / 2.0
    second_y = (second[1] + second[3]) / 2.0
    return math.hypot(first_x - second_x, first_y - second_y)


class PoseEventEngine:
    """Assign lightweight track IDs and turn stable posture/trajectory into events."""

    def __init__(
        self,
        *,
        keypoint_confidence: float = 0.35,
        min_visible_keypoints: int = 5,
        stable_hits: int = 3,
        crouch_seconds: float = 4.0,
        loiter_seconds: float = 20.0,
        event_cooldown_seconds: float = 15.0,
        track_ttl_seconds: float = 3.0,
        match_iou_threshold: float = 0.25,
        posture_window_frames: int | None = None,
        climb_rise_seconds: float = 1.6,
        climb_rise_ratio: float = 0.22,
    ) -> None:
        self._keypoint_confidence = max(0.0, min(1.0, keypoint_confidence))
        self._min_visible_keypoints = max(1, min_visible_keypoints)
        self._stable_hits = max(1, stable_hits)
        self._crouch_seconds = max(0.0, crouch_seconds)
        self._loiter_seconds = max(0.0, loiter_seconds)
        self._event_cooldown_seconds = max(0.0, event_cooldown_seconds)
        self._track_ttl_seconds = max(0.1, track_ttl_seconds)
        self._match_iou_threshold = max(0.0, min(1.0, match_iou_threshold))
        # 投票窗口略大于确认帧数：stable_hits 票即确认，多出的名额
        # 用来吸收单帧误分类。
        self._posture_window_frames = (
            max(2, posture_window_frames)
            if posture_window_frames is not None
            else max(self._stable_hits + 2, self._stable_hits * 2)
        )
        self._climb_rise_seconds = max(0.2, climb_rise_seconds)
        self._climb_rise_ratio = max(0.05, climb_rise_ratio)
        self._tracks: dict[int, _TrackState] = {}
        self._next_track_id = 1

    def update(
        self,
        poses: list[RawPose],
        *,
        zone_gate: ZoneGate | None = None,
        now: float | None = None,
    ) -> tuple[list[PoseObservation], list[PoseEvent]]:
        timestamp = time.monotonic() if now is None else now
        self._drop_stale_tracks(timestamp)
        assignments = self._assign_tracks(poses)
        observations: list[PoseObservation] = []
        events: list[PoseEvent] = []

        for pose_index, pose in enumerate(poses):
            track_id = assignments[pose_index]
            state = self._tracks.get(track_id)
            if state is None:
                state = _TrackState(
                    track_id=track_id,
                    bbox=pose.bbox,
                    first_seen_at=timestamp,
                    last_seen_at=timestamp,
                    posture_since=timestamp,
                )
                self._tracks[track_id] = state

            posture, posture_confidence = classify_posture(
                pose,
                keypoint_confidence=self._keypoint_confidence,
                min_visible_keypoints=self._min_visible_keypoints,
            )
            anchor = ((pose.bbox[0] + pose.bbox[2]) // 2, pose.bbox[3])
            zone_is_configured = (
                bool(getattr(zone_gate, "has_zones", True))
                if zone_gate is not None
                else True
            )
            inside_zone = (
                zone_is_configured and zone_gate.is_inside_zone(anchor)
                if zone_gate is not None
                else True
            )

            state.bbox = pose.bbox
            state.last_seen_at = timestamp
            if inside_zone:
                if state.inside_since is None:
                    state.inside_since = timestamp
            else:
                state.inside_since = None

            if posture != state.posture:
                state.posture = posture
                state.posture_since = timestamp

            state.posture_window.append((timestamp, posture))
            while len(state.posture_window) > self._posture_window_frames:
                state.posture_window.popleft()
            state.posture_present_since.setdefault(posture, timestamp)
            present = {p for _, p in state.posture_window}
            for stale_posture in [
                p for p in state.posture_present_since if p not in present
            ]:
                state.posture_present_since.pop(stale_posture, None)

            height = max(1.0, float(pose.bbox[3] - pose.bbox[1]))
            ankles = _midpoint(
                pose.keypoints,
                LEFT_ANKLE,
                RIGHT_ANKLE,
                self._keypoint_confidence,
            )
            feet_y = ankles.y if ankles is not None else float(pose.bbox[3])
            wrist_raised = (
                count_raised_wrists(
                    pose.keypoints,
                    height,
                    self._keypoint_confidence,
                )
                >= 1
            )
            state.motion_history.append((timestamp, feet_y, height, wrist_raised))
            while (
                state.motion_history
                and timestamp - state.motion_history[0][0]
                > self._climb_rise_seconds * 1.5
            ):
                state.motion_history.popleft()

            dwell_seconds = (
                max(0.0, timestamp - state.inside_since)
                if state.inside_since is not None
                else 0.0
            )
            observation = PoseObservation(
                track_id=track_id,
                bbox=pose.bbox,
                confidence=pose.confidence,
                keypoints=pose.keypoints,
                posture=posture,
                posture_confidence=posture_confidence,
                inside_zone=inside_zone,
                dwell_seconds=dwell_seconds,
            )
            observations.append(observation)
            events.extend(self._events_for_observation(observation, state, timestamp))

        return observations, events

    def _assign_tracks(self, poses: list[RawPose]) -> dict[int, int]:
        assignments: dict[int, int] = {}
        available_track_ids = set(self._tracks)
        candidates: list[tuple[float, int, int]] = []
        for pose_index, pose in enumerate(poses):
            for track_id in available_track_ids:
                previous_bbox = self._tracks[track_id].bbox
                iou = bbox_iou(pose.bbox, previous_bbox)
                center_distance = _bbox_center_distance(pose.bbox, previous_bbox)
                max_extent = max(
                    pose.bbox[2] - pose.bbox[0],
                    pose.bbox[3] - pose.bbox[1],
                    previous_bbox[2] - previous_bbox[0],
                    previous_bbox[3] - previous_bbox[1],
                    1,
                )
                center_gate = max(48.0, max_extent * 0.55)
                if iou >= self._match_iou_threshold or center_distance <= center_gate:
                    center_score = max(0.0, 1.0 - center_distance / center_gate)
                    candidates.append(
                        (iou * 3.0 + center_score, pose_index, track_id)
                    )

        used_poses: set[int] = set()
        used_tracks: set[int] = set()
        for _score, pose_index, track_id in sorted(candidates, reverse=True):
            if pose_index in used_poses or track_id in used_tracks:
                continue
            assignments[pose_index] = track_id
            used_poses.add(pose_index)
            used_tracks.add(track_id)

        for pose_index in range(len(poses)):
            if pose_index in assignments:
                continue
            assignments[pose_index] = self._next_track_id
            self._next_track_id += 1
        return assignments

    def _events_for_observation(
        self,
        observation: PoseObservation,
        state: _TrackState,
        now: float,
    ) -> list[PoseEvent]:
        event_specs: list[tuple[str, float, float]] = []
        window_hits = sum(
            1 for _, posture in state.posture_window if posture is observation.posture
        )
        posture_confirmed = window_hits >= self._stable_hits
        posture_duration = max(
            0.0,
            now - state.posture_present_since.get(observation.posture, now),
        )

        climbing_pose_confirmed = (
            observation.posture is Posture.CLIMBING and posture_confirmed
        )
        climb_motion, climb_motion_confidence = self._detect_climb_motion(state)
        if climbing_pose_confirmed or climb_motion:
            confidence = max(
                observation.posture_confidence if climbing_pose_confirmed else 0.0,
                climb_motion_confidence,
            )
            duration = (
                posture_duration
                if climbing_pose_confirmed
                else max(0.0, now - state.motion_history[0][0])
            )
            event_specs.append(("POSE_CLIMBING_SUSPECTED", confidence, duration))

        if observation.posture is Posture.LYING and posture_confirmed:
            event_specs.append(
                ("POSE_LYING", observation.posture_confidence, posture_duration)
            )

        if (
            observation.posture is Posture.CROUCHING
            and observation.inside_zone
            and posture_confirmed
            and posture_duration >= self._crouch_seconds
        ):
            event_specs.append(
                ("POSE_CROUCHING", observation.posture_confidence, posture_duration)
            )

        if (
            observation.inside_zone
            and observation.dwell_seconds >= self._loiter_seconds
        ):
            dwell_confidence = _clamp(
                0.65 + 0.3 * observation.dwell_seconds / max(self._loiter_seconds, 1.0)
            )
            event_specs.append(
                ("POSE_LOITERING", dwell_confidence, observation.dwell_seconds)
            )

        events: list[PoseEvent] = []
        for event_type, confidence, duration in event_specs:
            last_event_at = state.last_events.get(event_type)
            if (
                last_event_at is not None
                and now - last_event_at < self._event_cooldown_seconds
            ):
                continue
            state.last_events[event_type] = now
            events.append(
                PoseEvent(
                    event_type=event_type,
                    track_id=observation.track_id,
                    confidence=_clamp(confidence),
                    bbox=observation.bbox,
                    posture=observation.posture,
                    duration_seconds=duration,
                )
            )
        return events

    def _detect_climb_motion(self, state: _TrackState) -> tuple[bool, float]:
        """攀升轨迹判定：脚部在短时间内相对身高持续升高且期间有手高于肩。

        静态姿态规则覆盖不到的攀爬阶段（引体上拉、翻越中）在图像上表现为
        脚部 y 坐标持续减小；要求框高尺度基本不变，排除机器狗自身前后
        移动导致的框位置变化。
        """
        history = state.motion_history
        if len(history) < 3:
            return False, 0.0
        raised_frames = sum(1 for _, _, _, raised in history if raised)
        if raised_frames < 2:
            return False, 0.0
        base_time, base_feet_y, base_height, _ = history[0]
        newest_time, newest_feet_y, newest_height, _ = history[-1]
        if newest_time - base_time < self._climb_rise_seconds * 0.6:
            return False, 0.0
        scale = newest_height / max(1.0, base_height)
        if not 0.75 <= scale <= 1.35:
            return False, 0.0
        mean_height = max(1.0, (base_height + newest_height) / 2.0)
        rise_ratio = (base_feet_y - newest_feet_y) / mean_height
        if rise_ratio < self._climb_rise_ratio:
            return False, 0.0
        return True, _clamp(0.55 + 0.5 * rise_ratio)

    def _drop_stale_tracks(self, now: float) -> None:
        stale_ids = [
            track_id
            for track_id, state in self._tracks.items()
            if now - state.last_seen_at > self._track_ttl_seconds
        ]
        for track_id in stale_ids:
            self._tracks.pop(track_id, None)


class UltralyticsPoseDetector:
    """Ultralytics pose model adapter returning framework-neutral data."""

    def __init__(
        self,
        *,
        model_path: str,
        device: str,
        confidence: float,
        inference_imgsz: int,
        frame_width: int,
        frame_height: int,
    ) -> None:
        if not Path(model_path).is_file():
            raise FileNotFoundError(f"姿态模型不存在：{model_path}")

        import numpy as np
        import torch
        from ultralytics import YOLO

        self._np = np
        self._frame_width = frame_width
        self._frame_height = frame_height
        self._confidence = max(0.0, min(1.0, confidence))
        self._inference_imgsz = max(160, int(inference_imgsz))
        self._device = (
            "cuda" if device == "auto" and torch.cuda.is_available()
            else "cpu" if device == "auto"
            else device
        )
        self._model = YOLO(model_path, task="pose")

    @property
    def device(self) -> str:
        return self._device

    def detect(self, frame_bytes: bytes) -> list[RawPose]:
        frame = self._np.frombuffer(frame_bytes, dtype=self._np.uint8)
        frame = frame.reshape((self._frame_height, self._frame_width, 3))
        results = self._model.predict(
            frame,
            conf=self._confidence,
            imgsz=self._inference_imgsz,
            device=self._device,
            verbose=False,
        )
        if not results:
            return []

        result = results[0]
        if result.keypoints is None or result.boxes is None:
            return []

        keypoint_rows = result.keypoints.data.detach().cpu().tolist()
        box_rows = result.boxes.xyxy.detach().cpu().tolist()
        confidence_rows = result.boxes.conf.detach().cpu().tolist()
        poses: list[RawPose] = []
        for bbox_values, detection_confidence, keypoint_values in zip(
            box_rows,
            confidence_rows,
            keypoint_rows,
        ):
            bbox = tuple(int(round(value)) for value in bbox_values)
            if len(bbox) != 4:
                continue
            keypoints = tuple(
                PoseKeypoint(
                    x=float(values[0]),
                    y=float(values[1]),
                    confidence=float(values[2]) if len(values) >= 3 else 1.0,
                )
                for values in keypoint_values
            )
            poses.append(
                RawPose(
                    bbox=(bbox[0], bbox[1], bbox[2], bbox[3]),
                    confidence=float(detection_confidence),
                    keypoints=keypoints,
                )
            )
        return poses
