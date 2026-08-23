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
        smoothing_window=5,
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
