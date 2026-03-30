"""
控制服务模块。

职责边界：
- 接收来自 HTTP 接口的控制命令
- 校验命令合法性
- 检查系统状态（E_STOP 时拒绝）
- 调用 RobotAdapter 转发命令
- 维护 Watchdog：超时未收到命令自动执行 stop
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

from .logging_config import logger
from .robot_adapter import BaseRobotAdapter, VALID_COMMANDS
from .schemas import ControlAckDTO


# 结果常量
RESULT_ACCEPTED = "ACCEPTED"
RESULT_REJECTED_E_STOP = "REJECTED_E_STOP"
RESULT_REJECTED_INVALID_CMD = "REJECTED_INVALID_CMD"
RESULT_RATE_LIMITED = "RATE_LIMITED"


class ControlService:
    """
    控制服务。

    功能：
    - 命令校验与转发
    - 速率限制（防止前端过快发送）
    - Watchdog：超时自动 stop
    """

    def __init__(
        self,
        adapter: BaseRobotAdapter,
        state_machine=None,
        watchdog_timeout_ms: int = 500,
        cmd_rate_limit_ms: int = 50,
    ):
        """
        初始化控制服务。

        Args:
            adapter: 机器狗适配器实例
            state_machine: 系统状态机（可选，用于 E_STOP 检查）
            watchdog_timeout_ms: Watchdog 超时时间（毫秒）
            cmd_rate_limit_ms: 最小命令间隔（毫秒）
        """
        self._adapter = adapter
        self._state_machine = state_machine
        self._watchdog_timeout_s = watchdog_timeout_ms / 1000.0
        self._rate_limit_s = cmd_rate_limit_ms / 1000.0

        # Watchdog 内部状态
        self._last_cmd_time: float = 0.0
        self._watchdog_active: bool = False  # 有活跃动作时为 True
        self._watchdog_last_reset: float = 0.0

        # 速率限制状态
        self._last_request_time: float = 0.0

    async def handle_command(self, cmd: str) -> ControlAckDTO:
        """
        处理控制命令。

        Args:
            cmd: 动作名（forward/backward/left/right/sit/stand/stop）

        Returns:
            ControlAckDTO 应答
        """
        start_ts = time.monotonic()

        # 1. 校验命令名
        if cmd not in VALID_COMMANDS:
            logger.warning(f"[ControlService] 非法命令: {cmd!r}")
            return ControlAckDTO(
                ack_cmd=cmd,
                result=RESULT_REJECTED_INVALID_CMD,
                latency_ms=_elapsed_ms(start_ts),
            )

        # 2. 检查 E_STOP 状态
        if self._is_e_stop_active():
            logger.warning(f"[ControlService] E_STOP 激活，拒绝命令: {cmd}")
            return ControlAckDTO(
                ack_cmd=cmd,
                result=RESULT_REJECTED_E_STOP,
                latency_ms=_elapsed_ms(start_ts),
            )

        # 3. 速率限制（stop/stand/sit 跳过限制：stop 需立即响应，stand/sit 是一次性姿态命令）
        POSTURE_COMMANDS = frozenset({"stop", "stand", "sit"})
        now = time.monotonic()
        if cmd not in POSTURE_COMMANDS and (now - self._last_request_time) < self._rate_limit_s:
            return ControlAckDTO(
                ack_cmd=cmd,
                result=RESULT_RATE_LIMITED,
                latency_ms=_elapsed_ms(start_ts),
            )
        self._last_request_time = now

        # 4. 执行命令
        try:
            await self._adapter.send_command(cmd)
        except Exception as exc:  # noqa: BLE001
            logger.exception(f"[ControlService] 适配器执行命令失败: {exc}")
            # 不向前端暴露内部错误，仍返回 ACCEPTED（保持接口稳定）

        # 5. 更新 Watchdog 状态
        # 只有持续运动命令（forward/backward/left/right）激活 Watchdog；
        # stand/sit 是一次性姿态命令，不需要周期性续命，发完即可。
        MOTION_COMMANDS = frozenset({"forward", "backward", "left", "right"})
        self._watchdog_last_reset = time.monotonic()
        if cmd == "stop":
            self._watchdog_active = False
        elif cmd in MOTION_COMMANDS:
            self._watchdog_active = True
        # stand/sit：不改变 _watchdog_active，维持当前状态

        return ControlAckDTO(
            ack_cmd=cmd,
            result=RESULT_ACCEPTED,
            latency_ms=_elapsed_ms(start_ts),
        )

    async def handle_velocity(self, vx: float, vyaw: float) -> ControlAckDTO:
        """
        处理连续速度控制命令（由 AutoTrackService 调用）。

        Args:
            vx: 前进/后退线速度（m/s）
            vyaw: 自转角速度（rad/s）
        """
        start_ts = time.monotonic()

        # 1. 检查 E_STOP 状态
        if self._is_e_stop_active():
            logger.warning("[ControlService] E_STOP 激活，拒绝执行 velocity 命令")
            return ControlAckDTO(
                ack_cmd="velocity",
                result=RESULT_REJECTED_E_STOP,
                latency_ms=_elapsed_ms(start_ts),
            )

        # 2. 速率限制
        now = time.monotonic()
        if (now - self._last_request_time) < self._rate_limit_s:
            return ControlAckDTO(
                ack_cmd="velocity",
                result=RESULT_RATE_LIMITED,
                latency_ms=_elapsed_ms(start_ts),
            )
        self._last_request_time = now

        # 3. 传给适配器
        try:
            await self._adapter.send_velocity(vx, vyaw)
        except Exception as exc:  # noqa: BLE001
            logger.exception(f"[ControlService] 适配器执行速度失败: {exc}")

        # 4. 重点：更新 Watchdog，只要发速度命令就视为活跃
        self._watchdog_last_reset = time.monotonic()
        self._watchdog_active = True

        return ControlAckDTO(
            ack_cmd="velocity",
            result=RESULT_ACCEPTED,
            latency_ms=_elapsed_ms(start_ts),
        )

    async def run_watchdog(self, stop_event: asyncio.Event) -> None:
        """
        Watchdog 后台任务。

        超过 watchdog_timeout 未收到命令时，自动执行 stop。
        设计：以 watchdog_timeout / 5 的频率轮询，保证超时精度。

        Args:
            stop_event: 应用级停止事件
        """
        check_interval = self._watchdog_timeout_s / 5
        logger.info(
            f"[Watchdog] 已启动，超时: {self._watchdog_timeout_s * 1000:.0f}ms，"
            f"检查间隔: {check_interval * 1000:.0f}ms"
        )

        while not stop_event.is_set():
            try:
                await asyncio.sleep(check_interval)

                if not self._watchdog_active:
                    continue

                elapsed = time.monotonic() - self._watchdog_last_reset
                if elapsed >= self._watchdog_timeout_s:
                    logger.warning(
                        f"[Watchdog] 超时 ({elapsed * 1000:.0f}ms)，自动执行 stop"
                    )
                    self._watchdog_active = False
                    try:
                        await self._adapter.stop()
                    except Exception as exc:  # noqa: BLE001
                        logger.exception(f"[Watchdog] 执行 stop 失败: {exc}")

            except asyncio.CancelledError:
                logger.info("[Watchdog] 已停止")
                break
            except Exception as exc:  # noqa: BLE001
                logger.exception(f"[Watchdog] 异常: {exc}")

    def _is_e_stop_active(self) -> bool:
        """检查 E_STOP 是否激活。"""
        if self._state_machine is None:
            return False
        try:
            from .state_machine import SystemState
            return self._state_machine.state == SystemState.E_STOP_TRIGGERED
        except Exception:  # noqa: BLE001
            return False


# ─── 工具函数 ────────────────────────────────────────────────────────────────

def _elapsed_ms(start_ts: float) -> float:
    """计算从 start_ts 到现在的毫秒数，保留两位小数。"""
    return round((time.monotonic() - start_ts) * 1000, 2)


# ─── 全局单例 ────────────────────────────────────────────────────────────────

_control_service: Optional[ControlService] = None


def get_control_service() -> Optional[ControlService]:
    """获取控制服务实例。"""
    return _control_service


def set_control_service(service: ControlService) -> None:
    """注入控制服务实例（供初始化和测试使用）。"""
    global _control_service
    _control_service = service
