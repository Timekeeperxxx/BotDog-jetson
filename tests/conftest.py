"""BotDog 测试公共夹具。"""

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


def _apply_test_settings(monkeypatch: pytest.MonkeyPatch, db_path: Path) -> None:
    """应用测试环境配置并重置全局单例。"""
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("SIMULATION_WORKER_ENABLED", "false")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", '["http://localhost:3000"]')
    monkeypatch.setenv("CORS_ALLOW_CREDENTIALS", "false")

    from backend import config, database, main

    config.get_settings.cache_clear()
    new_settings = config.get_settings()

    monkeypatch.setattr(config, "settings", new_settings)
    monkeypatch.setattr(database, "settings", new_settings)
    monkeypatch.setattr(main, "settings", new_settings)
    monkeypatch.setattr(database, "_engine", None)
    monkeypatch.setattr(database, "_SessionFactory", None)


@pytest.fixture
def test_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FastAPI:
    """构建隔离配置的 FastAPI 应用实例。"""
    db_path = tmp_path / "test.db"
    _apply_test_settings(monkeypatch, db_path)

    from backend.main import create_app

    return create_app()


@pytest.fixture
async def async_client(test_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """提供异步 HTTP 客户端。"""
    from backend.database import init_db
    from httpx import ASGITransport

    await init_db()

    transport = ASGITransport(app=test_app)
    async with AsyncClient(base_url="http://test", transport=transport) as client:
        yield client


@pytest.fixture
async def test_db(test_app: FastAPI) -> AsyncGenerator[AsyncSession, None]:
    """提供隔离数据库会话。"""
    from backend.database import get_session_factory, init_db

    await init_db()
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session


@pytest.fixture
def override_settings(monkeypatch: pytest.MonkeyPatch, test_app: FastAPI):
    """按测试粒度覆盖 settings 字段。"""

    def _override(**kwargs):
        from backend import config, database, main

        for key, value in kwargs.items():
            monkeypatch.setattr(config.settings, key, value)
            monkeypatch.setattr(database.settings, key, value)
            monkeypatch.setattr(main.settings, key, value)

    return _override
