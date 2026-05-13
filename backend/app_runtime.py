"""后端运行时服务装配。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from .alert_service import AlertService, set_alert_service
from .auto_track_service import AutoTrackService, set_auto_track_service
from .config import settings
from .control_arbiter import ControlArbiter, set_control_arbiter
from .guard_mission_service import GuardMissionService, set_guard_mission_service
from .logging_config import get_logger
from .nav_bridge_state import set_ros_nav_bridge
from .services_ros_nav import RosNavBridge
from .state_machine import StateMachine
from .stranger_policy import StrangerPolicy, set_stranger_policy
from .target_manager import TargetManager
from .ws_broadcaster import WebSocketBroadcaster
from .ws_event_broadcaster import EventBroadcaster
from .ws_runtime_state import set_ws_runtime
from .zone_service import ZoneService, set_zone_service

telemetry_logger = get_logger("机器人遥测")
ai_logger = get_logger("AI识别")
ros_logger = get_logger("ROS导航")
zone_logger = get_logger("重点区服务")
auto_track_logger = get_logger("自动跟踪")
guard_logger = get_logger("驱离任务")
control_logger = get_logger("机器人控制")


async def initialize_runtime_services(
    *,
    queue_manager,
    state_machine: StateMachine,
    session_factory,
    snapshot_dir: Path,
    stop_event: asyncio.Event,
    startup_summary: dict[str, tuple[str, str]],
    mavlink_gateway,
    tasks: list[asyncio.Task[None]],
) -> tuple[Any, Any, Any, Any, Any, Any, Any]:
    """
    装配运行时服务。

    这一步只负责把业务运行态对象串起来，不改变既有行为。
    """

    # 1) 遥测广播器
    ws_broadcaster = WebSocketBroadcaster(
        queue_manager=queue_manager,
        broadcast_interval=1.0 / settings.TELEMETRY_BROADCAST_HZ,
    )
    tasks.append(asyncio.create_task(ws_broadcaster.start()))
    telemetry_logger.info("遥测广播服务启动请求已提交")

    # 2) 事件广播器与 ROS 导航桥
    event_broadcaster = EventBroadcaster()
    from .global_event_broadcaster import set_global_event_broadcaster

    set_global_event_broadcaster(event_broadcaster)
    set_ws_runtime(queue_manager, state_machine, event_broadcaster)
    get_logger("WebSocket事件").info("事件广播器已初始化")

    ros_nav_bridge = None
    if settings.ROS_NAV_ENABLED:
        ros_nav_bridge = RosNavBridge(
            broadcaster=event_broadcaster,
            loop=asyncio.get_running_loop(),
        )
        ros_nav_bridge.start()
        set_ros_nav_bridge(ros_nav_bridge)
        ros_logger.info(
            "ROS2 导航桥启动请求已提交：topic={}，type={}",
            settings.ROS_NAV_POSE_TOPIC,
            settings.ROS_NAV_POSE_TYPE,
        )
        if settings.ROS_NAV_POSE_TYPE.strip().lower() in ("tf", "tf2", "transform", "transformstamped"):
            startup_summary["ROS导航"] = (
                "waiting",
                f"等待 TF：target={settings.ROS_NAV_FRAME_ID}，source={settings.ROS_NAV_BASE_FRAME_ID}",
            )
        else:
            startup_summary["ROS导航"] = (
                "waiting",
                f"等待定位数据：topic={settings.ROS_NAV_POSE_TOPIC}，type={settings.ROS_NAV_POSE_TYPE}",
            )
    else:
        startup_summary["ROS导航"] = ("disabled", "ROS_NAV_ENABLED=false")
        ros_logger.info("ROS2 导航桥已禁用：ROS_NAV_ENABLED=false")

    # 3) 告警服务
    alert_service_instance = AlertService(event_broadcaster=event_broadcaster)
    set_alert_service(alert_service_instance)
    get_logger("应用服务").info("告警服务已初始化")

    # 4) 控制服务
    from .control_service import ControlService, set_control_service
    from .robot_adapter import create_adapter

    _adapter_kwargs: dict[str, Any] = {}
    if settings.CONTROL_ADAPTER_TYPE == "unitree_b2":
        _adapter_kwargs = {
            "network_interface": settings.UNITREE_NETWORK_IFACE,
            "vx": settings.UNITREE_B2_VX,
            "vyaw": settings.UNITREE_B2_VYAW,
        }

    if settings.CONTROL_ADAPTER_TYPE == "unitree_b2":
        control_service = ControlService(
            adapter=None,
            state_machine=state_machine,
            watchdog_timeout_ms=settings.CONTROL_WATCHDOG_TIMEOUT_MS,
            cmd_rate_limit_ms=settings.CONTROL_CMD_RATE_LIMIT_MS,
        )
        set_control_service(control_service)
        tasks.append(asyncio.create_task(control_service.run_watchdog(stop_event)))
        control_logger.info("控制服务已启动：等待 Unitree B2 适配器完成初始化")
        startup_summary["机器人控制"] = (
            "waiting",
            f"适配器=UnitreeB2，网卡={settings.UNITREE_NETWORK_IFACE}，运控模式=ai",
        )

        async def _init_b2_adapter_background() -> None:
            try:
                real_adapter = create_adapter("unitree_b2", **_adapter_kwargs)
                control_service.set_adapter(real_adapter)
                control_logger.info("UnitreeB2 适配器初始化完成，控制能力已恢复可用")
            except Exception as exc:
                control_logger.error("UnitreeB2 适配器初始化失败，控制命令将继续被拒绝：{}", exc)

        tasks.append(asyncio.create_task(_init_b2_adapter_background()))
    else:
        adapter = create_adapter(settings.CONTROL_ADAPTER_TYPE, **_adapter_kwargs)
        control_service = ControlService(
            adapter=adapter,
            state_machine=state_machine,
            watchdog_timeout_ms=settings.CONTROL_WATCHDOG_TIMEOUT_MS,
            cmd_rate_limit_ms=settings.CONTROL_CMD_RATE_LIMIT_MS,
        )
        set_control_service(control_service)
        tasks.append(asyncio.create_task(control_service.run_watchdog(stop_event)))
        control_logger.info(
            "控制服务已启动：适配器={}，watchdog={}ms",
            settings.CONTROL_ADAPTER_TYPE,
            settings.CONTROL_WATCHDOG_TIMEOUT_MS,
        )
        startup_summary["机器人控制"] = (
            "ready",
            f"适配器={settings.CONTROL_ADAPTER_TYPE}，watchdog={settings.CONTROL_WATCHDOG_TIMEOUT_MS}ms",
        )

    # 5) 重点区、自动跟踪、驱离
    _zone_service = ZoneService()
    async with session_factory() as zone_session:
        await _zone_service.load_from_db(zone_session)
    set_zone_service(_zone_service)
    zone_logger.info("重点区服务已初始化：已加载区域数={}", _zone_service.zone_count)
    startup_summary["重点区服务"] = ("ready", f"已加载区域数={_zone_service.zone_count}")

    _target_manager = TargetManager(
        frame_width=settings.AI_FRAME_WIDTH,
        frame_height=settings.AI_FRAME_HEIGHT,
    )
    _arbiter = ControlArbiter()
    set_control_arbiter(_arbiter)

    _stranger_policy = StrangerPolicy()
    set_stranger_policy(_stranger_policy)

    _auto_track_service = AutoTrackService(
        zone_service=_zone_service,
        control_service=control_service,
        event_broadcaster=event_broadcaster,
        state_machine=state_machine,
        session_factory=session_factory,
        snapshot_dir=snapshot_dir,
        frame_width=settings.AI_FRAME_WIDTH,
        frame_height=settings.AI_FRAME_HEIGHT,
        stable_hits=settings.AI_STABLE_HITS,
        reset_misses=settings.AI_RESET_MISSES,
        out_of_zone_frames=settings.AUTO_TRACK_OUT_OF_ZONE_FRAMES,
        lost_timeout_frames=settings.AUTO_TRACK_LOST_TIMEOUT_FRAMES,
        command_interval_ms=settings.AUTO_TRACK_COMMAND_INTERVAL_MS,
        yaw_deadband_px=settings.AUTO_TRACK_YAW_DEADBAND_PX,
        forward_area_ratio=settings.AUTO_TRACK_FORWARD_AREA_RATIO,
        anchor_y_stop_ratio=settings.AUTO_TRACK_ANCHOR_Y_STOP_RATIO,
        stop_snapshot_enabled=settings.AUTO_TRACK_STOP_SNAPSHOT_ENABLED,
        default_enabled=settings.AUTO_TRACK_ENABLED,
        yaw_pulse_ms=settings.AUTO_TRACK_YAW_PULSE_MS,
        target_manager=_target_manager,
        control_arbiter=_arbiter,
    )
    set_auto_track_service(_auto_track_service)
    auto_track_logger.info(
        "自动跟踪服务已初始化：默认启用={}，多目标模式=true",
        settings.AUTO_TRACK_ENABLED,
    )
    startup_summary["自动跟踪"] = (
        "ready",
        f"默认启用={settings.AUTO_TRACK_ENABLED}，多目标模式=true",
    )

    _guard_mission_service = GuardMissionService(
        zone_service=_zone_service,
        control_service=control_service,
        control_arbiter=_arbiter,
        event_broadcaster=event_broadcaster,
        config=settings,
        session_factory=session_factory,
        snapshot_dir=snapshot_dir,
        frame_width=settings.AI_FRAME_WIDTH,
        frame_height=settings.AI_FRAME_HEIGHT,
    )
    set_guard_mission_service(_guard_mission_service)
    guard_logger.info("驱离任务服务已初始化：默认启用={}", settings.GUARD_MISSION_ENABLED)
    startup_summary["驱离任务"] = (
        "ready",
        f"默认启用={settings.GUARD_MISSION_ENABLED}",
    )

    return (
        ws_broadcaster,
        event_broadcaster,
        ros_nav_bridge,
        control_service,
        _zone_service,
        _auto_track_service,
        _guard_mission_service,
    )
