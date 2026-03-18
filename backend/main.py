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
    EStopResetResponse,
    EStopResponse,
    EvidenceBulkDeleteRequest,
    EvidenceDeleteResponse,
    EvidenceListResponse,
    LogsPage,
    SessionStartRequest,
    SessionStartResponse,
    SessionStopRequest,
    SessionStopResponse,
    SystemHealthResponse,
    utc_now_iso,
)
from .services_evidence import list_evidence, delete_evidence_by_ids
from .services_logs import list_logs, write_log
from .services_tasks import create_task, stop_task
from .alert_service import AlertService
from .mavlink_gateway import MAVLinkGateway
from .mavlink_dto import SystemStatusDTO
from .state_machine import StateMachine, SystemState
from .telemetry_queue import TelemetryQueueManager, set_telemetry_queue_manager
from .workers_telemetry import TelemetryPersistenceWorker
from .ws_broadcaster import websocket_telemetry_handler, WebSocketBroadcaster
from .ws_event_broadcaster import EventBroadcaster


APP_START_MONO = time.monotonic()

# 全局组件（在 lifespan 中初始化）
_state_machine: StateMachine | None = None
_queue_manager: TelemetryQueueManager | None = None
_mavlink_gateway: MAVLinkGateway | None = None
_ws_broadcaster: WebSocketBroadcaster | None = None
_persistence_worker: TelemetryPersistenceWorker | None = None
_event_broadcaster: EventBroadcaster | None = None
_ai_worker: Any | None = None


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

    # Startup
    setup_logging()
    logger.info("BotDog backend starting up (lifespan)...")
    await init_db()
    logger.info("Database initialized.")

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

        # 3. 初始化 MAVLink 网关
        global _mavlink_gateway
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

        # 8. 初始化告警服务并注入 broadcaster
        alert_service_instance = AlertService(event_broadcaster=_event_broadcaster)
        set_alert_service(alert_service_instance)
        logger.info(f"告警服务已初始化，broadcaster ID: {id(_event_broadcaster)}")

        logger.info("所有后台任务已启动，应用就绪")

        yield

    finally:
        # Shutdown
        logger.info("BotDog backend shutting down (lifespan)...")
        stop_event.set()

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

    return app


def register_routes(app: FastAPI) -> None:
    """
    路由注册函数。

    注意：
    - 只组织路由，不引入具体业务实现，以降低 main.py 与领域逻辑的耦合度。
    - 后续可拆分为多个 router 模块（system / telemetry / session 等）在此集中挂载。
    """

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


app = create_app()
