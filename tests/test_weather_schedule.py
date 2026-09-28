import asyncio
from types import SimpleNamespace
from backend.weather_detection import WeatherDetectionService
from backend.workers_ai import AIWorker


def test_worker_uses_new_frames_and_honors_round_deadlines(monkeypatch):
    now=[100.0]
    monkeypatch.setattr('backend.workers_ai.time.monotonic',lambda:now[0])
    samples=[]
    class Classifier:
        device='cpu'
        def predict(self,frame):
            samples.append(frame)
            return {'normal' if len(samples)<=3 else 'rain':.9}
    service=WeatherDetectionService(enabled=True,classifier=Classifier())
    async def inference(label,fn,frame):return fn(frame)
    worker=SimpleNamespace(_weather_service=service,_last_weather_inference_at=0,
                           _last_weather_ms=0,_weather_warmed_up=False,_run_inference=inference)
    async def check():
        for t in [100,100.1,100.5,101,200,400.9,401,401.5,402,411.9,412,412.5,413]:
            now[0]=t
            await AIWorker._maybe_process_weather(worker,str(t).encode())
    asyncio.run(check())
    assert samples==[str(t).encode() for t in [100,100.5,101,401,401.5,402,412,412.5,413]]
    assert service.get_status()['label']=='rain'
    assert service.next_sample_at==713


def test_page_refresh_starts_new_round(monkeypatch):
    now = [100.0]
    monkeypatch.setattr('backend.weather_detection.time.monotonic', lambda: now[0])
    class Classifier:
        device = 'cpu'
        def predict(self, frame):
            return {'normal': 0.9}
    service = WeatherDetectionService(enabled=True, classifier=Classifier())
    for t in [100.0, 100.5, 101.0]:
        now[0] = t
        service.process_frame(b'frame')
    assert service.next_sample_at == 401.0
    now[0] = 110.0
    assert service.request_refresh()
    assert service.next_sample_at == 0.0
    assert not service.request_refresh()
    for t in [110.0, 110.5, 111.0]:
        now[0] = t
        service.process_frame(b'frame')
    assert service.get_status()['rounds_processed'] == 2
    assert service.next_sample_at == 411.0
