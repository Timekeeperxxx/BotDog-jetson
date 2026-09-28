import asyncio
from backend.ws_event_broadcaster import EventBroadcaster


def test_slow_client_keeps_only_latest_and_does_not_block_producer():
    async def run():
        broadcaster = EventBroadcaster()
        entered, release = asyncio.Event(), asyncio.Event()
        class Client:
            def __init__(self): self.frames = []
            async def send_json(self, message):
                self.frames.append(message['frame'])
                if len(self.frames) == 1:
                    entered.set(); await release.wait()
        client = Client(); broadcaster._connections.add(client)
        broadcaster.publish_latest_overlay({'frame': 1}, 1)
        await entered.wait()
        task = broadcaster._overlay_task
        for i in range(2, 101): broadcaster.publish_latest_overlay({'frame': i}, 1)
        assert broadcaster._overlay_task is task
        assert client.frames == [1]
        release.set(); await task
        assert client.frames == [1, 100]
        assert broadcaster._pending_overlay is None
        # A blocked connection cannot keep a sender alive indefinitely.
        class Slow:
            async def send_json(self, message): await asyncio.sleep(10)
        slow = Slow(); broadcaster._connections.add(slow)
        broadcaster.publish_latest_overlay({'frame': 101}, .01)
        await asyncio.wait_for(broadcaster._overlay_task, .2)
        assert slow not in broadcaster._connections
    asyncio.run(run())
