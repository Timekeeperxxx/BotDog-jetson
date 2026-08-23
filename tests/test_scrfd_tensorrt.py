from __future__ import annotations

import numpy as np

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
