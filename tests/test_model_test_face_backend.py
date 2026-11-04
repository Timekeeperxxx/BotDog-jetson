from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from backend import model_test_service as service


@pytest.mark.parametrize('backend,runtime,suffix,description', [
    ('scrfd_tensorrt', 'TensorRT', '.engine', 'SCRFD'),
    ('yunet', 'ONNX / CPU', '.onnx', 'YuNet'),
])
def test_face_option_matches_configured_detector(monkeypatch, tmp_path, backend, runtime, suffix, description):
    path = tmp_path / ('face' + suffix)
    path.write_bytes(b'existing-model')
    monkeypatch.setattr(service.settings, 'FACE_DETECT_BACKEND', backend)
    monkeypatch.setattr(service.settings, 'FACE_DETECT_MODEL_PATH', str(path))
    model = service.get_model_definitions()['face']
    assert model.kind == backend
    assert model.runtime == runtime
    assert model.path == path
    assert description in model.description
    assert model.available
    path.unlink()
    assert not model.available


def test_unknown_face_backend_is_reported(monkeypatch):
    monkeypatch.setattr(service.settings, 'FACE_DETECT_BACKEND', 'unknown')
    with pytest.raises(ValueError, match='不支持的人脸检测后端'):
        service.get_model_definitions()


def test_scrfd_dispatch_uses_scrfd_runner(monkeypatch, tmp_path):
    expected = object()
    seen = []
    monkeypatch.setattr(service, 'SCRFDTensorRTRunner', lambda path: seen.append(path) or expected)
    service._build_runner.cache_clear()
    try:
        path = tmp_path / 'face.engine'
        assert service._build_runner('scrfd_tensorrt', str(path), ('face',)) is expected
        assert seen == [path]
    finally:
        service._build_runner.cache_clear()


@pytest.mark.parametrize('has_face', [True, False])
def test_scrfd_runner_passes_threshold_and_draws_current_faces(monkeypatch, has_face):
    from backend.face_recognition import scrfd_tensorrt

    image = np.zeros((80, 120, 3), dtype=np.uint8)
    face = np.asarray([10, 20, 30, 40, 17, 30, 31, 30, 24, 40, 18, 50, 31, 50, .91], dtype=np.float32)
    calls = []
    class Detector:
        def __init__(self, path, *, input_size, nms_threshold):
            calls.append((path, input_size, nms_threshold))
        def detect(self, frame, *, score_threshold):
            assert frame is image
            assert score_threshold == .65
            return [face] if has_face else []
    monkeypatch.setattr(scrfd_tensorrt, 'SCRFDTensorRTDetector', Detector)
    monkeypatch.setattr(service.settings, 'FACE_DETECT_INPUT_SIZE', 640)
    monkeypatch.setattr(service.settings, 'FACE_DETECT_NMS_THRESHOLD', .4)
    runner = service.SCRFDTensorRTRunner(Path('/test/face.engine'))
    annotated, count = runner.process(image, .65)
    assert calls == [(Path('/test/face.engine'), 640, .4)]
    assert count == int(has_face)
    assert annotated.shape == image.shape and annotated.dtype == image.dtype
    assert annotated is not image
    assert bool(annotated.any()) == has_face
    assert not image.any()


def test_yunet_runner_keeps_onnx_detection_contract(monkeypatch):
    image = np.zeros((80, 120, 3), dtype=np.uint8)
    calls = []
    detector = SimpleNamespace(
        setInputSize=lambda size: calls.append(('size',size)),
        setScoreThreshold=lambda score: calls.append(('score',score)),
        detect=lambda frame: (None, None),
    )
    def create(*args):
        calls.append(('model',args[0]))
        return detector
    monkeypatch.setattr(service.cv2, 'FaceDetectorYN', SimpleNamespace(create=create))
    runner = service.YuNetRunner(Path('/test/face.onnx'))
    result, count = runner.process(image, .7)
    assert calls == [('model','/test/face.onnx'),('size',(120,80)),('score',.7)]
    assert count == 0
    assert np.array_equal(result,image) and result is not image
