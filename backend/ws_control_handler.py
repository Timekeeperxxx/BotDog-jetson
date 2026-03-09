"""
控制 WebSocket 处理模块。

职责边界：
- 处理 /ws/control 连接
- 接收前端 MANUAL_CONTROL 消息
- 实现速率限流
- 状态检查（E_STOP_TRIGGERED 时拒绝）
- 转换为 MAVLink MANUAL_CONTROL 报文
- 回发 CONTROL_ACK
"""

import asyncio
import time
from collections import deque
from typing import Any, Dict

from fastapi import WebSocket, WebSocketDisconnect

from backend.config import settings
from backend.logging_config import logger
from backend.schemas import ControlAckDTO, ManualControlDTO
from backend.state_machine import StateMachine


class ControlRateLimiter:
    """
    控制指令速率限制器。

    使用令牌桶算法实现速率限制。
    """

    def __init__(self, rate_limit_hz: float):
        """
        初始化速率限制器。

        Args:
            rate_limit_hz: 速率限制（Hz）
        """
        self.rate_limit_hz = rate_limit_hz
        self.min_interval = 1.0 / rate_limit_hz if rate_limit_hz > 0 else 0
        self.last_send_time = 0.0
        self.last_reject_time = 0.0

    def can_send(self) -> bool:
        """
        判断是否可以发送控制指令。

        Returns:
            True=可以发送，False=被限流
        """
        current_time = time.time()
        if current_time - self.last_send_time >= self.min_interval:
            return True
        return False

    def record_send(self) -> None:
        """记录发送时间。"""
        self.last_send_time = time.time()

    def record_reject(self) -> None:
        """记录拒绝时间。"""
        self.last_reject_time = time.time()


class ControlWebSocketHandler:
    """
    控制 WebSocket 处理器。

    功能：
    - 管理 /ws/control 连接
    - 处理 MANUAL_CONTROL 消息
    - 实现速率限流和状态检查
    - 发送 CONTROL_ACK 确认
    """

    def __init__(self, state_machine: StateMachine):
        """
        初始化控制 WebSocket 处理器。

        Args:
            state_machine: 系统状态机
        """
        self.state_machine = state_machine
        self.rate_limiter = ControlRateLimiter(
            rate_limit_hz=settings.CONTROL_RATE_LIMIT_HZ
        )

    async def handle_connection(self, websocket: WebSocket) -> None:
        """
        处理 WebSocket 连接。

        Args:
            websocket: WebSocket 连接对象
        """
        await websocket.accept()
        logger.info("客户端已连接到 /ws/control")

        try:
            while True:
                # 接收客户端消息
                data = await websocket.receive_json()
                await self._process_control_message(websocket, data)

        except WebSocketDisconnect:
            logger.info("客户端已断开 /ws/control")
        except Exception as exc:  # noqa: BLE001
            logger.exception(f"控制 WebSocket 异常: {exc}")
        finally:
            try:
                await websocket.close()
            except Exception:
                pass

    async def _process_control_message(
        self, websocket: WebSocket, data: Dict[str, Any]
    ) -> None:
        """
        处理控制消息。

        Args:
            websocket: WebSocket 连接对象
            data: 消息数据
        """
        start_time = time.time()

        try:
            # 解析控制消息
            control_dto = ManualControlDTO(**data)

            # 应用死区
            x = self._apply_deadzone(control_dto.x)
            y = self._apply_deadzone(control_dto.y)
            z = self._apply_deadzone(control_dto.z)
            r = self._apply_deadzone(control_dto.r)

            # 检查状态机是否接受控制
            if not self.state_machine.can_accept_control:
                result = "REJECTED_E_STOP"
                logger.warning(f"控制指令被拒绝：系统状态为 {self.state_machine.state}")

                # 发送 ACK
                await self._send_ack(
                    websocket,
                    "MANUAL_CONTROL",
                    result,
                    start_time,
                )
                return

            # 检查速率限制
            if not self.rate_limiter.can_send():
                self.rate_limiter.record_reject()
                result = "RATE_LIMITED"
                logger.debug("控制指令被限流")

                # 发送 ACK
                await self._send_ack(
                    websocket,
                    "MANUAL_CONTROL",
                    result,
                    start_time,
                )
                return

            # 接受控制指令
            self.rate_limiter.record_send()
            result = "ACCEPTED"

            # TODO: 转换为 MAVLink MANUAL_CONTROL 报文并发送
            # 这里需要集成到 MAVLink 网关的发送队列
            logger.debug(
                f"控制指令: x={x}, y={y}, z={z}, r={r}"
            )

            # 发送 ACK
            await self._send_ack(
                websocket,
                "MANUAL_CONTROL",
                result,
                start_time,
            )

        except Exception as exc:  # noqa: BLE001
            logger.exception(f"处理控制消息失败: {exc}")

            # 发送错误 ACK
            await self._send_ack(
                websocket,
                "MANUAL_CONTROL",
                "REJECTED_INVALID",
                start_time,
            )

    def _apply_deadzone(self, value: int) -> int:
        """
        应用死区处理。

        Args:
            value: 原始值

        Returns:
            处理后的值（在死区内返回 0）
        """
        if abs(value) < settings.CONTROL_DEADZONE:
            return 0
        return value

    async def _send_ack(
        self,
        websocket: WebSocket,
        cmd: str,
        result: str,
        start_time: float,
    ) -> None:
        """
        发送控制确认消息。

        Args:
            websocket: WebSocket 连接对象
            cmd: 指令类型
            result: 处理结果
            start_time: 开始处理时间
        """
        latency_ms = (time.time() - start_time) * 1000

        ack = ControlAckDTO(
            ack_cmd=cmd,
            result=result,
            latency_ms=round(latency_ms, 2),
        )

        try:
            await websocket.send_json({
                "timestamp": time.time(),
                "msg_type": "CONTROL_ACK",
                "payload": ack.dict(),
            })
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"发送 ACK 失败: {exc}")
