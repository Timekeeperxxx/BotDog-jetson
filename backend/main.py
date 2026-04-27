"""
应用层入口。

职责边界：
- 只负责 FastAPI 应用的装配：中间件、生命周期钩子、路由注册；
- 不直接承载业务逻辑，业务逻辑拆分到 service / gateway / repository 等模块。
"""

import asyncio
import contextlib
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, AsyncIterator, Optional

from fastapi import Depends, FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import get_db, init_db, get_session_factory
from .logging_config import logger, setup_logging
from .schemas import (
    ControlAckDTO,
    DeleteWaypointResponse,
    EStopResetResponse,
    EStopResponse,
    EvidenceBulkDeleteRequest,
    EvidenceDeleteResponse,
    EvidenceListResponse,
    LogsPage,
    NavWaypointCreateRequest,
    NavWaypointDTO,
    NavWaypointListResponse,
    NavStateResponse,
    PcdMapListResponse,
    PcdMetadataResponse,
    PcdPreviewResponse,
    SessionStartRequest,
    SessionStartResponse,
    SessionStopRequest,
    SessionStopResponse,
    SystemHealthResponse,
    utc_now_iso,
)
from .services_evidence import list_evidence, delete_evidence_by_ids
from .services_logs import list_logs, write_log
from .services_tasks import create_task, stop_task, cleanup_stale_tasks
from .alert_service import AlertService
from .mavlink_gateway import MAVLinkGateway

from .state_machine import StateMachine, SystemState
from .telemetry_queue import TelemetryQueueManager, set_telemetry_queue_manager
from .workers_telemetry import TelemetryPersistenceWorker
from .ws_broadcaster import websocket_telemetry_handler, WebSocketBroadcaster
from .ws_event_broadcaster import EventBroadcaster
from .control_service import ControlService, set_control_service, get_control_service
from .robot_adapter import create_adapter
from .guard_mission_types import GuardStatusDTO



APP_START_MONO = time.monotonic()

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


def _get_state_machine() -> StateMachine | None:
    """
    获取状态机实例。

    Returns:
        状态机实例，如果未初始化则返回 None
    """
    global _state_machine
    return _state_machine


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
        db_configs = await config_service.get_all_configs(_session)
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
        logger.info("事件广播器已初始化")

        # 8.1 初始化 ROS2 导航状态订阅转发（可选）
        if settings.ROS_NAV_ENABLED:
            from .services_ros_nav import RosNavBridge

            _ros_nav_bridge = RosNavBridge(
                broadcaster=_event_broadcaster,
                loop=asyncio.get_running_loop(),
            )
            _ros_nav_bridge.start()
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
            # UnitreeB2Adapter.__init__ 含同步阻塞 SDK 调用（约 20s），
            # 用 SimulatedRobotAdapter 占位先启动服务，后台完成后热替换。
            from .robot_adapter import SimulatedRobotAdapter
            _placeholder_adapter = SimulatedRobotAdapter()
            _control_service = ControlService(
                adapter=_placeholder_adapter,
                state_machine=_state_machine,
                watchdog_timeout_ms=settings.CONTROL_WATCHDOG_TIMEOUT_MS,
                cmd_rate_limit_ms=settings.CONTROL_CMD_RATE_LIMIT_MS,
            )
            set_control_service(_control_service)
            tasks.append(asyncio.create_task(_control_service.run_watchdog(stop_event)))
            logger.info(
                f"控制服务已启动（临时模拟模式），B2 适配器后台初始化中..."
            )

            async def _init_b2_adapter_background() -> None:
                """后台初始化 B2 适配器，完成后热替换到 ControlService。"""
                try:
                    real_adapter = create_adapter("unitree_b2", **_adapter_kwargs)
                    
                    _control_service._adapter = real_adapter
                    logger.info("[B2Init] UnitreeB2Adapter 初始化完成，已热替换控制适配器")
                except Exception as exc:
                    logger.error(f"[B2Init] UnitreeB2Adapter 初始化失败，保持模拟模式: {exc}")

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

        if _ros_nav_bridge is not None:
            _ros_nav_bridge.stop()
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
    - 后续可拆分为多个 router 模块（system / telemetry / session 等）在此集中挂载。
    """

    # ── 导航巡逻 / PCD 点云地图 Demo ─────────────────────────────────────

    @app.get("/api/v1/nav/pcd-maps", response_model=PcdMapListResponse)
    async def nav_list_pcd_maps():
        from .services_pcd_maps import PcdMapError, list_pcd_maps

        try:
            return list_pcd_maps()
        except PcdMapError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/api/v1/nav/state", response_model=NavStateResponse)
    async def nav_get_state():
        from .services_nav_state import get_nav_state

        return get_nav_state()

    @app.get("/api/v1/nav/pcd-maps/{map_id}/metadata", response_model=PcdMetadataResponse)
    async def nav_get_pcd_metadata(map_id: str):
        from .services_pcd_maps import PcdMapError, get_pcd_metadata

        try:
            return get_pcd_metadata(map_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"PCD 文件不存在: {map_id}")
        except PcdMapError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/api/v1/nav/pcd-maps/{map_id}/preview", response_model=PcdPreviewResponse)
    async def nav_get_pcd_preview(map_id: str, max_points: int | None = None):
        from .services_pcd_maps import PcdMapError, get_pcd_preview

        try:
            return get_pcd_preview(map_id, max_points=max_points)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"PCD 文件不存在: {map_id}")
        except PcdMapError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/api/v1/nav/pcd-maps/{map_id}/waypoints", response_model=NavWaypointListResponse)
    async def nav_list_waypoints(map_id: str):
        from .services_pcd_maps import PcdMapError
        from .services_nav_waypoints import list_waypoints

        try:
            return list_waypoints(map_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"PCD 文件不存在: {map_id}")
        except PcdMapError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/api/v1/nav/pcd-maps/{map_id}/waypoints", response_model=NavWaypointDTO)
    async def nav_create_waypoint(map_id: str, body: NavWaypointCreateRequest):
        from .services_nav_waypoints import create_waypoint
        from .services_pcd_maps import PcdMapError

        try:
            return create_waypoint(map_id, body.model_dump())
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"PCD 文件不存在: {map_id}")
        except (PcdMapError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.delete(
        "/api/v1/nav/pcd-maps/{map_id}/waypoints/{waypoint_id}",
        response_model=DeleteWaypointResponse,
    )
    async def nav_delete_waypoint(map_id: str, waypoint_id: str):
        from .services_nav_waypoints import delete_waypoint
        from .services_pcd_maps import PcdMapError

        try:
            ok = delete_waypoint(map_id, waypoint_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"PCD 文件不存在: {map_id}")
        except PcdMapError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        if not ok:
            raise HTTPException(status_code=404, detail=f"导航点不存在: {waypoint_id}")

        return {"success": True}

    @app.get("/api/v1/system/health", response_model=SystemHealthResponse)
    async def system_health() -> SystemHealthResponse:
        """
        返回系统健康状态。

        阶段 1 更新：
        - status 根据 state_machine 状态映射（healthy/degraded/offline）
        - mavlink_connected 从 state_machine 读取（如果已初始化）
        - uptime 为进程启动以来的秒数
        """

        state_machine = _get_state_machine()
        uptime = time.monotonic() - APP_START_MONO

        # 状态映射（如果状态机未初始化，默认为 offline）
        if state_machine is None:
            status = "offline"
            mavlink_connected = False
        else:
            state = state_machine.state
            if state == SystemState.DISCONNECTED:
                status = "degraded" if uptime > 10 else "offline"
            elif state == SystemState.E_STOP_TRIGGERED:
                status = "degraded"
            else:
                status = "healthy"
            mavlink_connected = state_machine.is_connected

        return SystemHealthResponse(
            status=status,
            mavlink_connected=mavlink_connected,
            uptime=round(uptime, 3),
        )

    # ── 控制诊断端点 ──────────────────────────────────────────────────────────

    @app.get("/api/v1/control/debug")
    async def control_debug() -> dict:
        """诊断端点：返回当前控制服务和适配器的详细状态。"""
        svc = get_control_service()
        if svc is None:
            return {"error": "控制服务未初始化"}
        adapter = svc._adapter
        adapter_info = {
            "type": type(adapter).__name__,
            "module": type(adapter).__module__,
        }
        # 如果是 UnitreeB2Adapter，附加更多信息
        if hasattr(adapter, '_initialized'):
            adapter_info["initialized"] = adapter._initialized
        if hasattr(adapter, '_sport_client'):
            adapter_info["sport_client_exists"] = adapter._sport_client is not None
        if hasattr(adapter, '_worker_thread'):
            adapter_info["worker_thread_alive"] = adapter._worker_thread.is_alive()
        if hasattr(adapter, '_cmd_queue'):
            adapter_info["cmd_queue_size"] = adapter._cmd_queue.qsize()
        return {
            "adapter": adapter_info,
            "watchdog_timeout_s": svc._watchdog_timeout_s,
            "rate_limit_s": svc._rate_limit_s,
            "watchdog_active": svc._watchdog_active,
        }

    # ── 驱离任务端点 ────────────────────────────────────────────────────────
    
    @app.post("/api/v1/guard-mission/enable")
    async def enable_guard_mission():
        from .guard_mission_service import get_guard_mission_service
        from .auto_track_service import get_auto_track_service
        from .control_arbiter import get_control_arbiter
        
        gm = get_guard_mission_service()
        if gm is None:
            raise HTTPException(status_code=503, detail="驱离服务未初始化")
            
        # 释放可能存在的人工干预锁，防止自动驱离被永远拦截
        arbiter = get_control_arbiter()
        if arbiter:
            arbiter.release_manual_override()
            
        # 互斥：开启驱离时，必须关闭自动跟踪
        at = get_auto_track_service()
        if at is not None and at._enabled:
            at.disable()
            logger.info("[GuardMission] 互斥切换：已自动关闭自动跟踪")
        gm.enabled = True
        return {"success": True, "enabled": True}

    @app.post("/api/v1/guard-mission/disable")
    async def disable_guard_mission():
        from .guard_mission_service import get_guard_mission_service
        gm = get_guard_mission_service()
        if gm is None:
            raise HTTPException(status_code=503, detail="驱离服务未初始化")
        gm.enabled = False
        return {"success": True, "enabled": False}

    @app.post("/api/v1/guard-mission/abort")
    async def abort_guard_mission():
        from .guard_mission_service import get_guard_mission_service
        gm = get_guard_mission_service()
        if gm is None:
            raise HTTPException(status_code=503, detail="驱离服务未初始化")
        
        if gm.state.value not in ("STANDBY", "MANUAL_OVERRIDE"):
            gm._abort_mission("API 手动终止")
            from .guard_mission_types import GuardMissionState
            gm._state = GuardMissionState.STANDBY
        return {"success": True}

    @app.get("/api/v1/guard-mission/status", response_model=GuardStatusDTO)
    async def get_guard_status():
        from .guard_mission_service import get_guard_mission_service
        gm = get_guard_mission_service()
        if gm is None:
            raise HTTPException(status_code=503, detail="驱离服务未初始化")
        return gm.get_status()

    # ── 音频控制接口 ────────────────────────────────────────────────────────

    @app.post("/api/v1/audio/play")
    async def audio_play():
        """手动触发驱离音频循环播放。"""
        from .guard_mission_service import get_guard_mission_service
        gm = get_guard_mission_service()
        if gm is None:
            raise HTTPException(status_code=503, detail="驱离服务未初始化")
        await gm.start_audio()
        return {"success": True, "playing": True}

    @app.post("/api/v1/audio/stop")
    async def audio_stop():
        """手动停止驱离音频。"""
        from .guard_mission_service import get_guard_mission_service
        gm = get_guard_mission_service()
        if gm is None:
            raise HTTPException(status_code=503, detail="驱离服务未初始化")
        await gm.stop_audio()
        return {"success": True, "playing": False}

    @app.get("/api/v1/audio/status")
    async def audio_status():
        """查询驱离音频是否正在播放。"""
        from .guard_mission_service import get_guard_mission_service
        gm = get_guard_mission_service()
        playing = gm.is_audio_playing if gm is not None else False
        return {"playing": playing}

    # ── 控制命令接口 ────────────────────────────────────────────────────────

    from pydantic import BaseModel as _PydanticBase

    class ControlCommandRequest(_PydanticBase):
        """控制命令请求体。"""
        cmd: str

    @app.post("/api/v1/control/command", response_model=ControlAckDTO)
    async def control_command(body: ControlCommandRequest) -> ControlAckDTO:
        """
        发送控制命令到机器狗。

        支持的命令：forward / backward / left / right / sit / stand / stop

        - 按下时前端每 500ms 发一次，松手时立即发 stop
        - 非 stop 命令：自动向 ControlArbiter 申请 WEB_MANUAL 控制权（压制自动跟踪）
        - stop 命令：自动释放 WEB_MANUAL 覆盖权（允许自动跟踪恢复）
        - E_STOP 状态下所有命令被拒绝（返回 REJECTED_E_STOP）
        - Watchdog 超时后自动执行 stop
        """
        svc = get_control_service()
        if svc is None:
            raise HTTPException(status_code=503, detail="控制服务未就绪")

        # ── 仲裁器集成 ──────────────────────────────────────────────────────
        from .control_arbiter import get_control_arbiter
        from .tracking_types import ControlOwner
        arbiter = get_control_arbiter()
        if arbiter is not None:
            if body.cmd != "stop":
                # 按下任意运动/姿态命令 → 申请 WEB_MANUAL 控制权（压制 AUTO_TRACK）
                arbiter.request_control(ControlOwner.WEB_MANUAL)

        return await svc.handle_command(body.cmd)

    @app.post("/api/v1/control/stop", response_model=ControlAckDTO)
    async def control_stop() -> ControlAckDTO:
        """快捷停止接口（等同于发送 cmd='stop'），供前端紧急停止使用。"""
        svc = get_control_service()
        if svc is None:
            raise HTTPException(status_code=503, detail="控制服务未就绪")

        # 不需要在这里释放人工覆盖权，前端已经有专门的 api (`/api/v1/auto-track/release-override`)
        # 控制权应保持，直到用户明确在面板中点击“恢复自动跟踪”
        # from .control_arbiter import get_control_arbiter
        # arbiter = get_control_arbiter()
        # if arbiter is not None:
        #     arbiter.release_manual_override()

        return await svc.handle_command("stop")

    @app.post("/api/v1/session/start", response_model=SessionStartResponse)
    async def session_start(
        body: SessionStartRequest,
        db=Depends(get_db),
    ) -> SessionStartResponse:
        """
        启动新巡检任务（Session）。

        当前阶段：
        - 不做用户鉴权与并发 Session 限制；
        - 每次调用都会新建一条任务记录。
        """

        task = await create_task(db, task_name=body.task_name)
        await write_log(
            db,
            level="INFO",
            module="BACKEND",
            message=f"Session started: {task.task_name} (id={task.task_id})",
            task_id=task.task_id,
        )

        # 更新状态机的任务状态
        state_machine = _get_state_machine()
        state_machine.update_mission_status(True)

        return SessionStartResponse(
            task_id=task.task_id,
            task_name=task.task_name,
            status=task.status,
            started_at=task.started_at,
            ended_at=task.ended_at,
        )

    @app.post("/api/v1/session/stop", response_model=SessionStopResponse)
    async def session_stop(
        body: SessionStopRequest,
        db=Depends(get_db),
    ) -> SessionStopResponse:
        """
        停止指定任务。
        """

        task = await stop_task(db, task_id=body.task_id)
        if task is None:
            raise HTTPException(
                status_code=404,
                detail=f"task_id={body.task_id} not found",
            )

        await write_log(
            db,
            level="INFO",
            module="BACKEND",
            message=f"Session stopped: {task.task_name} (id={task.task_id})",
            task_id=task.task_id,
        )

        # 更新状态机的任务状态
        state_machine = _get_state_machine()
        state_machine.update_mission_status(False)

        return SessionStopResponse(
            task_id=task.task_id,
            task_name=task.task_name,
            status=task.status,
            started_at=task.started_at,
            ended_at=task.ended_at,
        )

    @app.get("/api/v1/logs", response_model=LogsPage)
    async def get_logs(db=Depends(get_db)) -> LogsPage:
        """
        简单日志查询：返回最近 N 条日志（默认 50 条）。
        """

        rows = await list_logs(db, limit=50)
        return LogsPage(
            items=[
                {
                    "log_id": row.log_id,
                    "level": row.level,
                    "module": row.module,
                    "message": row.message,
                    "task_id": row.task_id,
                    "created_at": row.created_at,
                }
                for row in rows
            ]
        )

    @app.get("/api/v1/evidence", response_model=EvidenceListResponse)
    async def get_evidence(
        task_id: int | None = None,
        db=Depends(get_db),
    ) -> EvidenceListResponse:
        """
        查询异常证据链列表。

        - 若提供 `task_id`，则仅返回对应任务的证据记录；
        - 默认按照 `created_at` 倒序，最多返回 100 条。
        """

        rows = await list_evidence(db, task_id=task_id, limit=100)
        return EvidenceListResponse(
            items=[
                {
                    "evidence_id": row.evidence_id,
                    "task_id": row.task_id,
                    "event_type": row.event_type,
                    "event_code": row.event_code,
                    "severity": row.severity,
                    "message": row.message,
                    "confidence": row.confidence,
                    "file_path": row.file_path,
                    "image_url": row.image_url,
                    "gps_lat": row.gps_lat,
                    "gps_lon": row.gps_lon,
                    "created_at": row.created_at,
                }
                for row in rows
            ]
        )

    @app.delete("/api/v1/evidence/{evidence_id}", response_model=EvidenceDeleteResponse)
    async def delete_evidence(
        evidence_id: int,
        db=Depends(get_db),
    ) -> EvidenceDeleteResponse:
        result = await delete_evidence_by_ids(db, evidence_ids=[evidence_id])
        return EvidenceDeleteResponse(success=True, **result)

    @app.post("/api/v1/evidence/bulk-delete", response_model=EvidenceDeleteResponse)
    async def bulk_delete_evidence(
        request: EvidenceBulkDeleteRequest,
        db=Depends(get_db),
    ) -> EvidenceDeleteResponse:
        result = await delete_evidence_by_ids(db, evidence_ids=request.evidence_ids)
        return EvidenceDeleteResponse(success=True, **result)

    @app.websocket("/ws/telemetry")
    async def telemetry_ws(websocket: WebSocket) -> None:
        """
        遥测 WebSocket 端点（阶段 1 增强）。

        功能：
        - 接受客户端连接
        - 通过 WebSocketBroadcaster 广播遥测数据
        - 管理客户端连接池
        - 结构严格遵守 `06_backend_protocol_schema.md`
        """

        state_machine = _get_state_machine()
        await websocket_telemetry_handler(websocket, _queue_manager, state_machine)

    @app.websocket("/ws/event")
    async def event_ws(websocket: WebSocket) -> None:
        """
        事件 WebSocket 端点（阶段 4）。

        功能：
        - 接受客户端连接
        - 广播告警事件
        - 推送实时通知
        """

        if _event_broadcaster is None:
            await websocket.close(code=1011, reason="事件广播服务未初始化")
            return

        # 使用 main.py 中的实例
        await _event_broadcaster.handle_connection(websocket)

    @app.post("/api/v1/control/e-stop", response_model=EStopResponse)
    async def emergency_stop(
        db=Depends(get_db),
    ) -> EStopResponse:
        """
        触发紧急制动。

        功能：
        - 更新系统状态为 E_STOP_TRIGGERED
        - 记录日志
        - 触发事件广播
        """

        state_machine = _get_state_machine()
        if state_machine is None:
            raise HTTPException(
                status_code=503,
                detail="状态机未初始化",
            )

        # 触发急停
        state_machine.trigger_emergency_stop()

        # 记录日志
        await write_log(
            db,
            level="WARN",
            module="BACKEND",
            message="Emergency stop triggered via API",
            task_id=None,
        )

        # TODO: 广播 E_STOP_TRIGGERED 事件到 /ws/event

        return EStopResponse(
            success=True,
            timestamp=utc_now_iso(),
            message="紧急制动已触发",
        )

    @app.post("/api/v1/control/e-stop/reset", response_model=EStopResetResponse)
    async def emergency_stop_reset(
        db=Depends(get_db),
    ) -> EStopResetResponse:
        """
        重置紧急制动状态。

        功能：
        - 将系统状态从 E_STOP_TRIGGERED 恢复到正常状态
        - 记录日志
        - 允许恢复控制指令
        """

        state_machine = _get_state_machine()
        if state_machine is None:
            raise HTTPException(
                status_code=503,
                detail="状态机未初始化",
            )

        # 重置急停
        old_state = state_machine.state
        state_machine.reset_emergency_stop()

        # 记录日志
        await write_log(
            db,
            level="INFO",
            module="BACKEND",
            message=f"Emergency stop reset: {old_state} -> {state_machine.state}",
            task_id=None,
        )

        return EStopResetResponse(
            success=True,
            timestamp=utc_now_iso(),
            message="紧急制动已重置，控制已恢复",
            state_after=state_machine.state,
        )

    @app.post("/api/v1/test/alert")
    async def trigger_test_alert(
        db=Depends(get_db),
    ):
        """
        测试端点：触发一个温度告警。

        用于验证事件 WebSocket 广播功能。
        """
        from .alert_service import get_alert_service
        from .temperature_monitor import TemperatureAlert
        import asyncio

        logger.info("测试端点：触发温度告警")

        alert_service = get_alert_service()

        test_alert = TemperatureAlert(
            temperature=99.0,
            threshold=60.0,
            timestamp=asyncio.get_event_loop().time(),
        )

        evidence = await alert_service.handle_temperature_alert(
            alert=test_alert,
            position={"lat": 39.9087, "lon": 116.3975},
            task_id=None,
            session=db,
        )

        return {
            "success": True,
            "message": "测试告警已触发",
            "evidence": {
                "event_type": evidence.event_type,
                "event_code": evidence.event_code,
                "message": evidence.message,
            }
        }

    @app.get("/api/v1/config")
    async def get_system_config(
        category: Optional[str] = None,
        db=Depends(get_db),
    ):
        """
        获取系统配置。

        查询参数:
            category: 配置类别过滤 (backend/frontend/storage)

        Returns:
            配置字典
        """
        from .services_config import get_config_service

        config_service = get_config_service()
        all_configs = await config_service.get_all_configs(db)

        # 按类别过滤
        if category:
            all_configs = {
                k: v for k, v in all_configs.items()
                if v.get("category") == category
            }

        return {
            "configs": all_configs,
            "total": len(all_configs),
        }

    @app.post("/api/v1/config")
    async def update_system_config(
        request: dict,
        db=Depends(get_db),
    ):
        """
        更新系统配置。

        请求体:
            key: 配置键
            value: 新值
            changed_by: 修改者（可选，默认 admin）
            reason: 修改原因（可选）

        Returns:
            更新后的配置
        """
        from .services_config import get_config_service

        config_service = get_config_service()

        key = request.get('key')
        value = request.get('value')
        changed_by = request.get('changed_by', 'admin')
        reason = request.get('reason', '')

        if not key or value is None:
            raise HTTPException(
                status_code=400,
                detail="缺少必要参数: key, value"
            )

        try:
            config = await config_service.update_config(
                session=db,
                key=key,
                value=value,
                changed_by=changed_by,
                reason=reason,
            )

            # 热更新自动跟踪参数
            if key.startswith("auto_track_"):
                from .auto_track_service import get_auto_track_service
                _at = get_auto_track_service()
                if _at:
                    _at.update_params(key, value)

            return {
                "success": True,
                "message": f"配置 {key} 已更新",
                "config": config.to_dict(),
            }

        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=str(e),
            )

    @app.get("/api/v1/config/history")
    async def get_config_history(
        key: Optional[str] = None,
        limit: int = 50,
        db=Depends(get_db),
    ):
        """
        获取配置变更历史。

        查询参数:
            key: 配置键过滤
            limit: 最大返回数量

        Returns:
            变更历史列表
        """
        from .services_config import get_config_service

        config_service = get_config_service()
        history = await config_service.get_config_history(
            session=db,
            key=key,
            limit=limit,
        )

        return {
            "history": history,
            "total": len(history),
        }

    # ── 重点区 CRUD API ────────────────────────────────────────────────────────

    from pydantic import BaseModel as _PydanticBaseModel2
    from datetime import datetime

    class FocusZoneRequest(_PydanticBaseModel2):
        zone_name: str = "default"
        enabled: bool = True
        polygon_json: str  # [[x,y],...] JSON 串

    class FocusZoneResponse(_PydanticBaseModel2):
        zone_id: int
        zone_name: str
        enabled: bool
        polygon_json: str
        created_at: str
        updated_at: str

    @app.get("/api/v1/focus-zones", response_model=list[FocusZoneResponse])
    async def list_focus_zones(db=Depends(get_db)) -> list[FocusZoneResponse]:
        """查询所有重点区配置。"""
        from sqlalchemy import select
        from .models import FocusZone
        result = await db.execute(select(FocusZone))
        zones = result.scalars().all()
        return [
            FocusZoneResponse(
                zone_id=z.zone_id,
                zone_name=z.zone_name,
                enabled=bool(z.enabled),
                polygon_json=z.polygon_json,
                created_at=z.created_at,
                updated_at=z.updated_at,
            )
            for z in zones
        ]

    @app.post("/api/v1/focus-zones", response_model=FocusZoneResponse, status_code=201)
    async def create_focus_zone(
        body: FocusZoneRequest,
        db=Depends(get_db),
    ) -> FocusZoneResponse:
        """新增重点区。polygon_json 坐标为图像像素坐标。"""
        import json
        from .models import FocusZone
        # 验证 JSON 格式
        try:
            pts = json.loads(body.polygon_json)
            if len(pts) < 3:
                raise ValueError("polygon 至少需要 3 个顶点")
        except (json.JSONDecodeError, ValueError) as e:
            raise HTTPException(status_code=422, detail=f"polygon_json 格式错误: {e}")

        ts = utc_now_iso()
        zone = FocusZone(
            zone_name=body.zone_name,
            enabled=1 if body.enabled else 0,
            polygon_json=body.polygon_json,
            created_at=ts,
            updated_at=ts,
        )
        db.add(zone)
        await db.commit()
        await db.refresh(zone)

        # 重新加载区域到内存
        from .zone_service import get_zone_service
        zs = get_zone_service()
        if zs:
            await zs.load_from_db(db)

        return FocusZoneResponse(
            zone_id=zone.zone_id,
            zone_name=zone.zone_name,
            enabled=bool(zone.enabled),
            polygon_json=zone.polygon_json,
            created_at=zone.created_at,
            updated_at=zone.updated_at,
        )

    @app.put("/api/v1/focus-zones/{zone_id}", response_model=FocusZoneResponse)
    async def update_focus_zone(
        zone_id: int,
        body: FocusZoneRequest,
        db=Depends(get_db),
    ) -> FocusZoneResponse:
        """更新重点区配置。"""
        import json
        from .models import FocusZone
        from sqlalchemy import select
        result = await db.execute(select(FocusZone).where(FocusZone.zone_id == zone_id))
        zone = result.scalar_one_or_none()
        if zone is None:
            raise HTTPException(status_code=404, detail=f"zone_id={zone_id} 不存在")

        try:
            pts = json.loads(body.polygon_json)
            if len(pts) < 3:
                raise ValueError("polygon 至少需要 3 个顶点")
        except (json.JSONDecodeError, ValueError) as e:
            raise HTTPException(status_code=422, detail=f"polygon_json 格式错误: {e}")

        zone.zone_name = body.zone_name
        zone.enabled = 1 if body.enabled else 0
        zone.polygon_json = body.polygon_json
        zone.updated_at = utc_now_iso()
        await db.commit()
        await db.refresh(zone)

        # 重新加载区域到内存
        from .zone_service import get_zone_service
        zs = get_zone_service()
        if zs:
            await zs.load_from_db(db)

        return FocusZoneResponse(
            zone_id=zone.zone_id,
            zone_name=zone.zone_name,
            enabled=bool(zone.enabled),
            polygon_json=zone.polygon_json,
            created_at=zone.created_at,
            updated_at=zone.updated_at,
        )

    @app.delete("/api/v1/focus-zones/{zone_id}")
    async def delete_focus_zone(
        zone_id: int,
        db=Depends(get_db),
    ) -> dict:
        """删除重点区。"""
        from .models import FocusZone
        from sqlalchemy import select
        result = await db.execute(select(FocusZone).where(FocusZone.zone_id == zone_id))
        zone = result.scalar_one_or_none()
        if zone is None:
            raise HTTPException(status_code=404, detail=f"zone_id={zone_id} 不存在")
        await db.delete(zone)
        await db.commit()

        # 重新加载区域到内存
        from .zone_service import get_zone_service
        zs = get_zone_service()
        if zs:
            await zs.load_from_db(db)

        return {"success": True, "deleted_zone_id": zone_id}

    # ── 自动跟踪 API ────────────────────────────────────────────────────────────

    @app.get("/api/v1/auto-track/debug")
    async def auto_track_debug() -> dict:
        """调试端点：返回当前自动跟踪状态快照。"""
        from .auto_track_service import get_auto_track_service
        svc = get_auto_track_service()
        if svc is None:
            raise HTTPException(status_code=503, detail="自动跟踪服务未初始化")
        return svc.get_status()

    @app.post("/api/v1/auto-track/enable")
    async def auto_track_enable() -> dict:
        """运行时启用自动跟踪。"""
        from .auto_track_service import get_auto_track_service
        from .guard_mission_service import get_guard_mission_service
        svc = get_auto_track_service()
        if svc is None:
            raise HTTPException(status_code=503, detail="自动跟踪服务未初始化")
        # 互斥：开启自动跟踪时，必须关闭驱离
        gm = get_guard_mission_service()
        if gm is not None and gm.enabled:
            gm.enabled = False
            logger.info("[AutoTrack] 互斥切换：已自动关闭自动驱离")
        svc.enable()
        return {"success": True, "state": svc.get_status()["state"]}

    @app.post("/api/v1/auto-track/disable")
    async def auto_track_disable() -> dict:
        """运行时禁用自动跟踪，立即停止并发出 stop 命令。"""
        from .auto_track_service import get_auto_track_service
        svc = get_auto_track_service()
        if svc is None:
            raise HTTPException(status_code=503, detail="自动跟踪服务未初始化")
        svc.disable()
        return {"success": True, "state": svc.get_status()["state"]}

    @app.post("/api/v1/auto-track/pause")
    async def auto_track_pause() -> dict:
        """暂停自动跟踪（保留目标状态，停发控制命令）。"""
        from .auto_track_service import get_auto_track_service
        svc = get_auto_track_service()
        if svc is None:
            raise HTTPException(status_code=503, detail="自动跟踪服务未初始化")
        svc.pause()
        return {"success": True, "state": svc.get_status()["state"]}

    @app.post("/api/v1/auto-track/resume")
    async def auto_track_resume() -> dict:
        """恢复自动跟踪。"""
        from .auto_track_service import get_auto_track_service
        svc = get_auto_track_service()
        if svc is None:
            raise HTTPException(status_code=503, detail="自动跟踪服务未初始化")
        svc.resume()
        return {"success": True, "state": svc.get_status()["state"]}

    @app.post("/api/v1/auto-track/manual-override")
    async def auto_track_manual_override() -> dict:
        """人工接管控制权（自动命令将被拦截）。"""
        from .control_arbiter import get_control_arbiter
        from .tracking_types import ControlOwner
        arbiter = get_control_arbiter()
        if arbiter is None:
            raise HTTPException(status_code=503, detail="仲裁器未初始化")
        arbiter.request_control(ControlOwner.WEB_MANUAL)
        return {"success": True, "arbiter": arbiter.get_status()}

    @app.post("/api/v1/auto-track/release-override")
    async def auto_track_release_override() -> dict:
        """释放人工覆盖，允许自动跟踪恢复发命令。"""
        from .control_arbiter import get_control_arbiter
        arbiter = get_control_arbiter()
        if arbiter is None:
            raise HTTPException(status_code=503, detail="仲裁器未初始化")
        arbiter.release_manual_override()
        return {"success": True, "arbiter": arbiter.get_status()}

    @app.get("/api/v1/auto-track/arbiter")
    async def auto_track_arbiter_status() -> dict:
        """查询当前控制权仲裁状态。"""
        from .control_arbiter import get_control_arbiter
        arbiter = get_control_arbiter()
        if arbiter is None:
            raise HTTPException(status_code=503, detail="仲裁器未初始化")
        return arbiter.get_status()

    @app.post("/api/v1/auto-track/mark-known/{track_id}")
    async def auto_track_mark_known(track_id: int) -> dict:
        """将指定 track_id 标记为已知人员（不再跟踪）。"""
        from .stranger_policy import get_stranger_policy
        from .auto_track_service import get_auto_track_service
        policy = get_stranger_policy()
        if policy is None:
            raise HTTPException(status_code=503, detail="陌生人策略未初始化")
        policy.mark_known(track_id, reason="operator")
        svc = get_auto_track_service()
        if svc and svc._target_manager:
            svc._target_manager.mark_known(track_id)
        return {
            "success": True,
            "track_id": track_id,
            "known_count": policy.known_count,
        }

    @app.post("/api/v1/auto-track/unmark-known/{track_id}")
    async def auto_track_unmark_known(track_id: int) -> dict:
        """取消 track_id 的已知标记（误操作恢复）。"""
        from .stranger_policy import get_stranger_policy
        policy = get_stranger_policy()
        if policy is None:
            raise HTTPException(status_code=503, detail="陌生人策略未初始化")
        policy.unmark_known(track_id)
        return {
            "success": True,
            "track_id": track_id,
            "known_count": policy.known_count,
        }

    @app.get("/api/v1/auto-track/known-list")
    async def auto_track_known_list() -> dict:
        """查询当前会话已知人员列表。"""
        from .stranger_policy import get_stranger_policy
        policy = get_stranger_policy()
        if policy is None:
            raise HTTPException(status_code=503, detail="陌生人策略未初始化")
        return {
            "known_ids": policy.get_known_ids(),
            "total": policy.known_count,
        }

    # ── 视频源管理 API ─────────────────────────────────────────────────────────

    from pydantic import BaseModel as _PydanticBaseVS

    class VideoSourceRequest(_PydanticBaseVS):
        """视频源请求体。"""
        name: str
        label: str
        source_type: str = "whep"
        whep_url: Optional[str] = None
        rtsp_url: Optional[str] = None
        enabled: bool = True
        is_primary: bool = False
        is_ai_source: bool = False
        sort_order: int = 0

    class VideoSourceResponse(_PydanticBaseVS):
        """视频源响应体。"""
        source_id: int
        name: str
        label: str
        source_type: str
        whep_url: Optional[str] = None
        rtsp_url: Optional[str] = None
        enabled: bool
        is_primary: bool
        is_ai_source: bool
        sort_order: int
        created_at: str
        updated_at: str

    @app.get("/api/v1/video-sources")
    async def list_video_sources(db=Depends(get_db)) -> dict:
        """获取所有视频源列表。"""
        from .services_video_sources import get_video_source_service
        svc = get_video_source_service()
        sources = await svc.list_all(db)
        return {"sources": sources, "total": len(sources)}

    @app.get("/api/v1/video-sources/active")
    async def list_active_video_sources(db=Depends(get_db)) -> dict:
        """获取所有已启用的视频源（供前端视频播放器消费）。"""
        from .services_video_sources import get_video_source_service
        svc = get_video_source_service()
        sources = await svc.list_active(db)
        return {"sources": sources, "total": len(sources)}

    @app.post("/api/v1/video-sources", status_code=201)
    async def create_video_source(
        body: VideoSourceRequest,
        db=Depends(get_db),
    ) -> dict:
        """新增视频源。"""
        from .services_video_sources import get_video_source_service
        svc = get_video_source_service()
        try:
            source = await svc.create(db, body.model_dump())
            return {"success": True, "source": source}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.put("/api/v1/video-sources/{source_id}")
    async def update_video_source(
        source_id: int,
        body: VideoSourceRequest,
        db=Depends(get_db),
    ) -> dict:
        """更新视频源。"""
        from .services_video_sources import get_video_source_service
        svc = get_video_source_service()
        result = await svc.update(db, source_id, body.model_dump())
        if result is None:
            raise HTTPException(status_code=404, detail=f"视频源 id={source_id} 不存在")
        return {"success": True, "source": result}

    @app.delete("/api/v1/video-sources/{source_id}")
    async def delete_video_source(
        source_id: int,
        db=Depends(get_db),
    ) -> dict:
        """删除视频源。"""
        from .services_video_sources import get_video_source_service
        svc = get_video_source_service()
        deleted = await svc.delete(db, source_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"视频源 id={source_id} 不存在")
        return {"success": True, "deleted_source_id": source_id}

    # ── 网口管理 API ───────────────────────────────────────────────────────────

    class NetworkInterfaceRequest(_PydanticBaseVS):
        """网口配置请求体。"""
        name: str
        label: str
        iface_name: str
        ip_address: Optional[str] = None
        purpose: str = "other"
        enabled: bool = True

    class NetworkInterfaceResponse(_PydanticBaseVS):
        """网口配置响应体。"""
        iface_id: int
        name: str
        label: str
        iface_name: str
        ip_address: Optional[str] = None
        purpose: str
        enabled: bool
        created_at: str
        updated_at: str

    @app.get("/api/v1/network-interfaces")
    async def list_network_interfaces(db=Depends(get_db)) -> dict:
        """获取所有网口配置。"""
        from .services_video_sources import get_network_interface_service
        svc = get_network_interface_service()
        ifaces = await svc.list_all(db)
        return {"interfaces": ifaces, "total": len(ifaces)}

    @app.post("/api/v1/network-interfaces", status_code=201)
    async def create_network_interface(
        body: NetworkInterfaceRequest,
        db=Depends(get_db),
    ) -> dict:
        """新增网口配置。"""
        from .services_video_sources import get_network_interface_service
        svc = get_network_interface_service()
        try:
            iface = await svc.create(db, body.model_dump())
            return {"success": True, "interface": iface}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.put("/api/v1/network-interfaces/{iface_id}")
    async def update_network_interface(
        iface_id: int,
        body: NetworkInterfaceRequest,
        db=Depends(get_db),
    ) -> dict:
        """更新网口配置。"""
        from .services_video_sources import get_network_interface_service
        svc = get_network_interface_service()
        result = await svc.update(db, iface_id, body.model_dump())
        if result is None:
            raise HTTPException(status_code=404, detail=f"网口 id={iface_id} 不存在")
        return {"success": True, "interface": result}

    @app.delete("/api/v1/network-interfaces/{iface_id}")
    async def delete_network_interface(
        iface_id: int,
        db=Depends(get_db),
    ) -> dict:
        """删除网口配置。"""
        from .services_video_sources import get_network_interface_service
        svc = get_network_interface_service()
        deleted = await svc.delete(db, iface_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"网口 id={iface_id} 不存在")
        return {"success": True, "deleted_iface_id": iface_id}

    # ── 系统硬件信息（只读）──────────────────────────────────────────────────────

    @app.get("/api/v1/system-info")
    async def get_system_info() -> dict:
        """
        返回系统关键硬件参数（只读，来源于 .env 静态配置）。

        这些参数通常由硬件拓扑决定，不支持运行时修改。
        前端用于在「后台管理 > 系统信息」中只读展示，方便现场排查。
        """
        from urllib.parse import urlparse

        # 从 AI_RTSP_URL 提取媒体服务主机
        mediamtx_host = "127.0.0.1"
        try:
            parsed = urlparse(settings.AI_RTSP_URL)
            if parsed.hostname:
                mediamtx_host = parsed.hostname
        except Exception:
            pass

        return {
            "groups": [
                {
                    "group": "机器人连接",
                    "icon": "robot",
                    "items": [
                        {
                            "key": "unitree_network_iface",
                            "label": "宇树 B2 网卡名",
                            "value": settings.UNITREE_NETWORK_IFACE,
                            "note": "OrangePi 上连接机器狗的物理网卡，用 `ip addr` 查看",
                            "env_key": "UNITREE_NETWORK_IFACE",
                        },
                        {
                            "key": "unitree_b2_ip",
                            "label": "宇树 B2 默认 IP",
                            "value": "192.168.123.161",
                            "note": "B2 机器人的固定出厂 IP，不可更改",
                            "env_key": "—",
                        },
                        {
                            "key": "control_adapter",
                            "label": "控制适配器类型",
                            "value": settings.CONTROL_ADAPTER_TYPE,
                            "note": "unitree_b2=真实硬件，simulation=仅打印日志",
                            "env_key": "CONTROL_ADAPTER_TYPE",
                        },
                    ],
                },
                {
                    "group": "视频 / 图传",
                    "icon": "video",
                    "items": [
                        {
                            "key": "ai_rtsp_url",
                            "label": "AI 推理 RTSP 地址",
                            "value": settings.AI_RTSP_URL,
                            "note": "AI Worker 从此地址拉取视频帧进行推理",
                            "env_key": "AI_RTSP_URL",
                        },
                        {
                            "key": "mediamtx_rtsp_port",
                            "label": "MediaMTX RTSP 端口",
                            "value": f"{mediamtx_host}:8554",
                            "note": "摄像头推流到此地址（如 ffmpeg/OBS 的推流目标）",
                            "env_key": "—",
                        },
                        {
                            "key": "mediamtx_whep_port",
                            "label": "MediaMTX WHEP 端口",
                            "value": f"{mediamtx_host}:8889",
                            "note": "前端 WebRTC 播放地址的主机和端口",
                            "env_key": "—",
                        },
                        {
                            "key": "hm30_sky_ip",
                            "label": "HM30 天空端 IP",
                            "value": "192.168.0.2",
                            "note": "HM30 图传天空端的默认管理地址（连接后可访问 Web 配置页）",
                            "env_key": "—",
                        },
                        {
                            "key": "hm30_ground_ip",
                            "label": "HM30 地面端 IP",
                            "value": "192.168.0.3",
                            "note": "HM30 图传地面端的默认管理地址",
                            "env_key": "—",
                        },
                    ],
                },
                {
                    "group": "后端服务",
                    "icon": "server",
                    "items": [
                        {
                            "key": "backend_host",
                            "label": "后端监听地址",
                            "value": f"{settings.BACKEND_HOST}:{settings.BACKEND_PORT}",
                            "note": "前端通过此地址访问 API 和 WebSocket",
                            "env_key": "BACKEND_HOST / BACKEND_PORT",
                        },
                        {
                            "key": "mavlink_endpoint",
                            "label": "MAVLink 端点",
                            "value": settings.MAVLINK_ENDPOINT,
                            "note": "MAVLink 数据来源（udp=模拟/真实飞控）",
                            "env_key": "MAVLINK_ENDPOINT",
                        },
                        {
                            "key": "mavlink_source",
                            "label": "MAVLink 数据源",
                            "value": settings.MAVLINK_SOURCE,
                            "note": "mavlink=真实硬件，simulation=内置模拟器",
                            "env_key": "MAVLINK_SOURCE",
                        },
                    ],
                },
            ]
        }



app = create_app()
