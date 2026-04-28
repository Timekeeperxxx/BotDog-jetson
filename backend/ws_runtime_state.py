"""WebSocket 路由运行时状态。"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .state_machine import StateMachine
    from .telemetry_queue import TelemetryQueueManager
    from .ws_event_broadcaster import EventBroadcaster


_queue_manager: "TelemetryQueueManager | None" = None
_state_machine: "StateMachine | None" = None
_event_broadcaster: "EventBroadcaster | None" = None


def set_ws_runtime(
    queue_manager: "TelemetryQueueManager | None",
    state_machine: "StateMachine | None",
    event_broadcaster: "EventBroadcaster | None",
) -> None:
    """设置 WebSocket 路由所需的运行时对象。"""
    global _queue_manager, _state_machine, _event_broadcaster
    _queue_manager = queue_manager
    _state_machine = state_machine
    _event_broadcaster = event_broadcaster


def clear_ws_runtime() -> None:
    """清空 WebSocket 路由运行时对象。"""
    set_ws_runtime(None, None, None)


def get_queue_manager() -> "TelemetryQueueManager | None":
    """返回当前遥测队列管理器。"""
    return _queue_manager


def get_state_machine() -> "StateMachine | None":
    """返回当前状态机。"""
    return _state_machine


def get_event_broadcaster() -> "EventBroadcaster | None":
    """返回当前事件广播器。"""
    return _event_broadcaster
