"""
全局事件广播器模块。

提供一个真正全局的单例实例，解决 Python 模块导入问题。
"""

from .ws_event_broadcaster import EventBroadcaster

# 创建真正的全局实例（模块级变量）
_global_event_broadcaster: EventBroadcaster = None


def get_global_event_broadcaster() -> EventBroadcaster:
    """
    获取全局事件广播器实例。

    Returns:
        事件广播器实例
    """
    global _global_event_broadcaster
    if _global_event_broadcaster is None:
        _global_event_broadcaster = EventBroadcaster()
    return _global_event_broadcaster


def set_global_event_broadcaster(broadcaster: EventBroadcaster) -> None:
    """
    设置全局事件广播器实例。

    Args:
        broadcaster: 事件广播器实例
    """
    global _global_event_broadcaster
    _global_event_broadcaster = broadcaster
