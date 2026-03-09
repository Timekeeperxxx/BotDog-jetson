"""CORS 配置与启动校验单元测试。"""

import pytest


class TestCorsConfiguration:
    """CORS 配置校验在 create_app() 中的测试。"""

    def test_cors_valid_wildcard_no_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """通配符 origins 配合 credentials=False 应为合法。"""
        from backend import config, database, main

        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
        monkeypatch.setenv("SIMULATION_WORKER_ENABLED", "false")
        monkeypatch.setenv("CORS_ALLOW_ORIGINS", '["*"]')
        monkeypatch.setenv("CORS_ALLOW_CREDENTIALS", "false")

        config.get_settings.cache_clear()
        settings = config.get_settings()
        for m in (config, database, main):
            monkeypatch.setattr(m, "settings", settings)
        monkeypatch.setattr(database, "_engine", None)
        monkeypatch.setattr(database, "_SessionFactory", None)

        app = main.create_app()
        assert app is not None

    def test_cors_valid_specific_origin_with_credentials(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """指定 origins 配合 credentials=True 应为合法。"""
        from backend import config, database, main

        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
        monkeypatch.setenv("SIMULATION_WORKER_ENABLED", "false")
        monkeypatch.setenv("CORS_ALLOW_ORIGINS", '["http://localhost:3000"]')
        monkeypatch.setenv("CORS_ALLOW_CREDENTIALS", "true")

        config.get_settings.cache_clear()
        settings = config.get_settings()
        for m in (config, database, main):
            monkeypatch.setattr(m, "settings", settings)
        monkeypatch.setattr(database, "_engine", None)
        monkeypatch.setattr(database, "_SessionFactory", None)

        app = main.create_app()
        assert app is not None

    def test_cors_invalid_wildcard_with_credentials_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """通配符 origins 与 credentials=True 组合在启动期应抛出 ValueError。"""
        from backend import config, database, main

        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
        monkeypatch.setenv("SIMULATION_WORKER_ENABLED", "false")
        monkeypatch.setenv("CORS_ALLOW_ORIGINS", '["*"]')
        monkeypatch.setenv("CORS_ALLOW_CREDENTIALS", "true")

        config.get_settings.cache_clear()
        settings = config.get_settings()
        for m in (config, database, main):
            monkeypatch.setattr(m, "settings", settings)

        with pytest.raises(ValueError, match="Invalid CORS settings"):
            main.create_app()
