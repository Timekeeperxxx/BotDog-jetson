"""WebSocket 路由。"""

from fastapi import APIRouter, WebSocket

from ...ws_broadcaster import websocket_telemetry_handler
from ...ws_runtime_state import (
    get_event_broadcaster,
    get_queue_manager,
    get_state_machine,
)

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/telemetry")
async def telemetry_ws(websocket: WebSocket) -> None:
    """
    遥测 WebSocket 端点（阶段 1 增强）。

    功能：
    - 接受客户端连接
    - 通过 WebSocketBroadcaster 广播遥测数据
    - 管理客户端连接池
    - 结构严格遵守 `06_backend_protocol_schema.md`
    """
    queue_manager = get_queue_manager()
    if queue_manager is None:
        await websocket.close(code=1011, reason="遥测队列管理器未初始化")
        return

    state_machine = get_state_machine()
    if state_machine is None:
        await websocket.close(code=1011, reason="状态机未初始化")
        return

    await websocket_telemetry_handler(websocket, queue_manager, state_machine)


@router.websocket("/ws/event")
async def event_ws(websocket: WebSocket) -> None:
    """
    事件 WebSocket 端点（阶段 4）。

    功能：
    - 接受客户端连接
    - 广播告警事件
    - 推送实时通知
    """
    event_broadcaster = get_event_broadcaster()
    if event_broadcaster is None:
        await websocket.close(code=1011, reason="事件广播服务未初始化")
        return

    await event_broadcaster.handle_connection(websocket)
