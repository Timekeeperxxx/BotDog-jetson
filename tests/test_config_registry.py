from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.api.routes.config import _apply_runtime_update
from backend.config import settings
from backend.models_config import ConfigChangeHistory, SystemConfig
from backend.services_config import ConfigService


async def test_database_config_restores_modified_runtime_value(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'config.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(SystemConfig.__table__.create)
        await connection.run_sync(ConfigChangeHistory.__table__.create)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    service = ConfigService()
    original_ai_fps = settings.AI_FPS
    try:
        settings.AI_FPS = 7
        async with session_factory() as session:
            await service.initialize_defaults(session)
            row = await session.scalar(select(SystemConfig).where(SystemConfig.key == "ai_fps"))
            assert row is not None
            assert row.value == "7"

            await service.update_config(session, "ai_fps", "11", changed_by="tester")

        # 有修改历史的值不能再被新的 .env/default 覆盖。
        settings.AI_FPS = 3
        async with session_factory() as session:
            await service.initialize_defaults(session)
            restored_count = await service.load_into_settings(session)
            public = await service.get_config(session, "ai_fps")

        assert restored_count > 100
        assert settings.AI_FPS == 11
        assert public is not None
        assert public["validation"] == {"min": 1, "max": 60}
    finally:
        settings.AI_FPS = original_ai_fps
        await engine.dispose()


def test_registry_excludes_sensitive_credentials() -> None:
    configs = ConfigService.DEFAULT_CONFIGS

    assert len(configs) >= 160
    assert "auth_admin_password" not in configs
    assert "jwt_secret" not in configs
    assert "database_url" not in configs
    assert {"ai", "control", "guard", "navigation", "ros", "logging"}.issubset(
        {definition["category"] for definition in configs.values()}
    )


def test_restart_only_config_does_not_mutate_live_setting() -> None:
    original_ai_fps = settings.AI_FPS
    try:
        result = _apply_runtime_update("ai_fps", "12")

        assert settings.AI_FPS == original_ai_fps
        assert result == {
            "applied": False,
            "target": "ai",
            "message": "已保存，重启后端后生效",
        }
    finally:
        settings.AI_FPS = original_ai_fps


def test_hot_auto_track_setting_updates_settings_and_service(monkeypatch) -> None:
    class FakeAutoTrackService:
        def __init__(self) -> None:
            self.calls: list[tuple[str, object]] = []

        def update_params(self, key: str, value: object) -> bool:
            self.calls.append((key, value))
            return True

    fake_service = FakeAutoTrackService()
    monkeypatch.setattr(
        "backend.auto_track_service.get_auto_track_service",
        lambda: fake_service,
    )
    original_vx = settings.AUTO_TRACK_VX
    try:
        result = _apply_runtime_update("auto_track_vx", "0.25")

        assert settings.AUTO_TRACK_VX == 0.25
        assert fake_service.calls == [("auto_track_vx", "0.25")]
        assert result == {
            "applied": True,
            "target": "auto_track",
            "message": "运行时已生效",
        }
    finally:
        settings.AUTO_TRACK_VX = original_vx


def test_lidar_mount_calibration_is_admin_managed_and_applies_to_next_start() -> None:
    configs = ConfigService.DEFAULT_CONFIGS
    expected = {
        "nav_lidar_mount_x_m",
        "nav_lidar_mount_y_m",
        "nav_lidar_mount_z_m",
        "nav_lidar_mount_roll_deg",
        "nav_lidar_mount_pitch_deg",
        "nav_lidar_mount_yaw_deg",
    }

    assert expected.issubset(configs)
    assert all(configs[key]["category"] == "navigation" for key in expected)
    assert all(configs[key]["is_hot_reloadable"] is True for key in expected)

    original_height = settings.NAV_LIDAR_MOUNT_Z_M
    try:
        result = _apply_runtime_update("nav_lidar_mount_z_m", "0.85")
        assert settings.NAV_LIDAR_MOUNT_Z_M == 0.85
        assert result == {
            "applied": True,
            "target": "navigation",
            "message": "已载入，下一次建图或定位启动时生效",
        }
    finally:
        settings.NAV_LIDAR_MOUNT_Z_M = original_height
