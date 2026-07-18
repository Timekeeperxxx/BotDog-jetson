"""后台配置中心可管理参数注册表。"""

from __future__ import annotations

from typing import Any

from .config import settings


def _serialize(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _value_type(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    return "string"


def _definition(
    setting: str,
    category: str,
    description: str,
    *,
    hot: bool = False,
    validation: dict[str, Any] | None = None,
    key: str | None = None,
) -> tuple[str, dict[str, Any]]:
    value = getattr(settings, setting)
    return key or setting.lower(), {
        "value": _serialize(value),
        "value_type": _value_type(value),
        "category": category,
        "description": description,
        "is_hot_reloadable": hot,
        "setting": setting,
        "validation": validation or {},
    }


_SPECS = [
    # 系统运行与遥测
    _definition("MAVLINK_SOURCE", "backend", "遥测数据源", validation={"options": ["mavlink", "simulation"]}),
    _definition("SIMULATION_WORKER_ENABLED", "backend", "是否启用模拟遥测 Worker"),
    _definition("TELEMETRY_SAMPLING_HZ", "backend", "遥测落盘采样频率 (Hz)", validation={"min": 0.1, "max": 60}),
    _definition("TELEMETRY_BROADCAST_HZ", "backend", "遥测 WebSocket 广播频率 (Hz)", validation={"min": 0.1, "max": 60}),

    # 日志
    _definition("LOG_CONSOLE_LEVEL", "logging", "控制台日志等级", validation={"options": ["DEBUG", "INFO", "WARNING", "ERROR"]}),
    _definition("LOG_ROTATION_SIZE_MB", "logging", "单个日志文件轮转大小 (MB)", validation={"min": 1, "max": 1024}),
    _definition("LOG_RETENTION_DAYS", "logging", "运行日志保留天数", validation={"min": 1, "max": 365}),
    _definition("LOG_COMPRESSION", "logging", "归档日志压缩格式", validation={"options": ["zip", "gz", "bz2", "xz", ""]}),

    # AI 推理
    _definition("AI_ENABLED", "ai", "是否启用 AI Worker"),
    _definition("AI_RTSP_URL", "ai", "AI 推理主 RTSP 地址"),
    _definition("AI_RTSP_FALLBACK_URLS", "ai", "AI 备用 RTSP 地址（逗号分隔）"),
    _definition("AI_FRAME_WIDTH", "ai", "AI 输入画面宽度", validation={"min": 160, "max": 3840}),
    _definition("AI_FRAME_HEIGHT", "ai", "AI 输入画面高度", validation={"min": 120, "max": 2160}),
    _definition("AI_FPS", "ai", "AI 拉流处理帧率", validation={"min": 1, "max": 60}),
    _definition("AI_INFERENCE_IMGSZ", "ai", "模型推理输入尺寸", validation={"min": 160, "max": 1920}),
    _definition("AI_FFMPEG_RETRY_MIN_SECONDS", "ai", "FFmpeg 重试最小间隔 (秒)", validation={"min": 0.1, "max": 60}),
    _definition("AI_FFMPEG_RETRY_MAX_SECONDS", "ai", "FFmpeg 重试最大间隔 (秒)", validation={"min": 0.1, "max": 300}),
    _definition("AI_FRAME_PROCESS_TIMEOUT_SECONDS", "ai", "单帧 AI 处理超时 (秒)", validation={"min": 1, "max": 300}),
    _definition("AI_EXIT_ON_FRAME_TIMEOUT", "ai", "单帧处理超时时是否退出进程"),
    _definition("AI_EVENT_SEND_TIMEOUT_SECONDS", "ai", "AI 事件发送超时 (秒)", validation={"min": 0.005, "max": 10}),
    _definition("AI_MAX_FRAME_AGE_SECONDS", "ai", "允许处理的最大帧延迟 (秒)", validation={"min": 0.01, "max": 10}),
    _definition("AI_PATROL_SKIP", "ai", "巡逻模式推理跳帧数", validation={"min": 1, "max": 30}),
    _definition("AI_AUTO_TRACK_SKIP", "ai", "自动跟踪模式推理跳帧数", validation={"min": 1, "max": 30}),
    _definition("AI_SUSPECT_SKIP", "ai", "疑似目标模式推理跳帧数", validation={"min": 1, "max": 30}),
    _definition("AI_RESET_MISSES", "ai", "连续未命中重置帧数", validation={"min": 1, "max": 600}),
    _definition("AI_COOLDOWN_SECONDS", "ai", "同一目标告警冷却时间 (秒)", validation={"min": 0, "max": 3600}),
    _definition("AI_SIMULATE_DETECTION", "ai", "是否启用模拟检测（仅调试）"),
    _definition("AI_SIMULATE_PROB", "ai", "模拟检测触发概率", validation={"min": 0, "max": 1}),
    _definition("AI_DEVICE", "ai", "推理设备（auto/cpu/cuda）"),
    _definition("AI_MODEL_PATH", "ai", "AI 模型文件路径"),
    _definition("AI_CONFIDENCE_THRESHOLD", "ai", "AI 检测置信度阈值", validation={"min": 0, "max": 1}),
    _definition("AI_USE_BYTETRACK", "ai", "是否启用 ByteTrack"),
    _definition("AI_PASSIVE_SESSION_DETECTION_ENABLED", "ai", "普通巡检时是否启用被动 AI 检测"),

    # 控制与硬件
    _definition("CONTROL_ADAPTER_TYPE", "control", "机器人控制适配器", validation={"options": ["simulation", "mavlink", "unitree_b2"]}),
    _definition("CONTROL_WATCHDOG_TIMEOUT_MS", "control", "控制命令看门狗超时 (ms)", validation={"min": 100, "max": 10000}),
    _definition("CONTROL_CMD_RATE_LIMIT_MS", "control", "控制命令最小间隔 (ms)", validation={"min": 0, "max": 5000}),
    _definition("UNITREE_B2_VX", "control", "宇树 B2 默认前进/后退速度 (m/s)", validation={"min": 0, "max": 0.6}),
    _definition("UNITREE_B2_VYAW", "control", "宇树 B2 默认偏航速度 (rad/s)", validation={"min": 0, "max": 0.8}),

    # 自动跟踪
    _definition("AI_STABLE_HITS", "auto_track", "锁定目标所需连续命中帧数", hot=True, validation={"min": 5, "max": 120}, key="auto_track_stable_hits"),
    _definition("AUTO_TRACK_ENABLED", "auto_track", "后端启动后是否默认启用自动跟踪", hot=True),
    _definition("AUTO_TRACK_OUT_OF_ZONE_FRAMES", "auto_track", "目标连续出区停止阈值", hot=True, validation={"min": 1, "max": 600}),
    _definition("AUTO_TRACK_LOST_TIMEOUT_FRAMES", "auto_track", "目标丢失超时帧数", hot=True, validation={"min": 1, "max": 1200}),
    _definition("AUTO_TRACK_VIDEO_LOST_GRACE_SECONDS", "auto_track", "视频短断宽限时间 (秒)", hot=True, validation={"min": 0, "max": 120}),
    _definition("AUTO_TRACK_OVERLAY_INTERVAL_SECONDS", "auto_track", "跟踪覆盖层广播间隔 (秒)", hot=True, validation={"min": 0.05, "max": 10}),
    _definition("AUTO_TRACK_COMMAND_INTERVAL_MS", "auto_track", "跟踪命令最小发送间隔 (ms)", hot=True, validation={"min": 0, "max": 5000}),
    _definition("AUTO_TRACK_YAW_DEADBAND_PX", "auto_track", "跟踪偏航死区 (像素)", hot=True, validation={"min": 0, "max": 1920}),
    _definition("AUTO_TRACK_FORWARD_AREA_RATIO", "auto_track", "停止前进的目标面积比例", hot=True, validation={"min": 0.01, "max": 1}),
    _definition("AUTO_TRACK_ANCHOR_Y_STOP_RATIO", "auto_track", "底部停止警戒线比例", hot=True, validation={"min": 0.1, "max": 1}),
    _definition("AUTO_TRACK_STOP_SNAPSHOT_ENABLED", "auto_track", "跟踪停止时是否保存快照", hot=True),
    _definition("AUTO_TRACK_YAW_PULSE_MS", "auto_track", "跟踪脉冲转向时长 (ms)", hot=True, validation={"min": 0, "max": 2000}),
    _definition("AUTO_TRACK_VX", "auto_track", "自动跟踪前进/后退速度 (m/s)", hot=True, validation={"min": 0, "max": 0.6}),
    _definition("AUTO_TRACK_VYAW", "auto_track", "自动跟踪偏航速度 (rad/s)", hot=True, validation={"min": 0, "max": 0.8}),

    # 驱离任务（服务持有部分初始化状态，除总开关外统一重启生效）
    _definition("GUARD_MISSION_ENABLED", "guard", "是否启用驱离任务", hot=True),
    _definition("GUARD_CONFIRM_TIME_S", "guard", "入侵确认时间 (秒)", validation={"min": 0, "max": 60}),
    _definition("GUARD_CLEAR_TIME_S", "guard", "区域清空确认时间 (秒)", validation={"min": 0, "max": 60}),
    _definition("GUARD_MIN_DURATION_S", "guard", "单次驱离最短持续时间 (秒)", validation={"min": 0, "max": 600}),
    _definition("GUARD_MAX_DURATION_S", "guard", "单次驱离最大持续时间 (秒)", validation={"min": 1, "max": 3600}),
    _definition("GUARD_COOLDOWN_S", "guard", "两次驱离之间的冷却时间 (秒)", validation={"min": 0, "max": 3600}),
    _definition("GUARD_DEPLOY_DURATION_S", "guard", "前往驱离点的动作时长 (秒)", validation={"min": 0, "max": 600}),
    _definition("GUARD_RETURN_DURATION_S", "guard", "返回起点的动作时长 (秒)", validation={"min": 0, "max": 600}),
    _definition("GUARD_DEPLOY_SETTLE_S", "guard", "出动前稳定等待时间 (秒)", validation={"min": 0, "max": 60}),
    _definition("GUARD_RETURN_SETTLE_S", "guard", "返航后稳定等待时间 (秒)", validation={"min": 0, "max": 60}),
    _definition("GUARD_ALERT_AUDIO_PATH", "guard", "驱离警告音频文件路径"),
    _definition("GUARD_CLEAR_MIN_CONF", "guard", "清空判定最低置信度", validation={"min": 0, "max": 1}),
    _definition("GUARD_CLEAR_MIN_AREA", "guard", "清空判定最小目标面积 (px)", validation={"min": 0, "max": 10000000}),
    _definition("GUARD_VISUAL_TIMEOUT_S", "guard", "视觉链路健康超时 (秒)", validation={"min": 0.1, "max": 120}),
    _definition("GUARD_ZONE_MEMORY_FRAMES", "guard", "区域丢失后位置记忆帧数", validation={"min": 0, "max": 1200}),
    _definition("GUARD_ZONE_LOST_RETURN_S", "guard", "区域丢失后触发返航时间 (秒)", validation={"min": 0, "max": 120}),
    _definition("GUARD_ANCHOR_MIN_QUALITY", "guard", "锚点跟踪最低质量", validation={"min": 0, "max": 1}),
    _definition("GUARD_ANCHOR_LOST_TIMEOUT_S", "guard", "锚点丢失超时 (秒)", validation={"min": 0, "max": 120}),
    _definition("GUARD_MAX_ADVANCE_TIME_S", "guard", "最大推进保护时间 (秒)", validation={"min": 0, "max": 600}),
    _definition("GUARD_MAX_VIEW_RATIO", "guard", "前进贴脸保护比例", validation={"min": 0.1, "max": 1}),
    _definition("GUARD_ZONE_EDGE_MARGIN_RATIO", "guard", "画面边缘安全裕量比例", validation={"min": 0, "max": 0.5}),
    _definition("GUARD_OVERLAP_CLEAR_RATIO", "guard", "人员离区重叠比例上限", validation={"min": 0, "max": 1}),
    _definition("GUARD_RETURN_POS_TOLERANCE_PX", "guard", "返航水平位置容差 (px)", validation={"min": 0, "max": 1920}),
    _definition("GUARD_RETURN_AREA_TOLERANCE_RATIO", "guard", "返航面积误差比例", validation={"min": 0, "max": 5}),
    _definition("GUARD_RETURN_STABLE_FRAMES", "guard", "返航完成稳定帧数", validation={"min": 1, "max": 1200}),
    _definition("GUARD_RETURN_AREA_STOP_RATIO", "guard", "返航面积停止阈值", validation={"min": 0, "max": 1}),
    _definition("GUARD_RETURN_AREA_STABLE_FRAMES", "guard", "返航面积稳定帧数", validation={"min": 1, "max": 1200}),
    _definition("GUARD_YAW_DEADBAND_PX", "guard", "驱离偏航死区 (px)", validation={"min": 0, "max": 1920}),
    _definition("GUARD_COMMAND_RATE_LIMIT_MS", "guard", "驱离命令最小间隔 (ms)", validation={"min": 0, "max": 5000}),
    _definition("GUARD_VX", "guard", "驱离前进/后退速度 (m/s)", validation={"min": 0, "max": 0.6}),
    _definition("GUARD_VYAW", "guard", "驱离偏航速度 (rad/s)", validation={"min": 0, "max": 0.8}),

    # 地图与导航
    _definition("PCD_MAP_ROOT", "navigation", "PCD 点云地图根目录"),
    _definition("SCENE_MAP_ROOT", "navigation", "场景地图根目录"),
    _definition("PCD_FRAME_ID", "navigation", "点云和导航点默认坐标系"),
    _definition("PCD_PREVIEW_DEFAULT_POINTS", "navigation", "点云预览默认点数", validation={"min": 1000, "max": 5000000}),
    _definition("PCD_PREVIEW_MAX_POINTS", "navigation", "点云预览最大点数", validation={"min": 1000, "max": 10000000}),
    _definition("PCD_SCENE_PREVIEW_VOXEL_SIZE_M", "navigation", "3D 场景体素边长 (m)", validation={"min": 0.01, "max": 2}),
    _definition("PCD_SCENE_PREVIEW_POINTS_PER_VOXEL", "navigation", "3D 场景每体素最大点数", validation={"min": 1, "max": 32}),
    _definition("PCD_SCENE_PREVIEW_CACHE_DIR", "navigation", "3D 场景预览缓存目录"),
    _definition("PCD_SCENE_PREVIEW_CACHE_MAX_ENTRIES", "navigation", "3D 场景预览缓存条目数", validation={"min": 1, "max": 32}),
    _definition("PCD_SCENE_TILE_CACHE_DIR", "navigation", "分层点云瓦片缓存目录"),
    _definition("PCD_SCENE_TILE_SIZE_M", "navigation", "点云空间瓦片边长 (m)", validation={"min": 1, "max": 32}),
    _definition("PCD_SCENE_TILE_BALANCED_VOXEL_SIZE_M", "navigation", "点云均衡档体素边长 (m)", validation={"min": 0.01, "max": 1}),
    _definition("PCD_SCENE_TILE_BALANCED_POINTS_PER_VOXEL", "navigation", "点云均衡档每体素最大点数", validation={"min": 1, "max": 16}),
    _definition("PCD_SCENE_TILE_PERFORMANCE_VOXEL_SIZE_M", "navigation", "点云流畅档体素边长 (m)", validation={"min": 0.01, "max": 1}),
    _definition("PCD_SCENE_TILE_PERFORMANCE_POINTS_PER_VOXEL", "navigation", "点云流畅档每体素最大点数", validation={"min": 1, "max": 16}),
    _definition("PCD_SCENE_TILE_MAX_POINTS", "navigation", "点云单文件拆分阈值（不丢点）", validation={"min": 4096, "max": 262144}),
    _definition("PCD_SCENE_TILE_ROOT_POINTS", "navigation", "点云首屏粗图点数", validation={"min": 10000, "max": 500000}),
    _definition("PCD_SCENE_TILE_BUILD_CHUNK_POINTS", "navigation", "点云瓦片构建分块点数", validation={"min": 50000, "max": 2000000}),
    _definition("PCD_SCENE_TILE_CACHE_MAX_SCENES", "navigation", "点云瓦片缓存场景数", validation={"min": 1, "max": 16}),
    _definition("PCD_SCENE_TILE_CACHE_MAX_BYTES", "navigation", "点云瓦片缓存最大字节数", validation={"min": 1073741824, "max": 107374182400}),
    _definition("NAV_WAYPOINT_STORE_DIR", "navigation", "导航点存储目录"),
    _definition("NAV_LOCALIZATION_STORE_DIR", "navigation", "定位初始化数据目录"),
    _definition("NAV_TASK_STORE_DIR", "navigation", "导航任务存储目录"),
    _definition("NAV_RUNTIME_DIR", "navigation", "导航运行时数据目录"),
    _definition("NAV_WAYPOINT_GROUND_SNAP_MAX_DISTANCE_M", "navigation", "导航点地面吸附最大距离 (m)", validation={"min": 0, "max": 20}),
    _definition("NAV_WAYPOINT_GROUND_SNAP_NEIGHBORS", "navigation", "导航点地面吸附邻点数", validation={"min": 1, "max": 1000}),
    _definition("NAV_LIDAR_MOUNT_X_M", "navigation", "雷达安装 X：雷达原点在 base_footprint 中的前后位置 (m)，保存后从下一次建图/定位启动生效", hot=True, validation={"min": -5, "max": 5}),
    _definition("NAV_LIDAR_MOUNT_Y_M", "navigation", "雷达安装 Y：雷达原点在 base_footprint 中的左右位置 (m)，保存后从下一次建图/定位启动生效", hot=True, validation={"min": -5, "max": 5}),
    _definition("NAV_LIDAR_MOUNT_Z_M", "navigation", "雷达安装高度：雷达原点距机器人地面原点的高度 (m)，用于让初始地面接近 Z=0", hot=True, validation={"min": 0, "max": 5}),
    _definition("NAV_LIDAR_MOUNT_ROLL_DEG", "navigation", "雷达安装横滚角 (deg)，以 base_footprint 为参考", hot=True, validation={"min": -180, "max": 180}),
    _definition("NAV_LIDAR_MOUNT_PITCH_DEG", "navigation", "雷达安装俯仰角 (deg)，正值表示朝前下倾；当前默认约 19.48°", hot=True, validation={"min": -180, "max": 180}),
    _definition("NAV_LIDAR_MOUNT_YAW_DEG", "navigation", "雷达安装偏航角 (deg)，以机器人正前方为 0°", hot=True, validation={"min": -180, "max": 180}),
    _definition("NAV_ORIGIN_WAYPOINT_Z", "navigation", "默认原点导航点 Z 坐标", validation={"min": -100, "max": 100}),
    _definition("NAV_ORIGIN_WAYPOINT_YAW", "navigation", "默认原点导航点朝向", validation={"min": -6.2832, "max": 6.2832}),
    _definition("NAV_AUTO_TRACK_DURING_NAV_ENABLED", "navigation", "导航执行中是否允许自动跟踪", hot=True),
    _definition("NAV_AUTO_TRACK_AUTO_ENABLE", "navigation", "导航任务开始时是否自动开启跟踪", hot=True),
    _definition("NAV_AUTO_TRACK_RESUME_TIMEOUT_S", "navigation", "跟踪结束后恢复导航等待时间 (秒)", hot=True, validation={"min": 0, "max": 60}),
    _definition("NAV_AUTO_TRACK_REQUIRE_FRESH_TF", "navigation", "恢复导航前是否要求最新 TF", hot=True),

    # ROS2 导航桥
    _definition("ROS_NAV_ENABLED", "ros", "是否启用 ROS2 导航桥"),
    _definition("ROS_NAV_POSE_TOPIC", "ros", "机器人位姿 Topic"),
    _definition("ROS_NAV_POSE_TYPE", "ros", "机器人位姿消息类型", validation={"options": ["TF", "PoseWithCovarianceStamped", "PoseStamped", "Odometry"]}),
    _definition("ROS_NAV_FRAME_ID", "ros", "地图目标坐标系"),
    _definition("ROS_NAV_BASE_FRAME_ID", "ros", "机器人本体坐标系"),
    _definition("ROS_NAV_TF_MAX_AGE_SECONDS", "ros", "TF 最大允许延迟 (秒)", validation={"min": 0, "max": 60}),
    _definition("ROS_NAV_TF_WARNING_INTERVAL_SECONDS", "ros", "TF 告警输出间隔 (秒)", validation={"min": 1, "max": 3600}),
    _definition("ROS_NAV_BROADCAST_HZ", "ros", "导航位姿广播频率 (Hz)", validation={"min": 0.1, "max": 120}),
    _definition("ROS_NAV_PAGE_OPEN_TOPIC", "ros", "导航页面打开信号 Topic"),
    _definition("ROS_NAV_START_TOPIC", "ros", "导航启动 Topic"),
    _definition("ROS_NAV_TASK_START_TOPIC", "ros", "导航任务启动 Topic"),
    _definition("ROS_NAV_GOAL_TOPIC", "ros", "兼容导航目标 Topic"),
    _definition("ROS_NAV_GOAL_XYZ_TOPIC", "ros", "导航目标坐标 Topic"),
    _definition("ROS_NAV_GOAL_YAW_TOPIC", "ros", "导航目标朝向 Topic"),
    _definition("ROS_NAV_GOAL_Z_SEARCH_OFFSET_M", "ros", "规划目标 Z 搜索偏移 (m)", validation={"min": -10, "max": 10}),
    _definition("ROS_NAV_GLOBAL_PATH_TOPIC", "ros", "全局规划路径 Topic"),
    _definition("ROS_NAV_EXECUTION_PATH_TOPIC", "ros", "任务执行路径 Topic"),
    _definition("ROS_NAV_STOP_TOPIC", "ros", "导航停止 Topic"),
    _definition("ROS_NAV_INITIAL_POSE_TOPIC", "ros", "初始位姿 Topic"),
    _definition("ROS_NAV_MAPPING_CLOUD_FORWARD_ENABLED", "ros", "是否转发建图实时点云"),
    _definition("ROS_NAV_MAPPING_CLOUD_TOPIC", "ros", "建图实时点云 Topic"),
    _definition("ROS_NAV_MAPPING_TOPIC", "ros", "建图开关 Topic"),
    _definition("ROS_NAV_STATUS_TOPIC", "ros", "导航状态 Topic"),

    # 文件存储
    _definition("SNAPSHOT_DIR", "storage", "抓拍图片存储目录"),
    _definition("RECORDING_DIR", "storage", "录像文件存储目录"),
]


OPERATIONAL_CONFIGS: dict[str, dict[str, Any]] = dict(_SPECS)


def config_setting_name(key: str, definition: dict[str, Any] | None = None) -> str | None:
    if definition and definition.get("setting"):
        return str(definition["setting"])
    candidate = key.upper()
    return candidate if hasattr(settings, candidate) else None


def coerce_setting_value(setting_name: str, value: Any) -> Any:
    current = getattr(settings, setting_name)
    if isinstance(current, bool):
        normalized = str(value).strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"布尔值无效: {value}")
    if isinstance(current, int):
        return int(value)
    if isinstance(current, float):
        return float(value)
    return str(value)


def serialize_setting_value(setting_name: str) -> str:
    return _serialize(getattr(settings, setting_name))
