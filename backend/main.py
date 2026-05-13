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

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import get_session_factory
from .logging_config import get_access_logger, get_logger, setup_logging
from .state_machine_state import set_state_machine
from .control_service import ControlService
from .mavlink_gateway import MAVLinkGateway

from .state_machine import StateMachine
from .telemetry_queue import TelemetryQueueManager, set_telemetry_queue_manager
from .workers_telemetry import TelemetryPersistenceWorker
from .ws_broadcaster import WebSocketBroadcaster
from .ws_event_broadcaster import EventBroadcaster
from .app_bootstrap import prepare_bootstrap_state
from .app_runtime import initialize_runtime_services
from .app_shutdown import shutdown_runtime_services
from .startup_summary import StartupSummary, coerce_startup_summary

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

startup_logger = get_logger("启动环境")
app_logger = get_logger("应用服务")
config_logger = get_logger("核心配置")
db_logger = get_logger("数据库")
cleanup_logger = get_logger("启动清理")
control_logger = get_logger("机器人控制")
telemetry_logger = get_logger("机器人遥测")
ai_logger = get_logger("AI识别")
ros_logger = get_logger("ROS导航")
zone_logger = get_logger("重点区服务")
auto_track_logger = get_logger("自动跟踪")
guard_logger = get_logger("驱离任务")
summary_logger = get_logger("启动摘要")
access_logger = get_access_logger()

IMPORTANT_ACCESS_PREFIXES = (
    "/api/v1/control",
    "/api/v1/nav",
    "/api/v1/guard-mission",
    "/api/v1/session",
    "/api/v1/config",
    "/api/v1/audio/play",
    "/api/v1/audio/stop",
    "/api/v1/auto-track",
)


def _format_status_text(status: str) -> str:
    mapping = {
        "ready": "正常",
        "normal": "正常",
        "degraded": "降级",
        "failed": "失败",
        "waiting": "等待中",
        "disabled": "已禁用",
    }
    return mapping.get(status, status)


def _format_http_error_code(status_code: int) -> str:
    if status_code == 400:
        return "bad_request"
    if status_code == 401:
        return "unauthorized"
    if status_code == 403:
        return "forbidden"
    if status_code == 404:
        return "not_found"
    if status_code == 409:
        return "conflict"
    if status_code == 422:
        return "validation_error"
    if status_code == 503:
        return "service_unavailable"
    return "http_error"


def _log_startup_summary(summary: StartupSummary) -> None:
    summary_logger.info("=" * 80)
    summary_logger.info("BotDog 后端启动完成：{}", summary.overall_status())
    summary_logger.info("=" * 80)
    for item in summary.items():
        summary_logger.info("{:<12} {}，{}", f"{item.name}：", _format_status_text(item.status), item.detail)
    summary_logger.info("=" * 80)


def _write_startup_summary_snapshot(summary: StartupSummary | dict[str, tuple[str, str]], snapshot_dir: Path) -> tuple[str, str]:
    return coerce_startup_summary(summary).write_snapshot(snapshot_dir)


def _render_http_exception(exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    message = detail if isinstance(detail, str) else str(detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": detail,
            "message": message,
            "status_code": exc.status_code,
            "error": _format_http_error_code(exc.status_code),
        },
    )


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
    app_logger.info("开始初始化 FastAPI 生命周期")
    startup_summary, snapshot_dir = await prepare_bootstrap_state()

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
        get_logger("状态机").info("状态机已初始化：heartbeat_timeout={}s", settings.HEARTBEAT_TIMEOUT)

        # 2. 初始化遥测队列管理器
        global _queue_manager
        _queue_manager = TelemetryQueueManager(
            sampling_interval=1.0 / settings.TELEMETRY_SAMPLING_HZ,
        )
        # 注册为全局单例，供 Worker 无法注入时通过 get_telemetry_queue_manager() 获取
        set_telemetry_queue_manager(_queue_manager)
        tasks.append(asyncio.create_task(_queue_manager.start_sampling_task(stop_event)))
        telemetry_logger.info(
            "遥测队列管理器已初始化：sampling_hz={}，broadcast_hz={}",
            settings.TELEMETRY_SAMPLING_HZ,
            settings.TELEMETRY_BROADCAST_HZ,
        )
        startup_summary.set(
            "遥测服务",
            "ready",
            f"DDS/数据源已启动，WebSocket 广播频率={settings.TELEMETRY_BROADCAST_HZ}Hz",
        )

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
            telemetry_logger.info(
                "Unitree 遥测 Worker 启动请求已提交：网卡={}",
                settings.UNITREE_NETWORK_IFACE,
            )
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
            telemetry_logger.info("MAVLink 网关启动请求已提交：数据源={}", settings.MAVLINK_SOURCE)

        # 4. 初始化 WebSocket 广播器
        global _ws_broadcaster
        _ws_broadcaster = WebSocketBroadcaster(
            queue_manager=_queue_manager,
            broadcast_interval=1.0 / settings.TELEMETRY_BROADCAST_HZ,
        )
        tasks.append(asyncio.create_task(_ws_broadcaster.start()))
        get_logger("WebSocket遥测").info("遥测广播服务启动请求已提交")

        # 5. 初始化遥测落盘 Worker
        if settings.MAVLINK_SOURCE != "simulation" or settings.SIMULATION_WORKER_ENABLED:
            session_factory = get_session_factory()
            global _persistence_worker
            _persistence_worker = TelemetryPersistenceWorker(
                session_factory=session_factory,
                sampling_interval=1.0 / settings.TELEMETRY_SAMPLING_HZ,
            )
            tasks.append(asyncio.create_task(_persistence_worker.start(stop_event)))
            telemetry_logger.info("遥测落盘 Worker 启动请求已提交")
        else:
            telemetry_logger.info("遥测落盘 Worker 已跳过：simulation 且 SIMULATION_WORKER_ENABLED=false")

        # 6. 可选：启动模拟数据 Worker（开发/测试）
        if settings.SIMULATION_WORKER_ENABLED:
            from .workers_simulation import simulation_worker

            tasks.append(asyncio.create_task(simulation_worker(stop_event)))
            telemetry_logger.info("模拟数据 Worker 启动请求已提交")

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
            ai_status = _ai_worker.get_startup_status()
            startup_summary.set(
                "AI识别",
                ai_status["status"],
                ai_status["detail"],
            )
        else:
            startup_summary.set("AI识别", "disabled", "AI_ENABLED=false")
            ai_logger.info("AI 识别已禁用：AI_ENABLED=false")

        await initialize_runtime_services(
            queue_manager=_queue_manager,
            state_machine=_state_machine,
            session_factory=get_session_factory(),
            snapshot_dir=snapshot_dir,
            stop_event=stop_event,
            startup_summary=startup_summary,
            mavlink_gateway=_mavlink_gateway,
            tasks=tasks,
        )

        startup_summary.set(
            "API 服务",
            "ready",
            f"地址=http://{settings.BACKEND_HOST}:{settings.BACKEND_PORT}",
        )
        startup_summary.set(
            "接口文档",
            "ready",
            f"地址=http://{settings.BACKEND_HOST}:{settings.BACKEND_PORT}/api/docs",
        )
        frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
        if frontend_dist.is_dir():
            startup_summary.set("前端页面", "ready", f"目录={frontend_dist}")
        else:
            startup_summary.set("前端页面", "degraded", f"未找到构建产物：目录={frontend_dist}")

        startup_generated_at, startup_snapshot_file = _write_startup_summary_snapshot(startup_summary, snapshot_dir)
        app.state.startup_summary = startup_summary
        app.state.startup_summary_generated_at = startup_generated_at
        app.state.startup_summary_snapshot_file = startup_snapshot_file
        _log_startup_summary(startup_summary)

        yield

    finally:
        # Shutdown
        app_logger.info("开始关闭 FastAPI 生命周期")
        stop_event.set()
        _state_machine = None
        await shutdown_runtime_services(
            tasks=tasks,
            ros_nav_bridge=_ros_nav_bridge,
        )
        _ros_nav_bridge = None


def create_app() -> FastAPI:
    """
    创建 FastAPI 应用实例。

    约定：
    - 此函数为应用装配的唯一入口，便于测试与 CLI 复用。
    - 不在全局模块级别做 I/O 操作，避免导入副作用。
    """

    setup_logging()

    app = FastAPI(
        title="BotDog Backend",
        version="0.3.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_: Request, exc: HTTPException):
        return _render_http_exception(exc)

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

    @app.middleware("http")
    async def access_log_middleware(request: Request, call_next):
        client_host = request.client.host if request.client else "-"
        method = request.method.upper()
        path = request.url.path

        try:
            response = await call_next(request)
        except Exception:
            access_logger.warning(
                "接口处理异常：{} {}，来源={}，状态码=500",
                method,
                path,
                client_host,
            )
            raise

        status_code = response.status_code
        if status_code >= 400:
            access_logger.warning(
                "接口返回异常：{} {}，来源={}，状态码={}",
                method,
                path,
                client_host,
                status_code,
            )
        elif method != "GET" and path.startswith(IMPORTANT_ACCESS_PREFIXES):
            access_logger.info(
                "收到接口请求：{} {}，来源={}，状态码={}",
                method,
                path,
                client_host,
                status_code,
            )

        return response

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

        app_logger.info("前端 SPA 已挂载：目录={}", _frontend_dist)
    else:
        app_logger.warning(
            "未找到前端构建产物：目录={}，当前仅提供 API 服务",
            _frontend_dist,
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
    from .api.routes import auth as _auth_routes
    from .api.routes import audio as _audio_routes
    from .api.routes import config as _config_routes
    from .api.routes import control as _control_routes
    from .api.routes import control_debug as _control_debug_routes
    from .api.routes import evidence as _evidence_routes
    from .api.routes import focus_zones as _focus_zone_routes
    from .api.routes import guard_mission as _guard_mission_routes
    from .api.routes import log_files as _log_files_routes
    from .api.routes import logs as _logs_routes
    from .api.routes import network_interfaces as _network_interface_routes
    from .api.routes import session as _session_routes
    from .api.routes import system as _system_routes
    from .api.routes import system_info as _system_info_routes
    from .api.routes import test_alert as _test_alert_routes
    from .api.routes import auto_track as _auto_track_routes
    from .api.routes import video_sources as _video_source_routes
    from .api.routes import websocket as _websocket_routes
    from .api.routes import users as _users_routes
    app.include_router(_auth_routes.router)
    app.include_router(_users_routes.router)
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
    app.include_router(_log_files_routes.router)
    app.include_router(_logs_routes.router)
    app.include_router(_websocket_routes.router)



app = create_app()
