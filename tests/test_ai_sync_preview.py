import asyncio
import json
import threading
import time
from types import SimpleNamespace
from backend import ai_sync_preview as p


def test_latest_only_and_bounded_encoder(monkeypatch):
    async def run():
        p._latest = p._cached = p._encoding = None
        p._sequence = 0
        started, release = threading.Event(), threading.Event()
        calls = []
        def encode(sample):
            calls.append(sample[0]); started.set()
            assert release.wait(3)
            return {'seq': sample[0], 'image': 'test'}
        monkeypatch.setattr(p, '_encode', encode)
        d = SimpleNamespace(bbox=(0, 0, 1, 1), label='person', confidence=.9)
        p.publish(b'old', 1, 1, time.monotonic(), [d], [], False, False)
        for i in range(20):
            p.publish(b'new', 1, 1, time.monotonic(), [], [], True, False)
        assert p._latest[1] == b'new' and p._latest[6]['detections'] == []
        request = asyncio.create_task(p.latest_frame())
        while not started.is_set(): await asyncio.sleep(.001)
        request.cancel()
        try: await request
        except asyncio.CancelledError: pass
        p.publish(b'newest', 1, 1, time.monotonic(), [], [], False, True)
        results = await asyncio.gather(*(p.latest_frame() for _ in range(25)))
        assert all(r.status_code == 429 for r in results)
        assert calls == [21]
        release.set(); await p._encoding
        response = await p.latest_frame()
        assert json.loads(response.body)['seq'] == 22
        assert (await p.latest_frame(after=22)).status_code == 204
        p.publish(b'stale', 1, 1, time.monotonic()-3, [], [], False, False)
        assert (await p.latest_frame()).status_code == 503
    asyncio.run(run())
