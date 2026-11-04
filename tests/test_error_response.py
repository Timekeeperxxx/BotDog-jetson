from __future__ import annotations


import pytest
from fastapi.testclient import TestClient

from backend.config import settings

from runtime_fixtures import app  # noqa: F401 -- shared pytest fixture


@pytest.fixture(scope="module")
def client(app):
    with TestClient(app) as c:
        yield c



def test_http_exception_response_is_normalized(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    body = response.json()
    assert body["detail"] == "缺少访问令牌"
    assert body["message"] == "缺少访问令牌"
    assert body["status_code"] == 401
    assert body["error"] == "unauthorized"
    assert len(response.headers["X-Request-ID"]) == 16


def test_request_id_is_preserved_when_valid(client: TestClient) -> None:
    response = client.get(
        "/api/v1/auth/me",
        headers={"X-Request-ID": "ground-console-42"},
    )

    assert response.status_code == 401
    assert response.headers["X-Request-ID"] == "ground-console-42"


def test_invalid_request_id_is_replaced(client: TestClient) -> None:
    response = client.get(
        "/api/v1/auth/me",
        headers={"X-Request-ID": "invalid request id"},
    )

    assert response.status_code == 401
    assert response.headers["X-Request-ID"] != "invalid request id"
    assert len(response.headers["X-Request-ID"]) == 16
