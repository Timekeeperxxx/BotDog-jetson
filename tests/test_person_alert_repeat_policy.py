from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend import workers_ai_processing
from backend.workers_ai_processing import AIWorkerProcessingMixin


async def feed(worker, persons, frame):
    for _ in range(5):
        await worker._process_person_alerts(persons, frame)


def make_worker(monkeypatch, clock, *, reset_misses=3):
    monkeypatch.setattr(workers_ai_processing.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(workers_ai_processing.settings, 'AI_COOLDOWN_SECONDS', 30)
    worker = AIWorkerProcessingMixin()
    worker._person_alert_last_seen = {}
    worker._person_pose_hits = {}
    worker._person_alert_frame = 0
    worker._reset_misses = reset_misses
    worker._raise_alert = AsyncMock()
    worker._record_recognized_person = AsyncMock(return_value=True)
    return worker


def person(track_id, bbox=(10, 20, 110, 220)):
    return SimpleNamespace(
        label='person', track_id=track_id, bbox=bbox,
        face_status='unknown', identity_id=None,
    )


@pytest.mark.asyncio
async def test_source_id_changes_inherit_original_thirty_second_timer(monkeypatch):
    clock = [100.0]
    worker = make_worker(monkeypatch, clock)
    await feed(worker, [person(1)], b'primary')
    clock[0] = 101
    await feed(worker, [person(9, (12, 22, 115, 224))], b'pose')
    clock[0] = 129.999
    await feed(worker, [person(2)], b'primary-new-id')
    assert worker._raise_alert.await_count == 1
    clock[0] = 130
    await feed(worker, [person(9)], b'pose-again')
    assert worker._raise_alert.await_count == 2


@pytest.mark.asyncio
async def test_confirmed_exit_does_not_bypass_category_interval(monkeypatch):
    clock = [100.0]
    worker = make_worker(monkeypatch, clock)
    await feed(worker, [person(1)], b'first')
    await feed(worker, [], b'miss-one')
    await feed(worker, [], b'miss-two')
    clock[0] = 102
    await feed(worker, [person(7)], b'back-before-confirmed-exit')
    assert worker._raise_alert.await_count == 1
    for _ in range(3):
        await feed(worker, [], b'confirmed-empty')
    clock[0] = 105
    await feed(worker, [person(8)], b'reentered')
    assert worker._raise_alert.await_count == 1
    clock[0] = 130
    await feed(worker, [person(8)], b'interval-expired')
    assert worker._raise_alert.await_count == 2


@pytest.mark.asyncio
async def test_additional_people_share_the_category_interval(monkeypatch):
    clock = [100.0]
    worker = make_worker(monkeypatch, clock)
    original = person(1)
    await feed(worker, [original], b'one-person')
    clock[0] = 101
    # Two distinct current track IDs must not be merged, even with overlapping boxes.
    await feed(worker, [original, person(2)], b'two-people')
    assert worker._raise_alert.await_count == 1
    clock[0] = 102
    await feed(worker, [original, person(2)], b'both-remain')
    assert worker._raise_alert.await_count == 1


@pytest.mark.asyncio
async def test_unrelated_new_person_does_not_bypass_category_timer(monkeypatch):
    clock = [100.0]
    worker = make_worker(monkeypatch, clock)
    await feed(worker, [person(1)], b'left-person')
    clock[0] = 101
    await feed(worker, [person(2, (400, 20, 500, 220))], b'right-person')
    assert worker._raise_alert.await_count == 1


@pytest.mark.asyncio
async def test_face_status_fluctuation_does_not_bypass_repeat_timer(monkeypatch):
    clock = [100.0]
    worker = make_worker(monkeypatch, clock)
    target = person(1)
    await feed(worker, [target], b'unknown')
    target.face_status, target.identity_id = 'recognized', 4
    clock[0] = 101
    await feed(worker, [target], b'authorized')
    target.face_status, target.identity_id = 'no_face', None
    clock[0] = 102
    await feed(worker, [target], b'face-temporarily-missing')
    assert worker._raise_alert.await_count == 1


@pytest.mark.asyncio
async def test_failed_capture_does_not_consume_repeat_timer(monkeypatch):
    clock = [100.0]
    worker = make_worker(monkeypatch, clock)
    worker._raise_alert.side_effect = [RuntimeError('capture unavailable'), None]
    with pytest.raises(RuntimeError):
        await feed(worker, [person(1)], b'failed')
    clock[0] = 101
    await feed(worker, [person(1)], b'retry')
    assert worker._raise_alert.await_count == 2
