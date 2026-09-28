from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from backend import workers_ai
from backend.pose_detection import PoseObservation, Posture
from backend.workers_ai import (
    AIWorker,
    AIWorkerFrameTimeout,
    DetectionResult,
    _AIFrame,
    _YoloDetector,
)


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

    async def communicate(self) -> tuple[bytes, bytes]:
        await self.wait()
        return b"", b""


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
    monkeypatch.setattr(workers_ai.settings, "FACE_RECOGNITION_ENABLED", False)
    monkeypatch.setattr(workers_ai.settings, "POSE_ENABLED", False)
    monkeypatch.setattr(workers_ai.settings, "WEATHER_ENABLED", False)
    monkeypatch.setattr(workers_ai.settings, "WEAPON_PERSON_CROP_ENABLED", False)
    worker = AIWorker(
        session_factory=_SessionFactory(),
        state_machine=object(),
        mavlink_gateway=_MavlinkGateway(),
        snapshot_dir=tmp_path,
    )
    worker._frame_process_timeout_s = 0.01
    return worker


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_exit_enabled", [True, False])
async def test_ai_timeout_recovers_without_exiting_or_overlapping(
    tmp_path, monkeypatch, legacy_exit_enabled,
):
    worker = _worker(tmp_path, monkeypatch)
    monkeypatch.setattr(workers_ai.settings, "AI_EXIT_ON_FRAME_TIMEOUT", legacy_exit_enabled)
    calls = []
    exits = []

    async def noop():
        pass

    async def timeout(stop_event):
        calls.append(1)
        if len(calls) == 1:
            raise AIWorkerFrameTimeout("test stalled inference")
        stop_event.set()

    monkeypatch.setattr(worker, "_warmup_models", noop, raising=False)
    monkeypatch.setattr(worker, "_update_current_task_id", noop)
    monkeypatch.setattr(worker, "_is_mission_active", lambda: True)
    monkeypatch.setattr(worker, "_run_ffmpeg_loop", timeout)
    monkeypatch.setattr(workers_ai.os, "_exit", exits.append)
    try:
        await asyncio.wait_for(worker.start(asyncio.Event()), 4.0)
    except asyncio.TimeoutError:
        pytest.fail("AI must recover after pending work completes")
    assert exits == []
    assert calls == [1, 1]
    assert worker._startup_status == "ready"


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

    await worker._wait_for_pending_inferences(asyncio.Event())

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

    await worker._wait_for_pending_inferences(asyncio.Event())

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


@pytest.mark.parametrize("continuous", [False, True])
def test_ai_continuous_detection_runs_without_task_or_tracking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    continuous: bool,
) -> None:
    worker = _worker(tmp_path, monkeypatch)
    monkeypatch.setattr(workers_ai.settings, "AI_CONTINUOUS_DETECTION_ENABLED", continuous)

    import backend.auto_track_service as auto_track_service
    import backend.fence_detection_service as fence_detection_service
    import backend.guard_mission_service as guard_mission_service

    monkeypatch.setattr(auto_track_service, "get_auto_track_service", lambda: None)
    monkeypatch.setattr(fence_detection_service, "get_fence_detection_service", lambda: None)
    monkeypatch.setattr(guard_mission_service, "get_guard_mission_service", lambda: None)

    assert worker._current_task_id is None
    assert worker._is_mission_active() is continuous
    worker._current_task_id = 1
    monkeypatch.setattr(workers_ai.settings, "AI_PASSIVE_SESSION_DETECTION_ENABLED", True)
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
            raise AssertionError("first processed AI frame must skip pose inference")

    worker._pose_detector = _UnexpectedPoseDetector()  # type: ignore[assignment]
    worker._pose_event_engine = _FakePoseEventEngine()  # type: ignore[assignment]

    async def noop(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(worker, "_process_detection", noop)

    # 原始帧号即使是偶数，第一次实际处理的 AI 帧也必须按 cycle=1 跳过。
    await worker._detect_and_process_frame(b"\0", frame_index=546)

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


def test_yolo_weapon_region_detection_maps_coordinates_and_suppresses_duplicates() -> None:
    detector = object.__new__(_YoloDetector)
    detector._np = np
    detector._frame_width = 4
    detector._frame_height = 4
    detector._inference_imgsz = 640
    detector._confidence = 0.25
    detector._target_classes = {"knife"}
    detector._class_names = {1: "knife"}
    fake_box = SimpleNamespace(
        cls=np.asarray([1]),
        conf=np.asarray([0.82]),
        xyxy=np.asarray([[1.0, 1.0, 3.0, 3.0]]),
        id=None,
    )

    class _FakeModel:
        def predict(self, *args: object, **kwargs: object) -> list[object]:
            del args, kwargs
            return [SimpleNamespace(boxes=[fake_box])]

    detector._model = _FakeModel()

    detections = detector.detect_many_regions(
        bytes(4 * 4 * 3),
        [(0, 0, 4, 4), (0, 0, 4, 4)],
        expand_ratio=0.0,
        max_regions=3,
        nms_iou=0.5,
    )

    assert detections == [
        DetectionResult(label="knife", confidence=0.82, bbox=(1, 1, 3, 3))
    ]


def test_yolo_weapon_class_aliases_keep_canonical_alert_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ultralytics

    fake_model = SimpleNamespace(
        names={
            0: "Blunt_Weapon",
            3: "Firearm",
            4: "Melee_Weapon",
        }
    )
    monkeypatch.setattr(
        ultralytics,
        "YOLO",
        lambda *args, **kwargs: fake_model,
    )

    detector = _YoloDetector(
        model_path="weapon-v13.engine",
        device="cpu",
        confidence=0.4,
        target_classes=["guns", "knife"],
        frame_width=1280,
        frame_height=720,
        inference_imgsz=640,
        use_bytetrack=False,
        class_aliases={"Firearm": "guns", "Melee_Weapon": "knife"},
    )

    assert detector._class_names == {
        0: "Blunt_Weapon",
        3: "guns",
        4: "knife",
    }


@pytest.mark.asyncio
async def test_weapon_person_crop_inference_uses_primary_person_regions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)
    calls: list[dict[str, object]] = []
    expected = DetectionResult(
        label="knife",
        confidence=0.82,
        bbox=(150, 120, 185, 210),
    )

    class _RegionDetector:
        def detect_many(self, frame: bytes) -> list[DetectionResult]:
            del frame
            raise AssertionError("person-crop mode must not run full-frame weapon inference")

        def detect_many_regions(
            self,
            frame: bytes,
            regions: list[tuple[int, int, int, int]],
            **kwargs: object,
        ) -> list[DetectionResult]:
            calls.append({"frame": frame, "regions": regions, **kwargs})
            return [expected]

    worker._weapon_detector = _RegionDetector()  # type: ignore[assignment]
    monkeypatch.setattr(workers_ai.settings, "WEAPON_PERSON_CROP_ENABLED", True)
    monkeypatch.setattr(workers_ai.settings, "WEAPON_PERSON_CROP_EXPAND_RATIO", 0.35)
    monkeypatch.setattr(workers_ai.settings, "WEAPON_PERSON_CROP_MAX_REGIONS", 3)
    monkeypatch.setattr(workers_ai.settings, "WEAPON_PERSON_CROP_NMS_IOU", 0.5)
    person = DetectionResult(
        label="person",
        confidence=0.91,
        bbox=(100, 50, 300, 350),
    )

    detections, elapsed_ms = await worker._infer_weapon(b"frame", [person])

    assert detections == [expected]
    assert elapsed_ms >= 0.0
    assert calls == [
        {
            "frame": b"frame",
            "regions": [(100, 50, 300, 350)],
            "expand_ratio": 0.35,
            "max_regions": 3,
            "nms_iou": 0.5,
        }
    ]


@pytest.mark.asyncio
async def test_weapon_person_crop_inference_skips_when_no_person_is_detected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)

    class _UnexpectedDetector:
        def detect_many_regions(self, *args: object, **kwargs: object) -> list[object]:
            raise AssertionError("no person means no weapon crop inference")

    worker._weapon_detector = _UnexpectedDetector()  # type: ignore[assignment]
    monkeypatch.setattr(workers_ai.settings, "WEAPON_PERSON_CROP_ENABLED", True)

    detections, elapsed_ms = await worker._infer_weapon(b"frame", [])

    assert detections == []
    assert elapsed_ms >= 0.0


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


def test_weapon_filter_rejects_oversized_full_frame_candidate(
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
    monkeypatch.setattr(workers_ai.settings, "WEAPON_MAX_FRAME_AREA_RATIO", 0.35)
    full_frame_false_positive = DetectionResult(
        label="guns",
        confidence=0.99,
        bbox=(0, 0, worker._frame_width, worker._frame_height),
    )
    centered_person = DetectionResult(
        label="person",
        confidence=0.91,
        bbox=(
            worker._frame_width // 3,
            0,
            worker._frame_width * 2 // 3,
            worker._frame_height,
        ),
    )

    result = worker._filter_weapon_detections(
        [full_frame_false_positive],
        [centered_person],
    )

    assert result == []


def test_weapon_filter_strict_carrying_mode_rejects_unattended_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)
    monkeypatch.setattr(workers_ai.settings, "WEAPON_REQUIRE_PERSON_ASSOCIATION", True)
    monkeypatch.setattr(workers_ai.settings, "WEAPON_PERSON_EXPAND_RATIO", 0.35)
    monkeypatch.setattr(
        workers_ai.settings,
        "WEAPON_UNATTENDED_CONFIDENCE_THRESHOLD",
        1.0,
    )
    monkeypatch.setattr(workers_ai.settings, "WEAPON_MAX_FRAME_AREA_RATIO", 1.0)
    unattended_candidate = DetectionResult(
        label="knife",
        confidence=0.99,
        bbox=(100, 100, 160, 220),
    )

    assert worker._filter_weapon_detections([unattended_candidate], []) == []


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


def test_pose_person_fallback_keeps_source_marker() -> None:
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
async def test_pose_person_fallback_requires_stability_and_deduplicates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)
    monkeypatch.setattr(workers_ai.settings, "POSE_STABLE_HITS", 3)

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
        track_id=9,
        face_status="unknown",
    )

    for _ in range(worker._stable_hits + 2):
        await worker._process_detection([fallback], b"empty-background")

    assert alerts == []
    assert worker._hits == 0

    for hits in (1, 2):
        worker._person_pose_hits[9] = hits
        await worker._process_detection([fallback], b"unconfirmed")
    assert alerts == []
    worker._person_pose_hits[9] = 3
    fallback.face_status, fallback.identity_id = "recognized", 1
    await worker._process_detection([fallback], b"known-person")
    assert alerts == []
    fallback.face_status, fallback.identity_id = "unknown", None
    await worker._process_detection([fallback], b"confirmed-person")
    await worker._process_detection([fallback], b"same-person")
    assert alerts == [fallback]

    primary = DetectionResult(
        label="person",
        confidence=0.91,
        bbox=(100, 40, 220, 340),
        track_id=10,
    )
    for _ in range(worker._stable_hits):
        await worker._process_detection([primary], b"real-person")

    assert alerts == [fallback, primary]
    worker._reset_detection_state()
    assert worker._person_pose_hits == {}
    assert worker._person_alert_last_seen == {}


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


@pytest.mark.asyncio
async def test_ai_stream_with_partial_frame_reconnects(tmp_path, monkeypatch):
    worker = _worker(tmp_path, monkeypatch)
    worker._ffmpeg_frame_timeout_s = 0.01
    process = _FakeProcess()
    process.stdout = asyncio.StreamReader()
    process.stdout.feed_data(b"partial frame")

    async def start():
        return process

    async def noop(*args):
        pass

    monkeypatch.setattr(worker, "_start_ffmpeg", start)
    monkeypatch.setattr(worker, "_update_current_task_id", noop)
    monkeypatch.setattr(worker, "_notify_auto_track_video_lost", noop)
    monkeypatch.setattr(worker, "_is_mission_active", lambda: True)
    await asyncio.wait_for(worker._run_ffmpeg_loop(asyncio.Event()), timeout=0.5)
    assert process.terminated
    assert worker._ffmpeg_last_exit_reason == "frame_read_timeout"


@pytest.mark.asyncio
@pytest.mark.parametrize("message,terminated", [
    (b"[rtsp] CSeq 8 expected, 0 received.\n", True),
    (b"[h264] time_scale/num_units_in_tick invalid or unsupported (0/0)\n", False),
])
async def test_ai_protocol_desync_reconnects_without_restarting_on_vui_warning(
    tmp_path, monkeypatch, message, terminated,
):
    worker = _worker(tmp_path, monkeypatch)
    process = _FakeProcess(stderr=_FakeStderr(message))
    await worker._drain_stderr(process)
    assert process.terminated is terminated
    if terminated:
        assert worker._ffmpeg_last_exit_reason == "RTSP_Protocol_Error"


@pytest.mark.asyncio
@pytest.mark.parametrize("tracking_override", [False, True])
async def test_fence_worker_only_passes_frames_to_tracking_when_linked(tmp_path, monkeypatch, tracking_override):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    worker = _worker(tmp_path, monkeypatch)
    worker._detector = _FastDetector()
    auto_track = _FakeAutoTrack(enabled=True)
    auto_track.process_frame = AsyncMock()
    guard = SimpleNamespace(enabled=True, process_frame=AsyncMock(), update_effective_fps=Mock())
    fence = SimpleNamespace(enabled=True, tracking_override=tracking_override, process_frame=Mock(return_value=[]))
    monkeypatch.setattr("backend.auto_track_service.get_auto_track_service", lambda: auto_track)
    monkeypatch.setattr("backend.guard_mission_service.get_guard_mission_service", lambda: guard)
    monkeypatch.setattr("backend.fence_detection_service.get_fence_detection_service", lambda: fence)

    await worker._detect_and_process_frame(b"\0", frame_index=1)
    assert auto_track.process_frame.await_count == int(tracking_override)
    guard.process_frame.assert_not_awaited()


@pytest.mark.asyncio
async def test_chest_damage_event_creates_formal_alert_with_snapshot(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock
    from backend import workers_ai_processing
    from backend.pose_detection import PoseEvent, Posture
    worker = _worker(tmp_path, monkeypatch)
    snapshot = tmp_path / "damage.jpg"
    monkeypatch.setattr(worker, "_save_snapshot", AsyncMock(return_value=(snapshot, "/damage.jpg")))
    alert = AsyncMock()
    monkeypatch.setattr(workers_ai_processing, "get_alert_service", lambda: alert)
    event = PoseEvent("POSE_DAMAGE_SUSPECTED", 3, .7, (0, 0, 100, 200), Posture.STANDING, .8)
    await worker._process_pose_events([event], b"frame")
    worker._save_snapshot.assert_awaited_once_with(b"frame")
    kwargs = alert.handle_ai_event.call_args.kwargs
    assert kwargs["event_code"] == "E_POSE_DAMAGE_SUSPECTED"
    assert kwargs["event_type"] == "POSE_DAMAGE_SUSPECTED"
    assert "疑似破坏动作" in kwargs["message"]
    assert kwargs["file_path"] == str(snapshot)


@pytest.mark.asyncio
@pytest.mark.parametrize('enabled', [False, True])
async def test_patrol_gates_behavior_and_keeps_weapon_detection(tmp_path, monkeypatch, enabled):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock
    worker = _worker(tmp_path, monkeypatch)
    worker._detector = _FastDetector()
    worker._pose_detector = object()
    worker._pose_event_engine = Mock()
    worker._pose_event_engine.update.return_value = ([], [])
    monkeypatch.setattr(workers_ai.settings, 'POSE_FRAME_SKIP', 1)
    monkeypatch.setattr(worker, '_infer_pose', AsyncMock(return_value=([], 1.0, 0.1)))
    monkeypatch.setattr(worker, '_is_weapon_due', lambda _, **kwargs: True)
    monkeypatch.setattr(worker, '_infer_weapon', AsyncMock(return_value=([], 0.1)))
    monkeypatch.setattr(worker, '_process_weapon_detections', AsyncMock())
    monkeypatch.setattr(worker, '_process_detection', AsyncMock())
    monkeypatch.setattr(worker, '_broadcast_pose_overlay', AsyncMock())
    monkeypatch.setattr(worker, '_report_face_service_fault', AsyncMock())
    fence = SimpleNamespace(enabled=enabled, tracking_override=False, process_frame=Mock(return_value=[]))
    monkeypatch.setattr('backend.fence_detection_service.get_fence_detection_service', lambda: fence)
    worker._weapon_active_until = time.monotonic() + 10
    await worker._detect_and_process_frame(b'frame', frame_index=1)
    # 围栏只决定姿态事件是否对外生效；刀枪是独立告警，不再受围栏开关影响。
    assert worker._pose_event_engine.update.call_args.kwargs['events_enabled'] is enabled
    assert worker._process_weapon_detections.await_count == 1
    worker._process_detection.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancelled_inference_is_retained_until_thread_finishes(tmp_path, monkeypatch):
    worker = _worker(tmp_path, monkeypatch)
    release = threading.Event()
    def slow():
        release.wait(1)
        return "old-frame-result"
    try:
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(worker._run_inference("test", slow), 0.02)
        assert len(worker._pending_inferences) == 1
        recovery = asyncio.create_task(worker._wait_for_pending_inferences(asyncio.Event()))
        await asyncio.sleep(0.02)
        assert not recovery.done()
        release.set()
        await asyncio.wait_for(recovery, 0.5)
        assert not worker._pending_inferences
        assert await worker._run_inference("new", lambda: "new-frame-result") == "new-frame-result"
    finally:
        release.set()


@pytest.mark.asyncio
async def test_warmup_runs_models_once_without_alert_processing(tmp_path, monkeypatch):
    worker = _worker(tmp_path, monkeypatch)
    calls = []
    class Detector:
        def detect_many(self, frame):
            assert len(frame) == worker._frame_size
            calls.append("detector")
            return []
    class Pose:
        def detect(self, frame):
            calls.append("pose")
            return []
    worker._detector = Detector()
    worker._weapon_detector = Detector()
    worker._pose_detector = Pose()
    await worker._warmup_models()
    await worker._warmup_models()
    assert calls == ["detector", "pose", "detector"]


@pytest.mark.asyncio
@pytest.mark.parametrize("main_person,pose_person", [(False, True), (False, False), (True, False)])
@pytest.mark.parametrize("cycle", [3, 6])
async def test_weapon_crops_use_current_pose_person_before_inference(tmp_path, monkeypatch, main_person, pose_person, cycle):
    from unittest.mock import AsyncMock, Mock
    worker = _worker(tmp_path, monkeypatch)
    monkeypatch.setattr(workers_ai.settings, "WEAPON_PERSON_CROP_ENABLED", True)
    monkeypatch.setattr(workers_ai.settings, "POSE_FRAME_SKIP", 2)
    monkeypatch.setattr(workers_ai.settings, "WEAPON_REQUIRE_PERSON_ASSOCIATION", True)
    worker._frames_processed = cycle - 1
    worker._detector = Mock()
    person = DetectionResult(label="person", confidence=.9, bbox=(100, 40, 220, 340))
    worker._detector.detect_many.return_value = [person] if main_person else []
    observation = PoseObservation(track_id=9, bbox=person.bbox, confidence=.8, keypoints=(),
        posture=Posture.UNKNOWN, posture_confidence=0., inside_zone=False, dwell_seconds=0.)
    worker._latest_pose_observations = [observation]  # stale display box must not trigger a crop
    worker._pose_detector = object()
    worker._pose_event_engine = Mock()
    worker._pose_event_engine.update.return_value = ([observation] if pose_person else [], [])
    monkeypatch.setattr(worker, "_infer_pose", AsyncMock(return_value=([], 1., .1)))
    monkeypatch.setattr(worker, "_is_weapon_due", lambda *args, **kwargs: True)
    knife = DetectionResult(label="knife", confidence=.8, bbox=(130, 100, 150, 170))
    monkeypatch.setattr(worker, "_infer_weapon", AsyncMock(return_value=([knife], .1)))
    monkeypatch.setattr(worker, "_process_weapon_detections", AsyncMock())
    for name in ["_process_detection", "_broadcast_pose_overlay", "_report_face_service_fault"]:
        monkeypatch.setattr(worker, name, AsyncMock())
    fence = SimpleNamespace(enabled=True, tracking_override=False, process_frame=Mock(return_value=[]))
    monkeypatch.setattr("backend.fence_detection_service.get_fence_detection_service", lambda: fence)
    await worker._detect_and_process_frame(b"frame", frame_index=1)
    crops = worker._infer_weapon.call_args.args[1]
    assert len(crops) == int(main_person or pose_person)
    assert worker._infer_pose.await_count == int(not main_person)
    accepted = worker._process_weapon_detections.call_args.args[0]
    assert accepted == ([knife] if main_person or pose_person else [])
    if crops:
        assert crops[0].bbox == person.bbox
