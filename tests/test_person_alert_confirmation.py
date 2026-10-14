from types import SimpleNamespace

import pytest

from backend.person_alert_confirmation import PersonAlertConfirmation


def person(track_id=6, *, status='no_face', bbox=(10, 20, 110, 220), fallback=False):
    return SimpleNamespace(
        track_id=track_id, bbox=bbox, face_status=status,
        identity_id=2 if status == 'recognized' else None,
        is_pose_fallback=fallback,
    )


def update(gate, persons, frame, batch=0):
    return gate.update(persons, frame=frame, required_hits=5, pose_batch=batch,
                       fresh_pose_ids={item.track_id for item in persons if item.is_pose_fallback})


def test_main_detection_needs_five_consecutive_observations():
    gate = PersonAlertConfirmation()
    for frame in range(1, 5):
        assert update(gate, [person()], frame) == set()
    assert update(gate, [person()], 5) == {6}


def test_single_frame_detection_does_not_survive_a_gap():
    gate = PersonAlertConfirmation()
    assert not update(gate, [person()], 1)
    assert not update(gate, [], 2)
    for frame in range(3, 7):
        assert not update(gate, [person()], frame)
    assert update(gate, [person()], 7) == {6}


def test_cached_pose_boxes_are_not_new_observations():
    gate = PersonAlertConfirmation()
    target = person(fallback=True)
    for frame in range(1, 10):
        assert not update(gate, [target], frame, batch=1)
    for frame, batch in zip(range(10, 13), range(2, 5)):
        assert not update(gate, [target], frame, batch)
    assert update(gate, [target], 13, batch=5) == {6}


def test_main_and_fresh_pose_observations_share_confirmation():
    gate = PersonAlertConfirmation()
    assert not update(gate, [person(6)], 1)
    assert not update(gate, [person(6)], 2)
    assert not update(gate, [person(9, fallback=True)], 3, batch=1)
    assert not update(gate, [person(9, fallback=True)], 4, batch=2)
    assert update(gate, [person(9, fallback=True)], 5, batch=3) == {9}


def test_pose_batch_already_seen_with_main_detection_is_not_counted_again():
    gate = PersonAlertConfirmation()
    assert not update(gate, [person()], 1, batch=1)
    assert not update(gate, [person(fallback=True)], 2, batch=1)
    assert gate._tracks[6].hits == 1


def test_duplicate_boxes_in_one_frame_count_once():
    gate = PersonAlertConfirmation()
    assert not update(gate, [person() for _ in range(8)], 1)
    assert gate._tracks[6].hits == 1


def test_two_current_people_do_not_share_confirmation_hits():
    gate = PersonAlertConfirmation()
    for frame in range(1, 5):
        assert not update(gate, [person(6)], frame)
    assert update(gate, [person(6), person(9)], 5) == {6}
    assert gate._tracks[9].hits == 1


def test_identity_pending_never_generates_personnel_alerts():
    gate = PersonAlertConfirmation()
    for frame in range(1, 20):
        assert not update(gate, [person(status='pending')], frame)
    assert gate._tracks[6].hits == 0


def test_recognized_frame_cancels_unauthorized_streak():
    gate = PersonAlertConfirmation()
    for frame in range(1, 5):
        assert not update(gate, [person()], frame)
    assert not update(gate, [person(status='recognized')], 5)
    for frame in range(6, 10):
        assert not update(gate, [person()], frame)
    assert update(gate, [person()], 10) == {6}


@pytest.mark.parametrize('status', ['unknown', 'no_face', 'unavailable'])
def test_final_unauthorized_states_can_confirm_after_five_observations(status):
    gate = PersonAlertConfirmation()
    for frame in range(1, 5):
        assert not update(gate, [person(status=status)], frame)
    assert update(gate, [person(status=status)], 5) == {6}


def test_unassigned_ids_are_not_stable_tracks():
    gate = PersonAlertConfirmation()
    for frame in range(1, 10):
        assert not update(gate, [person(-1)], frame)


def test_task_reset_clears_confirmation():
    gate = PersonAlertConfirmation()
    for frame in range(1, 5):
        update(gate, [person()], frame)
    gate.clear()
    assert not update(gate, [person()], 5)
    assert gate._tracks[6].hits == 1


def test_absent_tracks_are_pruned():
    gate = PersonAlertConfirmation(max_missing_frames=3)
    update(gate, [person()], 1)
    for frame in range(2, 5):
        update(gate, [], frame)
    assert not gate._tracks
