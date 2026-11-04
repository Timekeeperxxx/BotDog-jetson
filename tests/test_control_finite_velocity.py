"""Finite velocity boundary regressions; never initialize a hardware adapter."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import control
from backend.control_service import ControlService, RESULT_REJECTED_INVALID_CMD
from backend.database import get_db
from backend.schemas import ControlAckDTO


@pytest.fixture
def control_api(monkeypatch):
    from backend import control_arbiter

    service = SimpleNamespace(
        handle_command=AsyncMock(return_value=ControlAckDTO(ack_cmd="forward", result="ACCEPTED", latency_ms=0)),
        force_stop=AsyncMock(return_value=ControlAckDTO(ack_cmd="stop", result="ACCEPTED", latency_ms=0)),
    )
    get_service = Mock(return_value=service)
    arbiter = Mock()
    monkeypatch.setattr(control, "get_control_service", get_service)
    monkeypatch.setattr(control_arbiter, "get_control_arbiter", lambda: arbiter)
    app = FastAPI()
    app.include_router(control.router)
    app.dependency_overrides[control.require_operator] = lambda: SimpleNamespace(username="test", role="operator")

    async def db():
        yield None

    app.dependency_overrides[get_db] = db
    with TestClient(app) as client:
        yield client, service, get_service, arbiter


@pytest.mark.parametrize("field", ["vx", "vyaw"])
@pytest.mark.parametrize("value", ["NaN", "nan", "Infinity", "-Infinity", "1e309", float("nan"), float("inf"), -float("inf")])
def test_http_rejects_non_finite_before_claiming_control(control_api, field, value):
    client, service, get_service, arbiter = control_api
    response = client.post(
        "/api/v1/control/command", content=json.dumps({"cmd": "forward", field: value}),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert "有限数值" in response.json()["detail"]
    get_service.assert_not_called()
    arbiter.request_control.assert_not_called()
    service.handle_command.assert_not_awaited()


def test_http_rejects_valid_json_numeric_overflow(control_api):
    client, service, _, arbiter = control_api
    response = client.post(
        "/api/v1/control/command", content='{"cmd":"forward","vx":1e309}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    service.handle_command.assert_not_awaited()
    arbiter.request_control.assert_not_called()


@pytest.mark.parametrize("payload,expected", [
    ({}, {"vx": None, "vyaw": None}),
    ({"vx": 0, "vyaw": -0.2}, {"vx": 0, "vyaw": -0.2}),
    ({"vx": -2, "vyaw": 2}, {"vx": -0.6, "vyaw": 0.8}),
])
def test_http_preserves_finite_limits_and_defaults(control_api, payload, expected):
    client, service, _, _ = control_api
    assert client.post("/api/v1/control/command", json={"cmd": "forward", **payload}).status_code == 200
    service.handle_command.assert_awaited_once_with("forward", **expected)


def test_dedicated_stop_does_not_depend_on_velocity_validation(control_api):
    client, service, _, _ = control_api
    assert client.post("/api/v1/control/stop").status_code == 200
    service.force_stop.assert_awaited_once_with()


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["vx", "vyaw"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
async def test_internal_non_finite_never_reaches_adapter_or_updates_watchdog(field, value):
    adapter = SimpleNamespace(send_command=AsyncMock(), is_ready=Mock(return_value=True))
    service = ControlService(adapter=adapter, cmd_rate_limit_ms=0)
    service._watchdog_active = True
    service._watchdog_last_reset = 123.0
    result = await service.handle_command("forward", **{field: value})
    assert result.result == RESULT_REJECTED_INVALID_CMD
    assert result.safety_reason == "速度必须是有限数值"
    adapter.send_command.assert_not_awaited()
    adapter.is_ready.assert_not_called()
    assert service._watchdog_active is True
    assert service._watchdog_last_reset == 123.0
    assert service._last_request_time == 0
