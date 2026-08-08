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
from .multisensor_fusion import MultiSensorFusionService, set_multisensor_fusion_service
from .nav_auto_track_coordinator import NavAutoTrackCoordinator, set_nav_auto_track_coordinator
from .nav_bridge_state import set_ros_nav_bridge
from .navigation_velocity_udp import (
    NavigationVelocityUdpService,
    set_navigation_velocity_udp_service,
)
from .services_ros_nav import RosNavBridge
from .state_machine import StateMachine
from .stranger_policy import StrangerPolicy, set_stranger_policy
from .target_manager import TargetManager
from .startup_summary import StartupSummary
from .ws_broadcaster import WebSocketBroadcaster
from .ws_event_broadcaster import EventBroadcaster
from .ws_runtime_state import set_ws_runtime
from .z2mini_gimbal import GcuProtocolError, get_z2mini_gimbal
from .fence_detection_service import FenceDetectionService, set_fence_detection_service
from .zone_service import ZoneService, set_zone_service

telemetry_logger = get_logger("机器人遥测")
ai_logger = get_logger("AI识别")
ros_logger = get_logger("ROS导航")
zone_logger = get_logger("重点区服务")
auto_track_logger = get_logger("自动跟踪")
guard_logger = get_logger("驱离任务")
control_logger = get_logger("机器人控制")
gimbal_logger = get_logger("云台控制")


async def initialize_runtime_services(
    *,
    queue_manager,
    state_machine: StateMachine,
    session_factory,
    snapshot_dir: Path,
    stop_event: asyncio.Event,
    startup_summary: StartupSummary,
    mavlink_gateway,
    tasks: list[asyncio.Task[None]],
) -> tuple[Any, Any, Any, Any, Any, Any, Any, Any]:
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
    mapping_cloud_broadcaster = EventBroadcaster()
    from .global_event_broadcaster import set_global_event_broadcaster

    set_global_event_broadcaster(event_broadcaster)
    set_ws_runtime(queue_manager, state_machine, event_broadcaster, mapping_cloud_broadcaster)
    get_logger("WebSocket事件").info("事件广播器已初始化")
    get_logger("WebSocket事件").info("导航建图点云广播器已初始化")

    # 多源服务必须先于 ROS bridge 注册，bridge 创建节点时才会挂载原始
    # Livox 订阅。默认关闭；未标定时只报告缺项，不输出三维坐标。
    multisensor_service = MultiSensorFusionService.from_settings()
    set_multisensor_fusion_service(multisensor_service)
    multisensor_status = multisensor_service.get_status()
    startup_summary.set(
        "多源融合",
        (
            "disabled"
            if multisensor_status["state"] == "disabled"
            else "waiting"
            if multisensor_status["state"] != "ready"
            else "ready"
        ),
        multisensor_status["detail"],
    )

    ros_nav_bridge = None
    if settings.ROS_NAV_ENABLED:
        ros_nav_bridge = RosNavBridge(
            broadcaster=event_broadcaster,
            mapping_cloud_broadcaster=mapping_cloud_broadcaster,
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
            startup_summary.set(
                "ROS导航",
                "waiting",
                f"等待 TF：target={settings.ROS_NAV_FRAME_ID}，source={settings.ROS_NAV_BASE_FRAME_ID}",
            )
        else:
            startup_summary.set(
                "ROS导航",
                "waiting",
                f"等待定位数据：topic={settings.ROS_NAV_POSE_TOPIC}，type={settings.ROS_NAV_POSE_TYPE}",
            )
    else:
        startup_summary.set("ROS导航", "disabled", "ROS_NAV_ENABLED=false")
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
        startup_summary.set(
            "机器人控制",
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
        startup_summary.set(
            "机器人控制",
            "ready",
            f"适配器={settings.CONTROL_ADAPTER_TYPE}，watchdog={settings.CONTROL_WATCHDOG_TIMEOUT_MS}ms",
        )

    # 5) 相机默认使用纯可见光，避免设备重启后停在热成像或画中画。
    gimbal_service = get_z2mini_gimbal()
    try:
        picture_status = await gimbal_service.set_picture_mode(
            settings.Z2MINI_DEFAULT_PICTURE_MODE
        )
        gimbal_logger.info(
            "Z2-Mini 默认画面已应用：mode={}，code={}",
            picture_status.picture_mode,
            picture_status.picture_mode_code,
        )
        startup_summary.set(
            "Z2-Mini 相机",
            "ready",
            (
                f"默认画面={picture_status.picture_mode}，"
                f"模式码={picture_status.picture_mode_code}"
            ),
        )
    except (OSError, GcuProtocolError, ValueError) as exc:
        gimbal_logger.warning("Z2-Mini 默认画面设置失败：{}", exc)
        startup_summary.set(
            "Z2-Mini 相机",
            "degraded",
            f"默认画面设置失败：{exc}",
        )

    if settings.MULTISENSOR_ENABLED:
        async def _poll_multisensor_gimbal_status() -> None:
            interval = 1.0 / max(0.2, float(settings.MULTISENSOR_GIMBAL_POLL_HZ))
            warned = False
            while not stop_event.is_set():
                try:
                    await gimbal_service.status()
                    warned = False
                except (OSError, GcuProtocolError, ValueError) as exc:
                    if not warned:
                        gimbal_logger.warning("多源融合读取云台姿态失败：{}", exc)
                        warned = True
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=interval)
                except asyncio.TimeoutError:
                    pass

        tasks.append(asyncio.create_task(_poll_multisensor_gimbal_status()))
        gimbal_logger.info(
            "多源融合云台姿态轮询已启动：频率={}Hz",
            settings.MULTISENSOR_GIMBAL_POLL_HZ,
        )

    # 复用同一导航位姿、Z2-Mini 和 AI 解码帧，不创建第二条视频链路。
    _fence_detection_service = FenceDetectionService(gimbal_service=gimbal_service)
    set_fence_detection_service(_fence_detection_service)
    tasks.append(asyncio.create_task(_fence_detection_service.run(stop_event)))
    startup_summary.set("自动围栏检测", "ready", "默认关闭，等待控制台开启")

    # 6) 重点区、自动跟踪、驱离
    _zone_service = ZoneService()
    async with session_factory() as zone_session:
        await _zone_service.load_from_db(zone_session)
    set_zone_service(_zone_service)
    zone_logger.info("重点区服务已初始化：已加载区域数={}", _zone_service.zone_count)
    startup_summary.set("重点区服务", "ready", f"已加载区域数={_zone_service.zone_count}")

    _target_manager = TargetManager(
        frame_width=settings.AI_FRAME_WIDTH,
        frame_height=settings.AI_FRAME_HEIGHT,
    )
    _arbiter = ControlArbiter()
    set_control_arbiter(_arbiter)
    set_navigation_velocity_udp_service(None)
    if settings.CONTROL_ADAPTER_TYPE == "unitree_b2":
        navigation_velocity_udp = NavigationVelocityUdpService(
            control_service=control_service,
            control_arbiter=_arbiter,
        )
        set_navigation_velocity_udp_service(navigation_velocity_udp)
        try:
            navigation_velocity_udp.bind()
        except Exception as exc:
            navigation_velocity_udp.close()
            set_navigation_velocity_udp_service(None)
            control_logger.critical(
                "Navigation velocity UDP listener failed to bind: {}",
                exc,
            )
            raise RuntimeError(
                "failed to bind navigation velocity UDP listener on 127.0.0.1:52345"
            ) from exc
        navigation_velocity_task = asyncio.create_task(
            navigation_velocity_udp.run(stop_event)
        )
        navigation_velocity_task.add_done_callback(
            lambda _task: navigation_velocity_udp.close()
        )
        tasks.append(navigation_velocity_task)
        startup_summary.set(
            "Navigation velocity ingress",
            "ready",
            (
                "UDP=127.0.0.1:52345, "
                f"timeout={navigation_velocity_udp.get_status()['timeout_s'] * 1000:.0f}ms, "
                "single UnitreeB2Adapter writer"
            ),
        )
    else:
        startup_summary.set(
            "Navigation velocity ingress",
            "disabled",
            f"adapter={settings.CONTROL_ADAPTER_TYPE}",
        )
    _nav_auto_track_coordinator = NavAutoTrackCoordinator()
    set_nav_auto_track_coordinator(_nav_auto_track_coordinator)

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
        video_lost_grace_seconds=settings.AUTO_TRACK_VIDEO_LOST_GRACE_SECONDS,
        command_interval_ms=settings.AUTO_TRACK_COMMAND_INTERVAL_MS,
        yaw_deadband_px=settings.AUTO_TRACK_YAW_DEADBAND_PX,
        forward_area_ratio=settings.AUTO_TRACK_FORWARD_AREA_RATIO,
        anchor_y_stop_ratio=settings.AUTO_TRACK_ANCHOR_Y_STOP_RATIO,
        stop_snapshot_enabled=settings.AUTO_TRACK_STOP_SNAPSHOT_ENABLED,
        default_enabled=settings.AUTO_TRACK_ENABLED,
        yaw_pulse_ms=settings.AUTO_TRACK_YAW_PULSE_MS,
        gimbal_enabled=settings.AUTO_TRACK_GIMBAL_ENABLED,
        gimbal_body_deadband_deg=settings.AUTO_TRACK_GIMBAL_BODY_DEADBAND_DEG,
        gimbal_forward_deadband_deg=settings.AUTO_TRACK_GIMBAL_FORWARD_DEADBAND_DEG,
        gimbal_realign_frames=settings.AUTO_TRACK_GIMBAL_REALIGN_FRAMES,
        gimbal_horizontal_fov_deg=settings.AUTO_TRACK_GIMBAL_HORIZONTAL_FOV_DEG,
        gimbal_servo_gain=settings.AUTO_TRACK_GIMBAL_SERVO_GAIN,
        gimbal_pixel_deadband_px=settings.AUTO_TRACK_GIMBAL_PIXEL_DEADBAND_PX,
        gimbal_command_interval_ms=settings.AUTO_TRACK_GIMBAL_COMMAND_INTERVAL_MS,
        gimbal_min_body_vyaw=settings.AUTO_TRACK_GIMBAL_MIN_BODY_VYAW,
        gimbal_service=(
            gimbal_service
            if settings.AUTO_TRACK_GIMBAL_ENABLED
            else None
        ),
        target_manager=_target_manager,
        control_arbiter=_arbiter,
    )
    set_auto_track_service(_auto_track_service)
    auto_track_logger.info(
        "自动跟踪服务已初始化：默认启用={}，多目标模式=true，云台协同={}",
        settings.AUTO_TRACK_ENABLED,
        settings.AUTO_TRACK_GIMBAL_ENABLED,
    )
    startup_summary.set(
        "自动跟踪",
        "ready",
        (
            f"默认启用={settings.AUTO_TRACK_ENABLED}，多目标模式=true，"
            f"云台协同={settings.AUTO_TRACK_GIMBAL_ENABLED}"
        ),
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
    startup_summary.set("驱离任务", "ready", f"默认启用={settings.GUARD_MISSION_ENABLED}")

    return (
        ws_broadcaster,
        event_broadcaster,
        mapping_cloud_broadcaster,
        ros_nav_bridge,
        control_service,
        _zone_service,
        _auto_track_service,
        _guard_mission_service,
    )
