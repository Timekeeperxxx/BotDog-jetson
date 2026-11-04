"""Recording ownership regressions with temporary SQLite and fake FFmpeg only."""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.api.routes import recording
from backend.config import settings
from backend.database import Base
from backend.models import Recording

_REAL_SPAWN = asyncio.create_subprocess_exec


class FakeProcess:
    def __init__(self):
        self.returncode = None
        self.terminated = 0
        self.killed = 0
        self.exited = asyncio.Event()

    async def wait(self):
        await self.exited.wait()
        return self.returncode

    def exit(self, code=0):
        self.returncode = code
        self.exited.set()

    def terminate(self):
        self.terminated += 1
        self.exit(255)  # FFmpeg commonly returns 255 after SIGTERM.

    def kill(self):
        self.killed += 1
        self.exit(-9)


@pytest_asyncio.fixture
async def env(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'recording.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    processes, filenames, remuxes = [], [], []

    async def spawn(*args, **kwargs):
        await asyncio.sleep(0)  # Force the same await interleaving as a real launch.
        proc = FakeProcess()
        if "-movflags" in args:
            remuxes.append(proc)
            Path(args[-1]).write_bytes(b"faststart-video")
            proc.exit()
        else:
            processes.append(proc)
            filenames.append(args[-1])
            Path(args[-1]).write_bytes(b"recorded-video")
        return proc

    monkeypatch.setattr(settings, "RECORDING_DIR", str(tmp_path / "videos"))
    monkeypatch.setattr(recording, "get_session_factory", lambda: factory)
    monkeypatch.setattr(recording, "_recording_lock", asyncio.Lock())
    monkeypatch.setattr(recording, "_current_recording", None)
    monkeypatch.setattr(recording, "_monitor_tasks", set())
    monkeypatch.setattr(recording, "_STARTUP_PROBE_SECONDS", 0.001)
    monkeypatch.setattr(recording.asyncio, "create_subprocess_exec", spawn)

    async def rows():
        async with factory() as session:
            return list((await session.scalars(select(Recording).order_by(Recording.recording_id))).all())

    yield SimpleNamespace(factory=factory, processes=processes, filenames=filenames, remuxes=remuxes, spawn=spawn, rows=rows)
    for proc in processes + remuxes:
        proc.exit()
    tasks = list(recording._monitor_tasks)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await engine.dispose()


@pytest.mark.asyncio
async def test_many_simultaneous_starts_create_exactly_one_owned_process(env):
    app = FastAPI()
    app.include_router(recording.router)
    app.dependency_overrides[recording.require_viewer] = lambda: object()
    app.dependency_overrides[recording.require_operator] = lambda: object()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        results = await asyncio.gather(*(client.post("/api/v1/recording/start") for _ in range(20)))
    successes = [r for r in results if r.status_code == 200]
    failures = [r for r in results if r.status_code == 409]
    assert len(successes) == 1
    assert len(failures) == 19
    assert len(env.processes) == 1
    assert recording._current_recording.proc is env.processes[0]
    rows = await env.rows()
    assert len(rows) == 1 and rows[0].ended_at is None
    assert (await recording.get_recording_status()).recording_id == successes[0].json()["recording_id"]


@pytest.mark.asyncio
async def test_simultaneous_stops_finalize_once(env):
    started = await recording.start_recording()
    first, second = await asyncio.gather(recording.stop_recording(), recording.stop_recording(), return_exceptions=True)
    assert isinstance(first, recording.RecordingStopResponse)
    assert first.recording_id == started.recording_id
    assert isinstance(second, HTTPException) and second.status_code == 409
    assert env.processes[0].terminated == 1 and len(env.remuxes) == 1
    assert recording._current_recording is None
    row, = await env.rows()
    assert row.ended_at == first.ended_at and row.file_size_bytes == len(b"faststart-video")
    assert first.video_url.startswith("/api/v1/media/recordings/")


@pytest.mark.asyncio
async def test_stop_during_start_waits_until_process_is_owned(env, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed_spawn(*args, **kwargs):
        entered.set()
        await release.wait()
        return await env.spawn(*args, **kwargs)

    monkeypatch.setattr(recording.asyncio, "create_subprocess_exec", delayed_spawn)
    start = asyncio.create_task(recording.start_recording())
    await entered.wait()
    stop = asyncio.create_task(recording.stop_recording())
    await asyncio.sleep(0)
    assert not stop.done()
    release.set()
    started, stopped = await asyncio.gather(start, stop)
    assert stopped.recording_id == started.recording_id
    assert env.processes[0].returncode is not None
    assert recording._current_recording is None


@pytest.mark.asyncio
async def test_start_during_stop_waits_for_remux_and_uses_new_file(env, monkeypatch):
    await recording.start_recording()
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed_spawn(*args, **kwargs):
        if "-movflags" in args:
            entered.set()
            await release.wait()
        return await env.spawn(*args, **kwargs)

    monkeypatch.setattr(recording.asyncio, "create_subprocess_exec", delayed_spawn)
    stop = asyncio.create_task(recording.stop_recording())
    await entered.wait()
    start = asyncio.create_task(recording.start_recording())
    await asyncio.sleep(0)
    assert not start.done() and len(env.processes) == 1
    release.set()
    _, started = await asyncio.gather(stop, start)
    assert recording._current_recording.recording_id == started.recording_id
    assert recording._current_recording.proc is env.processes[1]
    assert env.filenames[0] != env.filenames[1]


@pytest.mark.asyncio
async def test_repeated_starts_with_identical_timestamp_never_reuse_filename(env, monkeypatch):
    class FrozenTime:
        @staticmethod
        def now(*args):
            from datetime import datetime, timezone
            return datetime(2026, 11, 3, 1, 0, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(recording, "datetime", FrozenTime)
    # Preserve normal parsing for duration calculation.
    from datetime import datetime
    FrozenTime.fromisoformat = datetime.fromisoformat
    for _ in range(3):
        await recording.start_recording()
        await recording.stop_recording()
    assert len(set(env.filenames)) == 3


@pytest.mark.asyncio
async def test_spawn_failure_rolls_back_and_next_start_can_succeed(env, monkeypatch):
    async def failed_spawn(*args, **kwargs):
        raise FileNotFoundError("ffmpeg missing")

    monkeypatch.setattr(recording.asyncio, "create_subprocess_exec", failed_spawn)
    with pytest.raises(HTTPException) as error:
        await recording.start_recording()
    assert error.value.status_code == 502
    assert await env.rows() == [] and recording._current_recording is None
    monkeypatch.setattr(recording.asyncio, "create_subprocess_exec", env.spawn)
    await recording.start_recording()
    assert len(env.processes) == 1


@pytest.mark.asyncio
async def test_immediate_exit_rolls_back_row_and_removes_partial_file(env, monkeypatch):
    async def dead_spawn(*args, **kwargs):
        proc = await env.spawn(*args, **kwargs)
        proc.exit(1)
        return proc

    monkeypatch.setattr(recording.asyncio, "create_subprocess_exec", dead_spawn)
    with pytest.raises(HTTPException) as error:
        await recording.start_recording()
    assert error.value.status_code == 502
    assert recording._current_recording is None and await env.rows() == []
    assert not Path(env.filenames[0]).exists()


@pytest.mark.asyncio
async def test_commit_failure_stops_unowned_process_and_rolls_back(env, monkeypatch):
    async def failed_commit(self):
        raise RuntimeError("simulated commit failure")

    monkeypatch.setattr(AsyncSession, "commit", failed_commit)
    with pytest.raises(RuntimeError, match="commit failure"):
        await recording.start_recording()
    assert env.processes[0].terminated == 1 and env.processes[0].returncode is not None
    assert recording._current_recording is None and await env.rows() == []
    assert not Path(env.filenames[0]).exists()


@pytest.mark.asyncio
async def test_cancelled_start_after_spawn_stops_process_and_rolls_back(env, monkeypatch):
    monkeypatch.setattr(recording, "_STARTUP_PROBE_SECONDS", 60)
    task = asyncio.create_task(recording.start_recording())
    while not env.processes:
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert env.processes[0].terminated == 1
    assert await env.rows() == [] and recording._current_recording is None


@pytest.mark.asyncio
async def test_unexpected_exit_finalizes_without_a_stop_request_and_can_restart(env):
    await recording.start_recording()
    active = recording._current_recording
    monitor, = recording._monitor_tasks
    env.processes[0].exit(2)
    await asyncio.wait_for(monitor, 1)
    assert recording._current_recording is None
    assert (await recording.get_recording_status()).is_recording is False
    row, = await env.rows()
    assert row.recording_id == active.recording_id and row.ended_at is not None
    await recording.start_recording()
    assert len(env.processes) == 2 and env.filenames[0] != env.filenames[1]


@pytest.mark.asyncio
async def test_failed_finalization_keeps_ownership_until_db_recovers(env, monkeypatch):
    await recording.start_recording()
    active = recording._current_recording
    original_commit = AsyncSession.commit

    async def failed_commit(self):
        raise RuntimeError("simulated finalize failure")

    monkeypatch.setattr(AsyncSession, "commit", failed_commit)
    with pytest.raises(RuntimeError, match="finalize failure"):
        await recording.stop_recording()
    assert recording._current_recording is active
    assert env.processes[0].returncode is not None
    with pytest.raises(RuntimeError, match="finalize failure"):
        await recording.start_recording()
    assert len(env.processes) == 1
    monkeypatch.setattr(AsyncSession, "commit", original_commit)
    await recording.start_recording()
    assert len(env.processes) == 2
    first, second = await env.rows()
    assert first.ended_at is not None and second.ended_at is None


@pytest.mark.asyncio
async def test_missing_output_is_reported_as_failure_after_finalization(env):
    await recording.start_recording()
    Path(env.filenames[0]).unlink()
    # An unsuccessful remux must not create a synthetic successful video.
    async def failed_remux(*args, **kwargs):
        proc = FakeProcess()
        proc.exit(1)
        return proc
    from unittest.mock import patch
    with patch.object(recording.asyncio, "create_subprocess_exec", failed_remux):
        with pytest.raises(HTTPException) as error:
            await recording.stop_recording()
    assert error.value.status_code == 502
    row, = await env.rows()
    assert row.ended_at is not None and row.file_size_bytes == 0
    assert recording._current_recording is None


@pytest.mark.asyncio
async def test_remux_timeout_reaps_process_and_removes_temp_file(env, monkeypatch):
    await recording.start_recording()
    original_wait_for = asyncio.wait_for

    async def short_remux_timeout(awaitable, timeout):
        return await original_wait_for(awaitable, 0.001 if timeout == 30.0 else timeout)

    async def hung_remux(*args, **kwargs):
        proc = FakeProcess()
        env.remuxes.append(proc)
        Path(args[-1]).write_bytes(b"partial-remux")
        return proc

    monkeypatch.setattr(recording.asyncio, "create_subprocess_exec", hung_remux)
    monkeypatch.setattr(recording.asyncio, "wait_for", short_remux_timeout)
    result = await recording.stop_recording()
    assert env.remuxes[0].returncode is not None and env.remuxes[0].terminated == 1
    assert result.file_size_bytes == len(b"recorded-video")
    assert not Path(env.filenames[0] + ".tmp.mp4").exists()


@pytest.mark.asyncio
async def test_terminate_timeout_kills_and_reaps_process(env, monkeypatch):
    proc = FakeProcess()
    proc.terminate = lambda: None
    original_wait_for = asyncio.wait_for

    async def short_timeout(awaitable, timeout):
        return await original_wait_for(awaitable, 0.001)

    monkeypatch.setattr(recording.asyncio, "wait_for", short_timeout)
    await recording._terminate_process(proc)
    assert proc.killed == 1 and proc.returncode == -9


@pytest.mark.asyncio
async def test_remux_does_not_extend_recording_duration(env, monkeypatch):
    await recording.start_recording()
    active = recording._current_recording

    async def slow_remux(*args, **kwargs):
        assert active.ended_at is not None
        # A later wall-clock time must not be used for the process end timestamp.
        monkeypatch.setattr(recording, "_utc_now_iso", lambda: "2099-01-01T00:00:00.000Z")
        return await env.spawn(*args, **kwargs)

    monkeypatch.setattr(recording.asyncio, "create_subprocess_exec", slow_remux)
    result = await recording.stop_recording()
    assert result.ended_at == active.ended_at and not result.ended_at.startswith("2099")
    assert result.duration_seconds < 2


@pytest.mark.asyncio
async def test_background_finalize_failure_is_logged_and_retried_after_recovery(env, monkeypatch):
    await recording.start_recording()
    active = recording._current_recording
    monitor, = recording._monitor_tasks
    original_commit = AsyncSession.commit
    logger = Mock()
    monkeypatch.setattr(recording, "_logger", logger)

    async def failed_commit(self):
        raise RuntimeError("database offline")

    monkeypatch.setattr(AsyncSession, "commit", failed_commit)
    env.processes[0].exit(1)
    await asyncio.wait_for(monitor, 1)
    logger.exception.assert_called_once()
    assert recording._current_recording is active
    row, = await env.rows()
    assert row.ended_at is None
    ended_at = active.ended_at
    monkeypatch.setattr(AsyncSession, "commit", original_commit)
    await recording.start_recording()
    first, second = await env.rows()
    assert first.ended_at == ended_at and second.ended_at is None


@pytest.mark.asyncio
async def test_flush_failure_never_launches_a_process(env, monkeypatch):
    async def failed_flush(self, *args, **kwargs):
        raise RuntimeError("database write failed")

    monkeypatch.setattr(AsyncSession, "flush", failed_flush)
    with pytest.raises(RuntimeError, match="database write failed"):
        await recording.start_recording()
    assert env.processes == [] and recording._current_recording is None


@pytest.mark.asyncio
@pytest.mark.parametrize("signal", ["terminate", "kill"])
async def test_process_exits_between_state_check_and_signal(env, monkeypatch, signal):
    proc = FakeProcess()

    def already_exited():
        proc.exit()
        raise ProcessLookupError("exited before signal")

    setattr(proc, signal, already_exited)
    if signal == "kill":
        proc.terminate = lambda: None
        original_wait_for = asyncio.wait_for

        async def short_timeout(awaitable, timeout):
            return await original_wait_for(awaitable, 0.001)

        monkeypatch.setattr(recording.asyncio, "wait_for", short_timeout)
    await recording._terminate_process(proc)
    assert proc.returncode == 0 and proc.exited.is_set()


@pytest.mark.asyncio
async def test_real_os_child_is_owned_once_and_reaped_without_camera_or_ffmpeg(env, monkeypatch):
    processes = []

    async def spawn_stub(*args, **kwargs):
        if "-movflags" in args:
            return await env.spawn(*args, **kwargs)
        proc = await _REAL_SPAWN(
            sys.executable, "-u", "-c",
            "import pathlib,sys,time; pathlib.Path(sys.argv[1]).write_bytes(b'fake-stream'); print('ready',flush=True); time.sleep(60)",
            args[-1], stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        processes.append(proc)
        assert await asyncio.wait_for(proc.stdout.readline(), 2) == b"ready\n"
        return proc

    monkeypatch.setattr(recording.asyncio, "create_subprocess_exec", spawn_stub)
    try:
        results = await asyncio.gather(recording.start_recording(), recording.start_recording(), return_exceptions=True)
        assert sum(isinstance(r, recording.RecordingStartResponse) for r in results) == 1
        assert sum(isinstance(r, HTTPException) and r.status_code == 409 for r in results) == 1
        assert len(processes) == 1 and recording._current_recording.proc.pid == processes[0].pid
        await recording.stop_recording()
        assert processes[0].returncode is not None and recording._current_recording is None
    finally:
        for proc in processes:
            if proc.returncode is None:
                proc.kill()
            await proc.wait()


@pytest.mark.asyncio
async def test_exit_during_db_commit_does_not_return_start_success(env, monkeypatch):
    original_commit = AsyncSession.commit

    async def exit_during_commit(self):
        await original_commit(self)
        env.processes[0].exit(3)

    monkeypatch.setattr(AsyncSession, "commit", exit_during_commit)
    with pytest.raises(HTTPException) as error:
        await recording.start_recording()
    assert error.value.status_code == 502
    assert recording._current_recording is None
    row, = await env.rows()
    assert row.ended_at is not None and row.file_size_bytes > 0


@pytest.mark.asyncio
async def test_missing_authoritative_row_fails_without_synthetic_video_url(env):
    await recording.start_recording()
    active = recording._current_recording
    async with env.factory() as session:
        await session.execute(delete(Recording))
        await session.commit()
    with pytest.raises(RuntimeError, match="录像记录不存在"):
        await recording.stop_recording()
    assert recording._current_recording is active
    assert active.proc.returncode is not None
