"""后端运行时关闭流程。"""

from __future__ import annotations

import asyncio
from typing import Any

from .control_service import get_control_service, set_control_service
from .fence_detection_service import get_fence_detection_service, set_fence_detection_service
from .logging_config import get_logger
from .multisensor_fusion import set_multisensor_fusion_service
from .nav_bridge_state import set_ros_nav_bridge
from .navigation_velocity_udp import (
    get_navigation_velocity_udp_service,
    set_navigation_velocity_udp_service,
)
from .services_mapping import get_mapping_service
from .state_machine_state import set_state_machine
from .ws_runtime_state import clear_ws_runtime
from .weather_detection import set_weather_detection_service

app_logger = get_logger("应用服务")


async def shutdown_runtime_services(
    *,
    tasks: list[asyncio.Task[None]],
    ros_nav_bridge: Any | None,
) -> None:
    """停止运行时服务，保持现有关闭语义不变。"""

    set_state_machine(None)
    clear_ws_runtime()
    set_multisensor_fusion_service(None)
    set_weather_detection_service(None)

    navigation_velocity_udp = get_navigation_velocity_udp_service()
    if navigation_velocity_udp is not None:
        navigation_velocity_udp.close()
        set_navigation_velocity_udp_service(None)

    try:
        mapping_service = get_mapping_service()
        mapping_status = mapping_service.get_status()
        if mapping_status["running"] or mapping_status.get("saving"):
            mapping_logger = get_logger("建图服务")
            mapping_logger.info("应用关闭时等待建图停止和地图保存流程完成")
            await asyncio.to_thread(mapping_service.stop)
    except Exception as exc:
        app_logger.warning("关闭建图服务时发生异常：{}", exc)

    if ros_nav_bridge is not None:
        ros_nav_bridge.stop()
        set_ros_nav_bridge(None)

    fence_detection = get_fence_detection_service()
    if fence_detection is not None:
        try:
            await fence_detection.disable(center_gimbal=True)
        except Exception as exc:
            app_logger.warning("关闭围栏检测服务时发生异常：{}", exc)
        set_fence_detection_service(None)

    for task in tasks:
        task.cancel()

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            app_logger.warning("后台任务关闭时出现异常：{}", result)

    control_service = get_control_service()
    if control_service is not None:
        try:
            await control_service.force_stop()
        except Exception as exc:
            app_logger.warning("应用关闭时最终停车失败：{}", exc)
        await asyncio.to_thread(control_service.set_adapter, None)
        set_control_service(None)

    app_logger.info("所有后台任务已停止")
