from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from backend import workers_ai
from backend.pose_detection import PoseObservation, Posture
from backend.workers_ai import AIWorker, AIWorkerFrameTimeout, DetectionResult, _AIFrame


class _SessionFactory:
    def __call__(self) -> "_SessionFactory":
        return self

    async def __aenter__(self) -> "_SessionFactory":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None


class _MavlinkGateway:
    def get_latest_position(self) -> None:
        return None


class _HangingDetector:
    def detect_many(self, frame: bytes) -> list[DetectionResult]:
        time.sleep(0.2)
        return []


class _FastDetector:
    def detect_many(self, frame: bytes) -> list[DetectionResult]:
        return []


class _BarrierDetector:
    def __init__(self, barrier: threading.Barrier) -> None:
        self._barrier = barrier

    def detect_many(self, frame: bytes) -> list[DetectionResult]:
        self._barrier.wait(timeout=0.5)
        return []


class _BarrierPoseDetector:
    def __init__(self, barrier: threading.Barrier) -> None:
        self._barrier = barrier

    def detect(self, frame: bytes) -> list[object]:
        self._barrier.wait(timeout=0.5)
        return []


class _FakePoseEventEngine:
    def update(self, *args: Any, **kwargs: Any) -> tuple[list[object], list[object]]:
        return [], []


class _FakeAutoTrack:
    def __init__(
        self,
        *,
        enabled: bool,
        paused: bool = False,
        active_target: object | None = None,
        candidates: dict[int, object] | None = None,
    ) -> None:
        self._enabled = enabled
        self._paused = paused
        self._active_target = active_target
        self._candidates = candidates or {}


class _FakeStderr:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    async def read(self, size: int) -> bytes:
        del size
        payload, self._payload = self._payload, b""
        return payload


class _FakeProcess:
    def __init__(
        self,
        *,
        wait_never_finishes: bool = False,
        pid: int = 4242,
        stderr: _FakeStderr | None = None,
    ) -> None:
        self.pid = pid
        self.stdout = None
        self.stderr = stderr
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False
        self.wait_never_finishes = wait_never_finishes

    def terminate(self) -> None:
        self.terminated = True
        if not self.wait_never_finishes:
            self.returncode = -15

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    async def wait(self) -> int:
        if self.wait_never_finishes and not self.killed:
            await asyncio.Future()
        return self.returncode or 0


def _worker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AIWorker:
    monkeypatch.setattr(workers_ai.settings, "AI_SIMULATE_DETECTION", True)
    monkeypatch.setattr(workers_ai.settings, "AI_FRAME_PROCESS_TIMEOUT_SECONDS", 1.0)
    monkeypatch.setattr(workers_ai.settings, "AI_EXIT_ON_FRAME_TIMEOUT", False)
    monkeypatch.setattr(workers_ai.settings, "AI_MAX_FRAME_AGE_SECONDS", 0.35)
    monkeypatch.setattr(workers_ai.settings, "AI_EVENT_SEND_TIMEOUT_SECONDS", 0.03)
    monkeypatch.setattr(workers_ai.settings, "AI_FFMPEG_MAX_RSS_MB", 512)
    monkeypatch.setattr(workers_ai.settings, "AI_FFMPEG_MEMORY_CHECK_INTERVAL_SECONDS", 1.0)
    monkeypatch.setattr(workers_ai.settings, "AI_PATROL_SKIP", 2)
    monkeypatch.setattr(workers_ai.settings, "AI_AUTO_TRACK_SKIP", 1)
    monkeypatch.setattr(workers_ai.settings, "AI_SUSPECT_SKIP", 1)
    monkeypatch.setattr(workers_ai.settings, "AI_PARALLEL_INFERENCE_ENABLED", True)
    monkeypatch.setattr(workers_ai.settings, "AI_CONTINUOUS_DETECTION_ENABLED", False)
    monkeypatch.setattr(workers_ai.settings, "POSE_ENABLED", False)
    worker = AIWorker(
        session_factory=_SessionFactory(),
        state_machine=object(),
        mavlink_gateway=_MavlinkGateway(),
        snapshot_dir=tmp_path,
    )
    worker._frame_process_timeout_s = 0.01
    return worker


@pytest.mark.asyncio
async def test_ai_frame_processing_timeout_detects_stuck_detector(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)
    worker._detector = _HangingDetector()

    async def noop_video_lost(reason: str) -> None:
        return None

    monkeypatch.setattr(worker, "_notify_auto_track_video_lost", noop_video_lost)

    with pytest.raises(AIWorkerFrameTimeout):
        await worker._process_frame_with_timeout(b"\0", frame_index=542)

    assert worker._frames_processed == 0
    assert worker._last_frame_timeout_reason is not None
    assert "frame_index=542" in worker._last_frame_timeout_reason
    assert worker._ffmpeg_last_exit_reason.startswith("AI_Frame_Process_Timeout")


@pytest.mark.asyncio
async def test_ai_frame_processing_timeout_detects_stuck_post_processing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)
    worker._detector = _FastDetector()

    async def slow_process_detection(*args: Any, **kwargs: Any) -> None:
        await asyncio.sleep(0.2)

    async def noop_video_lost(reason: str) -> None:
        return None

    monkeypatch.setattr(worker, "_process_detection", slow_process_detection)
    monkeypatch.setattr(worker, "_notify_auto_track_video_lost", noop_video_lost)

    with pytest.raises(AIWorkerFrameTimeout):
        await worker._process_frame_with_timeout(b"\0", frame_index=543)

    assert worker._frames_processed == 0
    assert worker._last_frame_timeout_reason is not None
    assert "frame_index=543" in worker._last_frame_timeout_reason


@pytest.mark.asyncio
async def test_ai_frame_processing_clears_timeout_after_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)
    worker._detector = _FastDetector()
    worker._last_frame_timeout_reason = "previous"

    async def noop_process_detection(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(worker, "_process_detection", noop_process_detection)

    await worker._process_frame_with_timeout(b"\0", frame_index=544)

    assert worker._frames_processed == 1
    assert worker._last_frame_timeout_reason is None
    assert worker._last_frame_completed_at >= worker._last_frame_started_at


@pytest.mark.asyncio
async def test_ai_frame_queue_keeps_only_latest_frame() -> None:
    queue: asyncio.Queue[_AIFrame] = asyncio.Queue(maxsize=1)
    old_frame = _AIFrame(data=b"old", index=1, read_at=1.0)
    latest_frame = _AIFrame(data=b"latest", index=2, read_at=2.0)

    assert await AIWorker._put_latest_frame(queue, old_frame) == 0
    assert await AIWorker._put_latest_frame(queue, latest_frame) == 1

    queued = queue.get_nowait()
    assert queued.data == b"latest"
    assert queued.index == 2


def test_ai_frame_skip_uses_patrol_skip_without_tracking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)

    import backend.auto_track_service as auto_track_service
    import backend.guard_mission_service as guard_mission_service

    monkeypatch.setattr(auto_track_service, "get_auto_track_service", lambda: None)
    monkeypatch.setattr(guard_mission_service, "get_guard_mission_service", lambda: None)

    assert worker._get_frame_skip() == 2


def test_ai_continuous_detection_runs_without_task_or_tracking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)
    monkeypatch.setattr(workers_ai.settings, "AI_CONTINUOUS_DETECTION_ENABLED", True)

    assert worker._current_task_id is None
    assert worker._is_mission_active() is True


def test_ai_frame_skip_uses_auto_track_skip_while_finding_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)

    import backend.auto_track_service as auto_track_service
    import backend.guard_mission_service as guard_mission_service

    monkeypatch.setattr(
        auto_track_service,
        "get_auto_track_service",
        lambda: _FakeAutoTrack(enabled=True, active_target=None, candidates={}),
    )
    monkeypatch.setattr(guard_mission_service, "get_guard_mission_service", lambda: None)

    assert worker._get_frame_skip() == 1


def test_ai_frame_skip_falls_back_to_patrol_when_auto_track_paused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)

    import backend.auto_track_service as auto_track_service
    import backend.guard_mission_service as guard_mission_service

    monkeypatch.setattr(
        auto_track_service,
        "get_auto_track_service",
        lambda: _FakeAutoTrack(enabled=True, paused=True),
    )
    monkeypatch.setattr(guard_mission_service, "get_guard_mission_service", lambda: None)

    assert worker._get_frame_skip() == 2


@pytest.mark.asyncio
async def test_ai_frame_processing_records_latency_metrics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)
    worker._detector = _FastDetector()

    async def noop_process_detection(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(worker, "_process_detection", noop_process_detection)
    broadcast_metrics: list[tuple[int, float, float]] = []

    async def capture_status() -> None:
        broadcast_metrics.append(
            (
                worker._last_processed_frame_index,
                worker._last_processing_ms,
                worker._last_end_to_end_ms,
            )
        )

    monkeypatch.setattr(worker, "_maybe_broadcast_status", capture_status)

    frame_read_at = time.monotonic() - 0.05
    await worker._process_frame_with_timeout(
        b"\0",
        frame_index=545,
        frame_read_at=frame_read_at,
    )

    assert worker._last_processed_frame_index == 545
    assert worker._last_frame_age_ms >= 0
    assert worker._last_processing_ms >= 0
    assert worker._last_end_to_end_ms >= worker._last_processing_ms
    assert broadcast_metrics == [
        (545, worker._last_processing_ms, worker._last_end_to_end_ms)
    ]


@pytest.mark.asyncio
async def test_ai_detector_and_pose_run_concurrently_after_warmup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)
    barrier = threading.Barrier(2)
    worker._detector = _BarrierDetector(barrier)
    worker._pose_detector = _BarrierPoseDetector(barrier)  # type: ignore[assignment]
    worker._pose_event_engine = _FakePoseEventEngine()  # type: ignore[assignment]
    worker._detector_warmed_up = True
    worker._pose_warmed_up = True
    monkeypatch.setattr(workers_ai.settings, "POSE_FRAME_SKIP", 1)

    async def noop(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(worker, "_process_detection", noop)
    monkeypatch.setattr(worker, "_process_pose_events", noop)
    monkeypatch.setattr(worker, "_broadcast_pose_overlay", noop)

    await asyncio.wait_for(
        worker._detect_and_process_frame(b"\0", frame_index=546),
        timeout=1.0,
    )

    assert worker._frames_processed == 1
    assert worker._pose_frames_processed == 1
    assert worker._last_detect_ms >= 0
    assert worker._last_pose_ms >= 0


@pytest.mark.asyncio
async def test_ai_pose_skip_keeps_detector_running_every_frame(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)
    worker._detector = _FastDetector()
    monkeypatch.setattr(workers_ai.settings, "POSE_FRAME_SKIP", 2)

    class _UnexpectedPoseDetector:
        def detect(self, frame: bytes) -> list[object]:
            raise AssertionError("odd source frame must skip pose inference")

    worker._pose_detector = _UnexpectedPoseDetector()  # type: ignore[assignment]
    worker._pose_event_engine = _FakePoseEventEngine()  # type: ignore[assignment]

    async def noop(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(worker, "_process_detection", noop)

    await worker._detect_and_process_frame(b"\0", frame_index=547)

    assert worker._frames_processed == 1
    assert worker._pose_frames_processed == 0
    assert worker._last_pose_ms == 0.0


def test_weapon_detector_runs_low_frequency_then_every_frame_when_active(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)
    worker._weapon_detector = _FastDetector()  # type: ignore[assignment]
    worker._weapon_frame_skip = 3

    assert worker._is_weapon_due(1, now=10.0) is False
    assert worker._is_weapon_due(3, now=10.0) is True

    worker._weapon_active_until = 20.0
    assert worker._is_weapon_due(4, now=19.0) is True
    assert worker._is_weapon_due(4, now=21.0) is False


def test_weapon_filter_rejects_unassociated_chair_false_positive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)
    monkeypatch.setattr(workers_ai.settings, "WEAPON_REQUIRE_PERSON_ASSOCIATION", True)
    monkeypatch.setattr(workers_ai.settings, "WEAPON_PERSON_EXPAND_RATIO", 0.35)
    monkeypatch.setattr(
        workers_ai.settings,
        "WEAPON_UNATTENDED_CONFIDENCE_THRESHOLD",
        0.85,
    )
    chair_false_positive = DetectionResult(
        label="guns",
        confidence=0.6919,
        bbox=(294, 243, 385, 285),
    )
    person_at_left = DetectionResult(
        label="person",
        confidence=0.4225,
        bbox=(0, 20, 178, 348),
    )

    result = worker._filter_weapon_detections(
        [chair_false_positive],
        [person_at_left],
    )

    assert result == []


def test_weapon_filter_keeps_person_associated_or_high_confidence_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)
    monkeypatch.setattr(workers_ai.settings, "WEAPON_REQUIRE_PERSON_ASSOCIATION", True)
    monkeypatch.setattr(workers_ai.settings, "WEAPON_PERSON_EXPAND_RATIO", 0.35)
    monkeypatch.setattr(
        workers_ai.settings,
        "WEAPON_UNATTENDED_CONFIDENCE_THRESHOLD",
        0.85,
    )
    person = DetectionResult(
        label="person",
        confidence=0.91,
        bbox=(100, 50, 300, 350),
    )
    held_weapon = DetectionResult(
        label="guns",
        confidence=0.72,
        bbox=(280, 150, 350, 215),
    )
    unattended_high_confidence = DetectionResult(
        label="knife",
        confidence=0.91,
        bbox=(500, 100, 540, 200),
    )

    result = worker._filter_weapon_detections(
        [held_weapon, unattended_high_confidence],
        [person],
    )

    assert result == [held_weapon, unattended_high_confidence]


def test_weapon_filter_can_be_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)
    monkeypatch.setattr(workers_ai.settings, "WEAPON_REQUIRE_PERSON_ASSOCIATION", False)
    candidate = DetectionResult(
        label="guns",
        confidence=0.66,
        bbox=(294, 243, 385, 285),
    )

    assert worker._filter_weapon_detections([candidate], []) == [candidate]


def test_pose_person_fallback_is_marked_as_non_alert_evidence() -> None:
    observation = PoseObservation(
        track_id=9,
        bbox=(100, 40, 220, 340),
        confidence=0.36,
        keypoints=(),
        posture=Posture.UNKNOWN,
        posture_confidence=0.0,
        inside_zone=False,
        dwell_seconds=0.0,
    )

    detections = AIWorker._merge_pose_person_fallback([], [observation])

    assert len(detections) == 1
    assert detections[0].label == "person"
    assert detections[0].is_pose_fallback is True


@pytest.mark.asyncio
async def test_pose_person_fallback_does_not_raise_legacy_stranger_alert(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)

    import backend.auto_track_service as auto_track_service
    import backend.guard_mission_service as guard_mission_service

    monkeypatch.setattr(auto_track_service, "get_auto_track_service", lambda: None)
    monkeypatch.setattr(guard_mission_service, "get_guard_mission_service", lambda: None)
    alerts: list[DetectionResult] = []

    async def capture_alert(detection: DetectionResult, frame: bytes) -> None:
        del frame
        alerts.append(detection)

    monkeypatch.setattr(worker, "_raise_alert", capture_alert)
    fallback = DetectionResult(
        label="person",
        confidence=0.36,
        bbox=(100, 40, 220, 340),
        is_pose_fallback=True,
    )

    for _ in range(worker._stable_hits + 2):
        await worker._process_detection([fallback], b"empty-background")

    assert alerts == []
    assert worker._hits == 0

    primary = DetectionResult(
        label="person",
        confidence=0.91,
        bbox=(100, 40, 220, 340),
    )
    for _ in range(worker._stable_hits):
        await worker._process_detection([primary], b"real-person")

    assert alerts == [primary]


@pytest.mark.asyncio
async def test_weapon_detection_requires_stable_hits_and_respects_cooldown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)
    monkeypatch.setattr(workers_ai.settings, "WEAPON_ACTIVE_SECONDS", 3.0)
    monkeypatch.setattr(workers_ai.settings, "WEAPON_STABLE_HITS", 2)
    monkeypatch.setattr(workers_ai.settings, "WEAPON_CONFIRM_IOU_THRESHOLD", 0.4)
    monkeypatch.setattr(
        workers_ai.settings,
        "WEAPON_ALERT_COOLDOWN_SECONDS",
        10.0,
    )
    alerts: list[tuple[str, bytes]] = []

    async def capture_alert(detection: DetectionResult, frame: bytes) -> None:
        alerts.append((detection.label, frame))

    monkeypatch.setattr(worker, "_raise_alert", capture_alert)
    detection = DetectionResult(
        label="knife",
        confidence=0.81,
        bbox=(10, 20, 30, 40),
    )
    before = asyncio.get_running_loop().time()

    await worker._process_weapon_detections([detection], b"frame-1")
    assert alerts == []
    assert worker._weapon_active_until >= before + 3.0

    await worker._process_weapon_detections([detection], b"frame-2")
    assert alerts == [("knife", b"frame-2")]
    assert worker._weapon_alerts_count == 1

    await worker._process_weapon_detections([detection], b"frame-3")
    await worker._process_weapon_detections([detection], b"frame-4")
    assert alerts == [("knife", b"frame-2")]

    await worker._process_weapon_detections([], b"frame-5")
    assert worker._weapon_hits["knife"] == 0
    assert worker._weapon_last_bbox["knife"] is None


@pytest.mark.asyncio
async def test_weapon_confirmation_requires_spatially_consistent_bbox(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)
    monkeypatch.setattr(workers_ai.settings, "WEAPON_STABLE_HITS", 3)
    monkeypatch.setattr(workers_ai.settings, "WEAPON_CONFIRM_IOU_THRESHOLD", 0.4)
    monkeypatch.setattr(workers_ai.settings, "WEAPON_ALERT_COOLDOWN_SECONDS", 0.0)
    alerts: list[tuple[tuple[int, int, int, int] | None, bytes]] = []

    async def capture_alert(detection: DetectionResult, frame: bytes) -> None:
        alerts.append((detection.bbox, frame))

    monkeypatch.setattr(worker, "_raise_alert", capture_alert)
    first_location = DetectionResult(
        label="guns",
        confidence=0.82,
        bbox=(10, 20, 50, 70),
    )
    distant_location = DetectionResult(
        label="guns",
        confidence=0.91,
        bbox=(300, 250, 350, 310),
    )

    await worker._process_weapon_detections([first_location], b"frame-1")
    await worker._process_weapon_detections([distant_location], b"frame-2")
    await worker._process_weapon_detections([first_location], b"frame-3")
    assert alerts == []
    assert worker._weapon_hits["guns"] == 1

    await worker._process_weapon_detections([first_location], b"frame-4")
    await worker._process_weapon_detections([first_location], b"frame-5")

    assert alerts == [((10, 20, 50, 70), b"frame-5")]


@pytest.mark.asyncio
async def test_weapon_confirmation_follows_matching_bbox_not_highest_confidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)
    monkeypatch.setattr(workers_ai.settings, "WEAPON_STABLE_HITS", 2)
    monkeypatch.setattr(workers_ai.settings, "WEAPON_CONFIRM_IOU_THRESHOLD", 0.4)
    monkeypatch.setattr(workers_ai.settings, "WEAPON_ALERT_COOLDOWN_SECONDS", 0.0)
    alerts: list[DetectionResult] = []

    async def capture_alert(detection: DetectionResult, frame: bytes) -> None:
        del frame
        alerts.append(detection)

    monkeypatch.setattr(worker, "_raise_alert", capture_alert)
    initial = DetectionResult(
        label="knife",
        confidence=0.80,
        bbox=(100, 100, 160, 180),
    )
    matching = DetectionResult(
        label="knife",
        confidence=0.70,
        bbox=(104, 103, 164, 183),
    )
    unrelated = DetectionResult(
        label="knife",
        confidence=0.99,
        bbox=(400, 300, 460, 380),
    )

    await worker._process_weapon_detections([initial], b"frame-1")
    await worker._process_weapon_detections([unrelated, matching], b"frame-2")

    assert alerts == [matching]


@pytest.mark.asyncio
async def test_ai_ffmpeg_termination_kills_after_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)
    process = _FakeProcess(wait_never_finishes=True)

    await worker._terminate_ffmpeg_process(
        process,  # type: ignore[arg-type]
        reason="mission_inactive",
        terminate_timeout_s=0.01,
    )

    assert process.terminated is True
    assert process.killed is True
    assert process.returncode == -9
    assert worker._ffmpeg_last_exit_reason == "mission_inactive"


@pytest.mark.asyncio
async def test_ai_ffmpeg_command_avoids_timestamp_dependent_fps_and_hwaccel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)
    process = _FakeProcess()
    captured: dict[str, object] = {}

    async def fake_create_subprocess_exec(*command: str, **kwargs: object) -> _FakeProcess:
        captured["command"] = command
        captured["kwargs"] = kwargs
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    assert await worker._start_ffmpeg() is process
    command = captured["command"]
    assert isinstance(command, tuple)
    assert "-hwaccel" not in command
    assert "-use_wallclock_as_timestamps" not in command
    assert "-vsync" in command
    assert command[command.index("-vsync") + 1] == "0"
    video_filter = command[command.index("-vf") + 1]
    assert video_filter == "scale=640:360:flags=fast_bilinear"
    assert "fps=" not in video_filter


def test_ai_ffmpeg_rss_reads_proc_status() -> None:
    proc_root = Path("/tmp")
    # 使用 tmp_path 的测试在下一个用例覆盖；这里直接验证缺失进程安全返回。
    assert AIWorker._read_process_rss_bytes(999_999_999, proc_root) is None


def test_ai_ffmpeg_rss_parses_kibibytes(tmp_path: Path) -> None:
    process_dir = tmp_path / "4242"
    process_dir.mkdir()
    (process_dir / "status").write_text(
        "Name:\tffmpeg\nVmPeak:\t200000 kB\nVmRSS:\t131072 kB\n",
        encoding="utf-8",
    )

    assert AIWorker._read_process_rss_bytes(4242, tmp_path) == 128 * 1024 * 1024


@pytest.mark.asyncio
async def test_ai_ffmpeg_memory_watchdog_restarts_oversized_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)
    worker._ffmpeg_memory_check_interval_s = 0.001
    process = _FakeProcess(pid=4242)
    stop_event = asyncio.Event()
    monkeypatch.setattr(
        worker,
        "_read_process_rss_bytes",
        lambda pid: 700 * 1024 * 1024,
    )

    await worker._stop_ffmpeg_on_memory_limit(  # type: ignore[arg-type]
        process,
        stop_event,
    )

    assert process.terminated is True
    assert process.returncode == -15
    assert worker._ffmpeg_peak_rss_bytes == 700 * 1024 * 1024
    assert worker._ffmpeg_last_exit_reason.startswith("memory_limit_exceeded")


@pytest.mark.asyncio
async def test_ai_ffmpeg_output_backlog_forces_stream_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)
    process = _FakeProcess(
        stderr=_FakeStderr(
            b"[buffersink] 100 buffers queued in out_0_0, something may be wrong.\n"
        )
    )

    await worker._drain_stderr(process)  # type: ignore[arg-type]

    assert process.terminated is True
    assert worker._ffmpeg_last_exit_reason == "output_buffer_backlog"
    assert worker._ffmpeg_stream_unavailable is True
