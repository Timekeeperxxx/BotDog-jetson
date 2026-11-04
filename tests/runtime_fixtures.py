"""API lifespan tests use one temporary DB and restore settings per module."""
import asyncio
from copy import deepcopy

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from backend import database
from backend.config import settings
from backend.main import create_app


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    directory = tmp_path_factory.mktemp("api-runtime")
    original = deepcopy(settings.__dict__)
    engine = create_async_engine(f"sqlite+aiosqlite:///{directory / 'api.db'}", poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(database, "_engine", engine)
        patch.setattr(database, "_SessionFactory", factory)
        for name, value in {
            "DATABASE_URL": f"sqlite+aiosqlite:///{directory / 'api.db'}", "AUTH_ENABLED": True,
            "AUTH_ADMIN_USERNAME": "admin", "AUTH_ADMIN_PASSWORD": "ValidPassword123!",
            "CONTROL_ADAPTER_TYPE": "simulation", "ROS_NAV_ENABLED": False, "AI_ENABLED": False,
            "WEATHER_ENABLED": False, "SIMULATION_WORKER_ENABLED": False, "MAVLINK_SOURCE": "simulation",
            "WEAPON_ENABLED": False, "PACKAGE_ENABLED": False, "POSE_ENABLED": False,
            "FACE_RECOGNITION_ENABLED": False, "AUTO_TRACK_ENABLED": False, "GUARD_MISSION_ENABLED": False,
            "SNAPSHOT_DIR": str(directory / "snapshots"), "RECORDING_DIR": str(directory / "recordings"),
        }.items():
            setattr(settings, name, value)
        try:
            yield create_app()
        finally:
            asyncio.run(engine.dispose())
            settings.__dict__.clear()
            settings.__dict__.update(original)
