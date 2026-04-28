"""
应用层入口。

职责边界：
- 只负责 FastAPI 应用的装配：中间件、生命周期钩子、路由注册；
- 不直接承载业务逻辑，业务逻辑拆分到 service / gateway / repository 等模块。
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import init_db, get_session_factory
from .logging_config import logger, setup_logging
from .services_tasks import cleanup_stale_tasks
from .state_machine_state import set_state_machine
from .alert_service import AlertService
from .mavlink_gateway import MAVLinkGateway

from .state_machine import StateMachine
from .telemetry_queue import TelemetryQueueManager, set_telemetry_queue_manager
from .workers_telemetry import TelemetryPersistenceWorker
from .ws_broadcaster import WebSocketBroadcaster
from .ws_event_broadcaster import EventBroadcaster
from .ws_runtime_state import clear_ws_runtime, set_ws_runtime
from .control_service import ControlService, set_control_service
from .robot_adapter import create_adapter

# 全局组件（在 lifespan 中初始化）
_state_machine: StateMachine | None = None
_queue_manager: TelemetryQueueManager | None = None
_mavlink_gateway: MAVLinkGateway | None = None
_ws_broadcaster: WebSocketBroadcaster | None = None
_persistence_worker: TelemetryPersistenceWorker | None = None
_event_broadcaster: EventBroadcaster | None = None
_ai_worker: Any | None = None
_control_service: ControlService | None = None
_ros_nav_bridge: Any | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    应用生命周期管理（FastAPI 推荐的 lifespan 模式）。

    阶段 1 集成的组件：
    - 状态机（心跳超时检测）
    - 遥测队列管理器（广播队列 + 落盘队列）
    - MAVLink 网关（支持真实/模拟数据源）
    - WebSocket 广播器（遥测数据推送）
    - 遥测落盘 Worker（数据库写入）

    """

    global _ros_nav_bridge

    # Startup
    setup_logging()
    logger.info("BotDog backend starting up (lifespan)...")
    logger.info("Config loaded from {}", settings.Config.env_file)
    logger.info("THERMAL_THRESHOLD={}°C", settings.THERMAL_THRESHOLD)
    await init_db()
    logger.info("Database initialized.")

    from .services_config import get_config_service
    config_service = get_config_service()
    async with get_session_factory()() as _session:
        await config_service.initialize_defaults(_session)
        await config_service.get_all_configs(_session)
    logger.info("系统配置服务已初始化加载")

    # 初始化视频源和网口默认数据
    from .services_video_sources import get_video_source_service, get_network_interface_service
    _vs_service = get_video_source_service()
    _ni_service = get_network_interface_service()
    async with get_session_factory()() as _vs_session:
        await _vs_service.initialize_defaults(_vs_session)
        await _ni_service.initialize_defaults(_vs_session)
    logger.info("视频源 & 网口配置服务已初始化")

    # 清理上次进程遗留的僵尸任务（防止 AI Worker 误认为任务仍在运行）
    async with get_session_factory()() as _startup_session:
        _stale_count = await cleanup_stale_tasks(_startup_session)
        if _stale_count:
            logger.warning("启动清理: 发现并关闭了 {} 个遗留的 running 任务", _stale_count)
        else:
            logger.info("启动清理: 无遗留任务")

    snapshot_dir = Path(settings.SNAPSHOT_DIR)
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    # 全局停止事件
    global stop_event
    stop_event = asyncio.Event()

    # 任务列表
    tasks: list[asyncio.Task[None]] = []

    try:
        # 1. 初始化状态机
        global _state_machine
        _state_machine = StateMachine(
            heartbeat_timeout=settings.HEARTBEAT_TIMEOUT,
        )
        set_state_machine(_state_machine)
        tasks.append(asyncio.create_task(_state_machine.start_heartbeat_monitor()))
        logger.info("状态机已启动")

        # 2. 初始化遥测队列管理器
        global _queue_manager
        _queue_manager = TelemetryQueueManager(
            sampling_interval=1.0 / settings.TELEMETRY_SAMPLING_HZ,
        )
        # 注册为全局单例，供 Worker 无法注入时通过 get_telemetry_queue_manager() 获取
        set_telemetry_queue_manager(_queue_manager)
        tasks.append(asyncio.create_task(_queue_manager.start_sampling_task(stop_event)))
        logger.info("遥测队列管理器已启动")

        # 3. 初始化遥测数据源（根据适配器类型选择）
        global _mavlink_gateway
        if settings.CONTROL_ADAPTER_TYPE == "unitree_b2":
            # 宇树 B2 模式：使用 DDS 订阅 sportmodestate 获取真实遥测

            from .workers_unitree_telemetry import UnitreeTelemetryWorker
            _unitree_telemetry_worker = UnitreeTelemetryWorker(
                queue_manager=_queue_manager,
                state_machine=_state_machine,
                network_interface=settings.UNITREE_NETWORK_IFACE,
            )
            tasks.append(asyncio.create_task(_unitree_telemetry_worker.start(stop_event)))
            logger.info(f"宇树遥测 Worker 已启动，网卡={settings.UNITREE_NETWORK_IFACE}")
            # MAVLink gateway 仍需初始化供其他模块引用，但不启动
            _mavlink_gateway = MAVLinkGateway(
                queue_manager=_queue_manager,
                state_machine=_state_machine,
            )
        else:
            # MAVLink / 模拟模式
            _mavlink_gateway = MAVLinkGateway(
                queue_manager=_queue_manager,
                state_machine=_state_machine,
            )
            tasks.append(asyncio.create_task(_mavlink_gateway.start(stop_event)))
            logger.info(f"MAVLink 网关已启动，数据源: {settings.MAVLINK_SOURCE}")

        # 4. 初始化 WebSocket 广播器
        global _ws_broadcaster
        _ws_broadcaster = WebSocketBroadcaster(
            queue_manager=_queue_manager,
            broadcast_interval=1.0 / settings.TELEMETRY_BROADCAST_HZ,
        )
        tasks.append(asyncio.create_task(_ws_broadcaster.start()))
        logger.info("WebSocket 广播器已启动")

        # 5. 初始化遥测落盘 Worker
        if settings.MAVLINK_SOURCE != "simulation" or settings.SIMULATION_WORKER_ENABLED:
            session_factory = get_session_factory()
            global _persistence_worker
            _persistence_worker = TelemetryPersistenceWorker(
                session_factory=session_factory,
                sampling_interval=1.0 / settings.TELEMETRY_SAMPLING_HZ,
            )
            tasks.append(asyncio.create_task(_persistence_worker.start(stop_event)))
            logger.info("遥测落盘 Worker 已启动")
        else:
            logger.info("遥测落盘 Worker 已跳过（simulation + SIMULATION_WORKER_ENABLED=false）")

        # 6. 可选：启动模拟数据 Worker（开发/测试）
        if settings.SIMULATION_WORKER_ENABLED:
            from .workers_simulation import simulation_worker

            tasks.append(asyncio.create_task(simulation_worker(stop_event)))
            logger.info("模拟数据 Worker 已启动")

        # 7. 启动 AI Worker（旁路识别）
        if settings.AI_ENABLED:
            from .workers_ai import AIWorker
            global _ai_worker
            _ai_worker = AIWorker(
                session_factory=get_session_factory(),
                state_machine=_state_machine,
                mavlink_gateway=_mavlink_gateway,
                snapshot_dir=snapshot_dir,
            )
            tasks.append(asyncio.create_task(_ai_worker.start(stop_event)))
            logger.info("AI Worker 已启动")
        else:
            logger.info("AI Worker 已禁用")

        # 8. 初始化事件广播器（阶段 4）
        from .global_event_broadcaster import set_global_event_broadcaster
        from .alert_service import set_alert_service
        global _event_broadcaster
        _event_broadcaster = EventBroadcaster()
        set_global_event_broadcaster(_event_broadcaster)  # 设置全局单例
        set_ws_runtime(_queue_manager, _state_machine, _event_broadcaster)
        logger.info("事件广播器已初始化")

        # 8.1 初始化 ROS2 导航状态订阅转发（可选）
        if settings.ROS_NAV_ENABLED:
            from .services_ros_nav import RosNavBridge

            _ros_nav_bridge = RosNavBridge(
                broadcaster=_event_broadcaster,
                loop=asyncio.get_running_loop(),
            )
            _ros_nav_bridge.start()
            from .nav_bridge_state import set_ros_nav_bridge as _set_nav_bridge
            _set_nav_bridge(_ros_nav_bridge)
            logger.info(
                "ROS2 导航状态订阅转发已请求启动: topic={}, type={}",
                settings.ROS_NAV_POSE_TOPIC,
                settings.ROS_NAV_POSE_TYPE,
            )
        else:
            logger.info("ROS2 导航状态订阅转发已禁用")

        # 8. 初始化告警服务并注入 broadcaster
        alert_service_instance = AlertService(event_broadcaster=_event_broadcaster)
        set_alert_service(alert_service_instance)
        logger.info(f"告警服务已初始化，broadcaster ID: {id(_event_broadcaster)}")

        # 9. 初始化控制服务（阶段 6）
        global _control_service
        _adapter_kwargs = {}
        if settings.CONTROL_ADAPTER_TYPE == "unitree_b2":
            _adapter_kwargs = {
                "network_interface": settings.UNITREE_NETWORK_IFACE,
                "vx": settings.UNITREE_B2_VX,
                "vyaw": settings.UNITREE_B2_VYAW,
            }

        if settings.CONTROL_ADAPTER_TYPE == "unitree_b2":
            # UnitreeB2Adapter.__init__ 含同步阻塞 SDK 调用（约 20s）。
            # 先以 adapter=None 启动 ControlService；后台初始化成功后热替换。
            # 初始化期间控制命令返回 REJECTED_ADAPTER_NOT_READY，语义正确。
            _control_service = ControlService(
                adapter=None,
                state_machine=_state_machine,
                watchdog_timeout_ms=settings.CONTROL_WATCHDOG_TIMEOUT_MS,
                cmd_rate_limit_ms=settings.CONTROL_CMD_RATE_LIMIT_MS,
            )
            set_control_service(_control_service)
            tasks.append(asyncio.create_task(_control_service.run_watchdog(stop_event)))
            logger.info(
                "控制服务已启动（B2 适配器初始化中，控制命令暂时被拒绝）..."
            )

            async def _init_b2_adapter_background() -> None:
                """后台初始化 B2 适配器，完成后热替换到 ControlService。"""
                try:
                    real_adapter = create_adapter("unitree_b2", **_adapter_kwargs)
                    _control_service.set_adapter(real_adapter)
                    logger.info("[B2Init] UnitreeB2Adapter 初始化完成，已热替换控制适配器")
                except Exception as exc:
                    logger.error(f"[B2Init] B2 适配器初始化失败，控制命令将被拒绝: {exc}")

            tasks.append(asyncio.create_task(_init_b2_adapter_background()))
        else:
            _adapter = create_adapter(settings.CONTROL_ADAPTER_TYPE, **_adapter_kwargs)
            _control_service = ControlService(
                adapter=_adapter,
                state_machine=_state_machine,
                watchdog_timeout_ms=settings.CONTROL_WATCHDOG_TIMEOUT_MS,
                cmd_rate_limit_ms=settings.CONTROL_CMD_RATE_LIMIT_MS,
            )
            set_control_service(_control_service)
            tasks.append(asyncio.create_task(_control_service.run_watchdog(stop_event)))
            logger.info(
                f"控制服务已启动，适配器: {settings.CONTROL_ADAPTER_TYPE}，"
                f"Watchdog: {settings.CONTROL_WATCHDOG_TIMEOUT_MS}ms"
            )


        # 10. 初始化区域判断服务，从数据库加载重点区
        from .zone_service import ZoneService, set_zone_service
        _zone_service = ZoneService()
        async with get_session_factory()() as _zone_session:
            await _zone_service.load_from_db(_zone_session)
        set_zone_service(_zone_service)
        logger.info(f"重点区服务已初始化，共加载 {_zone_service.zone_count} 个区域")

        # 11. 初始化自动跟踪服务（始终装配，运行时启停由内部状态控制）
        from .target_manager import TargetManager
        from .control_arbiter import ControlArbiter, set_control_arbiter
        from .stranger_policy import StrangerPolicy, set_stranger_policy
        from .auto_track_service import AutoTrackService, set_auto_track_service

        _target_manager = TargetManager(
            frame_width=settings.AI_FRAME_WIDTH,
            frame_height=settings.AI_FRAME_HEIGHT,
        )
        _arbiter = ControlArbiter()
        set_control_arbiter(_arbiter)

        _stranger_policy = StrangerPolicy()
        set_stranger_policy(_stranger_policy)

        _auto_track_service = AutoTrackService(
            zone_service=_zone_service,
            control_service=_control_service,
            event_broadcaster=_event_broadcaster,
            state_machine=_state_machine,
            session_factory=get_session_factory(),
            snapshot_dir=snapshot_dir,
            frame_width=settings.AI_FRAME_WIDTH,
            frame_height=settings.AI_FRAME_HEIGHT,
            stable_hits=settings.AI_STABLE_HITS,
            reset_misses=settings.AI_RESET_MISSES,
            out_of_zone_frames=settings.AUTO_TRACK_OUT_OF_ZONE_FRAMES,
            lost_timeout_frames=settings.AUTO_TRACK_LOST_TIMEOUT_FRAMES,
            command_interval_ms=settings.AUTO_TRACK_COMMAND_INTERVAL_MS,
            yaw_deadband_px=settings.AUTO_TRACK_YAW_DEADBAND_PX,
            forward_area_ratio=settings.AUTO_TRACK_FORWARD_AREA_RATIO,
            anchor_y_stop_ratio=settings.AUTO_TRACK_ANCHOR_Y_STOP_RATIO,
            stop_snapshot_enabled=settings.AUTO_TRACK_STOP_SNAPSHOT_ENABLED,
            default_enabled=settings.AUTO_TRACK_ENABLED,
            yaw_pulse_ms=settings.AUTO_TRACK_YAW_PULSE_MS,
            target_manager=_target_manager,
            control_arbiter=_arbiter,
        )
        set_auto_track_service(_auto_track_service)
        logger.info(
            f"自动跟踪服务已初始化，默认启用={settings.AUTO_TRACK_ENABLED}，"
            f"多目标模式已开启"
        )
        
        # 12. 初始化自动驱离主脑服务
        from .guard_mission_service import GuardMissionService, set_guard_mission_service
        _guard_mission_service = GuardMissionService(
            zone_service=_zone_service,
            control_service=_control_service,
            control_arbiter=_arbiter,
            event_broadcaster=_event_broadcaster,
            config=settings,
            session_factory=get_session_factory(),
            snapshot_dir=snapshot_dir,
            frame_width=settings.AI_FRAME_WIDTH,
            frame_height=settings.AI_FRAME_HEIGHT,
        )
        set_guard_mission_service(_guard_mission_service)
        logger.info(
            f"驱离任务服务已初始化，默认启用={settings.GUARD_MISSION_ENABLED}"
        )


        logger.info("所有后台任务已启动，应用就绪")

        yield

    finally:
        # Shutdown
        logger.info("BotDog backend shutting down (lifespan)...")
        stop_event.set()
        set_state_machine(None)
        clear_ws_runtime()
        _state_machine = None

        if _ros_nav_bridge is not None:
            _ros_nav_bridge.stop()
            from .nav_bridge_state import set_ros_nav_bridge as _set_nav_bridge
            _set_nav_bridge(None)
            _ros_nav_bridge = None

        # 取消所有任务
        for task in tasks:
            task.cancel()

        # 等待所有任务完成
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                logger.warning(f"任务关闭时出现异常: {result}")

        logger.info("所有后台任务已停止")


def create_app() -> FastAPI:
    """
    创建 FastAPI 应用实例。

    约定：
    - 此函数为应用装配的唯一入口，便于测试与 CLI 复用。
    - 不在全局模块级别做 I/O 操作，避免导入副作用。
    """

    app = FastAPI(
        title="BotDog Backend",
        version="0.3.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    cors_allow_origins = settings.CORS_ALLOW_ORIGINS
    cors_allow_credentials = settings.CORS_ALLOW_CREDENTIALS
    if cors_allow_credentials and "*" in cors_allow_origins:
        raise ValueError(
            "Invalid CORS settings: CORS_ALLOW_CREDENTIALS=true cannot be used with '*' in CORS_ALLOW_ORIGINS"
        )

    # CORS（开发阶段放宽；生产环境建议收紧到前端域名）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_allow_origins,
        allow_credentials=cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.mount(
        "/api/v1/static",
        StaticFiles(directory=str(Path(settings.SNAPSHOT_DIR)), check_dir=False),
        name="static",
    )

    register_routes(app)

    # ── SPA 前端托管（生产模式）──────────────────────────────────────────────
    # 将 npm run build 产物挂载到根路径，实现地面端单端口访问（:8000 同时提供页面和 API）
    _frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if _frontend_dist.is_dir():
        from fastapi.responses import FileResponse as _FileResponse

        # 挂载静态资源（js/css/images 等）
        _assets_dir = _frontend_dist / "assets"
        if _assets_dir.is_dir():
            app.mount(
                "/assets",
                StaticFiles(directory=str(_assets_dir)),
                name="frontend_assets",
            )

        # SPA fallback：所有非 /api、/ws 的路径都返回 index.html
        # 注意：必须在 register_routes() 之后注册，避免覆盖 API 路由
        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
            # 根目录直接返回 index.html
            if not full_path:
                return _FileResponse(str(_frontend_dist / "index.html"))
            # 尝试精确匹配文件（favicon.ico 等根目录静态文件）
            _file = _frontend_dist / full_path
            if _file.is_file():
                return _FileResponse(str(_file))
            # SPA fallback：React Router 路由
            return _FileResponse(str(_frontend_dist / "index.html"))

        logger.info(f"前端 SPA 已挂载: {_frontend_dist}")
    else:
        logger.warning(
            f"未找到前端构建产物: {_frontend_dist}，仅提供 API 服务。"
            "运行 cd frontend && npm run build 后重启后端即可启用。"
        )

    return app


def register_routes(app: FastAPI) -> None:
    """
    路由注册函数。

    注意：
    - 只组织路由，不引入具体业务实现，以降低 main.py 与领域逻辑的耦合度。
    - 负责集中注册已拆分的 router 模块。
    """

    # ── 导航巡逻 / PCD 点云地图 ─────────────────────────────────────────────
    from .api.routes import nav as _nav_routes
    from .api.routes import audio as _audio_routes
    from .api.routes import config as _config_routes
    from .api.routes import control as _control_routes
    from .api.routes import control_debug as _control_debug_routes
    from .api.routes import evidence as _evidence_routes
    from .api.routes import focus_zones as _focus_zone_routes
    from .api.routes import guard_mission as _guard_mission_routes
    from .api.routes import logs as _logs_routes
    from .api.routes import network_interfaces as _network_interface_routes
    from .api.routes import session as _session_routes
    from .api.routes import system as _system_routes
    from .api.routes import system_info as _system_info_routes
    from .api.routes import test_alert as _test_alert_routes
    from .api.routes import auto_track as _auto_track_routes
    from .api.routes import video_sources as _video_source_routes
    from .api.routes import websocket as _websocket_routes
    app.include_router(_nav_routes.router)
    app.include_router(_system_routes.router)
    app.include_router(_control_debug_routes.router)
    app.include_router(_control_routes.router)
    app.include_router(_audio_routes.router)
    app.include_router(_auto_track_routes.router)
    app.include_router(_config_routes.router)
    app.include_router(_evidence_routes.router)
    app.include_router(_focus_zone_routes.router)
    app.include_router(_guard_mission_routes.router)
    app.include_router(_video_source_routes.router)
    app.include_router(_network_interface_routes.router)
    app.include_router(_session_routes.router)
    app.include_router(_system_info_routes.router)
    app.include_router(_test_alert_routes.router)
    app.include_router(_logs_routes.router)
    app.include_router(_websocket_routes.router)



app = create_app()
