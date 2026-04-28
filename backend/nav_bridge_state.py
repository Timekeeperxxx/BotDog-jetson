"""ROS 导航桥共享状态模块。

main.py lifespan 调用 set_ros_nav_bridge() 注册/注销实例；
nav router 调用 get_ros_nav_bridge() 获取实例。
两者通过此模块解耦，无循环导入。
"""

from typing import Any

_ros_nav_bridge: Any = None


def set_ros_nav_bridge(bridge: Any | None) -> None:
    """注册或注销 ROS 导航桥实例（由 lifespan 调用）。"""
    global _ros_nav_bridge
    _ros_nav_bridge = bridge


def get_ros_nav_bridge() -> Any | None:
    """返回当前 ROS 导航桥实例（由 nav router 调用）。"""
    return _ros_nav_bridge
