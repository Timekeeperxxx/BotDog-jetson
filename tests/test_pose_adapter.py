from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from backend.pose_detection import UltralyticsPoseDetector


@pytest.mark.parametrize('tracked', [False, True])
def test_pose_adapter_preserves_boxes_scores_and_keypoints_with_one_box_copy(tracked):
    class Rows:
        def __init__(self, data):
            self.data = np.asarray(data, dtype=np.float32)
            self.copies = 0

        def detach(self):
            return self

        def cpu(self):
            self.copies += 1
            return self

        def tolist(self):
            return self.data.tolist()

    detector = UltralyticsPoseDetector.__new__(UltralyticsPoseDetector)
    detector._np = np
    detector._frame_width, detector._frame_height = 4, 2
    detector._confidence, detector._inference_imgsz, detector._device = .35, 640, 'cpu'
    rows = [[1.4, 2.6, 10.5, 20.5, *([123] if tracked else []), .875, 0]]
    boxes = Rows(rows)
    points = Rows([[[i+.25, i+.75, .5] for i in range(17)]])
    detector._model = SimpleNamespace(predict=Mock(return_value=[SimpleNamespace(
        boxes=SimpleNamespace(data=boxes), keypoints=SimpleNamespace(data=points),
    )]))
    frame = np.arange(24, dtype=np.uint8).reshape(2, 4, 3)

    poses = detector.detect(frame.tobytes())

    assert len(poses) == 1
    assert poses[0].bbox == (1, 3, 10, 20)
    assert poses[0].confidence == .875
    assert [(p.x, p.y, p.confidence) for p in poses[0].keypoints] == [
        (i+.25, i+.75, .5) for i in range(17)
    ]
    assert boxes.copies == 1 and points.copies == 1
    np.testing.assert_array_equal(detector._model.predict.call_args.args[0], frame)
