"""
WebSocket 遥测广播 Worker。

职责边界：
- 从遥测队列获取最新快照
- 按照 TELEMETRY_UPDATE 协议封装为 JSON
- 广播给所有连接的 WebSocket 客户端
- 管理序列号（seq）
- 处理客户端连接/断开事件
"""

import asyncio
import time
from typing import Any, Dict, Set

from fastapi import WebSocket, WebSocketDisconnect

from backend.logging_config import logger
from backend.mavlink_dto import TelemetrySnapshotDTO
from backend.state_machine import SystemState
from backend.telemetry_queue import TelemetryQueueManager


class WebSocketBroadcaster:
    """
    WebSocket 遥测广播器。

    功能：
    - 维护 WebSocket 客户端连接池
    - 持续从队列获取遥测快照
    - 将快照广播给所有客户端
    - 管理序列号和时间戳
    """

    def __init__(self, queue_manager: TelemetryQueueManager, broadcast_interval: float = 0.067):
        """
        初始化广播器。

        Args:
            queue_manager: 遥测队列管理器
            broadcast_interval: 广播间隔（秒），默认 0.067s（约 15Hz）
        """
        self.queue_manager = queue_manager
        self.broadcast_interval = broadcast_interval
        self._sequence_number = 0
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """启动广播器。"""
        logger.info(f"WebSocket 广播器已启动，广播间隔: {self.broadcast_interval}s")

        while not self._stop_event.is_set():
            try:
                # 获取最新快照
                snapshot = await self._get_snapshot_with_timeout(timeout=0.1)

                if snapshot:
                    # 广播快照
                    await self._broadcast_snapshot(snapshot)

                # 等待广播间隔
                await asyncio.sleep(self.broadcast_interval)

            except asyncio.CancelledError:
                logger.info("WebSocket 广播器已停止")
                break
            except Exception as exc:  # noqa: BLE001
                logger.exception(f"WebSocket 广播器异常: {exc}")
                await asyncio.sleep(0.5)

    async def stop(self) -> None:
        """停止广播器。"""
        self._stop_event.set()

    async def _get_snapshot_with_timeout(self, timeout: float) -> TelemetrySnapshotDTO:
        """
        从队列获取快照（带超时）。

        Args:
            timeout: 超时时间（秒）

        Returns:
            遥测快照，或空快照（超时）
        """
        try:
            return await asyncio.wait_for(
                self.queue_manager.get_next_broadcast_snapshot(), timeout=timeout
            )
        except asyncio.TimeoutError:
            # 超时返回空快照，避免阻塞
            return TelemetrySnapshotDTO()

    async def _broadcast_snapshot(self, snapshot: TelemetrySnapshotDTO) -> None:
        """
        广播遥测快照给所有客户端。

        Args:
            snapshot: 遥测快照数据
        """
        clients = self.queue_manager.get_ws_clients()

        if not clients:
            return

        # 封装消息
        message = self._serialize_snapshot(snapshot)

        # 广播给所有客户端
        disconnected_clients = set()

        for client in clients:
            try:
                await client.send_json(message)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"向客户端发送消息失败: {exc}")
                disconnected_clients.add(client)

        # 清理断开的客户端
        for client in disconnected_clients:
            self.queue_manager.remove_ws_client(client)

    def _serialize_snapshot(self, snapshot: TelemetrySnapshotDTO) -> Dict[str, Any]:
        """
        将遥测快照序列化为 WebSocket 消息。

        Args:
            snapshot: 遥测快照数据

        Returns:
            WebSocket JSON 消息
        """
        self._sequence_number += 1

        message = {
            "timestamp": time.time(),
            "msg_type": "TELEMETRY_UPDATE",
            "seq": self._sequence_number,
            "source": "BACKEND_HUB",
            "payload": {},
        }

        # 添加姿态数据
        if snapshot.attitude:
            message["payload"]["attitude"] = {
                "pitch": round(snapshot.attitude.pitch, 2),
                "roll": round(snapshot.attitude.roll, 2),
                "yaw": round(snapshot.attitude.yaw, 2),
            }

        # 添加位置数据
        if snapshot.position:
            message["payload"]["position"] = {
                "lat": round(snapshot.position.lat, 7),
                "lon": round(snapshot.position.lon, 7),
                "alt": round(snapshot.position.alt, 1),
                "hdg": round(snapshot.position.hdg, 1),
            }

        # 添加电池数据
        if snapshot.battery:
            message["payload"]["battery"] = {
                "voltage": round(snapshot.battery.voltage, 1),
                "remaining_pct": snapshot.battery.remaining_pct,
            }

        # 添加系统状态
        if snapshot.system_status:
            message["payload"]["system"] = {
                "armed": snapshot.system_status.armed,
                "mode": snapshot.system_status.mode,
                "connected": snapshot.system_status.mavlink_connected,
            }

        return message


async def websocket_telemetry_handler(
    websocket: WebSocket,
    queue_manager: TelemetryQueueManager,
    state_machine,
) -> None:
    """
    WebSocket 遥测端点处理器。

    Args:
        websocket: WebSocket 连接对象
        queue_manager: 遥测队列管理器
        state_machine: 系统状态机
    """
    await websocket.accept()
    logger.info("客户端已连接到 /ws/telemetry")

    # 添加到连接池
    queue_manager.add_ws_client(websocket)

    try:
        while True:
            # 保持连接活跃，接收客户端消息（如 ping）
            _ = await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info("客户端已断开 /ws/telemetry")
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"WebSocket 遥测异常: {exc}")
    finally:
        # 从连接池移除
        queue_manager.remove_ws_client(websocket)
