from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest

from backend.workers_unitree_telemetry import UnitreeTelemetryWorker


@pytest.mark.asyncio
async def test_unitree_telemetry_closes_both_dds_subscribers(monkeypatch):
    subscriptions = []

    class FakeSubscriber:
        def __init__(self, topic, _message_type):
            self.topic = topic
            self.closed = False
            subscriptions.append(self)

        def Init(self, _callback, _queue_length):
            return None

        def Close(self):
            self.closed = True

    monkeypatch.setitem(sys.modules, "unitree_sdk2py.core.channel", SimpleNamespace(
        ChannelFactoryInitialize=lambda *_args: True, ChannelSubscriber=FakeSubscriber))
    monkeypatch.setitem(sys.modules, "unitree_sdk2py.idl.unitree_go.msg.dds_", SimpleNamespace(
        LowState_=object, SportModeState_=object))

    worker = UnitreeTelemetryWorker(
        queue_manager=object(),
        state_machine=object(),
        network_interface="eno1",
    )
    stop_event = asyncio.Event()
    stop_event.set()

    await worker.start(stop_event)

    assert len(subscriptions) == 2
    assert all(subscription.closed for subscription in subscriptions)
    assert worker._initialized is False
