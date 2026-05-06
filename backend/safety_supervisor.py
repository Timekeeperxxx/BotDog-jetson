"""故障安全总监督。

职责边界：
- 只负责判断当前是否允许执行运动命令；
- 不直接发送控制命令，也不直接触发 stop；
- 为 ControlService 和诊断接口提供统一安全结论。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .state_machine import SystemState
from .state_machine_state import get_state_machine

MOTION_COMMANDS = frozenset(
    {
        "forward",
        "backward",
        "left",
        "right",
        "strafe_left",
        "strafe_right",
    }
)
ALWAYS_ALLOW_COMMANDS = frozenset({"stop"})


@dataclass(slots=True)
class SafetyDecision:
    allowed: bool
    reason: str
    reasons: list[str]


class SafetySupervisor:
    """统一安全判定入口。"""

    def evaluate_command(
        self,
        cmd: str,
        adapter_status: dict[str, Any] | None = None,
    ) -> SafetyDecision:
        if cmd in ALWAYS_ALLOW_COMMANDS:
            return SafetyDecision(allowed=True, reason="停止命令永远允许", reasons=[])

        if cmd not in MOTION_COMMANDS:
            return SafetyDecision(allowed=True, reason="非运动命令暂不拦截", reasons=[])

        return self.get_motion_safety(adapter_status=adapter_status)

    def get_motion_safety(
        self,
        adapter_status: dict[str, Any] | None = None,
    ) -> SafetyDecision:
        reasons: list[str] = []
        state_machine = get_state_machine()

        if state_machine is None:
            reasons.append("状态机未初始化")
        else:
            state = getattr(state_machine, "state", None)
            if state == SystemState.E_STOP_TRIGGERED:
                reasons.append("系统处于急停状态")
            if state == SystemState.DISCONNECTED:
                reasons.append("底层链路断开")

        if adapter_status is not None and adapter_status.get("ready") is False:
            reasons.append("控制适配器未就绪")

        if reasons:
            return SafetyDecision(
                allowed=False,
                reason="；".join(reasons),
                reasons=reasons,
            )

        return SafetyDecision(
            allowed=True,
            reason="当前允许执行运动命令",
            reasons=[],
        )


_safety_supervisor: SafetySupervisor | None = None


def get_safety_supervisor() -> SafetySupervisor:
    """返回 SafetySupervisor 单例。"""
    global _safety_supervisor
    if _safety_supervisor is None:
        _safety_supervisor = SafetySupervisor()
    return _safety_supervisor


def set_safety_supervisor(supervisor: SafetySupervisor | None) -> None:
    """供测试替换 SafetySupervisor 单例。"""
    global _safety_supervisor
    _safety_supervisor = supervisor
