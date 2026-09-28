from __future__ import annotations

from collections.abc import Mapping

from backend.weather_detection import WeatherDetectionService


class FakeClassifier:
    device = "cpu"
    runtime = "fake"

    def __init__(self, outputs: list[Mapping[str, float]]) -> None:
        self._outputs = list(outputs)

    def predict(self, frame_bgr: bytes) -> Mapping[str, float]:
        assert frame_bgr == b"frame"
        return self._outputs.pop(0)


def test_weather_service_stabilizes_rain_after_required_votes() -> None:
    classifier = FakeClassifier(
        [
            {"rain": 0.91, "snow": 0.03, "sandstorm": 0.01, "dew": 0.05},
            {"rain": 0.88, "snow": 0.04, "sandstorm": 0.02, "dew": 0.06},
            {"rain": 0.93, "snow": 0.02, "sandstorm": 0.01, "dew": 0.04},
        ]
    )
    service = WeatherDetectionService(
        enabled=True,
        classifier=classifier,
        min_confidence=0.55,
        smoothing_window=3,
        stable_votes=3,
    )

    assert service.process_frame(b"frame")["state"] == "warming_up"
    assert service.process_frame(b"frame")["state"] == "warming_up"
    status = service.process_frame(b"frame")

    assert status["state"] == "ready"
    assert status["label"] == "rain"
    assert status["label_zh"] == "雨"
    assert status["frames_processed"] == 3
    assert status["radar_fused"] is False
    assert status["runtime"] == "fake"


def test_weather_service_maps_non_product_class_to_normal() -> None:
    service = WeatherDetectionService(
        enabled=True,
        classifier=FakeClassifier([{"fogsmog": 0.8, "rain": 0.1, "snow": 0.1}] * 3),
        stable_votes=3,
    )

    for _ in range(3):
        status = service.process_frame(b"frame")

    assert status["state"] == "ready"
    assert status["label"] == "normal"
    assert status["raw_label"] == "fogsmog"


def test_weather_service_rejects_low_confidence_adverse_label() -> None:
    service = WeatherDetectionService(
        enabled=True,
        classifier=FakeClassifier([{"sandstorm": 0.4, "dew": 0.35, "rain": 0.25}]),
        min_confidence=0.55,
        smoothing_window=1,
        stable_votes=1,
    )

    status = service.process_frame(b"frame")

    assert status["label"] == "normal"
    assert status["raw_label"] == "sandstorm"


def test_weather_service_maps_rime_to_snow_with_existing_threshold() -> None:
    for confidence, expected in ((0.8, "snow"), (0.4, "normal")):
        service = WeatherDetectionService(
            enabled=True,
            classifier=FakeClassifier([
                {"rime": confidence, "snow": 0.1, "dew": 0.1}
            ] * 3),
            min_confidence=0.55,
            stable_votes=3,
        )
        for _ in range(3):
            status = service.process_frame(b"frame")
        assert status["state"] == "ready"
        assert status["label"] == expected
        assert status["raw_label"] == "rime"
        assert status["probabilities"]["snow"] == round(confidence + 0.1, 4)
        assert status["probabilities"]["normal"] == round(0.9 - confidence, 4)


def test_weather_service_reports_initialization_failure_without_raising() -> None:
    service = WeatherDetectionService(
        enabled=True,
        classifier=None,
        initialization_error="model missing",
    )

    status = service.process_frame(b"frame")

    assert status["state"] == "failed"
    assert status["last_error"] == "model missing"
    assert status["frames_processed"] == 0


def test_three_sample_rounds_and_change_followups(monkeypatch):
    now = [100.0]
    monkeypatch.setattr('backend.weather_detection.time.monotonic', lambda: now[0])
    rounds = [('normal','normal','rain'), ('rain','rain','normal'),
              ('snow','rain','snow'), ('snow','snow','rain'),
              ('normal','rain','snow'), ('snow','snow','normal')]
    service = WeatherDetectionService(enabled=True, classifier=FakeClassifier(
        [{label: .9} for batch in rounds for label in batch]))
    expected = [('normal',300),('rain',10),('snow',10),('snow',300),('snow',10),('snow',300)]
    for index,(label,delay) in enumerate(expected):
        old = service.get_status()['label']
        for _ in range(2):
            assert service.process_frame(b'frame')['label'] == old
        status = service.process_frame(b'frame')
        assert status['label'] == label
        assert status['round_samples'] == 0
        assert status['rounds_processed'] == index+1
        assert service.next_sample_at == now[0]+delay
        now[0] = service.next_sample_at


def test_failed_round_discards_partial_votes_and_retries_in_ten_seconds(monkeypatch):
    monkeypatch.setattr('backend.weather_detection.time.monotonic', lambda: 100)
    service = WeatherDetectionService(enabled=True,classifier=FakeClassifier([
        {'rain': .9}, {}, {'snow': .9}, {'snow': .9}, {'normal': .9}]))
    service.process_frame(b'frame')
    failed = service.process_frame(b'frame')
    assert failed['state'] == 'degraded'
    assert failed['round_samples'] == 0
    assert service.next_sample_at == 110
    assert service.process_frame(b'frame')['label'] == 'unknown'
    assert service.process_frame(b'frame')['label'] == 'unknown'
    assert service.process_frame(b'frame')['label'] == 'snow'
