from __future__ import annotations

from types import SimpleNamespace
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from backend.auto_track_service import AutoTrackService
from backend.config import settings
from backend.face_recognition.engine import FaceExtraction
from backend.face_recognition.matcher import FaceMatcher, FaceTemplateRecord
from backend.face_recognition.runtime import FaceRecognitionRuntime
from backend.lightweight_tracker import LightweightIouTracker
from backend.services_face_identities import FaceIdentityService
from backend.tracking_types import DetectionResult


def _unit(index: int) -> np.ndarray:
    vector = np.zeros(128, dtype=np.float32)
    vector[index] = 1.0
    return vector


def test_matcher_accepts_known_and_rejects_unknown() -> None:
    matcher = FaceMatcher(threshold=0.45)
    matcher.replace([FaceTemplateRecord(7, 3, "测试人员A", _unit(0))])

    known = matcher.match(_unit(0))
    unknown = matcher.match(_unit(1))

    assert known.matched is True
    assert known.identity_id == 3
    assert known.display_name == "测试人员A"
    assert unknown.matched is False
    assert unknown.identity_id is None


class _FakeEngine:
    def detect(self, frame: np.ndarray):
        return [np.array([20, 20, 60, 60, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0.99], dtype=np.float32)]

    def extract_from_face(self, frame: np.ndarray, face: np.ndarray):
        return FaceExtraction(_unit(0), (20, 20, 80, 80), 0.99, 0.9)


def test_runtime_confirms_identity_and_expires_track() -> None:
    matcher = FaceMatcher(threshold=0.45)
    matcher.replace([FaceTemplateRecord(1, 9, "测试人员A", _unit(0))])
    runtime = FaceRecognitionRuntime(
        _FakeEngine(),  # type: ignore[arg-type]
        matcher,
        frame_skip=1,
        confirm_hits=3,
        track_ttl_seconds=1.0,
    )
    frame = np.zeros((120, 120, 3), dtype=np.uint8)
    person = SimpleNamespace(label="person", bbox=(0, 0, 110, 120), track_id=4)

    runtime.process(frame, [person], 1, now=1.0)
    assert person.face_status == "pending"
    runtime.process(frame, [person], 2, now=1.1)
    runtime.process(frame, [person], 3, now=1.2)
    assert person.face_status == "recognized"
    assert person.display_name == "测试人员A"

    # TTL 后相同轨迹号必须重新连续确认，避免旧姓名粘到新目标。
    runtime.process(frame, [person], 4, now=3.0)
    assert person.face_status == "pending"


def test_lightweight_tracker_reuses_iou_id() -> None:
    tracker = LightweightIouTracker(frame_width=640, max_age_frames=5)
    first = SimpleNamespace(bbox=(100, 50, 220, 300), confidence=0.9, track_id=-1)
    second = SimpleNamespace(bbox=(105, 55, 225, 305), confidence=0.9, track_id=-1)

    tracker.update([first], 1)
    tracker.update([second], 2)

    assert first.track_id > 0
    assert second.track_id == first.track_id


def test_registration_normalizes_exif_orientation_and_uses_enrollment_fallback(monkeypatch) -> None:
    monkeypatch.setattr(settings, "FACE_DETECT_THRESHOLD", 0.8)
    monkeypatch.setattr(settings, "FACE_ENROLL_DETECT_THRESHOLD", 0.7)
    image = Image.new("RGB", (40, 80), color=(120, 80, 40))
    exif = Image.Exif()
    exif[274] = 6  # 显示时顺时针旋转 90 度
    encoded = BytesIO()
    image.save(encoded, format="JPEG", exif=exif)

    calls: list[tuple[tuple[int, ...], float | None]] = []

    class _EnrollmentEngine:
        loaded = True

        def extract_exactly_one(self, frame, *, detect_threshold=None):
            calls.append((frame.shape, detect_threshold))
            if detect_threshold == 0.8:
                from backend.face_recognition.engine import FaceEngineError

                raise FaceEngineError("未检测到人脸")
            return FaceExtraction(_unit(0), (1, 1, 30, 30), 0.75, 0.8)

    service = FaceIdentityService()
    service.engine = _EnrollmentEngine()  # type: ignore[assignment]

    result = service.extract_template(encoded.getvalue())

    assert result.detection_score == 0.75
    assert calls[0][0] == (40, 80, 3)
    assert [threshold for _, threshold in calls[:4]] == [0.8, 0.8, 0.8, 0.8]
    assert calls[4][1] == 0.7


@pytest.mark.asyncio
async def test_passive_track_overlay_keeps_face_identity_fields(tmp_path: Path, monkeypatch) -> None:
    class _Zone:
        def is_inside_zone(self, anchor):
            return True

    class _Control:
        async def handle_command(self, command, **kwargs):
            return None

    service = AutoTrackService(
        zone_service=_Zone(),
        control_service=_Control(),
        event_broadcaster=SimpleNamespace(connection_count=0),
        state_machine=SimpleNamespace(),
        session_factory=None,
        snapshot_dir=tmp_path,
        frame_width=640,
        frame_height=360,
        default_enabled=False,
        stop_snapshot_enabled=False,
    )
    events = []

    async def capture(message_type, payload):
        events.append((message_type, payload))

    monkeypatch.setattr(service, "_broadcast_event", capture)
    detection = DetectionResult(
        bbox=(100, 40, 300, 350),
        confidence=0.94,
        class_name="person",
        track_id=8,
        identity_id=2,
        display_name="测试人员A",
        face_status="recognized",
        face_score=0.78,
    )
    await service.process_frame([detection], b"", frame_index=1)

    overlay = next(payload for message_type, payload in events if message_type == "TRACK_OVERLAY")
    assert service._enabled is False
    assert overlay["detections"][0]["display_name"] == "测试人员A"
    assert overlay["detections"][0]["identity_id"] == 2
    assert overlay["detections"][0]["face_status"] == "recognized"
    assert overlay["detections"][0]["face_score"] == 0.78
