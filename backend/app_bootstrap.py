"""后端启动前的持久化状态初始化。"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select

from .auth.security import get_password_hash
from .config import settings
from .database import get_session_factory, init_db
from .logging_config import get_logger
from .models import User
from .services_config import get_config_service
from .services_tasks import cleanup_stale_tasks
from .services_video_sources import get_network_interface_service, get_video_source_service
from .startup_summary import StartupSummary

startup_logger = get_logger("启动环境")
config_logger = get_logger("核心配置")
db_logger = get_logger("数据库")
cleanup_logger = get_logger("启动清理")


async def prepare_bootstrap_state() -> tuple[StartupSummary, Path]:
    """
    初始化与业务运行态无关的持久化基础状态。

    这一步只负责：
    - 读取和提示关键配置
    - 初始化数据库
    - 创建默认管理员
    - 初始化系统配置
    - 初始化视频源和网口默认值
    - 清理遗留任务
    - 创建快照目录
    """

    config_logger.info(
        "加载配置文件：path={}，THERMAL_THRESHOLD={}°C",
        Path(__file__).resolve().parent / ".env",
        settings.THERMAL_THRESHOLD,
    )
    if not settings.AUTH_ENABLED:
        config_logger.warning("鉴权已关闭，仅限开发环境：AUTH_ENABLED=false")
    if settings.AUTH_ADMIN_PASSWORD == "please_change_me":
        config_logger.warning("AUTH_ADMIN_PASSWORD 仍为默认值，生产环境必须修改")
    if settings.JWT_SECRET == "please_change_me":
        config_logger.warning("JWT_SECRET 仍为默认值，生产环境必须修改")
        if settings.AUTH_ENABLED:
            config_logger.warning("AUTH_ENABLED=true 且 JWT_SECRET 为默认值，这属于高风险配置！")

    startup_summary = StartupSummary()
    await init_db()
    db_logger.info("数据库初始化完成")
    startup_summary.set("数据库", "ready", "数据库连接可用")

    async with get_session_factory()() as session:
        user_count = await session.scalar(select(func.count(User.id)))
        if user_count == 0:
            config_logger.info("检测到 users 表为空，准备从 .env 创建 Bootstrap Admin...")
            new_admin = User(
                username=settings.AUTH_ADMIN_USERNAME,
                password_hash=get_password_hash(settings.AUTH_ADMIN_PASSWORD),
                role="admin",
                enabled=1,
            )
            session.add(new_admin)
            await session.commit()
            config_logger.info("已创建初始 Admin 账号：{}", settings.AUTH_ADMIN_USERNAME)

    config_service = get_config_service()
    async with get_session_factory()() as session:
        await config_service.initialize_defaults(session)
        await config_service.get_all_configs(session)
    config_logger.info("系统配置已加载完成")

    video_source_service = get_video_source_service()
    network_interface_service = get_network_interface_service()
    async with get_session_factory()() as session:
        await video_source_service.initialize_defaults(session)
        await network_interface_service.initialize_defaults(session)
    config_logger.info("视频源与网口默认配置已初始化")

    async with get_session_factory()() as session:
        stale_count = await cleanup_stale_tasks(session)
        if stale_count:
            cleanup_logger.warning("发现并关闭遗留任务：数量={}", stale_count)
        else:
            cleanup_logger.info("未发现遗留任务")

    snapshot_dir = Path(settings.SNAPSHOT_DIR)
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    return startup_summary, snapshot_dir
