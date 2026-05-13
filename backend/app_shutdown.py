"""后端运行时关闭流程。"""

from __future__ import annotations

import asyncio
from typing import Any

from .logging_config import get_logger
from .nav_bridge_state import set_ros_nav_bridge
from .services_mapping import get_mapping_service
from .state_machine_state import set_state_machine
from .ws_runtime_state import clear_ws_runtime

app_logger = get_logger("应用服务")


async def shutdown_runtime_services(
    *,
    tasks: list[asyncio.Task[None]],
    ros_nav_bridge: Any | None,
) -> None:
    """停止运行时服务，保持现有关闭语义不变。"""

    set_state_machine(None)
    clear_ws_runtime()

    try:
        mapping_service = get_mapping_service()
        mapping_status = mapping_service.get_status()
        if mapping_status["running"]:
            mapping_logger = get_logger("建图服务")
            mapping_logger.info("应用关闭时停止建图流程")
            await asyncio.to_thread(mapping_service.stop)
    except Exception as exc:
        app_logger.warning("关闭建图服务时发生异常：{}", exc)

    if ros_nav_bridge is not None:
        ros_nav_bridge.stop()
        set_ros_nav_bridge(None)

    for task in tasks:
        task.cancel()

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            app_logger.warning("后台任务关闭时出现异常：{}", result)

    app_logger.info("所有后台任务已停止")
