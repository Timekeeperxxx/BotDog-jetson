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


def test_loitering_works_without_configured_zones() -> None:
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
    _, events = engine.update(
        [_pose(keypoints=points)],
        zone_gate=_Zone(True, configured=False),
        now=1.2,
    )
    assert "POSE_LOITERING" in [event.event_type for event in events]


def test_loiter_event_uses_continuous_visibility_and_cooldown() -> None:
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


def test_full_frame_loitering_resets_on_missing_person():
    for zone in (_Zone(False), _Zone(True, configured=False)):
        engine = PoseEventEngine(stable_hits=1)
        for t in (0, 1, 2, 3, 4, 4.9):
            _, events = engine.update([_pose()], zone_gate=zone, now=t)
            assert not events
        observations, events = engine.update([_pose()], zone_gate=zone, now=5)
        track_id = observations[0].track_id
        assert [(e.event_type, e.duration_seconds) for e in events] == [("POSE_LOITERING", 5)]
        engine.update([], zone_gate=zone, now=5.1)
        observations, events = engine.update([_pose()], zone_gate=zone, now=5.2)
        assert observations[0].track_id == track_id
        assert observations[0].dwell_seconds == 0
        assert not events
        for t in (6, 7, 8, 9, 10.1):
            _, events = engine.update([_pose()], zone_gate=zone, now=t)
            assert not events
        _, events = engine.update([_pose()], zone_gate=zone, now=10.3)
        assert [e.event_type for e in events] == ["POSE_LOITERING"]
        assert abs(events[0].duration_seconds - 5.1) < 1e-6


def test_full_frame_crouching_resets_on_posture_interruption_or_absence():
    points = _keypoints()
    points[11] = PoseKeypoint(40.0, 100.0, 0.95)
    points[13] = PoseKeypoint(18.0, 128.0, 0.95)
    points[15] = PoseKeypoint(55.0, 134.0, 0.95)
    crouch = _pose(keypoints=points)
    for interruption in ([], [_pose()]):
        engine = PoseEventEngine(stable_hits=1, loiter_seconds=100)
        def update(poses, t):
            return engine.update(poses, zone_gate=_Zone(False), now=t)[1]
        for t in (0, 1, 2, 2.9):
            assert not update([crouch], t)
        events = update([crouch], 3)
        assert [(e.event_type, e.duration_seconds) for e in events] == [("POSE_CROUCHING", 3)]
        assert not update(interruption, 3.1)
        for t in (3.2, 4, 5, 6.1):
            assert not update([crouch], t)
        events = update([crouch], 6.3)
        assert [e.event_type for e in events] == ["POSE_CROUCHING"]
        assert abs(events[0].duration_seconds - 3.1) < 1e-6


def test_iou_tracker_keeps_identity_for_moving_person() -> None:
    engine = PoseEventEngine(stable_hits=1)
    first, _events = engine.update([_pose()], now=0.0)
    moved, _events = engine.update([_pose(bbox=(5, 4, 105, 204))], now=0.2)

    assert first[0].track_id == moved[0].track_id
    assert bbox_iou((0, 0, 100, 100), (50, 50, 150, 150)) > 0


def _chest_pose(step, *, mode="both", translate=0.0, scale=1.0):
    points = _keypoints()
    shift = 12.0 * (step % 2)
    points[9] = PoseKeypoint(30 + shift, 80, .95)
    points[10] = PoseKeypoint(70 - shift if mode != "one" else 70, 80, .95)
    if mode == "still":
        points[9] = PoseKeypoint(30, 80, .95)
        points[10] = PoseKeypoint(70, 80, .95)
    if mode == "low":
        points[9] = PoseKeypoint(30 + shift, 120, .95)
        points[10] = PoseKeypoint(70 - shift, 120, .95)
    if mode == "missing":
        points[10] = PoseKeypoint(70, 80, .1)
    if mode == "nan":
        points[10] = PoseKeypoint(float("nan"), 80, .95)
    points = [PoseKeypoint(p.x * scale + translate, p.y * scale + translate, p.confidence)
              for p in points]
    return _pose(keypoints=points)


def _damage_events(engine, pose, now):
    _, events = engine.update([pose], now=now)
    return [e for e in events if e.event_type == "POSE_DAMAGE_SUSPECTED"]


def test_chest_motion_emits_shared_event_under_two_seconds_and_cools_down():
    engine = PoseEventEngine()
    hits = []
    for i in range(16):
        hits.extend(_damage_events(engine, _chest_pose(i, translate=i * 2, scale=1 + i * .01), i * .2))
    assert len(hits) == 1
    assert .8 <= hits[0].duration_seconds < 2


def test_chest_motion_rejects_one_hand_low_hands_static_body_and_invalid_points():
    for mode in ("one", "low", "still", "missing", "nan"):
        engine = PoseEventEngine()
        for i in range(16):
            assert not _damage_events(engine, _chest_pose(i, mode=mode, translate=i * 2, scale=1 + i * .01), i * .2)


def test_chest_motion_resets_after_missing_pose_keypoints_or_time_gap():
    for mode in ("lost", "missing", "gap"):
        engine = PoseEventEngine(event_cooldown_seconds=0)
        for i in range(4):
            assert not _damage_events(engine, _chest_pose(i), i * .2)
        restart = 1.0
        if mode == "lost":
            engine.update([], now=.8)
        elif mode == "missing":
            assert not _damage_events(engine, _chest_pose(0, mode="missing"), .8)
        else:
            restart = 2.0
        for i in range(4):
            assert not _damage_events(engine, _chest_pose(i), restart + i * .2)
        assert _damage_events(engine, _chest_pose(4), restart + .8)


def test_chest_motion_does_not_combine_hands_from_different_people():
    engine = PoseEventEngine()
    for i in range(10):
        a = _chest_pose(i, mode="one")
        b = _chest_pose(i, mode="one", translate=300)
        b = RawPose((300, 300, 400, 500), b.confidence, b.keypoints)
        _, events = engine.update([a, b], now=i * .2)
        assert not any(e.event_type == "POSE_DAMAGE_SUSPECTED" for e in events)


def test_behavior_switch_does_not_count_disabled_time():
    engine = PoseEventEngine(stable_hits=1)
    for t, enabled in ((0, False), (1, False), (2, True), (3, True), (4, True), (5, True), (6, True)):
        _, events = engine.update([_pose()], now=t, events_enabled=enabled)
        assert not events
    _, events = engine.update([_pose()], now=7, events_enabled=True)
    assert [e.event_type for e in events] == ['POSE_LOITERING']
    for t, enabled in ((8, False), (9, True), (10, True), (11, True), (12, True), (13, True)):
        _, events = engine.update([_pose()], now=t, events_enabled=enabled)
        assert not events
    _, events = engine.update([_pose()], now=14, events_enabled=True)
    assert [e.event_type for e in events] == ['POSE_LOITERING']


def _vault_pose(*, single_leg: bool = False, missing_ankle: bool = False) -> RawPose:
    points = _keypoints()
    points[13] = PoseKeypoint(25.0, 115.0, 0.95)
    points[15] = PoseKeypoint(20.0, 140.0, 0.95)
    if not single_leg:
        points[14] = PoseKeypoint(75.0, 120.0, 0.95)
        points[16] = PoseKeypoint(80.0, 145.0, 0.95)
    if missing_ankle:
        points[16] = PoseKeypoint(80.0, 145.0, 0.1)
    return _pose(keypoints=[PoseKeypoint(p.x, p.y - 20, p.confidence) for p in points])


def test_vault_sequence_without_raised_hands_or_zone() -> None:
    engine = PoseEventEngine()
    sequence = [_pose(), _pose(), _vault_pose(), _vault_pose(), _pose(), _pose()]
    events = []
    for i, pose in enumerate(sequence):
        _, current = engine.update([pose], now=i * 0.2, zone_gate=_Zone(False))
        if i < len(sequence) - 1:
            assert not current
        events.extend(current)
    assert [e.event_type for e in events] == ["POSE_CLIMBING_SUSPECTED"]
    assert events[0].observed_monotonic == 1.0
    assert abs(events[0].duration_seconds - 0.6) < 1e-6


def test_vault_rejects_single_leg_single_frame_static_and_missing_points() -> None:
    crouch = _pose(keypoints=[PoseKeypoint(p.x, p.y + 40, p.confidence)
                             for p in _vault_pose().keypoints])
    for middle in (
        [_vault_pose(single_leg=True)] * 2,
        [_vault_pose()],
        [_vault_pose(missing_ankle=True)] * 2,
        [_pose()] * 2,
        [crouch] * 2,
    ):
        engine = PoseEventEngine()
        for i, pose in enumerate([_pose(), _pose(), *middle, _pose(), _pose()]):
            _, events = engine.update([pose], now=i * 0.2)
            assert not events
    engine = PoseEventEngine(crouch_seconds=100, loiter_seconds=100)
    for i in range(10):
        _, events = engine.update([_vault_pose()], now=i * 0.2)
        assert not events


def test_vault_does_not_join_disappearance_or_disabled_period() -> None:
    for mode in ('missing', 'disabled', 'gap'):
        engine = PoseEventEngine()
        for i, pose in enumerate([_pose(), _pose(), _vault_pose(), _vault_pose()]):
            engine.update([pose], now=i * 0.2)
        if mode == 'missing':
            engine.update([], now=0.7)
        elif mode == 'disabled':
            engine.update([_vault_pose()], now=0.7, events_enabled=False)
        for t in ((1.5, 1.7) if mode == 'gap' else (0.8, 1.0)):
            _, events = engine.update([_pose()], now=t)
            assert not events


def test_sequential_high_steps_require_both_legs_and_recovery() -> None:
    left = _vault_pose(single_leg=True)
    points = list(left.keypoints)
    for a, b in ((11, 12), (13, 14), (15, 16)):
        points[a], points[b] = points[b], points[a]
    right = _pose(keypoints=points)
    engine = PoseEventEngine()
    sequence = [_pose(), _pose(), left, left, _pose(), right, right, _pose(), _pose()]
    for i, pose in enumerate(sequence):
        _, events = engine.update([pose], now=i * 0.2)
        if i < len(sequence) - 1:
            assert not events
    assert [e.event_type for e in events] == ['POSE_CLIMBING_SUSPECTED']


def test_alternating_normal_steps_do_not_trigger_vault() -> None:
    engine = PoseEventEngine()
    for i in range(20):
        points = _keypoints()
        leg = i % 2
        points[13 + leg] = PoseKeypoint(40 + leg * 20, 140, .95)
        points[15 + leg] = PoseKeypoint(40 + leg * 20, 180, .95)
        _, events = engine.update([_pose(keypoints=points)], now=i * .2)
        assert not events
