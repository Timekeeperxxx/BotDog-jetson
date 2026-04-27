"""
事件 WebSocket 广播器。

职责边界：
- 管理 /ws/event WebSocket 连接
- 广告告警事件到前端
- 管理连接池
"""

import asyncio
import json
from typing import Dict, Set, Any, Optional
from datetime import datetime

from fastapi import WebSocket, WebSocketDisconnect

from .logging_config import logger
from .schemas import utc_now_iso


class EventBroadcaster:
    """
    事件广播器。

    功能：
    - 管理 WebSocket 连接
    - 广播事件消息
    - 管理连接生命周期
    """

    def __init__(self):
        """初始化事件广播器。"""
        self._connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        """
        接受新的 WebSocket 连接。

        Args:
            websocket: WebSocket 连接
        """
        await websocket.accept()

        async with self._lock:
            self._connections.add(websocket)

        logger.info(f"事件 WebSocket 已连接，当前连接数: {len(self._connections)}")

        # 发送欢迎消息
        try:
            await websocket.send_json({
                "msg_type": "welcome",
                "timestamp": utc_now_iso(),
                "message": "事件流已连接",
            })
        except Exception as exc:
            logger.info(f"事件 WebSocket 欢迎消息发送失败: {exc}")

    async def disconnect(self, websocket: WebSocket) -> None:
        """
        断开 WebSocket 连接。

        Args:
            websocket: WebSocket 连接
        """
        async with self._lock:
            self._connections.discard(websocket)

        logger.info(f"事件 WebSocket 已断开，当前连接数: {len(self._connections)}")

    async def broadcast_alert(
        self,
        event_type: str,
        event_code: str,
        severity: str,
        message: str,
        evidence_id: Optional[int] = None,
        image_url: Optional[str] = None,
        gps_lat: Optional[float] = None,
        gps_lon: Optional[float] = None,
        confidence: Optional[float] = None,
        **kwargs: Any,
    ) -> int:
        """
        广播告警事件。

        Args:
            event_type: 事件类型
            event_code: 事件代码
            severity: 严重程度
            message: 消息
            evidence_id: 证据 ID
            image_url: 图片 URL
            gps_lat: GPS 纬度
            gps_lon: GPS 经度
            confidence: 置信度
            **kwargs: 其他参数

        Returns:
            成功发送的连接数
        """
        if not self._connections:
            logger.debug("没有活跃的 WebSocket 连接，跳过广播")
            return 0

        # 构建消息
        alert_message = {
            "msg_type": "ALERT_RAISED",
            "timestamp": utc_now_iso(),
            "payload": {
                "event_type": event_type,
                "event_code": event_code,
                "severity": severity,
                "message": message,
                "evidence_id": evidence_id,
                "image_url": image_url,
                "gps": {
                    "lat": gps_lat,
                    "lon": gps_lon,
                } if gps_lat is not None and gps_lon is not None else None,
                "confidence": confidence,
                **kwargs,
            },
        }

        # 广播到所有连接
        success_count = 0
        failed_connections = []

        async with self._lock:
            for connection in self._connections:
                try:
                    await connection.send_json(alert_message)
                    success_count += 1
                except Exception as e:
                    logger.warning(f"发送告警消息失败: {e}")
                    failed_connections.append(connection)

            # 移除失败的连接
            for failed_conn in failed_connections:
                self._connections.discard(failed_conn)

        logger.info(
            f"告警已广播: {event_code} - {message} "
            f"(成功: {success_count}/{len(self._connections)})"
        )

        return success_count

    async def broadcast_event(self, event_type: str, data: dict[str, Any]) -> int:
        """
        广播标准业务事件。

        nav.* 事件使用 {type, data} 结构，避免把 ROS2 原始消息暴露给前端。
        """
        if not self._connections:
            logger.debug("没有活跃的 WebSocket 连接，跳过事件广播: {}", event_type)
            return 0

        message = {
            "type": event_type,
            "data": data,
            "timestamp": utc_now_iso(),
        }

        success_count = 0
        failed_connections = []

        async with self._lock:
            for connection in self._connections:
                try:
                    await connection.send_json(message)
                    success_count += 1
                except Exception as exc:
                    logger.warning(f"发送事件消息失败: {event_type}, {exc}")
                    failed_connections.append(connection)

            for failed_conn in failed_connections:
                self._connections.discard(failed_conn)

        return success_count

    async def handle_connection(self, websocket: WebSocket) -> None:
        """
        处理 WebSocket 连接的生命周期。

        Args:
            websocket: WebSocket 连接
        """
        await self.connect(websocket)

        try:
            while True:
                # 保持连接活跃，接收客户端消息（如 ping）
                try:
                    data = await websocket.receive_json()

                    # 处理心跳
                    if data.get("msg_type") == "ping":
                        await websocket.send_json({
                            "msg_type": "pong",
                            "timestamp": utc_now_iso(),
                        })

                except WebSocketDisconnect:
                    logger.info("客户端主动断开连接")
                    break

                except Exception:
                    # 客户端不主动发送消息时，保持连接
                    await asyncio.sleep(1.0)

        finally:
            await self.disconnect(websocket)

    @property
    def connection_count(self) -> int:
        """获取当前连接数。"""
        return len(self._connections)


# 全局事件广播器实例
_event_broadcaster: Optional[EventBroadcaster] = None


def get_event_broadcaster() -> EventBroadcaster:
    """
    获取事件广播器实例。

    Returns:
        事件广播器实例
    """
    from .global_event_broadcaster import get_global_event_broadcaster
    return get_global_event_broadcaster()


def set_event_broadcaster(broadcaster: EventBroadcaster) -> None:
    """
    设置事件广播器实例。

    Args:
        broadcaster: 事件广播器实例
    """
    from .global_event_broadcaster import set_global_event_broadcaster
    set_global_event_broadcaster(broadcaster)
