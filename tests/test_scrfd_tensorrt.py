from __future__ import annotations

import numpy as np
import pytest

from backend.face_recognition.scrfd_tensorrt import (
    _letterbox_blob,
    _nms,
    decode_scrfd_predictions,
)


def test_letterbox_blob_uses_top_left_padding_and_scrfd_normalization() -> None:
    image = np.full((100, 200, 3), (10, 20, 30), dtype=np.uint8)

    blob, scale = _letterbox_blob(image, 640)

    assert blob.shape == (1, 3, 640, 640)
    assert blob.dtype == np.float32
    assert scale == 3.2
    assert np.isclose(blob[0, 0, 0, 0], (30.0 - 127.5) / 128.0)
    assert np.isclose(blob[0, 2, 0, 0], (10.0 - 127.5) / 128.0)
    assert np.isclose(blob[0, :, 500, 0], -127.5 / 128.0).all()


def test_decode_scrfd_predictions_builds_sface_compatible_row() -> None:
    scores = np.zeros((12800, 1), dtype=np.float32)
    boxes = np.zeros((12800, 4), dtype=np.float32)
    keypoints = np.zeros((12800, 10), dtype=np.float32)
    # stride=8, grid=(x=20, y=10), first of two anchors => center=(160, 80)
    index = 2 * (10 * 80 + 20)
    scores[index] = 0.9
    boxes[index] = (2, 3, 4, 5)
    keypoints[index] = (-1, -1, 1, -1, 0, 0, -0.5, 1, 0.5, 1)

    faces = decode_scrfd_predictions(
        {8: (scores, boxes, keypoints)},
        input_size=640,
        image_shape=(640, 640),
        scale=1.0,
        score_threshold=0.5,
        nms_threshold=0.4,
    )

    assert len(faces) == 1
    np.testing.assert_allclose(faces[0][:4], (144, 56, 48, 64))
    np.testing.assert_allclose(
        faces[0][4:14],
        (152, 72, 168, 72, 160, 80, 156, 88, 164, 88),
    )
    assert np.isclose(faces[0][14], 0.9)


def test_nms_keeps_highest_scoring_overlapping_face() -> None:
    boxes = np.asarray(
        [[10, 10, 100, 100], [12, 12, 98, 98], [200, 200, 260, 260]],
        dtype=np.float32,
    )
    scores = np.asarray([0.95, 0.80, 0.70], dtype=np.float32)

    assert _nms(boxes, scores, 0.4) == [0, 2]


@pytest.mark.parametrize('shape', [(360, 640), (641, 359), (127, 127), (33, 1024)])
def test_preprocessing_is_bit_exact_to_numpy_for_all_pixel_values(shape) -> None:
    import cv2

    height, width = shape
    image = (np.arange(height * width * 3) % 256).astype(np.uint8).reshape(height, width, 3)
    if height > width:
        resized_height, resized_width = 640, max(1, int(640 / (height / width)))
    else:
        resized_width, resized_height = 640, max(1, int(640 * (height / width)))
    padded = np.zeros((640, 640, 3), dtype=np.uint8)
    padded[:resized_height, :resized_width] = cv2.resize(image, (resized_width, resized_height))
    expected = np.ascontiguousarray(
        ((padded[:, :, ::-1].astype(np.float32) - 127.5) / 128.0).transpose(2, 0, 1)[None]
    )

    actual, scale = _letterbox_blob(image, 640)

    np.testing.assert_array_equal(actual, expected)
    assert actual.dtype == np.float32 and actual.flags.c_contiguous
    assert scale == resized_height / height


def test_async_outputs_are_ready_before_decode_and_returned_faces_own_data() -> None:
    from contextlib import nullcontext
    from threading import Lock
    from types import SimpleNamespace
    from backend.face_recognition.scrfd_tensorrt import SCRFDTensorRTDetector

    pending = []
    submitted = []

    class Host:
        def __init__(self, shape):
            self.data = np.full(shape, np.nan, dtype=np.float32)

        def copy_(self, source, *, non_blocking):
            assert non_blocking is True
            submitted.append(source)
            pending.append(lambda: np.copyto(self.data, source))

        def numpy(self):
            assert not pending, 'CPU decode must wait for all CUDA copies'
            return self.data

    def synchronize():
        for copy in pending:
            copy()
        pending.clear()

    detector = SCRFDTensorRTDetector.__new__(SCRFDTensorRTDetector)
    detector._input_size = 32
    detector._device = 'cuda:0'
    detector._nms_threshold = .4
    detector._lock = Lock()
    stream = SimpleNamespace(cuda_stream=1, synchronize=synchronize)
    detector._torch = SimpleNamespace(
        inference_mode=nullcontext, from_numpy=lambda blob: blob,
        cuda=SimpleNamespace(current_stream=lambda **kwargs: stream),
    )
    detector._input_tensor = SimpleNamespace(copy_=lambda blob: None)
    detector._context = SimpleNamespace(execute_async_v3=lambda **kwargs: True)
    detector._prediction_names = {}
    detector._output_tensors = {}
    detector._host_output_tensors = {}
    for stride in (8, 16, 32):
        names = tuple(f'{stride}_{width}' for width in (1, 4, 10))
        detector._prediction_names[stride] = names
        rows = 2 * (32 // stride) ** 2
        for name, width in zip(names, (1, 4, 10)):
            detector._output_tensors[name] = np.zeros((rows, width), dtype=np.float32)
            detector._host_output_tensors[name] = Host((rows, width))
    detector._output_tensors['8_1'][10] = .9
    detector._output_tensors['8_4'][10] = 1
    image = np.zeros((32, 32, 3), dtype=np.uint8)

    faces = detector.detect(image, score_threshold=.5)
    assert len(faces) == 1 and len(submitted) == 9
    expected = faces[0].copy()
    detector._output_tensors['8_1'].fill(0)
    assert detector.detect(image, score_threshold=.5) == []
    np.testing.assert_array_equal(faces[0], expected)
