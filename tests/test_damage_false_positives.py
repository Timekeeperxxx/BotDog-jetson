"""普通动作的构造骨架回归；不是实测视频准确率。"""
from backend.pose_detection import PoseEventEngine
from test_damage_dual_hand import pose, update


def test_repeated_small_single_hand_adjustments_are_not_damage():
    engine = PoseEventEngine()
    for i in range(40):
        assert not update(engine, pose(30 + 7 * (i % 2), 70), i * .2)


def test_short_large_hand_gesture_does_not_satisfy_observation_time():
    engine = PoseEventEngine()
    for i in range(8):
        assert not update(engine, pose(30 + 14 * (i % 2), 70), i * .2)


def test_still_time_cannot_pad_a_short_burst_of_large_reversals():
    engine = PoseEventEngine()
    for i in range(10):
        assert not update(engine, pose(), i * .2)
    for i in range(6):
        assert not update(engine, pose(30 + 14 * (i % 2), 70), 2 + i * .1)


def test_separate_short_visible_segments_cannot_accumulate_reversals():
    engine = PoseEventEngine()
    for segment in range(6):
        start = segment * .8
        for i in range(3):
            assert not update(engine, pose(30 + 14 * (i % 2), 70), start + i * .2)
        assert not update(engine, pose(missing=9), start + .6)


def test_genuine_repeated_large_motion_still_triggers_after_the_stricter_gate():
    engine = PoseEventEngine()
    hits = []
    for i in range(15):
        hits += update(engine, pose(30 + 14 * (i % 2), 70), i * .2)
    assert len(hits) == 1
    assert hits[0].observed_monotonic == 1.6
    assert hits[0].confidence == .7  # 规则分数，不是破坏概率。
