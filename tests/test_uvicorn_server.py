from __future__ import annotations

import signal
import threading

import pytest
import uvicorn
from uvicorn.server import HANDLED_SIGNALS

from backend import uvicorn_server
from backend.uvicorn_server import BotDogUvicornServer, reinstall_exit_signal_handlers


def test_reinstall_exit_signal_handlers_registers_all_uvicorn_signals(monkeypatch):
    registered = []

    def handler(_signal_number, _frame):
        return None

    monkeypatch.setattr(signal, "signal", lambda sig, callback: registered.append((sig, callback)))

    assert reinstall_exit_signal_handlers(handler) is True
    assert registered == [(sig, handler) for sig in HANDLED_SIGNALS]


def test_reinstall_exit_signal_handlers_rejects_non_main_thread(monkeypatch):
    current_thread = object()
    main_thread = object()
    registered = []
    monkeypatch.setattr(threading, "current_thread", lambda: current_thread)
    monkeypatch.setattr(threading, "main_thread", lambda: main_thread)
    monkeypatch.setattr(signal, "signal", lambda sig, callback: registered.append((sig, callback)))

    assert reinstall_exit_signal_handlers(lambda _signal_number, _frame: None) is False
    assert registered == []


@pytest.mark.asyncio
async def test_server_reinstalls_handlers_after_application_startup(monkeypatch):
    events = []

    async def parent_startup(_server, sockets=None):
        events.append(("application_startup", sockets))

    def reinstall(handler):
        events.append(("signals_reinstalled", handler))
        return True

    monkeypatch.setattr(uvicorn.Server, "startup", parent_startup)
    monkeypatch.setattr(uvicorn_server, "reinstall_exit_signal_handlers", reinstall)
    server = BotDogUvicornServer(uvicorn.Config(app=lambda _scope: None))

    await server.startup()

    assert events == [
        ("application_startup", None),
        ("signals_reinstalled", server.handle_exit),
    ]


@pytest.mark.asyncio
async def test_server_does_not_reinstall_handlers_after_failed_startup(monkeypatch):
    async def parent_startup(server, sockets=None):
        server.should_exit = True

    reinstall = pytest.fail
    monkeypatch.setattr(uvicorn.Server, "startup", parent_startup)
    monkeypatch.setattr(uvicorn_server, "reinstall_exit_signal_handlers", reinstall)
    server = BotDogUvicornServer(uvicorn.Config(app=lambda _scope: None))

    await server.startup()


@pytest.mark.asyncio
async def test_server_reasserts_signal_handlers_once_per_second(monkeypatch):
    calls = []

    async def parent_on_tick(_server, counter):
        return False

    monkeypatch.setattr(uvicorn.Server, "on_tick", parent_on_tick)
    monkeypatch.setattr(
        uvicorn_server,
        "reinstall_exit_signal_handlers",
        lambda handler: calls.append(handler) or True,
    )
    server = BotDogUvicornServer(uvicorn.Config(app=lambda _scope: None))

    assert await server.on_tick(0) is False
    assert await server.on_tick(1) is False
    assert await server.on_tick(10) is False
    assert calls == [server.handle_exit, server.handle_exit]


@pytest.mark.asyncio
async def test_server_stops_reasserting_handlers_during_exit(monkeypatch):
    async def parent_on_tick(_server, _counter):
        return True

    monkeypatch.setattr(uvicorn.Server, "on_tick", parent_on_tick)
    monkeypatch.setattr(
        uvicorn_server,
        "reinstall_exit_signal_handlers",
        lambda _handler: pytest.fail("handler should not be reinstalled during exit"),
    )
    server = BotDogUvicornServer(uvicorn.Config(app=lambda _scope: None))

    assert await server.on_tick(10) is True


@pytest.mark.asyncio
async def test_server_consumes_systemd_shutdown_marker(monkeypatch, tmp_path):
    async def parent_on_tick(server, _counter):
        return server.should_exit

    monkeypatch.setattr(uvicorn.Server, "on_tick", parent_on_tick)
    marker = tmp_path / "backend.stop"
    marker.touch()
    server = BotDogUvicornServer(
        uvicorn.Config(app=lambda _scope: None),
        shutdown_marker=marker,
    )

    assert await server.on_tick(1) is True
    assert server.should_exit is True
    assert marker.exists() is False
