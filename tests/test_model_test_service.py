import json
import os
import subprocess
from pathlib import Path

import cv2
import numpy as np
import pytest

from backend import model_test_service
from backend.pose_detection import PoseKeypoint, RawPose


class _CopyRunner:
    def process(self, frame: np.ndarray, confidence: float) -> tuple[np.ndarray, int]:
        assert confidence == 0.35
        return frame.copy(), 3


def test_process_image_writes_annotated_result(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    destination = tmp_path / "result.jpg"
    assert cv2.imwrite(str(source), np.zeros((32, 48, 3), dtype=np.uint8))

    frames, detections = model_test_service.process_image(
        source,
        destination,
        _CopyRunner(),
        0.35,
    )

    assert frames == 1
    assert detections == 3
    assert destination.is_file()
    assert cv2.imread(str(destination)).shape == (32, 48, 3)


def test_process_video_samples_frames_and_writes_browser_h264(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    destination = tmp_path / "result.mp4"
    writer = cv2.VideoWriter(
        str(source),
        cv2.VideoWriter_fourcc(*"mp4v"),
        10.0,
        (48, 32),
    )
    assert writer.isOpened()
    for index in range(20):
        writer.write(np.full((32, 48, 3), index, dtype=np.uint8))
    writer.release()

    result = model_test_service.process_video(
        source,
        destination,
        _CopyRunner(),
        0.35,
        target_fps=5.0,
    )

    assert result.source_frames == 20
    assert result.processed_frames == 10
    assert result.detections == 30
    assert result.source_fps == 10.0
    assert result.processing_fps == 5.0
    probe = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,pix_fmt,nb_frames",
            "-of", "json", str(destination),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    stream = json.loads(probe.stdout)["streams"][0]
    assert stream["codec_name"] == "h264"
    assert stream["pix_fmt"] == "yuv420p"
    assert int(stream["nb_frames"]) == 10


def test_normalize_yolo_output_transposes_channel_first_shape() -> None:
    output = np.zeros((1, 7, 20), dtype=np.float32)
    normalized = model_test_service.normalize_yolo_output(output)
    assert normalized.shape == (20, 7)


def test_pose_status_distinguishes_seated_leg_geometry() -> None:
    points = [PoseKeypoint(0.0, 0.0, 0.0) for _ in range(17)]
    for hip, knee, ankle, x_offset in ((11, 13, 15, 0.0), (12, 14, 16, 30.0)):
        points[hip] = PoseKeypoint(10.0 + x_offset, 40.0, 0.9)
        points[knee] = PoseKeypoint(22.0 + x_offset, 42.0, 0.9)
        points[ankle] = PoseKeypoint(23.0 + x_offset, 70.0, 0.9)
    pose = RawPose(
        bbox=(0, 0, 80, 100),
        confidence=0.9,
        keypoints=tuple(points),
    )
    assert model_test_service._looks_seated(pose, 0.35)


def test_pose_preview_labels_shared_damage_event():
    runner = model_test_service.PoseStatusTensorRTRunner.__new__(
        model_test_service.PoseStatusTensorRTRunner
    )
    label, _ = runner._status_for_pose(None, None, "POSE_DAMAGE_SUSPECTED")
    assert label == "疑似破坏动作"


@pytest.mark.parametrize('event_type,label', [
    ('POSE_VAULTING_SUSPECTED', '疑似翻越'),
    ('POSE_CLIMBING_SUSPECTED', '疑似攀爬'),
])
def test_pose_preview_distinguishes_vaulting_and_climbing(event_type, label):
    runner = model_test_service.PoseStatusTensorRTRunner.__new__(
        model_test_service.PoseStatusTensorRTRunner
    )
    assert runner._status_for_pose(None, None, event_type)[0] == label


def test_pose_preview_keeps_vault_label_when_loitering_also_occurs(monkeypatch):
    from types import SimpleNamespace
    from collections import Counter
    import torch
    from backend.pose_detection import PoseObservation, PoseEvent, Posture

    frame = np.zeros((32, 48, 3), dtype=np.uint8)
    points = tuple(PoseKeypoint(0, 0, .9) for _ in range(17))
    observation = PoseObservation(1, (0, 0, 20, 30), .9, points, Posture.STANDING, .7, True, 20)
    events = [PoseEvent(kind, 1, .7, (0, 0, 20, 30), Posture.STANDING, .2)
              for kind in ('POSE_VAULTING_SUSPECTED', 'POSE_LOITERING')]
    result = SimpleNamespace(
        boxes=SimpleNamespace(xyxy=torch.tensor([[0, 0, 20, 30]]), conf=torch.tensor([.9])),
        keypoints=SimpleNamespace(data=torch.tensor([[[0, 0, .9]] * 17])),
        plot=lambda **_: frame,
    )
    runner = model_test_service.PoseStatusTensorRTRunner.__new__(model_test_service.PoseStatusTensorRTRunner)
    runner.model = SimpleNamespace(predict=lambda *_args, **_kwargs: [result])
    runner.event_engine = SimpleNamespace(update=lambda *_args, **_kwargs: ([observation], events))
    runner.frame_time = 20
    runner.label_counts = Counter()
    labels = []
    monkeypatch.setattr(model_test_service, '_draw_unicode_status_labels',
                        lambda image, statuses: labels.extend(statuses) or image)
    runner.process(frame, .35)
    assert labels[0][1] == '#1 疑似翻越'


def test_resolve_result_file_rejects_traversal(tmp_path: Path) -> None:
    result = tmp_path / "20260811-test-face.jpg"
    result.write_bytes(b"image")

    assert model_test_service.resolve_result_file(result.name, tmp_path) == result
    assert model_test_service.resolve_result_file("../20260811-test-face.jpg", tmp_path) is None
    assert model_test_service.resolve_result_file("not-a-result.txt", tmp_path) is None


def test_cleanup_stale_outputs_only_removes_expired_files(tmp_path: Path) -> None:
    stale = tmp_path / "stale.jpg"
    recent = tmp_path / "recent.jpg"
    stale.write_bytes(b"old")
    recent.write_bytes(b"new")
    stale.touch()
    recent.touch()
    now = recent.stat().st_mtime
    stale_age = now - model_test_service.MODEL_TEST_RESULT_TTL_SECONDS - 1
    stale.touch()
    os.utime(stale, (stale_age, stale_age))

    model_test_service.cleanup_stale_outputs(tmp_path, now=now)

    assert not stale.exists()
    assert recent.exists()
