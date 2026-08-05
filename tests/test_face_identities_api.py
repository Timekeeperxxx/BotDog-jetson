from __future__ import annotations

import numpy as np
import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.api.routes import face_identities as face_routes
from backend.auth.dependencies import require_admin, require_viewer
from backend.auth.schemas import AuthUserInternal
from backend.database import Base, get_db
from backend.face_recognition.engine import FaceExtraction
from backend.services_face_identities import FaceIdentityService


@pytest.mark.asyncio
async def test_face_identity_crud_template_and_immediate_cache_reload(tmp_path, monkeypatch) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'face-api.db'}"
    engine = create_async_engine(db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async def override_db():
        async with session_factory() as session:
            yield session

    admin = AuthUserInternal(id=1, username="admin", role="admin", token_version=0)
    service = FaceIdentityService()
    service._initialized = True
    service._available = True
    monkeypatch.setattr(face_routes, "get_face_identity_service", lambda: service)
    monkeypatch.setattr(
        service,
        "extract_template",
        lambda _: FaceExtraction(
            embedding=np.eye(1, 128, 0, dtype=np.float32).reshape(-1),
            bbox=(10, 10, 100, 100),
            detection_score=0.99,
            quality=0.9,
        ),
    )

    app = FastAPI()
    app.include_router(face_routes.router)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin] = lambda: admin
    app.dependency_overrides[require_viewer] = lambda: admin

    async with AsyncClient(app=app, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/face-identities",
            json={"display_name": "测试人员A", "notes": "验收", "enabled": True},
        )
        assert created.status_code == 201
        identity_id = created.json()["id"]

        uploaded = await client.post(
            f"/api/v1/face-identities/{identity_id}/templates",
            files={"image": ("face.png", b"synthetic-image", "image/png")},
        )
        assert uploaded.status_code == 201
        assert service.matcher.template_count == 1
        template_id = uploaded.json()["id"]

        status = await client.get("/api/v1/face-recognition/status")
        assert status.status_code == 200
        assert status.json()["template_count"] == 1

        deleted_template = await client.delete(
            f"/api/v1/face-identities/{identity_id}/templates/{template_id}"
        )
        assert deleted_template.status_code == 204
        assert service.matcher.template_count == 0

        deleted_identity = await client.delete(f"/api/v1/face-identities/{identity_id}")
        assert deleted_identity.status_code == 204
        assert (await client.get("/api/v1/face-identities")).json() == []

    await engine.dispose()
