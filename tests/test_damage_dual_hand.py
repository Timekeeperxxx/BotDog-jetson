"""构造骨架的规则测试；坐标和时间均为软件测试输入，不是实测识别率。"""
import math

import pytest

from backend.pose_detection import PoseEventEngine, PoseKeypoint, RawPose


def pose(left_x=30.0, right_x=70.0, *, wrist_y=100.0, hips=True,
         missing=None, translate=0.0, scale=1.0, angle=0.0):
    points = [PoseKeypoint(0, 0, 0) for _ in range(17)]
    for index, x, y in ((5, 35, 60), (6, 65, 60), (7, 30, 80), (8, 70, 80), (9, left_x, wrist_y),
                        (10, right_x, wrist_y), (11, 40, 110), (12, 60, 110)):
        confidence = 0.1 if index == missing or (not hips and index in (11, 12)) else .95
        points[index] = PoseKeypoint(x, y, confidence)
    points = tuple(PoseKeypoint(
        (p.x * math.cos(angle) - p.y * math.sin(angle)) * scale + translate,
        (p.x * math.sin(angle) + p.y * math.cos(angle)) * scale + translate,
        p.confidence,
    ) for p in points)
    return RawPose((int(translate), int(translate), int(100 * scale + translate),
                    int(200 * scale + translate)), .95, points)


def update(engine, observation, now, *, enabled=True):
    _, events = engine.update([] if observation is None else [observation],
                              now=now, events_enabled=enabled)
    return [event for event in events if event.event_type == 'POSE_DAMAGE_SUSPECTED']


@pytest.mark.parametrize('hips,wrist_y', [(True, 100), (True, 104), (False, 95)])
def test_dual_hands_above_waist_accept_repeated_different_motion(hips, wrist_y):
    engine = PoseEventEngine()
    hits = []
    for i, now in enumerate((0, .3, .6, .9, 1.2, 1.5, 1.8)):
        hits += update(engine, pose(30 + 12 * (i % 2), 70 - 2 * (i % 3),
                                    wrist_y=wrist_y, hips=hips), now)
    assert len(hits) == 1
    assert hits[0].duration_seconds == pytest.approx(1.8)


@pytest.mark.parametrize('missing', [5, 6, 9, 10])
def test_one_visible_hand_or_missing_shoulder_cannot_trigger(missing):
    engine = PoseEventEngine()
    for i in range(15):
        assert not update(engine, pose(30 + 12 * (i % 2), 70 - 7 * (i % 3),
                                       missing=missing), i * .2)


def test_three_samples_still_require_full_observation_duration():
    engine = PoseEventEngine()
    for i in range(8):
        assert not update(engine, pose(30 + 12 * (i % 2), 70), i * .2)
    assert update(engine, pose(30, 70), 1.6)


@pytest.mark.parametrize('hips,wrist_y', [(True, 115), (False, 110)])
def test_both_hands_below_waist_are_rejected(hips, wrist_y):
    engine = PoseEventEngine()
    for i in range(12):
        assert not update(engine, pose(30 + 12 * (i % 2), 70 - 6 * (i % 3),
                                       wrist_y=wrist_y, hips=hips), i * .2)


def test_static_hands_do_not_trigger_from_camera_translation_scale_or_rotation():
    engine = PoseEventEngine()
    for i in range(16):
        assert not update(engine, pose(translate=i * 2, scale=1 + i * .02,
                                       angle=i * .015), i * .2)


@pytest.mark.parametrize('mode', ['still', 'jitter', 'single_adjustment'])
def test_waist_height_does_not_turn_static_jitter_or_one_adjustment_into_damage(mode):
    engine = PoseEventEngine()
    for i in range(12):
        shift = .5 * (i % 2) if mode == 'jitter' else (12 if mode == 'single_adjustment' and i >= 2 else 0)
        assert not update(engine, pose(30 + shift, 70), i * .2)


@pytest.mark.parametrize('missing', [None, 9, 10])
def test_short_occlusion_preserves_progress_but_does_not_count_unseen_time(missing):
    engine = PoseEventEngine()
    for i in range(4):
        assert not update(engine, pose(30 + 12 * (i % 2)), i * .2)
    assert not update(engine, None if missing is None else pose(missing=missing), .8)
    assert not update(engine, pose(30), 1.0)
    # 漏点前后的往复次数不拼接；恢复后重新观察分布足够久的反复操作。
    for i in range(7):
        assert not update(engine, pose(42 - 12 * (i % 2)), 1.2 + i * .2)
    assert update(engine, pose(30), 2.6)


def test_displacement_across_occlusion_does_not_become_action_evidence():
    engine = PoseEventEngine()
    for i in range(3):
        assert not update(engine, pose(30 + .5 * i), i * .2)
    assert not update(engine, pose(missing=10), .5)
    for i in range(3):
        assert not update(engine, pose(50 + .5 * i), .6 + i * .2)


def test_long_gap_requires_fresh_dual_hand_motion():
    engine = PoseEventEngine()
    for i in range(4):
        assert not update(engine, pose(30 + 12 * (i % 2)), i * .2)
    for i in range(5):
        assert not update(engine, pose(30 + 12 * (i % 2)), 1.2 + i * .4)
    assert update(engine, pose(42), 3.2)


def test_disabling_behavior_clears_partial_motion_before_quick_reenable():
    engine = PoseEventEngine()
    for i in range(4):
        assert not update(engine, pose(30 + 12 * (i % 2)), i * .2)
    assert not update(engine, pose(30), .7, enabled=False)
    for i in range(8):
        assert not update(engine, pose(30 + 12 * (i % 2)), .8 + i * .2)
    assert update(engine, pose(30), 2.4)


def test_one_up_and_down_gesture_is_not_repeated_operation():
    engine = PoseEventEngine()
    for i, height in enumerate((100, 90, 80, 70, 60, 70, 80, 90, 100)):
        assert not update(engine, pose(wrist_y=height), i * .2)


def test_clapping_contact_resets_motion_instead_of_joining_apart_phases():
    engine = PoseEventEngine()
    for i in range(30):
        left, right = (47, 53) if i % 3 == 2 else (30, 70)
        assert not update(engine, pose(left, right, wrist_y=80), i * .2)


def test_natural_walking_swing_at_waist_is_not_operation():
    engine = PoseEventEngine()
    for i in range(20):
        assert not update(engine, pose(30 + 12 * (i % 2), 70 - 6 * (i % 2),
                                       wrist_y=110), i * .4)


def test_stretched_arms_are_not_operations_despite_wrist_jitter():
    engine = PoseEventEngine()
    for i in range(20):
        raw = pose(-15 + 12 * (i % 2), 115 - 5 * (i % 2), wrist_y=60)
        points = list(raw.keypoints)
        points[7], points[8] = PoseKeypoint(10, 60, .95), PoseKeypoint(90, 60, .95)
        assert not update(engine, RawPose(raw.bbox, raw.confidence, tuple(points)), i * .2)


def test_short_forearm_projection_does_not_turn_palm_location_jitter_into_motion():
    engine = PoseEventEngine()
    for i in range(20):
        raw = pose(30 + 12 * (i % 2), 70, wrist_y=80)
        points = list(raw.keypoints)
        points[7] = PoseKeypoint(points[9].x, 85, .95)
        points[8] = PoseKeypoint(points[10].x, 85, .95)
        assert not update(engine, RawPose(raw.bbox, raw.confidence, tuple(points)), i * .2)


def test_occluded_elbows_do_not_block_visible_dual_hand_pulling():
    engine = PoseEventEngine()
    hits = []
    for i in range(10):
        raw = pose(30 + 12 * (i % 2), 70, wrist_y=95)
        points = list(raw.keypoints)
        points[7] = points[8] = PoseKeypoint(0, 0, .1)
        hits += update(engine, RawPose(raw.bbox, raw.confidence, tuple(points)), i * .2)
    assert len(hits) == 1


def test_rare_subthreshold_reversals_do_not_accumulate_forever():
    engine = PoseEventEngine()
    for i in range(45):
        assert not update(engine, pose(30 + 10 * ((i // 12) % 2), 70,
                                       wrist_y=95), i * .2)
