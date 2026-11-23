import io
import json
from copy import deepcopy
from urllib.error import URLError

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import gas_monitor
from backend.api.routes import gases
from backend.auth.dependencies import require_viewer
from backend.auth.schemas import AuthUserInternal
from backend.database import get_db


def reading(value, low, high, unit="ppm", decimals=1):
    return {"value": value, "unit": unit, "decimals": decimals, "low_alarm": low, "high_alarm": high,
            "status_code": 1, "cached": False, "age_seconds": 10,
            "sampled_at": "2026-10-29T10:00:00+08:00"}


def snapshot():
    return {"read_at": "2026-10-29T10:00:10+08:00", "gases": {
        "ph3": reading(0, 2.4, 20), "co2": reading(600, 2000, 5000, decimals=0),
        "o2": reading(20.9, 19.5, 23.5, "%VOL"),
    }, "dust": reading(0.005, 0.075, 0.15, "mg/m3", 3)}


def evaluate(data):
    return gas_monitor.evaluate_snapshot(gas_monitor.SensorSnapshot.model_validate(data))


def test_normal_oxygen_between_lower_and_upper_limits_is_not_an_alarm():
    assert evaluate(snapshot()).alerts == []


@pytest.mark.parametrize("channel,value,severity", [
    ("ph3", 2.4, "WARNING"), ("ph3", 20, "CRITICAL"),
    ("co2", 2000, "WARNING"), ("co2", 5000, "CRITICAL"),
    ("o2", 19.5, "CRITICAL"), ("o2", 23.5, "CRITICAL"),
    ("dust", 0.075, "WARNING"), ("dust", 0.15, "CRITICAL"),
])
def test_uses_device_thresholds_including_boundary_values(channel, value, severity):
    data = snapshot()
    item = data["dust"] if channel == "dust" else data["gases"][channel]
    item["value"] = value
    alerts = evaluate(data).alerts
    assert len(alerts) == 1
    assert alerts[0].channel == channel and alerts[0].severity == severity
    assert alerts[0].kind == "concentration" and not alerts[0].stale


@pytest.mark.parametrize("code,severity", [(4, "WARNING"), (5, "WARNING"), (6, "CRITICAL"), (8, "CRITICAL"), (11, "CRITICAL"), (12, "CRITICAL")])
def test_instrument_alarm_state_is_respected_even_before_value_crosses_threshold(code, severity):
    data = snapshot()
    data["gases"]["ph3"]["status_code"] = code
    assert evaluate(data).alerts[0].severity == severity


def test_faulty_sensor_value_is_not_interpreted_as_a_valid_gas_concentration():
    data = snapshot()
    data["gases"]["ph3"].update(value=100, status_code=3)
    alarm = evaluate(data).alerts[0]
    assert alarm.kind == "sensor" and alarm.severity == "WARNING"
    assert "传感器故障" in alarm.message


@pytest.mark.parametrize("code", [0, 2, 7, 9, 10, 15, 99])
def test_non_normal_or_unknown_device_states_are_not_treated_as_normal(code):
    data = snapshot()
    data["gases"]["ph3"]["status_code"] = code
    assert evaluate(data).alerts[0].kind == "sensor"


def test_missing_channels_and_expired_normal_values_are_reported_as_sensor_issues():
    data = snapshot()
    del data["gases"]["co2"]
    data["dust"] = None
    data["gases"]["o2"]["age_seconds"] = 181
    data["gases"]["ph3"]["cached"] = True
    alarms = evaluate(data).alerts
    assert len(alarms) == 4
    assert all(alarm.kind == "sensor" and alarm.stale for alarm in alarms)


def test_expired_high_gas_value_stays_critical_and_is_explicitly_historical():
    data = snapshot()
    data["gases"]["ph3"].update(value=25, cached=True, age_seconds=200)
    alarm = evaluate(data).alerts[0]
    assert alarm.severity == "CRITICAL" and alarm.stale
    assert alarm.message.startswith("上次：") and "数据已过期" in alarm.message


def test_reads_existing_service_without_a_second_serial_reader(monkeypatch):
    def request(request, timeout):
        assert request.full_url == "http://127.0.0.1:8787/api/gases"
        assert timeout == 3.0
        return io.BytesIO(json.dumps(snapshot()).encode())
    monkeypatch.setattr(gas_monitor, "urlopen", request)
    assert gas_monitor.read_gas_monitor().alerts == []


@pytest.mark.parametrize("mutation", [
    lambda data: data["gases"]["ph3"].update(value=float("nan")),
    lambda data: data["gases"]["ph3"].update(high_alarm=1),
    lambda data: data["gases"]["ph3"].pop("status_code"),
])
def test_invalid_measurements_fail_explicitly_instead_of_appearing_normal(monkeypatch, mutation):
    data = deepcopy(snapshot())
    mutation(data)
    monkeypatch.setattr(gas_monitor, "urlopen", lambda *args, **kwargs: io.BytesIO(json.dumps(data).encode()))
    with pytest.raises(gas_monitor.GasMonitorError, match="数据无效"):
        gas_monitor.read_gas_monitor()


def test_service_outage_is_an_error_not_a_normal_snapshot(monkeypatch):
    def unavailable(*args, **kwargs):
        raise URLError("connection refused")
    monkeypatch.setattr(gas_monitor, "urlopen", unavailable)
    with pytest.raises(gas_monitor.GasMonitorError, match="无法连接"):
        gas_monitor.read_gas_monitor()


def test_authenticated_route_does_not_cache_results_or_hide_failures(monkeypatch):
    app = FastAPI()
    app.include_router(gases.router)
    app.dependency_overrides[require_viewer] = lambda: AuthUserInternal(id=1, username="viewer", role="viewer", token_version=0)
    monkeypatch.setattr(gases, "read_gas_monitor", lambda: evaluate(snapshot()))
    client = TestClient(app)
    response = client.get("/api/v1/gases")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert response.json()["alerts"] == []
    def unavailable():
        raise gas_monitor.GasMonitorError("无法连接气体监测服务")
    monkeypatch.setattr(gases, "read_gas_monitor", unavailable)
    assert client.get("/api/v1/gases").status_code == 503


def test_route_requires_login(monkeypatch):
    from backend.config import settings
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    app = FastAPI()
    app.include_router(gases.router)
    app.dependency_overrides[get_db] = lambda: object()
    assert TestClient(app).get("/api/v1/gases").status_code == 401
