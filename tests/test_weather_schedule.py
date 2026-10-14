import asyncio
from types import SimpleNamespace
from backend.weather_detection import WeatherDetectionService
from backend.workers_ai import AIWorker


def test_worker_samples_new_frames_at_two_second_intervals(monkeypatch):
    now = [100.0]
    monkeypatch.setattr('backend.workers_ai.time.monotonic', lambda: now[0])
    samples = []
    class Classifier:
        device = 'cpu'
        def predict(self, frame):
            samples.append(frame)
            return {'normal' if len(samples) <= 6 else 'rain': .9}
    service = WeatherDetectionService(enabled=True, classifier=Classifier())
    async def inference(label, fn, frame):
        return fn(frame)
    worker = SimpleNamespace(_weather_service=service, _last_weather_inference_at=0,
                             _last_weather_ms=0, _weather_warmed_up=False, _run_inference=inference)
    times = [100, 100.1, 100.5, 102, 104, 106, 108, 110, 200, 409.9,
             410, 412, 414, 416, 418, 420, 429.9, 430, 432, 434, 436, 438, 440]
    async def check():
        for t in times:
            now[0] = t
            await AIWorker._maybe_process_weather(worker, str(t).encode())
    asyncio.run(check())
    expected = [100, 102, 104, 106, 108, 110, 410, 412, 414, 416, 418, 420,
                430, 432, 434, 436, 438, 440]
    assert samples == [str(t).encode() for t in expected]
    assert service.get_status()['label'] == 'rain'
    assert service.next_sample_at == 450


def test_page_refresh_restarts_a_full_ten_second_round(monkeypatch):
    now = [100.0]
    monkeypatch.setattr('backend.weather_detection.time.monotonic', lambda: now[0])
    class Classifier:
        device = 'cpu'
        def predict(self, frame):
            return {'normal': .9}
    service = WeatherDetectionService(enabled=True, classifier=Classifier())
    for t in (100, 102, 104, 106, 108, 110):
        now[0] = t
        service.process_frame(b'frame')
    now[0] = 120
    assert service.request_refresh()
    assert not service.request_refresh()
    for t in (120, 122, 124, 126, 128):
        now[0] = t
        service.process_frame(b'frame')
        assert service.get_status()['rounds_processed'] == 1
    now[0] = 130
    service.process_frame(b'frame')
    assert service.get_status()['rounds_processed'] == 2
    assert service.next_sample_at == 430


def test_idle_round_keeps_one_reader_until_all_spaced_samples_finish(monkeypatch):
    now = [100.0]
    monkeypatch.setattr('backend.workers_ai.time.monotonic', lambda: now[0])
    samples, terminated = [], []
    class Classifier:
        device = 'cpu'
        def predict(self, frame):
            samples.append(now[0])
            return {'normal': .9}
    service = WeatherDetectionService(enabled=True, classifier=Classifier())
    class Reader:
        async def readexactly(self, size):
            now[0] += .5
            assert now[0] < 120, 'idle round failed to finish'
            return str(now[0]).encode()
    process = SimpleNamespace(stdout=Reader())
    async def start():
        return process
    async def drain(process):
        await asyncio.Future()
    async def terminate(process, reason):
        terminated.append(reason)
    async def broadcast():
        pass
    async def inference(label, fn, frame):
        return fn(frame)
    worker = SimpleNamespace(_weather_service=service, _last_weather_inference_at=0,
        _last_weather_ms=0, _weather_warmed_up=False, _run_inference=inference,
        _start_ffmpeg=start, _drain_stderr=drain, _terminate_ffmpeg_process=terminate,
        _frame_size=1, _ffmpeg_frame_timeout_s=1, _maybe_broadcast_status=broadcast)
    async def maybe(frame):
        await AIWorker._maybe_process_weather(worker, frame)
    worker._maybe_process_weather = maybe
    asyncio.run(AIWorker._sample_weather_round_idle(worker))
    assert samples == [100.5, 102.5, 104.5, 106.5, 108.5, 110.5]
    assert service.get_status()['label'] == 'normal'
    assert service.get_status()['rounds_processed'] == 1
    assert terminated == ['weather_refresh']
