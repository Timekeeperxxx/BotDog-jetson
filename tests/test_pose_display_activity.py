from unittest.mock import patch
from backend.pose_detection import PoseEventEngine, RawPose


def test_display_activity_survives_cooldown_without_extra_events():
    engine = PoseEventEngine()
    pose = RawPose((0, 0, 100, 200), .9, ())
    with patch.object(engine, '_detect_chest_motion', return_value=.8), patch.object(
        engine, '_detect_climb_motion', return_value=(True, .7)
    ):
        _, first = engine.update([pose], now=0)
        expected = {'POSE_DAMAGE_SUSPECTED', 'POSE_CLIMBING_SUSPECTED'}
        assert {event.event_type for event in first} == expected
        _, second = engine.update([pose], now=.1)
        assert second == []  # Existing cooldown and event output unchanged.
        assert engine.active_actions == expected
        engine.update([], now=.2)
        assert engine.active_actions == set()
        engine.update([pose], now=.3, events_enabled=False)
        assert engine.active_actions == set()
