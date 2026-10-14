from __future__ import annotations

import pytest
from backend.weather_detection import WeatherDetectionService

class FakeClassifier:
    device = 'cpu'
    runtime = 'fake'
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = 0
    def predict(self, frame):
        self.calls += 1
        return self.outputs.pop(0)

@pytest.fixture
def clock(monkeypatch):
    now = [100.0]
    monkeypatch.setattr('backend.weather_detection.time.monotonic', lambda: now[0])
    return now

def sample_round(service, clock):
    start = max(clock[0], service.next_sample_at)
    status = None
    for index in range(service.get_status()['smoothing_window']):
        clock[0] = start + index * service.get_status()['sample_interval_seconds']
        status = service.process_frame(b'frame')
    return status

def make_service(labels, **kwargs):
    return WeatherDetectionService(enabled=True, classifier=FakeClassifier(
        [{label: 0.9} if isinstance(label, str) else label for label in labels]), **kwargs)

def test_confirms_only_after_six_spaced_frames_and_ten_seconds(clock):
    service = make_service(['rain'] * 6)
    for index in range(5):
        clock[0] = 100 + index * 2
        status = service.process_frame(b'frame')
        assert status['label'] == 'unknown'
        assert status['observed_at'] is None
    clock[0] = 110
    status = service.process_frame(b'frame')
    assert status['label'] == 'rain'
    assert status['state'] == 'ready'
    assert status['frames_processed'] == 6
    assert status['result_status'] == 'confirmed'
    assert '观察10.0秒' in status['detail']

def test_burst_calls_cannot_confirm_or_consume_more_model_work(clock):
    service = make_service(['rain'] * 6)
    for index in range(20):
        clock[0] = 100 + index * .05
        assert service.process_frame(b'frame')['label'] == 'unknown'
    assert service.get_status()['frames_processed'] == 1
    assert service._classifier.calls == 1

def test_old_single_frame_settings_cannot_bypass_confirmation(clock):
    service = make_service(['rain'] * 6, smoothing_window=1, stable_votes=1,
                           sample_interval_seconds=0, min_observation_seconds=0)
    status = service.process_frame(b'frame')
    assert status['label'] == 'unknown'
    assert status['smoothing_window'] == 6
    assert status['stable_votes'] == 5
    assert status['min_observation_seconds'] == 10
    assert status['sample_interval_seconds'] == 2

def test_five_of_six_agree_but_four_of_six_is_uncertain(clock):
    service = make_service(['rain'] * 5 + ['normal'] + ['snow'] * 4 + ['rain'] * 2)
    assert sample_round(service, clock)['label'] == 'rain'
    status = sample_round(service, clock)
    assert status['label'] == 'unknown'
    assert status['last_confirmed_label'] == 'rain'
    assert status['result_status'] == 'uncertain'

def test_low_confidence_is_never_normal(clock):
    service = make_service([{'sandstorm': .4, 'normal': .35, 'rain': .25}] * 6)
    status = sample_round(service, clock)
    assert status['label'] == 'unknown'
    assert status['confidence'] == 0
    assert status['raw_label'] == 'sandstorm'
    assert status['result_status'] == 'uncertain'

def test_unsupported_label_is_not_normal(clock):
    service = make_service([{'fogsmog': .8, 'rain': .1, 'snow': .1}] * 6)
    assert sample_round(service, clock)['label'] == 'unknown'

def test_rime_maps_to_snow_only_when_confident(clock):
    for confidence, expected in ((.8, 'snow'), (.4, 'unknown')):
        service = make_service([{'rime': confidence, 'snow': .1, 'normal': .1}] * 6)
        status = sample_round(service, clock)
        assert status['label'] == expected

def test_initialization_failure_does_not_raise():
    service = WeatherDetectionService(enabled=True, initialization_error='model missing')
    status = service.process_frame(b'frame')
    assert status['state'] == 'failed'
    assert status['frames_processed'] == 0

def test_weather_change_requires_two_full_rounds(clock):
    service = make_service(['normal'] * 6 + ['rain'] * 12)
    assert sample_round(service, clock)['label'] == 'normal'
    pending = sample_round(service, clock)
    assert pending['label'] == 'unknown'
    assert pending['result_status'] == 'pending_change'
    assert pending['last_confirmed_label'] == 'normal'
    assert pending['candidate_rounds'] == 1
    assert sample_round(service, clock)['label'] == 'rain'

def test_one_bad_round_does_not_switch_confirmed_weather(clock):
    service = make_service(['normal'] * 6 + ['rain'] * 6 + ['normal'] * 6)
    sample_round(service, clock)
    assert sample_round(service, clock)['label'] == 'unknown'
    assert sample_round(service, clock)['label'] == 'normal'

def test_gap_discards_earlier_votes(clock):
    service = make_service(['rain'] * 6)
    for t in (100, 102, 104):
        clock[0] = t
        service.process_frame(b'frame')
    clock[0] = 120
    status = service.process_frame(b'frame')
    assert status['round_samples'] == 1
    assert status['label'] == 'unknown'
    assert status['rounds_processed'] == 0

def test_cancel_discards_votes_before_retry(clock):
    service = make_service(['rain'] * 4 + ['snow'] * 6)
    for t in (100, 102, 104, 106):
        clock[0] = t
        service.process_frame(b'frame')
    service.cancel_refresh('video lost')
    assert service.get_status()['round_samples'] == 0
    assert not service.round_in_progress
    assert sample_round(service, clock)['label'] == 'snow'

def test_failed_inference_resets_votes_and_honors_retry(clock):
    service = make_service(['rain', {}] + ['snow'] * 6)
    service.process_frame(b'frame')
    clock[0] = 102
    status = service.process_frame(b'frame')
    assert status['state'] == 'degraded'
    assert status['round_samples'] == 0
    assert service.next_sample_at == 112
    assert service.process_frame(b'frame')['label'] == 'unknown'
    assert sample_round(service, clock)['label'] == 'snow'

def test_expired_result_is_not_reported_as_current_weather(clock):
    service = make_service(['normal'] * 6)
    sample_round(service, clock)
    clock[0] = 451
    status = service.get_status()
    assert status['label'] == 'unknown'
    assert status['result_status'] == 'stale'
    assert status['last_confirmed_label'] == 'normal'
    assert status['observed_at'] is None

def test_probabilities_are_aggregated_not_last_frame(clock):
    service = make_service([{'rain': .9, 'normal': .1}] * 5 + [{'rain': .1, 'normal': .9}])
    status = sample_round(service, clock)
    assert status['label'] == 'rain'
    assert status['raw_label'] == 'normal'
    assert status['probabilities']['rain'] == round(4.6 / 6, 4)

def test_refresh_during_inference_does_not_reuse_inflight_frame(clock):
    service = make_service([])
    class RefreshingClassifier:
        def predict(self, frame):
            service.request_refresh()
            return {'rain': .9}
    service._classifier = RefreshingClassifier()
    status = service.process_frame(b'frame')
    assert status['round_samples'] == 0
    assert status['frames_processed'] == 0

def test_longer_observation_scales_spacing_without_stalling(clock):
    service = make_service(['rain'] * 6, min_observation_seconds=20)
    status = sample_round(service, clock)
    assert status['label'] == 'rain'
    assert status['sample_interval_seconds'] == 4

@pytest.mark.parametrize('probability', [float('nan'), float('inf'), -1, 2])
def test_invalid_probabilities_do_not_publish_weather(clock, probability):
    service = make_service([{'rain': probability}])
    status = service.process_frame(b'frame')
    assert status['state'] == 'degraded'
    assert status['label'] == 'unknown'
