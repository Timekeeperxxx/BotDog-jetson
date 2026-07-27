from __future__ import annotations

from backend.pose_detection import (
    PoseEventEngine,
    PoseKeypoint,
    Posture,
    RawPose,
    bbox_iou,
    classify_posture,
)


class _Zone:
    def __init__(self, inside: bool, *, configured: bool = True) -> None:
        self.inside = inside
        self.has_zones = configured

    def is_inside_zone(self, anchor_point: tuple[int, int]) -> bool:
        return self.inside


def _keypoints() -> list[PoseKeypoint]:
    points = [PoseKeypoint(50.0, 20.0, 0.95) for _ in range(17)]
    points[5] = PoseKeypoint(35.0, 60.0, 0.95)
    points[6] = PoseKeypoint(65.0, 60.0, 0.95)
    points[7] = PoseKeypoint(32.0, 90.0, 0.95)
    points[8] = PoseKeypoint(68.0, 90.0, 0.95)
    points[9] = PoseKeypoint(30.0, 115.0, 0.95)
    points[10] = PoseKeypoint(70.0, 115.0, 0.95)
    points[11] = PoseKeypoint(40.0, 110.0, 0.95)
    points[12] = PoseKeypoint(60.0, 110.0, 0.95)
    points[13] = PoseKeypoint(40.0, 150.0, 0.95)
    points[14] = PoseKeypoint(60.0, 150.0, 0.95)
    points[15] = PoseKeypoint(40.0, 195.0, 0.95)
    points[16] = PoseKeypoint(60.0, 195.0, 0.95)
    return points


def _pose(
    *,
    bbox: tuple[int, int, int, int] = (0, 0, 100, 200),
    keypoints: list[PoseKeypoint] | None = None,
) -> RawPose:
    return RawPose(
        bbox=bbox,
        confidence=0.9,
        keypoints=tuple(keypoints or _keypoints()),
    )


def test_classifies_standing_pose() -> None:
    posture, confidence = classify_posture(_pose())

    assert posture is Posture.STANDING
    assert confidence >= 0.7


def test_classifies_lying_from_horizontal_body_axis() -> None:
    points = _keypoints()
    points[5] = PoseKeypoint(35.0, 30.0, 0.95)
    points[6] = PoseKeypoint(35.0, 50.0, 0.95)
    points[11] = PoseKeypoint(115.0, 32.0, 0.95)
    points[12] = PoseKeypoint(115.0, 52.0, 0.95)
    points[13] = PoseKeypoint(155.0, 30.0, 0.95)
    points[14] = PoseKeypoint(155.0, 52.0, 0.95)
    points[15] = PoseKeypoint(205.0, 30.0, 0.95)
    points[16] = PoseKeypoint(205.0, 52.0, 0.95)

    posture, confidence = classify_posture(
        _pose(bbox=(0, 0, 220, 80), keypoints=points)
    )

    assert posture is Posture.LYING
    assert confidence >= 0.62


def test_rejects_posture_when_too_few_keypoints_are_visible() -> None:
    points = [
        PoseKeypoint(point.x, point.y, 0.1)
        for point in _keypoints()
    ]
    points[5] = PoseKeypoint(35.0, 60.0, 0.95)
    points[6] = PoseKeypoint(65.0, 60.0, 0.95)

    posture, confidence = classify_posture(
        _pose(bbox=(0, 0, 220, 80), keypoints=points)
    )

    assert posture is Posture.UNKNOWN
    assert confidence == 0.0


def test_rejects_wide_edge_cropped_person_as_lying() -> None:
    points = [
        PoseKeypoint(point.x, point.y, 0.1)
        for point in _keypoints()
    ]
    for index in (7, 9, 10, 11, 12):
        original = _keypoints()[index]
        points[index] = PoseKeypoint(original.x, original.y, 0.95)

    posture, _confidence = classify_posture(
        _pose(bbox=(300, 160, 638, 355), keypoints=points)
    )

    assert posture is Posture.UNKNOWN


def test_rejects_forward_leaning_person_as_lying() -> None:
    posture, _confidence = classify_posture(_pose(bbox=(20, 40, 310, 245)))

    assert posture is not Posture.LYING


def test_classifies_crouching_from_bent_knees() -> None:
    points = _keypoints()
    points[11] = PoseKeypoint(40.0, 100.0, 0.95)
    points[13] = PoseKeypoint(18.0, 128.0, 0.95)
    points[15] = PoseKeypoint(55.0, 134.0, 0.95)

    posture, confidence = classify_posture(_pose(keypoints=points))

    assert posture is Posture.CROUCHING
    assert confidence >= 0.55


def test_classifies_climbing_only_with_raised_arm_and_leg() -> None:
    points = _keypoints()
    points[9] = PoseKeypoint(30.0, 35.0, 0.95)
    points[13] = PoseKeypoint(38.0, 118.0, 0.95)

    posture, confidence = classify_posture(_pose(keypoints=points))

    assert posture is Posture.CLIMBING
    assert confidence >= 0.7


def test_climbing_event_requires_stable_hits_but_not_zone() -> None:
    points = _keypoints()
    points[9] = PoseKeypoint(30.0, 35.0, 0.95)
    points[13] = PoseKeypoint(38.0, 118.0, 0.95)
    climbing_pose = _pose(keypoints=points)
    engine = PoseEventEngine(stable_hits=3, event_cooldown_seconds=30.0)

    for timestamp in (0.0, 0.2):
        _observations, events = engine.update(
            [climbing_pose],
            zone_gate=_Zone(True),
            now=timestamp,
        )
        assert events == []

    observations, events = engine.update(
        [climbing_pose],
        zone_gate=_Zone(True),
        now=0.4,
    )

    assert observations[0].track_id == 1
    assert [event.event_type for event in events] == ["POSE_CLIMBING_SUSPECTED"]

    outside_engine = PoseEventEngine(stable_hits=1)
    _observations, outside_events = outside_engine.update(
        [climbing_pose],
        zone_gate=_Zone(False),
        now=0.0,
    )
    assert [event.event_type for event in outside_events] == [
        "POSE_CLIMBING_SUSPECTED"
    ]


def test_classifies_hanging_with_both_arms_overhead_as_climbing() -> None:
    points = _keypoints()
    points[9] = PoseKeypoint(30.0, 20.0, 0.95)
    points[10] = PoseKeypoint(70.0, 20.0, 0.95)
    points[7] = PoseKeypoint(32.0, 40.0, 0.95)
    points[8] = PoseKeypoint(68.0, 40.0, 0.95)

    posture, confidence = classify_posture(_pose(keypoints=points))

    assert posture is Posture.CLIMBING
    assert confidence >= 0.6


def test_climbing_event_survives_single_frame_flicker() -> None:
    points = _keypoints()
    points[9] = PoseKeypoint(30.0, 35.0, 0.95)
    points[13] = PoseKeypoint(38.0, 118.0, 0.95)
    climbing_pose = _pose(keypoints=points)
    standing_pose = _pose()
    engine = PoseEventEngine(stable_hits=3, event_cooldown_seconds=30.0)

    all_events = []
    for timestamp, pose in (
        (0.0, climbing_pose),
        (0.2, climbing_pose),
        (0.4, standing_pose),
        (0.6, climbing_pose),
    ):
        _observations, events = engine.update(
            [pose],
            zone_gate=_Zone(True),
            now=timestamp,
        )
        all_events.extend(events)

    assert [event.event_type for event in all_events] == ["POSE_CLIMBING_SUSPECTED"]


def _shifted_pose(dy: float, *, raised_wrist: bool) -> RawPose:
    points = _keypoints()
    if raised_wrist:
        points[9] = PoseKeypoint(30.0, 40.0, 0.95)
    shifted = [
        PoseKeypoint(point.x, point.y - dy, point.confidence) for point in points
    ]
    return _pose(
        bbox=(0, int(-dy), 100, int(200 - dy)),
        keypoints=shifted,
    )


def test_rising_feet_with_raised_wrist_triggers_climb_motion_event() -> None:
    engine = PoseEventEngine(stable_hits=99, event_cooldown_seconds=30.0)

    all_events = []
    for index in range(6):
        timestamp = index * 0.4
        _observations, events = engine.update(
            [_shifted_pose(index * 12.0, raised_wrist=True)],
            zone_gate=_Zone(True),
            now=timestamp,
        )
        all_events.extend(events)

    assert "POSE_CLIMBING_SUSPECTED" in [event.event_type for event in all_events]


def test_rising_feet_without_raised_wrist_stays_silent() -> None:
    engine = PoseEventEngine(stable_hits=99, event_cooldown_seconds=30.0)

    all_events = []
    for index in range(6):
        _observations, events = engine.update(
            [_shifted_pose(index * 12.0, raised_wrist=False)],
            zone_gate=_Zone(True),
            now=index * 0.4,
        )
        all_events.extend(events)

    assert all_events == []


def test_bbox_scale_change_suppresses_climb_motion_event() -> None:
    engine = PoseEventEngine(stable_hits=99, event_cooldown_seconds=30.0)

    all_events = []
    for index in range(6):
        dy = index * 12.0
        scale = 1.0 - index * 0.12
        points = _keypoints()
        points[9] = PoseKeypoint(30.0, 40.0, 0.95)
        shifted = [
            PoseKeypoint(point.x * scale, (point.y - dy) * scale, point.confidence)
            for point in points
        ]
        pose = _pose(
            bbox=(0, int(-dy * scale), int(100 * scale), int((200 - dy) * scale)),
            keypoints=shifted,
        )
        _observations, events = engine.update(
            [pose],
            zone_gate=_Zone(True),
            now=index * 0.4,
        )
        all_events.extend(events)

    assert all_events == []


def test_zone_events_stay_disabled_until_a_zone_is_configured() -> None:
    points = _keypoints()
    points[9] = PoseKeypoint(30.0, 35.0, 0.95)
    points[13] = PoseKeypoint(38.0, 118.0, 0.95)
    engine = PoseEventEngine(stable_hits=1, loiter_seconds=0.1)

    observation, events = engine.update(
        [_pose(keypoints=points)],
        zone_gate=_Zone(True, configured=False),
        now=1.0,
    )

    assert observation[0].inside_zone is False
    assert [event.event_type for event in events] == [
        "POSE_CLIMBING_SUSPECTED"
    ]


def test_loiter_event_uses_continuous_zone_dwell_and_cooldown() -> None:
    engine = PoseEventEngine(
        stable_hits=1,
        loiter_seconds=5.0,
        event_cooldown_seconds=10.0,
        track_ttl_seconds=10.0,
    )

    _observations, events = engine.update([_pose()], zone_gate=_Zone(True), now=0.0)
    assert events == []

    observations, events = engine.update([_pose()], zone_gate=_Zone(True), now=5.1)
    assert observations[0].dwell_seconds == 5.1
    assert [event.event_type for event in events] == ["POSE_LOITERING"]

    _observations, events = engine.update([_pose()], zone_gate=_Zone(True), now=7.0)
    assert events == []


def test_iou_tracker_keeps_identity_for_moving_person() -> None:
    engine = PoseEventEngine(stable_hits=1)
    first, _events = engine.update([_pose()], now=0.0)
    moved, _events = engine.update([_pose(bbox=(5, 4, 105, 204))], now=0.2)

    assert first[0].track_id == moved[0].track_id
    assert bbox_iou((0, 0, 100, 100), (50, 50, 150, 150)) > 0
