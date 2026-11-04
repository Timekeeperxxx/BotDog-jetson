"""P0 regressions: real authentication, temporary DB/files, no app lifespan/hardware."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.websockets import WebSocketDisconnect

from backend import main
from backend.auth import dependencies as auth_dependencies
from backend.auth.dependencies import BROWSER_SESSION_COOKIE
from backend.auth.schemas import AuthUserInternal
from backend.auth.security import get_password_hash
from backend.auth.service import create_access_token
from backend.config import settings
from backend.database import Base, get_db
from backend.models import User


ADMIN_WRITES = [
    ("POST", "/api/v1/video-sources", {"name": "probe", "label": "probe"}),
    ("PUT", "/api/v1/video-sources/9999", {"name": "probe", "label": "probe"}),
    ("DELETE", "/api/v1/video-sources/9999", None),
    ("POST", "/api/v1/network-interfaces", {"name": "probe", "label": "probe", "iface_name": "fake0"}),
    ("PUT", "/api/v1/network-interfaces/9999", {"name": "probe", "label": "probe", "iface_name": "fake0"}),
    ("DELETE", "/api/v1/network-interfaces/9999", None),
    ("POST", "/api/v1/focus-zones", {"polygon_json": "[[0,0],[1,0],[0,1]]"}),
    ("PUT", "/api/v1/focus-zones/9999", {"polygon_json": "[[0,0],[1,0],[0,1]]"}),
    ("DELETE", "/api/v1/focus-zones/9999", None),
    ("POST", "/api/v1/test/alert", None),
]
OPERATOR_WRITES = [
    ("POST", "/api/v1/audio/play", None),
    ("POST", "/api/v1/audio/stop", None),
    ("POST", "/api/v1/session/start", {"task_name": "security probe"}),
    ("POST", "/api/v1/session/stop", {"task_id": 9999}),
    ("POST", "/api/v1/snapshot", None),
    ("POST", "/api/v1/recording/start", None),
    ("POST", "/api/v1/recording/stop", None),
]
READS = [
    "/api/v1/video-sources", "/api/v1/video-sources/active", "/api/v1/network-interfaces",
    "/api/v1/focus-zones", "/api/v1/session/current", "/api/v1/audio/status",
    "/api/v1/recording/status", "/api/v1/recordings", "/api/v1/system/startup",
    "/api/v1/system/safety", "/api/v1/static/probe.txt", "/api/v1/media/recordings/probe.mp4",
]
WS_PATHS = ["/ws/telemetry", "/ws/event", "/ws/nav-mapping-cloud"]


@pytest.fixture(scope="module")
def security_password_hash():
    return get_password_hash("SecurityProbe123!")


@pytest.fixture
def security_app(tmp_path, monkeypatch, security_password_hash):
    frontend = tmp_path / "frontend" / "dist"
    (frontend / "assets").mkdir(parents=True)
    (frontend / "index.html").write_text("<html>security SPA</html>")
    (frontend / "assets" / "app.js").write_text("window.securityProbe = true")
    outside = tmp_path / "pytest.ini"
    outside.write_text("OUTSIDE_FRONTEND_BOUNDARY")
    (frontend / "outside-link.txt").symlink_to(outside)
    snapshots, recordings = tmp_path / "snapshots", tmp_path / "recordings"
    snapshots.mkdir()
    recordings.mkdir()
    (snapshots / "probe.txt").write_text("private snapshot")
    (snapshots / "outside-link.txt").symlink_to(outside)
    (recordings / "probe.mp4").write_bytes(b"0123456789")
    monkeypatch.setattr(main, "__file__", str(tmp_path / "backend" / "main.py"))
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "JWT_SECRET", "isolated-security-regression-secret")
    monkeypatch.setattr(settings, "JWT_EXPIRE_MINUTES", 15)
    monkeypatch.setattr(settings, "SNAPSHOT_DIR", str(snapshots))
    monkeypatch.setattr(settings, "RECORDING_DIR", str(recordings))
    monkeypatch.setattr(settings, "CORS_ALLOW_ORIGINS", ["*"])
    monkeypatch.setattr(settings, "CORS_ALLOW_CREDENTIALS", False)

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'security.db'}", poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    password_hash = security_password_hash

    async def initialize():
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as db:
            for i, role in enumerate(["viewer", "operator", "admin"], 1):
                db.add(User(id=i, username=f"security-{role}", role=role, password_hash=password_hash))
            await db.commit()

    asyncio.run(initialize())

    async def temporary_db():
        async with factory() as db:
            yield db

    monkeypatch.setattr(auth_dependencies, "get_session_factory", lambda: factory)
    from backend.api.routes import recording
    monkeypatch.setattr(recording, "get_session_factory", lambda: factory)
    app = main.create_app()
    app.dependency_overrides[get_db] = temporary_db
    # Do not enter TestClient as a context manager: app lifespan must not run.
    client = TestClient(app)
    tokens = {
        role: create_access_token(AuthUserInternal(id=i, username=f"security-{role}", role=role, token_version=0))
        for i, role in enumerate(["viewer", "operator", "admin"], 1)
    }
    yield SimpleNamespace(app=app, client=client, tokens=tokens, factory=factory)
    client.close()
    asyncio.run(engine.dispose())


def bearer(env, role):
    return {"Authorization": f"Bearer {env.tokens[role]}"}


@pytest.mark.parametrize("path", [
    "/%2e%2e/%2e%2e/pytest.ini", "/..%2f..%2fpytest.ini", "/outside-link.txt", "/%00",
    "/api/does-not-exist", "/ws/does-not-exist",
])
def test_spa_rejects_traversal_symlinks_and_unknown_api(security_app, path):
    response = security_app.client.get(path)
    assert response.status_code == 404
    assert "OUTSIDE_FRONTEND_BOUNDARY" not in response.text


@pytest.mark.parametrize("path", ["/", "/login", "/navigation", "/assets/app.js"])
def test_public_frontend_still_loads(security_app, path):
    assert security_app.client.get(path).status_code == 200


@pytest.mark.parametrize("method,path,body", ADMIN_WRITES + OPERATOR_WRITES)
@pytest.mark.parametrize("role,expected", [(None, 401), ("viewer", 403)])
def test_management_writes_reject_anonymous_and_viewer(security_app, method, path, body, role, expected):
    headers = bearer(security_app, role) if role else {}
    response = security_app.client.request(method, path, json=body, headers=headers)
    assert response.status_code == expected, response.text


@pytest.mark.parametrize("method,path,body", ADMIN_WRITES)
def test_operator_cannot_change_admin_configuration(security_app, method, path, body):
    response = security_app.client.request(method, path, json=body, headers=bearer(security_app, "operator"))
    assert response.status_code == 403, response.text


@pytest.mark.parametrize("path", READS)
def test_private_reads_require_authentication(security_app, path):
    assert security_app.client.get(path).status_code == 401
    assert security_app.client.get(path, headers=bearer(security_app, "viewer")).status_code == 200


def test_admin_video_source_crud_and_operator_session_use_temp_db(security_app):
    client = security_app.client
    admin = bearer(security_app, "admin")
    body = {"name": "probe", "label": "probe"}
    created = client.post("/api/v1/video-sources", json=body, headers=admin)
    assert created.status_code == 201, created.text
    source_id = created.json()["source"]["source_id"]
    assert client.put(f"/api/v1/video-sources/{source_id}", json={**body, "label": "changed"}, headers=admin).status_code == 200
    assert client.delete(f"/api/v1/video-sources/{source_id}", headers=admin).status_code == 200
    operator = bearer(security_app, "operator")
    started = client.post("/api/v1/session/start", json={"task_name": "security probe"}, headers=operator)
    assert started.status_code == 200, started.text
    assert client.post("/api/v1/session/stop", json={"task_id": started.json()["task_id"]}, headers=operator).status_code == 200


def test_operator_audio_uses_fake_hardware(security_app, monkeypatch):
    from backend import guard_mission_service
    fake = SimpleNamespace(start_audio=AsyncMock(), stop_audio=AsyncMock())
    monkeypatch.setattr(guard_mission_service, "get_guard_mission_service", lambda: fake)
    for action in ["play", "stop"]:
        assert security_app.client.post(f"/api/v1/audio/{action}", headers=bearer(security_app, "operator")).status_code == 200
    fake.start_audio.assert_awaited_once()
    fake.stop_audio.assert_awaited_once()


def test_media_cookie_logout_head_and_video_ranges(security_app):
    client = security_app.client
    login = client.post("/api/v1/auth/login", json={"username": "security-viewer", "password": "SecurityProbe123!"})
    assert login.status_code == 200
    cookie = login.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert client.get("/api/v1/static/probe.txt").text == "private snapshot"
    assert client.get("/api/v1/static/probe.txt").headers["cache-control"] == "private, no-store"
    assert client.head("/api/v1/media/recordings/probe.mp4").status_code == 200
    ranged = client.get("/api/v1/media/recordings/probe.mp4", headers={"Range": "bytes=2-4"})
    assert ranged.status_code == 206 and ranged.content == b"234"
    assert client.get("/api/v1/static/outside-link.txt").status_code == 404
    # A browser cookie must not authenticate mutable API requests (CSRF boundary).
    assert client.post("/api/v1/audio/play").status_code == 401
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/static/probe.txt").status_code == 401


def test_existing_bearer_session_gets_browser_cookie(security_app):
    response = security_app.client.get("https://testserver/api/v1/auth/me", headers=bearer(security_app, "viewer"))
    assert response.status_code == 200
    assert "secure" in response.headers["set-cookie"].lower()


@pytest.mark.parametrize("kind", ["invalid", "expired", "disabled", "revoked"])
def test_media_rejects_invalid_expired_and_revoked_credentials(security_app, monkeypatch, kind):
    token = security_app.tokens["viewer"]
    if kind == "invalid":
        token = "invalid.token.value"
    elif kind == "expired":
        monkeypatch.setattr(settings, "JWT_EXPIRE_MINUTES", -1)
        token = create_access_token(AuthUserInternal(id=1, username="security-viewer", role="viewer", token_version=0))
    else:
        async def revoke():
            async with security_app.factory() as db:
                values = {"enabled": 0} if kind == "disabled" else {"token_version": 1}
                await db.execute(update(User).where(User.id == 1).values(**values))
                await db.commit()
        asyncio.run(revoke())
    security_app.client.cookies.set(BROWSER_SESSION_COOKIE, token)
    assert security_app.client.get("/api/v1/static/probe.txt").status_code == 401


@pytest.mark.parametrize("path", WS_PATHS)
@pytest.mark.parametrize("credential", ["missing", "invalid", "cross-origin", "cookie", "bearer"])
def test_websocket_authentication_and_origin(security_app, monkeypatch, path, credential):
    from backend.api.routes import websocket as routes

    async def stream(ws, *args):
        await ws.accept()
        await ws.send_json({"authenticated": True})
        await ws.close()

    fake = SimpleNamespace(handle_connection=stream)
    monkeypatch.setattr(routes, "get_queue_manager", lambda: object())
    monkeypatch.setattr(routes, "get_state_machine", lambda: object())
    monkeypatch.setattr(routes, "websocket_telemetry_handler", stream)
    monkeypatch.setattr(routes, "get_event_broadcaster", lambda: fake)
    monkeypatch.setattr(routes, "get_mapping_cloud_broadcaster", lambda: fake)
    headers = {"Origin": "http://testserver"}
    if credential in {"cookie", "cross-origin"}:
        security_app.client.cookies.set(BROWSER_SESSION_COOKIE, security_app.tokens["viewer"])
    if credential == "cross-origin":
        headers["Origin"] = "http://untrusted.invalid"
    if credential == "invalid":
        headers["Authorization"] = "Bearer invalid.token.value"
    if credential == "bearer":
        headers.update(bearer(security_app, "viewer"))
    if credential in {"cookie", "bearer"}:
        with security_app.client.websocket_connect(path, headers=headers) as ws:
            assert ws.receive_json() == {"authenticated": True}
    else:
        with pytest.raises(WebSocketDisconnect) as error:
            with security_app.client.websocket_connect(path, headers=headers):
                pass
        assert error.value.code == 1008


def test_all_mutating_routes_have_auth_except_explicit_public_endpoints(security_app):
    public = {("post", "/api/v1/auth/login"), ("post", "/api/v1/auth/logout"), ("post", "/api/v1/control/e-stop")}
    spec = security_app.app.openapi()
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            if method in {"post", "put", "patch", "delete"} and (method, path) not in public:
                assert operation.get("security"), f"Unprotected write: {method.upper()} {path}"
    assert security_app.client.get("/api/v1/system/health").status_code == 200


def test_control_diagnostics_requires_operator_and_readiness_requires_login(security_app):
    client = security_app.client
    assert client.get("/api/v1/control/debug").status_code == 401
    assert client.get("/api/v1/control/debug", headers=bearer(security_app, "viewer")).status_code == 403
    for role in ["operator", "admin"]:
        assert client.get("/api/v1/control/debug", headers=bearer(security_app, role)).status_code == 200
    assert client.get("/api/v1/system/readiness").status_code == 401
    assert client.get("/api/v1/system/readiness", headers=bearer(security_app, "viewer")).status_code == 503
