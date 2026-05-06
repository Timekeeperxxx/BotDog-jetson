import asyncio
import pytest
from fastapi.testclient import TestClient

import tempfile
import os

from backend.config import settings
db_path = tempfile.mktemp(suffix=".db")
settings.DATABASE_URL = f"sqlite+aiosqlite:///{db_path}"
settings.AUTH_ENABLED = True
settings.AUTH_ADMIN_USERNAME = "admin"
settings.AUTH_ADMIN_PASSWORD = "ValidPassword123!"

from backend.main import create_app
from backend.database import get_engine, Base


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def client():
    # Lifespan starts here, which initializes DB and bootstraps the admin
    app = create_app()
    with TestClient(app) as c:
        yield c
    try:
        os.remove(db_path)
    except OSError:
        pass


def test_bootstrap_admin_created_and_login(client):
    # Because DB was empty when lifespan started, 'admin' should exist
    login_res = client.post("/api/v1/auth/login", json={"username": "admin", "password": "ValidPassword123!"})
    assert login_res.status_code == 200
    assert login_res.json()["user"]["username"] == "admin"
    data = login_res.json()
    assert "access_token" in data
    assert data["user"]["role"] == "admin"


def test_admin_can_create_operator(client):
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": "ValidPassword123!"})
    token = response.json()["access_token"]

    create_res = client.post(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "username": "operator1",
            "password": "OperatorPass123",
            "role": "operator",
            "enabled": True,
        }
    )
    assert create_res.status_code == 200
    assert create_res.json()["username"] == "operator1"


def test_admin_can_create_user_with_must_change_password(client):
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": "ValidPassword123!"})
    token = response.json()["access_token"]

    create_res = client.post(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "username": "must_change_user",
            "password": "MustChange123!",
            "role": "viewer",
            "enabled": True,
            "must_change_password": True,
        }
    )
    assert create_res.status_code == 200
    assert create_res.json()["must_change_password"] is True

    list_res = client.get("/api/v1/users", headers={"Authorization": f"Bearer {token}"})
    assert list_res.status_code == 200
    users = list_res.json()
    target = next(user for user in users if user["username"] == "must_change_user")
    assert target["must_change_password"] is True
    assert "token_version" not in target


def test_operator_cannot_access_user_management(client):
    response = client.post("/api/v1/auth/login", json={"username": "operator1", "password": "OperatorPass123"})
    token = response.json()["access_token"]

    res = client.get("/api/v1/users", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 403


def test_weak_password_rejected(client):
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": "ValidPassword123!"})
    token = response.json()["access_token"]
    create_res = client.post(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "username": "baduser",
            "password": "12345678",
            "role": "viewer",
            "enabled": True,
        }
    )
    assert create_res.status_code == 400


def test_get_users_does_not_return_password_hash(client):
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": "ValidPassword123!"})
    token = response.json()["access_token"]

    res = client.get("/api/v1/users", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    users = res.json()
    assert len(users) >= 2
    for user in users:
        assert "password_hash" not in user
        assert "token_version" not in user
        assert "password" not in user


def test_disabled_user_cannot_login(client):
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": "ValidPassword123!"})
    token = response.json()["access_token"]

    create_res = client.post(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "username": "disabled_user",
            "password": "ValidPassword123!",
            "role": "viewer",
            "enabled": False,
        }
    )
    assert create_res.status_code == 200

    login_res = client.post("/api/v1/auth/login", json={"username": "disabled_user", "password": "ValidPassword123!"})
    assert login_res.status_code == 403
    assert "禁用" in login_res.json()["detail"]


def test_soft_deleted_user_cannot_login(client):
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": "ValidPassword123!"})
    token = response.json()["access_token"]

    create_res = client.post(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "username": "delete_me",
            "password": "ValidPassword123!",
            "role": "viewer",
            "enabled": True,
        }
    )
    assert create_res.status_code == 200
    user_id = create_res.json()["id"]

    del_res = client.delete(f"/api/v1/users/{user_id}", headers={"Authorization": f"Bearer {token}"})
    assert del_res.status_code == 204

    login_res = client.post("/api/v1/auth/login", json={"username": "delete_me", "password": "ValidPassword123!"})
    assert login_res.status_code == 403
    assert "删除" in login_res.json()["detail"]


def test_change_password_invalidates_old_token(client):
    # create a user
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": "ValidPassword123!"})
    admin_token = response.json()["access_token"]

    create_res = client.post(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "username": "change_pwd_user",
            "password": "OldPassword123",
            "role": "viewer",
            "enabled": True,
        }
    )
    assert create_res.status_code == 200

    # login to get token
    login_res = client.post("/api/v1/auth/login", json={"username": "change_pwd_user", "password": "OldPassword123"})
    assert login_res.status_code == 200
    old_token = login_res.json()["access_token"]

    # test token works
    me_res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {old_token}"})
    assert me_res.status_code == 200

    # change password
    chg_res = client.post(
        "/api/v1/users/change-password",
        headers={"Authorization": f"Bearer {old_token}"},
        json={"old_password": "OldPassword123", "new_password": "NewPassword123"}
    )
    assert chg_res.status_code == 200

    # old token should be invalid
    me_res_invalid = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {old_token}"})
    assert me_res_invalid.status_code == 401
    assert "失效" in me_res_invalid.json()["detail"]

    # admin reset password
    login_res2 = client.post("/api/v1/auth/login", json={"username": "change_pwd_user", "password": "NewPassword123"})
    assert login_res2.status_code == 200
    new_token = login_res2.json()["access_token"]

    user_id = create_res.json()["id"]
    reset_res = client.post(
        f"/api/v1/users/{user_id}/reset-password",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"new_password": "ResetPassword123"}
    )
    assert reset_res.status_code == 200

    # new token should be invalid
    me_res_invalid2 = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_token}"})
    assert me_res_invalid2.status_code == 401


def test_last_admin_protection(client):
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": "ValidPassword123!"})
    assert response.status_code == 200
    admin_token = response.json()["access_token"]
    admin_id = response.json()["user"]["id"]

    # delete self
    del_res = client.delete(f"/api/v1/users/{admin_id}", headers={"Authorization": f"Bearer {admin_token}"})
    assert del_res.status_code == 400
    assert "不能删除自己" in del_res.json()["detail"]

    # disable self
    dis_res = client.patch(f"/api/v1/users/{admin_id}", headers={"Authorization": f"Bearer {admin_token}"}, json={"enabled": False})
    assert dis_res.status_code == 400
    assert "不能禁用自己" in dis_res.json()["detail"]

    # demote self
    dem_res = client.patch(f"/api/v1/users/{admin_id}", headers={"Authorization": f"Bearer {admin_token}"}, json={"role": "operator"})
    assert dem_res.status_code == 400
    assert "不能修改自己" in dem_res.json()["detail"]

    # Create another admin
    create_res = client.post(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "username": "admin2",
            "password": "Admin2Password",
            "role": "admin",
            "enabled": True,
        }
    )
    assert create_res.status_code == 200
    admin2_id = create_res.json()["id"]

    # Now we have 2 admins. Let's delete the second one from the first one. Should work.
    del2_res = client.delete(f"/api/v1/users/{admin2_id}", headers={"Authorization": f"Bearer {admin_token}"})
    assert del2_res.status_code == 204
