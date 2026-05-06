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

from .logging_config import get_logger
from .robot_adapter import BaseRobotAdapter, VALID_COMMANDS
from .safety_supervisor import get_safety_supervisor
from .schemas import ControlAckDTO


# 结果常量
RESULT_ACCEPTED = "ACCEPTED"
RESULT_REJECTED_E_STOP = "REJECTED_E_STOP"
RESULT_REJECTED_INVALID_CMD = "REJECTED_INVALID_CMD"
RESULT_RATE_LIMITED = "RATE_LIMITED"
RESULT_REJECTED_ADAPTER_NOT_READY = "REJECTED_ADAPTER_NOT_READY"
RESULT_REJECTED_ADAPTER_ERROR = "REJECTED_ADAPTER_ERROR"
RESULT_REJECTED_SAFETY_BLOCKED = "REJECTED_SAFETY_BLOCKED"


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
        adapter: BaseRobotAdapter | None,
        state_machine=None,
        watchdog_timeout_ms: int = 500,
        cmd_rate_limit_ms: int = 50,
    ):
        """
        初始化控制服务。

        Args:
            adapter: 机器狗适配器实例，可为 None（适配器未就绪时命令将被拒绝）
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

    async def handle_command(self, cmd: str, *, vx: Optional[float] = None, vyaw: Optional[float] = None) -> ControlAckDTO:
        """
        处理控制命令。

        Args:
            cmd: 动作名（forward/backward/left/right/strafe_left/strafe_right/sit/stand/stop）
            vx:   可选速度覆盖（m/s），传入时临时替换适配器默认速度。
            vyaw: 可选速度覆盖（rad/s），传入时临时替换适配器默认转速。

        Returns:
            ControlAckDTO 应答
        """
        start_ts = time.monotonic()
        control_logger = get_logger("机器人控制")

        # 1. 校验命令名
        if cmd not in VALID_COMMANDS:
            control_logger.warning("收到非法控制命令：command={}", cmd)
            return ControlAckDTO(
                ack_cmd=cmd,
                result=RESULT_REJECTED_INVALID_CMD,
                latency_ms=_elapsed_ms(start_ts),
            )

        # 2. 检查 E_STOP 状态
        if self._is_e_stop_active():
            control_logger.warning("E_STOP 已激活，拒绝控制命令：command={}", cmd)
            return ControlAckDTO(
                ack_cmd=cmd,
                result=RESULT_REJECTED_E_STOP,
                latency_ms=_elapsed_ms(start_ts),
            )

        # 3. 统一安全检查（stop 永远允许；监督器异常时默认拒绝非 stop 命令）
        try:
            supervisor = get_safety_supervisor()
            decision = supervisor.evaluate_command(
                cmd,
                adapter_status=self.get_adapter_status(),
            )
        except Exception as exc:  # noqa: BLE001
            if cmd != "stop":
                control_logger.exception("SafetySupervisor 判定异常，拒绝控制命令：command={}，原因={}", cmd, exc)
                return ControlAckDTO(
                    ack_cmd=cmd,
                    result=RESULT_REJECTED_SAFETY_BLOCKED,
                    latency_ms=_elapsed_ms(start_ts),
                )
            decision = None

        if decision is not None and not decision.allowed:
            control_logger.warning(
                "SafetySupervisor 拒绝控制命令：command={}，reason={}，reasons={}",
                cmd,
                decision.reason,
                decision.reasons,
            )
            return ControlAckDTO(
                ack_cmd=cmd,
                result=RESULT_REJECTED_SAFETY_BLOCKED,
                latency_ms=_elapsed_ms(start_ts),
            )

        # 4. 检查适配器就绪状态
        if self._adapter is None:
            control_logger.warning("控制适配器未配置，拒绝控制命令：command={}", cmd)
            return ControlAckDTO(
                ack_cmd=cmd,
                result=RESULT_REJECTED_ADAPTER_NOT_READY,
                latency_ms=_elapsed_ms(start_ts),
            )
        
        if not self._adapter.is_ready():
            control_logger.warning("控制适配器未就绪，拒绝控制命令：command={}", cmd)
            return ControlAckDTO(
                ack_cmd=cmd,
                result=RESULT_REJECTED_ADAPTER_NOT_READY,
                latency_ms=_elapsed_ms(start_ts),
            )

        # 5. 速率限制（stop/stand/sit 跳过限制：stop 需立即响应，stand/sit 是一次性姿态命令）
        POSTURE_COMMANDS = frozenset({"stop", "stand", "sit"})
        now = time.monotonic()
        if cmd not in POSTURE_COMMANDS and (now - self._last_request_time) < self._rate_limit_s:
            return ControlAckDTO(
                ack_cmd=cmd,
                result=RESULT_RATE_LIMITED,
                latency_ms=_elapsed_ms(start_ts),
            )
        self._last_request_time = now

        # 6. 执行命令
        try:
            control_logger.info("收到控制命令：command={}", cmd)
            await self._adapter.send_command(cmd, vx=vx, vyaw=vyaw)
        except Exception as exc:  # noqa: BLE001
            control_logger.exception("控制命令执行失败：command={}，原因={}", cmd, exc)
            return ControlAckDTO(
                ack_cmd=cmd,
                result=RESULT_REJECTED_ADAPTER_ERROR,
                latency_ms=_elapsed_ms(start_ts),
            )

        # 7. 更新 Watchdog 状态
        # 只有持续运动命令（forward/backward/left/right）激活 Watchdog；
        # stand/sit 是一次性姿态命令，不需要周期性续命，发完即可。
        MOTION_COMMANDS = frozenset({"forward", "backward", "left", "right", "strafe_left", "strafe_right"})
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

    async def run_watchdog(self, stop_event: asyncio.Event) -> None:
        """
        Watchdog 后台任务。

        超过 watchdog_timeout 未收到命令时，自动执行 stop。
        设计：以 watchdog_timeout / 5 的频率轮询，保证超时精度。

        Args:
            stop_event: 应用级停止事件
        """
        check_interval = self._watchdog_timeout_s / 5
        get_logger("机器人控制").info(
            "控制 Watchdog 已启动：超时={}ms，检查间隔={}ms",
            self._watchdog_timeout_s * 1000,
            check_interval * 1000,
        )

        while not stop_event.is_set():
            try:
                await asyncio.sleep(check_interval)

                if not self._watchdog_active:
                    continue

                elapsed = time.monotonic() - self._watchdog_last_reset
                if elapsed >= self._watchdog_timeout_s:
                    get_logger("机器人控制").warning(
                        "控制 Watchdog 超时，自动执行 stop：elapsed_ms={:.0f}",
                        elapsed * 1000,
                    )
                    self._watchdog_active = False
                    if self._adapter is not None and self._adapter.is_ready():
                        try:
                            await self._adapter.stop()
                        except Exception as exc:  # noqa: BLE001
                            get_logger("机器人控制").critical("Watchdog 执行 stop 失败：{}", exc)
                    else:
                        get_logger("机器人控制").warning("Watchdog 检测到适配器不可用，已跳过 stop")

            except asyncio.CancelledError:
                get_logger("机器人控制").info("控制 Watchdog 已停止")
                break
            except Exception as exc:  # noqa: BLE001
                get_logger("机器人控制").exception("控制 Watchdog 异常：{}", exc)

    def set_adapter(self, adapter: BaseRobotAdapter | None) -> None:
        """替换适配器实例（供后台热切换使用，adapter=None 表示不可用）。"""
        self._adapter = adapter

    def get_adapter_status(self) -> dict:
        """返回适配器状态摘要，供调试端点使用。"""
        if self._adapter is None:
            return {"type": None, "ready": False}
        info: dict = {
            "type": type(self._adapter).__name__,
            "module": type(self._adapter).__module__,
            "ready": self._adapter.is_ready(),
        }
        if hasattr(self._adapter, "_initialized"):
            info["initialized"] = self._adapter._initialized
        if hasattr(self._adapter, "_sport_client"):
            info["sport_client_exists"] = self._adapter._sport_client is not None
        if hasattr(self._adapter, "_worker_thread"):
            info["worker_thread_alive"] = self._adapter._worker_thread.is_alive()
        if hasattr(self._adapter, "_cmd_queue"):
            info["cmd_queue_size"] = self._adapter._cmd_queue.qsize()
        return info

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
    """注入控制服务实例（供初始化 and 测试使用）。"""
    global _control_service
    _control_service = service
