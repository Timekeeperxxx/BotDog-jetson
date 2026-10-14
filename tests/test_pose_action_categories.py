from unittest.mock import patch

from backend.pose_detection import PoseEventEngine, RawPose


CLIMB = 'POSE_CLIMBING_SUSPECTED'
VAULT = 'POSE_VAULTING_SUSPECTED'
POSE = RawPose((0, 0, 100, 200), .9, ())


def test_vault_evidence_takes_precedence_over_climb_for_same_person():
    engine = PoseEventEngine()
    with patch.object(engine, '_detect_climb_motion', return_value=(True, .7)), \
         patch.object(engine, '_detect_vault_motion', return_value=.2):
        _, first = engine.update([POSE], now=0)
        assert [event.event_type for event in first] == [VAULT]
        assert engine.active_actions == {VAULT}
        _, second = engine.update([POSE], now=.1)
        assert second == []
        assert engine.active_actions == {VAULT}


def test_climb_and_vault_cooldowns_are_independent():
    for first_type, second_type in ((CLIMB, VAULT), (VAULT, CLIMB)):
        engine = PoseEventEngine()
        for index, kind in enumerate((first_type, second_type, second_type)):
            with patch.object(engine, '_detect_climb_motion', return_value=(kind == CLIMB, .7)), \
                 patch.object(engine, '_detect_vault_motion', return_value=.2 if kind == VAULT else None):
                _, events = engine.update([POSE], now=index * .1)
                assert [event.event_type for event in events] == ([kind] if index < 2 else [])
                assert engine.active_actions == {kind}


def test_different_people_can_have_different_action_categories():
    engine = PoseEventEngine()
    other = RawPose((300, 0, 400, 200), .9, ())
    with patch.object(engine, '_detect_climb_motion', side_effect=lambda state: (state.track_id == 2, .7)), \
         patch.object(engine, '_detect_vault_motion', side_effect=lambda obs, *_: .2 if obs.track_id == 1 else None):
        _, events = engine.update([POSE, other], now=0)
        assert {(event.track_id, event.event_type) for event in events} == {(1, VAULT), (2, CLIMB)}
        assert engine.active_actions == {VAULT, CLIMB}
