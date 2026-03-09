"""
数据库基础设施层。

职责边界：
- 暴露 engine / SessionFactory / get_db 等“基础设施服务”；
- 不混入具体业务模型或查询逻辑，保持对上层 service 的低耦合。
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from .config import settings


class Base(DeclarativeBase):
    """SQLAlchemy 基类，后续所有 ORM 模型统一继承自此。"""


_engine: AsyncEngine | None = None
_SessionFactory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        # 延迟初始化 engine，避免导入时即触发 I/O。
        _engine = create_async_engine(
            str(settings.DATABASE_URL),
            echo=False,
            future=True,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )
    return _SessionFactory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI 依赖入口：为每个请求提供独立的 AsyncSession。

    设计要点：
    - 使用 `async with` 确保连接正确关闭。
    - 上层不要直接操作 engine，以防止连接泄漏。
    """

    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session


async def init_db() -> None:
    """
    初始化数据库结构。
    使用 SQLAlchemy 元数据创建表结构。
    注意：`db/schema.sql` 主要用于文档与手工初始化；运行时以 ORM 定义为准。
    """

    engine = get_engine()
    async with engine.begin() as conn:
        from . import models, models_config  # noqa: F401
        await conn.run_sync(Base.metadata.create_all)


__all__ = ["Base", "get_db", "get_engine", "get_session_factory", "init_db"]

