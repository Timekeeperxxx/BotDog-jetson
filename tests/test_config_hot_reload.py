import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from backend.config import settings

db_path = tempfile.mktemp(suffix=".db")
settings.DATABASE_URL = f"sqlite+aiosqlite:///{db_path}"
settings.AUTH_ENABLED = True
settings.AUTH_ADMIN_USERNAME = "admin"
settings.AUTH_ADMIN_PASSWORD = "ValidPassword123!"

from backend.api.routes.config import _apply_runtime_update  # noqa: E402
from backend.main import create_app  # noqa: E402
from backend.yellow_zone_detector import YellowZoneDetector  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return create_app()


@pytest.fixture(scope="module")
def client(app):
    with TestClient(app) as c:
        yield c
    try:
        os.remove(db_path)
    except OSError:
        pass


def _login(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "ValidPassword123!"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def test_system_config_contains_new_categories(client: TestClient):
    token = _login(client)
    response = client.get(
        "/api/v1/config",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    configs = body["configs"]
    assert "unitree_network_iface" in configs
    assert configs["unitree_network_iface"]["category"] == "hardware"
    assert "zone_draw_saved_fill_rgba" in configs
    assert configs["zone_draw_saved_fill_rgba"]["category"] == "frontend_draw"
    assert "zone_yellow_h_low" in configs
    assert configs["zone_yellow_h_low"]["category"] == "zone"


def test_hardware_config_returns_restart_message(client: TestClient):
    token = _login(client)
    response = client.post(
        "/api/v1/config",
        headers={"Authorization": f"Bearer {token}"},
        json={"key": "unitree_network_iface", "value": "eth1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["runtime_apply"] == {
        "applied": False,
        "target": "hardware",
        "message": "需重启后端或重新初始化硬件适配器",
    }
    assert body["config"]["value"] == "eth1"


def test_frontend_draw_config_runtime_apply(client: TestClient):
    token = _login(client)
    response = client.post(
        "/api/v1/config",
        headers={"Authorization": f"Bearer {token}"},
        json={"key": "zone_draw_toolbar_bottom_px", "value": "180"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["runtime_apply"]["applied"] is True
    assert body["runtime_apply"]["target"] == "frontend"
    assert "前端配置将在下一次配置刷新后生效" in body["runtime_apply"]["message"]
    assert body["config"]["value"] == 180


def test_zone_config_runtime_apply_uses_detector(monkeypatch, client: TestClient):
    class FakeGuardMissionService:
        def __init__(self) -> None:
            self.calls: list[tuple[str, object]] = []

        def update_zone_detector_config(self, key: str, value):
            self.calls.append((key, value))
            return True

    fake_service = FakeGuardMissionService()
    monkeypatch.setattr(
        "backend.guard_mission_service.get_guard_mission_service",
        lambda: fake_service,
    )

    token = _login(client)
    response = client.post(
        "/api/v1/config",
        headers={"Authorization": f"Bearer {token}"},
        json={"key": "zone_yellow_h_low", "value": "20"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["runtime_apply"] == {
        "applied": True,
        "target": "zone",
        "message": "运行时已生效",
    }
    assert fake_service.calls == [("zone_yellow_h_low", "20")]


def test_zone_runtime_apply_falls_back_when_detector_missing(monkeypatch):
    monkeypatch.setattr(
        "backend.guard_mission_service.get_guard_mission_service",
        lambda: None,
    )
    result = _apply_runtime_update("zone_yellow_h_low", "20")
    assert result == {
        "applied": False,
        "target": "zone",
        "message": "当前检测器实例未接入运行时热更新",
    }


def test_yellow_zone_detector_update_params():
    detector = YellowZoneDetector(frame_width=1280, frame_height=720)

    assert detector.update_params("zone_yellow_h_low", "18") is True
    assert detector._h_low == 18

    assert detector.update_params("zone_center_text_bonus", "0.75") is True
    assert detector._center_text_bonus == 0.75

    assert detector.update_params("unknown_key", "1") is False
