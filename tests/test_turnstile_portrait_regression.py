"""真实竖屏漏检回归及正常动作/时序边界检查。"""
import json
from pathlib import Path

import pytest

from backend.pose_detection import PoseEventEngine, PoseKeypoint, RawPose


ROWS = json.loads((Path(__file__).parent / 'fixtures/turnstile_portrait_6fps.json').read_text())['frames']
VAULT = 'POSE_VAULTING_SUSPECTED'
CLIMB = 'POSE_CLIMBING_SUSPECTED'
SEGMENTS = [(1, 3.8), (6, 7.8), (9.3, 14.3), (17.5, 23), (24.8, 30.5), (33.3, 37.3)]


def poses(row, *, dx=0, dy=0, scale=1):
    return [RawPose(
        tuple(round(v * scale + (dx if i % 2 == 0 else dy)) for i, v in enumerate(p['bbox'])),
        p['confidence'], tuple(PoseKeypoint(k[0] * scale + dx, k[1] * scale + dy, k[2])
                               for k in p['keypoints']),
    ) for p in row['poses']]


def engine():
    return PoseEventEngine(loiter_seconds=1000, crouch_seconds=1000)


def test_portrait_detects_each_demonstration_and_preserves_cooldown():
    e = engine()
    active, events = [], []
    for row in ROWS:
        _, ev = e.update(poses(row), now=row['time'])
        if VAULT in e.active_actions:
            active.append(row['time'])
        assert CLIMB not in e.active_actions
        assert all(event.event_type != CLIMB for event in ev)
        events.extend(ev)
    assert all(any(start <= t < end for t in active) for start, end in SEGMENTS)
    emitted = [ev.observed_monotonic for ev in events if ev.event_type == VAULT]
    assert len(emitted) >= len(SEGMENTS)
    assert all(b - a >= 2 for a, b in zip(emitted, emitted[1:]))


@pytest.mark.parametrize('offset', range(5))
def test_six_fps_sampling_phase_does_not_drop_demonstrations(offset):
    frames = json.loads((Path(__file__).parent / 'fixtures/turnstile_portrait_30fps.json').read_text())['frames']
    e = engine()
    active = []
    for row in frames[offset::5]:
        e.update(poses(row), now=row['time'])
        assert CLIMB not in e.active_actions
        if VAULT in e.active_actions:
            active.append(row['time'])
    assert all(any(start <= t < end for t in active) for start, end in SEGMENTS)


@pytest.mark.parametrize('start,end', [(3.8, 5.8), (7.8, 9.3), (14.3, 17.5), (23, 24.8), (30.5, 33.3)])
def test_portrait_normal_walking_and_waiting_do_not_trigger(start, end):
    e = engine()
    for row in ROWS:
        if start <= row['time'] < end:
            e.update(poses(row), now=row['time'])
            assert not {CLIMB, VAULT} & e.active_actions


@pytest.mark.parametrize('moving_camera', [False, True])
def test_static_raised_leg_and_small_jitter_do_not_trigger(moving_camera):
    row = min(ROWS, key=lambda r: abs(r['time'] - 1.5))
    e = engine()
    for i in range(40):
        scale = 1 + i * .01 if moving_camera else 1
        frame = poses(row, dx=i * 2 if moving_camera else 0,
                      dy=i if moving_camera else 0, scale=scale)
        p = frame[0]
        points = list(p.keypoints)
        for index in (13, 14, 15, 16):
            k = points[index]
            points[index] = PoseKeypoint(k.x + (i % 2), k.y + (i % 2), k.confidence)
        e.update([RawPose(p.bbox, p.confidence, tuple(points))], now=i / 6)
        assert not {CLIMB, VAULT} & e.active_actions


@pytest.mark.parametrize('mode', ['gap', 'disabled', 'long_ankle_occlusion'])
def test_supported_jump_does_not_bridge_interrupted_motion(mode):
    e = engine()
    jump = [r for r in ROWS if 5.8 <= r['time'] <= 7.4]
    for row in jump:
        if row['time'] >= 6.5:
            break
        e.update(poses(row), now=row['time'])
    if mode == 'disabled':
        e.update(poses(row), now=6.5, events_enabled=False)
    elif mode == 'long_ankle_occlusion':
        for r in jump:
            if 6.5 <= r['time'] <= 7.0:
                frame = poses(r)
                p = frame[0]
                points = list(p.keypoints)
                for index in (15, 16):
                    k = points[index]
                    points[index] = PoseKeypoint(k.x, k.y, .1)
                e.update([RawPose(p.bbox, p.confidence, tuple(points))], now=r['time'])
    else:
        e.update([], now=6.5)
    # 恢复伸腿本身不能补出丢失的腾起证据。
    for r in jump:
        if r['time'] >= 7.0:
            e.update(poses(r), now=r['time'])
            assert not {CLIMB, VAULT} & e.active_actions


def test_crouching_with_fixed_hands_does_not_look_like_supported_lift():
    from test_pose_detection import _keypoints, _pose
    e = engine()
    for i in range(12):
        points = _keypoints()
        if i >= 2:
            for index in (5, 6, 11, 12):
                k = points[index]
                points[index] = PoseKeypoint(k.x, k.y + 25, k.confidence)
            for index in (13, 14):
                k = points[index]
                points[index] = PoseKeypoint(k.x, 140, k.confidence)
            for index in (15, 16):
                k = points[index]
                points[index] = PoseKeypoint(k.x, 180, k.confidence)
        e.update([_pose(keypoints=points)], now=i / 6)
        assert not {CLIMB, VAULT} & e.active_actions
