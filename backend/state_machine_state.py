"""共享 StateMachine 轻量状态模块。"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .state_machine import StateMachine


_state_machine: "StateMachine | None" = None


def set_state_machine(state_machine: "StateMachine | None") -> None:
    """设置当前 StateMachine 实例。"""
    global _state_machine
    _state_machine = state_machine


def get_state_machine() -> "StateMachine | None":
    """返回当前 StateMachine 实例，未初始化时返回 None。"""
    return _state_machine
