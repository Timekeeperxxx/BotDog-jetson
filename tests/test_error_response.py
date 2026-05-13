from __future__ import annotations

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
settings.CONTROL_ADAPTER_TYPE = "simulation"
settings.ROS_NAV_ENABLED = False
settings.SIMULATION_WORKER_ENABLED = False
settings.AI_ENABLED = False
settings.MAVLINK_SOURCE = "simulation"

from backend.main import create_app


@pytest.fixture(scope="module")
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c
    try:
        os.remove(db_path)
    except OSError:
        pass


def test_http_exception_response_is_normalized(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    body = response.json()
    assert body["detail"] == "缺少访问令牌"
    assert body["message"] == "缺少访问令牌"
    assert body["status_code"] == 401
    assert body["error"] == "unauthorized"
