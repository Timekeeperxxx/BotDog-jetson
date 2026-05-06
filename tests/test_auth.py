from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.auth import router as auth_router
from backend.auth.dependencies import require_admin, require_authenticated, require_operator
from backend.auth.schemas import AuthUser
from backend.auth.service import create_access_token
from backend.config import settings
from backend.database import get_db


async def override_db():
    yield None


def create_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth_router)
    app.dependency_overrides[get_db] = override_db

    @app.post("/operator-only")
    async def operator_only(user: AuthUser = Depends(require_operator)):
        return {"username": user.username, "role": user.role}

    @app.post("/admin-only")
    async def admin_only(user: AuthUser = Depends(require_admin)):
        return {"username": user.username, "role": user.role}

    @app.get("/me")
    async def me(user: AuthUser = Depends(require_authenticated)):
        return {"username": user.username, "role": user.role}

    return app


def test_login_success(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "AUTH_ADMIN_USERNAME", "admin")
    monkeypatch.setattr(settings, "AUTH_ADMIN_PASSWORD", "secret")

    client = TestClient(create_test_app())
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    assert body["user"]["username"] == "admin"
    assert body["user"]["role"] == "admin"


def test_login_bad_password(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "AUTH_ADMIN_USERNAME", "admin")
    monkeypatch.setattr(settings, "AUTH_ADMIN_PASSWORD", "secret")

    client = TestClient(create_test_app())
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": "bad"})

    assert response.status_code == 401


def test_operator_requires_token(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    client = TestClient(create_test_app())
    response = client.post("/operator-only")
    assert response.status_code == 401


def test_invalid_token_rejected(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    client = TestClient(create_test_app())
    response = client.post("/operator-only", headers={"Authorization": "Bearer invalid.token.value"})
    assert response.status_code == 401


def test_admin_token_can_access_protected_route(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    token = create_access_token(AuthUser(username="admin", role="admin"))
    client = TestClient(create_test_app())
    response = client.post("/admin-only", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["role"] == "admin"


def test_me_returns_current_user(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    token = create_access_token(AuthUser(username="admin", role="admin"))
    client = TestClient(create_test_app())
    response = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == {"username": "admin", "role": "admin"}


def test_auth_disabled_allows_dev_admin(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_ENABLED", False)
    client = TestClient(create_test_app())
    response = client.post("/operator-only")
    assert response.status_code == 200
    assert response.json()["username"] == "dev"
    assert response.json()["role"] == "admin"


def test_me_allows_dev_user_when_auth_disabled(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_ENABLED", False)
    client = TestClient(create_test_app())
    response = client.get("/me")
    assert response.status_code == 200
    assert response.json() == {"username": "dev", "role": "admin"}
