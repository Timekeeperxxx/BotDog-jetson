from types import SimpleNamespace
import sys

import numpy as np
import pytest

from backend.workers_ai_packages import BackpackDetector, PackageDualDetector, PackageDetection


def detector_with_scores(tmp_path, monkeypatch, full_score, crop_score, budget=1):
    path = tmp_path / 'two-class.pt'
    path.touch()
    calls = []

    class Model:
        names = {0: 'backpack', 1: 'suitcase'}

        def predict(self, image, **kwargs):
            calls.append((image.shape, kwargs))
            score = full_score if len(calls) == 1 else crop_score
            coordinates = [20, 16, 32, 28] if len(calls) == 1 else [12, 12, 24, 24]
            box = SimpleNamespace(cls=np.array([0]), conf=np.array([score]),
                                  xyxy=np.array([coordinates]))
            return [SimpleNamespace(boxes=[box])]

    monkeypatch.setitem(sys.modules, 'ultralytics',
                        SimpleNamespace(YOLO=lambda *args, **kwargs: Model()))
    detector = BackpackDetector(str(path), 'cpu', .4, 640, 64, 48,
                                refine=True, include_luggage=True,
                                max_refine_crops=budget, refine_policy="weak")
    return detector, calls


@pytest.mark.parametrize('score', [.26, .3, .39])
def test_backpack_between_proposal_and_final_cutoffs_can_be_rescued(tmp_path, monkeypatch, score):
    detector, calls = detector_with_scores(tmp_path, monkeypatch, score, .8)
    result = detector.detect_many(bytes(64 * 48 * 3))
    assert len(calls) == 2
    assert len(result) == 1
    assert result[0].label == 'backpack'
    assert result[0].confidence == .8
    assert result[0].bbox == (20, 16, 32, 28)
    assert result[0].source == 'refined'
    assert detector.last_status['regions_evaluated'] == 2


def test_confident_backpack_keeps_whole_frame_detection(tmp_path, monkeypatch):
    detector, calls = detector_with_scores(tmp_path, monkeypatch, .7, .8)
    result = detector.detect_many(bytes(64 * 48 * 3))
    assert len(calls) == 1
    assert result[0].confidence == .7
    assert result[0].source == 'full'


def test_crop_still_has_to_pass_final_confidence(tmp_path, monkeypatch):
    detector, calls = detector_with_scores(tmp_path, monkeypatch, .3, .35)
    assert detector.detect_many(bytes(64 * 48 * 3)) == []
    assert len(calls) == 2


def detector_with_predictions(tmp_path, monkeypatch, predictions):
    path = tmp_path / 'two-class.pt'
    path.touch()
    calls = []

    class Model:
        names = {0: 'backpack', 1: 'suitcase'}

        def predict(self, image, **kwargs):
            calls.append((image.shape, kwargs))
            boxes = [SimpleNamespace(cls=np.array([c]), conf=np.array([score]),
                                     xyxy=np.array([box]))
                     for c, score, box in predictions[len(calls)-1]]
            return [SimpleNamespace(boxes=boxes)]

    monkeypatch.setitem(sys.modules, 'ultralytics',
                        SimpleNamespace(YOLO=lambda *args, **kwargs: Model()))
    return BackpackDetector(str(path), 'cpu', .4, 640, 64, 48,
                            refine=True, include_luggage=True, max_refine_crops=1,
                            refine_policy="weak"), calls


def test_confident_suitcase_does_not_trigger_redundant_crop(tmp_path, monkeypatch):
    detector, calls = detector_with_predictions(tmp_path, monkeypatch,
                                               [[(1, .8, [20, 16, 32, 28])]])
    result = detector.detect_many(bytes(64 * 48 * 3))
    assert len(calls) == 1
    assert result[0].label == 'suitcase' and result[0].confidence == .8
    assert result[0].source == 'full'


def test_weak_fragment_inside_accepted_bag_does_not_consume_crop_budget(tmp_path, monkeypatch):
    detector, calls = detector_with_predictions(tmp_path, monkeypatch, [[
        (1, .8, [10, 8, 50, 44]), (0, .2, [20, 16, 30, 28])]])
    result = detector.detect_many(bytes(64 * 48 * 3))
    assert len(calls) == 1 and len(result) == 1
    assert result[0].bbox == (10, 8, 50, 44)
    assert detector.last_status['refine_skipped_covered'] == 1


def test_crop_cannot_accept_a_different_object_outside_parent_candidate(tmp_path, monkeypatch):
    detector, calls = detector_with_predictions(tmp_path, monkeypatch,
        [[(0, .2, [20, 16, 32, 28])], [(0, .9, [30, 0, 34, 4])]])
    assert detector.detect_many(bytes(64 * 48 * 3)) == []
    assert len(calls) == 2
    assert detector.last_status['refine_rejected_unrelated'] == 1


def test_high_scoring_crop_fragment_does_not_replace_existing_whole_bag(tmp_path, monkeypatch):
    detector, calls = detector_with_predictions(tmp_path, monkeypatch,
        [[(0, .65, [20, 10, 44, 40]), (1, .1, [8, 20, 28, 36])],
         [(0, .95, [20, 16, 28, 32])]])
    result = detector.detect_many(bytes(64 * 48 * 3))
    assert len(calls) == 2 and len(result) == 1
    assert result[0].bbox == (20, 10, 44, 40)
    assert result[0].confidence == .65
    assert detector.last_status['refine_rejected_fragments'] == 1


def test_dual_detector_preserves_whole_bag_and_keeps_uncovered_detail(tmp_path, monkeypatch):
    primary_path, detail_path = tmp_path / 'primary.pt', tmp_path / 'detail.pt'
    primary_path.touch()
    detail_path.touch()
    empty = False
    detail_calls = []

    def boxes(rows):
        return [SimpleNamespace(boxes=[SimpleNamespace(cls=np.array([c]),
                conf=np.array([score]), xyxy=np.array([box])) for c, score, box in rows])]

    class PrimaryModel:
        names = {0: 'backpack', 1: 'suitcase'}

        def predict(self, image, **kwargs):
            return boxes([] if empty else [(0, .8, [20, 10, 44, 40])])

    class DetailModel:
        names = {0: 'backpack', 1: 'suitcase', 2: 'handbag'}

        def predict(self, image, **kwargs):
            detail_calls.append(image.shape)
            if empty:
                return boxes([])
            if len(detail_calls) == 1:
                return boxes([(1, .6, [20, 10, 44, 25]),
                              (1, .65, [48, 16, 60, 32])])
            return boxes([(1, .75, [12, 16, 24, 32])])

    monkeypatch.setitem(sys.modules, 'ultralytics', SimpleNamespace(YOLO=lambda path, **kw:
                        PrimaryModel() if str(path) == str(primary_path) else DetailModel()))
    detector = PackageDualDetector(str(primary_path), str(detail_path), 'cpu', .4,
                                   640, 64, 48, max_refine_crops=1)
    result = detector.detect_many(bytes(64 * 48 * 3))
    assert [(d.label, d.bbox) for d in result] == [
        ('backpack', (20, 10, 44, 40)), ('suitcase', (48, 16, 60, 32))]
    assert [d.confidence for d in result] == [.8, .75]
    assert detector.last_status['regions_evaluated'] == 3
    assert detector.last_status['output_labels'] == ['backpack', 'suitcase']
    empty = True
    assert detector.detect_many(bytes(64 * 48 * 3)) == []


def test_package_factory_uses_optional_detail_model(monkeypatch):
    from backend import workers_ai_packages as module
    calls = []
    sentinel = object()

    def dual(*args, **kwargs):
        calls.append((args, kwargs))
        return sentinel

    monkeypatch.setattr(module, 'PackageDualDetector', dual)
    monkeypatch.setattr(module.settings, 'PACKAGE_MODEL_PATH', 'primary.engine')
    monkeypatch.setattr(module.settings, 'PACKAGE_DETAIL_MODEL_PATH', 'detail.engine')
    monkeypatch.setattr(module.settings, 'PACKAGE_REVIEW_ENABLED', False)
    worker = module.PackageWorkerMixin()
    worker._frame_width, worker._frame_height = 64, 48
    detector, service = worker._create_package_components()
    assert detector is sentinel
    assert calls[0][0][:2] == ('primary.engine', 'detail.engine')
    assert service is not None


def test_dual_output_collapses_nested_live_replay_boxes_without_merging_adjacent_bag(
        tmp_path, monkeypatch):
    from backend import workers_ai_packages as module

    # Actual replay duplicate: IoU below .5, but 97% of the smaller box
    # belongs to the larger box. Both previously formed alarm tracks.
    large = PackageDetection('suitcase', .691, (288, 203, 351, 321))
    small = PackageDetection('suitcase', .4311, (290, 260, 353, 321))
    adjacent = PackageDetection('backpack', .7, (370, 260, 430, 321))

    class Detector:
        names = {0: 'backpack', 1: 'suitcase'}
        target_labels = {'backpack', 'suitcase'}
        last_status = {'regions_evaluated': 1}

        def __init__(self, path, *args, **kwargs):
            self.primary = path == 'primary'

        def detect_many(self, frame, **kwargs):
            return [small, adjacent] if self.primary else [large]

    # Retain the tested NMS implementation while substituting only inference.
    Detector._deduplicate = staticmethod(BackpackDetector._deduplicate)
    monkeypatch.setattr(module, 'BackpackDetector', Detector)
    detector = PackageDualDetector('primary', 'detail', 'cpu', .4, 640, 640, 360)
    result = detector.detect_many(bytes(640 * 360 * 3))
    assert result == [adjacent, large]
    assert result[1].confidence == .691 and result[1].label == 'suitcase'
    assert BackpackDetector._deduplicate([large, small]) == [large, small]
