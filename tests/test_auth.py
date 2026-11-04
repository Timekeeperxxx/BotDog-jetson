import asyncio
import pytest
from fastapi.testclient import TestClient


from backend.config import settings
from runtime_fixtures import app  # noqa: F401 -- shared pytest fixture



@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def client(app):
    with TestClient(app) as c:
        yield c



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
    assert response.json() == {
        "id": 1,
        "username": "admin",
        "role": "admin",
        "must_change_password": False,
    }


def test_auth_status_returns_current_user_fields(client):
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": "ValidPassword123!"})
    token = response.json()["access_token"]
    res = client.get("/api/v1/auth/status", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    body = res.json()
    assert body["auth_enabled"] is True
    assert body["current_user"] == {
        "id": 1,
        "username": "admin",
        "role": "admin",
        "must_change_password": False,
    }
    assert "token_version" not in body["current_user"]


def test_auth_disabled_allows_dev_admin(monkeypatch, client):
    monkeypatch.setattr(settings, "AUTH_ENABLED", False)
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 200
    assert response.json() == {
        "id": 0,
        "username": "dev",
        "role": "admin",
        "must_change_password": False,
    }


def test_me_allows_dev_user_when_auth_disabled(monkeypatch, client):
    monkeypatch.setattr(settings, "AUTH_ENABLED", False)
    response = client.get("/api/v1/auth/status")
    assert response.status_code == 200
    assert response.json() == {
        "auth_enabled": False,
        "current_user": {
            "id": 0,
            "username": "dev",
            "role": "admin",
            "must_change_password": False,
        },
    }
