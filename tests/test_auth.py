import asyncio
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import tempfile
import os

from backend.config import settings
db_path = tempfile.mktemp(suffix=".db")
settings.DATABASE_URL = f"sqlite+aiosqlite:///{db_path}"
settings.AUTH_ENABLED = True
settings.AUTH_ADMIN_USERNAME = "admin"
settings.AUTH_ADMIN_PASSWORD = "ValidPassword123!"

from backend.api.routes.auth import router as auth_router
from backend.auth.dependencies import require_admin, require_authenticated, require_operator
from backend.auth.schemas import AuthUser
from backend.auth.service import create_access_token
from backend.database import get_db
from backend.main import create_app


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def app():
    _app = create_app()
    return _app


@pytest.fixture(scope="module")
def client(app):
    with TestClient(app) as c:
        yield c
    try:
        os.remove(db_path)
    except OSError:
        pass


def test_login_success(client):
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": "ValidPassword123!"})
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    assert body["user"]["username"] == "admin"
    assert body["user"]["role"] == "admin"


def test_login_bad_password(client):
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": "bad"})
    assert response.status_code == 401


def test_operator_requires_token(client):
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_invalid_token_rejected(client):
    response = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer invalid.token.value"})
    assert response.status_code == 401


def test_admin_token_can_access_protected_route(client):
    # test using an admin route, e.g. GET /api/v1/users
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": "ValidPassword123!"})
    token = response.json()["access_token"]
    res = client.get("/api/v1/users", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200


def test_me_returns_current_user(client):
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": "ValidPassword123!"})
    token = response.json()["access_token"]
    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == {"username": "admin", "role": "admin"}


def test_auth_disabled_allows_dev_admin(monkeypatch, app):
    monkeypatch.setattr(settings, "AUTH_ENABLED", False)
    with TestClient(app) as local_client:
        response = local_client.get("/api/v1/auth/me")
        assert response.status_code == 200
        assert response.json()["username"] == "dev"
        assert response.json()["role"] == "admin"


def test_me_allows_dev_user_when_auth_disabled(monkeypatch, app):
    monkeypatch.setattr(settings, "AUTH_ENABLED", False)
    with TestClient(app) as local_client:
        response = local_client.get("/api/v1/auth/me")
        assert response.status_code == 200
        assert response.json() == {"username": "dev", "role": "admin"}
