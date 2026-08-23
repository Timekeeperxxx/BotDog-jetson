"""
配置中心。

职责边界：
- 将 `.env` / 环境变量 与 代码中的默认值解耦；
- 为其他模块提供类型安全的 Settings 对象（单例）。
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AnyUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    全局配置，结合 `.env` 与文档 `09_config_matrix.md`、`06_backend_protocol_schema.md`。

    注意：
    - 仅放“真正需要全局”的配置项，避免无节制膨胀；
    - 可与数据库中的 `config` 表组合，实现“默认值在代码、运行值在 DB”的模式。
    """

    # 基础网络配置
    BACKEND_HOST: str = '0.0.0.0'
    BACKEND_PORT: int = 8000

    # MAVLink / 数据库
    MAVLINK_ENDPOINT: str = 'udp:127.0.0.1:14550'
    DATABASE_URL: AnyUrl | str = 'sqlite+aiosqlite:///./data/botdog.db'

    # 安全配置
    JWT_SECRET: str = 'please_change_me_to_a_random_string'
    AUTH_ENABLED: bool = True
    AUTH_ADMIN_USERNAME: str = 'admin'
    AUTH_ADMIN_PASSWORD: str = 'admin123'
    JWT_EXPIRE_MINUTES: int = 720

    # CORS 配置
    CORS_ALLOW_ORIGINS: list[str] = ['*']
    CORS_ALLOW_CREDENTIALS: bool = False

    # 运行日志：Python 日志由 Loguru 轮转，外部进程日志由 logrotate 管理。
    LOG_CONSOLE_LEVEL: str = "INFO"
    LOG_ROTATION_SIZE_MB: int = 20
    LOG_RETENTION_DAYS: int = 14
    LOG_COMPRESSION: str = "zip"

    # 本地模拟数据 Worker 控制（默认保持当前启用行为）
    SIMULATION_WORKER_ENABLED: bool = True

    # MAVLink 数据源选择（mavlink|simulation）
    # - mavlink: 使用真实 MAVLink 端口
    # - simulation: 使用模拟数据生成器
    MAVLINK_SOURCE: str = 'simulation'

    # 配置矩阵中的关键参数（只列当前阶段会用到的）
    HEARTBEAT_TIMEOUT: float = 3.0  # heartbeat_timeout
    TELEMETRY_SAMPLING_HZ: float = 2.0  # 遥测落盘采样频率（Hz）
    TELEMETRY_BROADCAST_HZ: float = 15.0  # 遥测广播频率（Hz）

    # 阶段 4：AI 告警配置
    THERMAL_THRESHOLD: float = 80.0  # 温度阈值（°C）

    # 阶段 5：旁路 AI 识别与抓拍
    AI_ENABLED: bool = True
    AI_RTSP_URL: str = 'rtsp://127.0.0.1:8554/cam'
    # AI 备用 RTSP 地址，逗号分隔；默认不拉原始摄像头，避免源端被多客户端并发拉流拖慢。
    AI_RTSP_FALLBACK_URLS: str = ''
    AI_FRAME_WIDTH: int = 640
    AI_FRAME_HEIGHT: int = 360
    AI_FPS: int = 5
    AI_INFERENCE_IMGSZ: int = 640
    AI_FFMPEG_RETRY_MIN_SECONDS: float = 1.0
    AI_FFMPEG_RETRY_MAX_SECONDS: float = 3.0
    # FFmpeg 正常软件解码 640x360 RTSP 时常驻内存远低于此值；超过上限说明
    # 解码/滤镜输出发生异常积压，主动重拉流，避免挤占导航所需内存。
    AI_FFMPEG_MAX_RSS_MB: int = 512
    AI_FFMPEG_MEMORY_CHECK_INTERVAL_SECONDS: float = 1.0
    # 单帧 AI 处理超时保护。YOLO/TensorRT/CUDA 偶发卡死时，线程无法被 Python 安全杀掉；
    # 默认让后端失败退出，交给 systemd Restart=on-failure 自动重启，避免 AI 帧永久停住。
    AI_FRAME_PROCESS_TIMEOUT_SECONDS: float = 15.0
    AI_EXIT_ON_FRAME_TIMEOUT: bool = True
    AI_EVENT_SEND_TIMEOUT_SECONDS: float = 0.03
    AI_MAX_FRAME_AGE_SECONDS: float = 0.35
    AI_PATROL_SKIP: int = 1  # 巡逻态不跳帧；5fps 相机每帧检测以降低框延迟
    AI_AUTO_TRACK_SKIP: int = 1  # 自动跟踪启用时全速检测，提高锁定/重发现稳定性
    AI_SUSPECT_SKIP: int = 1  # 疑似目标全速推理
    # 目标检测与姿态模型完成首次顺序预热后并发推理，缩短同一帧总处理时间。
    AI_PARALLEL_INFERENCE_ENABLED: bool = True
    AI_STABLE_HITS: int = 5  # 连续命中阈值
    AI_RESET_MISSES: int = 20  # 连续未命中重置阈值
    AI_COOLDOWN_SECONDS: float = 5.0  # 冷却时间
    AI_SIMULATE_DETECTION: bool = False
    AI_SIMULATE_PROB: float = 0.02
    AI_DEVICE: str = 'auto'  # auto / cpu / cuda / cuda:0
    AI_MODEL_PATH: str = '/home/jetson/Projects/Models/helmet.engine'  # YOLO 模型路径
    AI_CONFIDENCE_THRESHOLD: float = 0.4  # 推理置信度阈值
    AI_TARGET_CLASSES: list[str] = ['person', 'head', 'helmet']  # 目标类别
    AI_USE_BYTETRACK: bool = False
    # 独立于巡检任务和自动跟踪，持续进行只读视觉分析；不会下发机器人运动命令。
    AI_CONTINUOUS_DETECTION_ENABLED: bool = False
    # 是否在普通巡检/session 运行时启用旧的被动 AI 告警。
    # 关闭后，AI 只在自动跟踪或驱离模式需要视觉结果时拉流推理，避免抢占主视频链路。
    AI_PASSIVE_SESSION_DETECTION_ENABLED: bool = True

    # 独立武器检测支路：复用 AI Worker 已解码的同一帧，不额外拉取 RTSP。
    # 巡逻时按 WEAPON_FRAME_SKIP 低频推理；一旦命中，在短暂活跃窗口内逐帧复核。
    WEAPON_ENABLED: bool = False
    WEAPON_MODEL_PATH: str = (
        '/home/jetson/Projects/Models/weapon-domain-v13-yolo26x-800-best.engine'
    )
    WEAPON_DEVICE: str = 'auto'
    WEAPON_INFERENCE_IMGSZ: int = 640
    WEAPON_CONFIDENCE_THRESHOLD: float = 0.25
    WEAPON_TARGET_CLASSES: list[str] = ['guns', 'knife']
    WEAPON_FRAME_SKIP: int = 3
    WEAPON_ACTIVE_SECONDS: float = 3.0
    WEAPON_STABLE_HITS: int = 5
    WEAPON_CONFIRM_IOU_THRESHOLD: float = 0.4
    WEAPON_REQUIRE_PERSON_ASSOCIATION: bool = True
    WEAPON_PERSON_EXPAND_RATIO: float = 0.35
    # 可选两阶段模式：先用主模型获得人员框，再在人员区域内放大检测刀枪。
    WEAPON_PERSON_CROP_ENABLED: bool = True
    WEAPON_PERSON_CROP_EXPAND_RATIO: float = 0.35
    WEAPON_PERSON_CROP_MAX_REGIONS: int = 2
    WEAPON_PERSON_CROP_NMS_IOU: float = 0.5
    # 携带刀枪场景默认不接受无人关联候选；设为 <1.0 可显式开启高置信度例外。
    WEAPON_UNATTENDED_CONFIDENCE_THRESHOLD: float = 1.0
    # 过滤覆盖画面过大的异常框（键盘、桌面等常见全幅误报）。
    WEAPON_MAX_FRAME_AREA_RATIO: float = 0.35
    WEAPON_ALERT_COOLDOWN_SECONDS: float = 60.0

    # 天气分类支路：复用 AI Worker 已解码的可见光帧，不创建第二条 RTSP。
    # 当前产品类别为 normal/rain/snow/sandstorm；雷达融合状态会在接口中明确标记。
    WEATHER_ENABLED: bool = False
    WEATHER_MODEL_PATH: str = (
        '/home/jetson/Projects/Models/weather_types_image_detection/'
        'weather_types_vit_4class_wedge_bdd_v2_fp16.engine'
    )
    WEATHER_DEVICE: str = 'auto'
    WEATHER_USE_FP16: bool = True
    WEATHER_INTERVAL_SECONDS: float = 3.0
    WEATHER_CONFIDENCE_THRESHOLD: float = 0.55
    WEATHER_SMOOTHING_WINDOW: int = 5
    WEATHER_STABLE_VOTES: int = 3

    # 姿态检测支路：COCO 17 点骨架 + 轻量时序状态机。
    POSE_ENABLED: bool = False
    POSE_MODEL_PATH: str = '/home/jetson/Projects/Models/yolo11n-pose.engine'
    POSE_DEVICE: str = 'auto'
    POSE_INFERENCE_IMGSZ: int = 640
    POSE_CONFIDENCE_THRESHOLD: float = 0.35
    POSE_KEYPOINT_CONFIDENCE: float = 0.35
    POSE_MIN_VISIBLE_KEYPOINTS: int = 5
    # 按 AI Worker 实际处理的帧计数，而不是摄像头原始帧号计数。
    # 5 FPS 主检测下每 2 帧运行一次姿态模型，人员框仍由主检测逐帧更新。
    POSE_FRAME_SKIP: int = 2
    POSE_STABLE_HITS: int = 3
    POSE_CROUCH_SECONDS: float = 4.0
    POSE_LOITER_SECONDS: float = 20.0
    POSE_EVENT_COOLDOWN_SECONDS: float = 15.0
    POSE_TRACK_TTL_SECONDS: float = 3.0
    POSE_OVERLAY_INTERVAL_SECONDS: float = 0.2

    # 人脸身份：SCRFD/YuNet 检测 + OpenCV SFace 特征；未匹配默认未授权。
    FACE_RECOGNITION_ENABLED: bool = True
    FACE_DETECT_BACKEND: Literal['yunet', 'scrfd_tensorrt'] = 'scrfd_tensorrt'
    FACE_DETECT_MODEL_PATH: str = '/home/jetson/Projects/Models/face_detection_scrfd_10g_640_fp16.engine'
    FACE_RECOGNITION_MODEL_PATH: str = '/home/jetson/Projects/Models/face_recognition_sface_2021dec.onnx'
    FACE_DETECT_INPUT_SIZE: int = 640
    FACE_DETECT_NMS_THRESHOLD: float = 0.40
    FACE_DETECT_THRESHOLD: float = 0.50
    # 后台注册照片允许稍低阈值；只用于人工上传，不影响实时视频检测。
    FACE_ENROLL_DETECT_THRESHOLD: float = 0.40
    FACE_MATCH_THRESHOLD: float = 0.45
    FACE_FRAME_SKIP: int = 2
    FACE_CONFIRM_HITS: int = 3
    FACE_TRACK_TTL_SECONDS: float = 2.0
    FACE_MIN_SIZE_PX: int = 64
    FACE_MAX_UPLOAD_BYTES: int = 8 * 1024 * 1024
    FACE_MAX_IMAGE_PIXELS: int = 12_000_000
    FACE_MAX_TEMPLATES_PER_IDENTITY: int = 5

    # 抓拍存储目录（用于 /api/v1/static）
    SNAPSHOT_DIR: str = 'data/snapshots'

    # 录像存储目录（用于 /api/v1/static/recordings）
    RECORDING_DIR: str = "data/recordings"

    # 先飞 Z2-Mini 云台私有协议（TCP Server）。
    Z2MINI_HOST: str = "192.168.123.108"
    Z2MINI_CONTROL_PORT: int = 2332
    Z2MINI_TIMEOUT_SECONDS: float = 2.0
    Z2MINI_JOG_SECONDS: float = 0.45
    Z2MINI_DEFAULT_PICTURE_MODE: Literal["visible", "thermal"] = "visible"

    # 自动围栏检测。检测阈值集中在这里；水平瞄准不依赖围栏高度。
    # 安装关系默认采用现场确认值，图像几何优先复用现有画面尺寸/FOV/实时变焦。
    FENCE_DETECTION_MAX_DISTANCE_M: float = 20.0
    FENCE_WARNING_DISTANCE_M: float = 2.0
    FENCE_DWELL_SECONDS: float = 10.0
    FENCE_NEAR_STABLE_FRAMES: int = 3
    FENCE_CONTACT_SEGMENT_MARGIN_M: float = 0.25
    FENCE_CONTACT_STABLE_FRAMES: int = 3
    FENCE_CROSS_MARGIN_M: float = 0.25
    FENCE_CROSS_STABLE_FRAMES: int = 3
    FENCE_CROSS_REQUIRE_CLIMBING_POSTURE: bool = True
    FENCE_KEYPOINT_CONFIDENCE: float = 0.35
    # 破坏围栏不由单帧接触触发：先在滑动窗口内检测手腕往复运动，
    # 再对人工绘制的地图围栏投影区进行结构变化复核。
    FENCE_TAMPER_ENABLED: bool = True
    FENCE_TAMPER_WINDOW_SECONDS: float = 2.4
    FENCE_TAMPER_MIN_DURATION_SECONDS: float = 1.0
    FENCE_TAMPER_MIN_TRAVEL_RATIO: float = 0.30
    FENCE_TAMPER_MIN_REVERSALS: int = 2
    FENCE_TAMPER_ACTION_SCORE_THRESHOLD: float = 0.75
    FENCE_TAMPER_STABLE_FRAMES: int = 2
    FENCE_TAMPER_STRUCTURE_ENABLED: bool = True
    FENCE_TAMPER_STRUCTURE_HEIGHT_M: float = 2.0
    FENCE_TAMPER_STRUCTURE_PATCH_RATIO: float = 0.45
    FENCE_TAMPER_STRUCTURE_CHANGE_THRESHOLD: float = 0.18
    FENCE_TAMPER_STRUCTURE_STABLE_FRAMES: int = 2
    FENCE_TAMPER_STRUCTURE_MIN_EDGE_PIXELS: int = 80
    FENCE_TAMPER_REFERENCE_CLEAR_FRAMES: int = 3
    FENCE_TAMPER_CONFIRM_GRACE_SECONDS: float = 5.0
    FENCE_TAMPER_ALIGN_MAX_SHIFT_PX: float = 16.0
    FENCE_TRACK_TTL_SECONDS: float = 2.0
    FENCE_ALERT_COOLDOWN_SECONDS: float = 15.0
    FENCE_CONTROL_HZ: float = 5.0
    FENCE_GIMBAL_YAW_DEADBAND_DEG: float = 0.8
    FENCE_GIMBAL_SMOOTHING_ALPHA: float = 0.35
    FENCE_GIMBAL_MAX_SPEED_DPS: float = 20.0
    FENCE_GIMBAL_SETTLE_ERROR_DEG: float = 1.5
    FENCE_GIMBAL_SETTLE_VELOCITY_DPS: float = 1.0
    FENCE_GIMBAL_SETTLE_SECONDS: float = 0.6
    FENCE_SWITCH_DELAY_SECONDS: float = 1.5
    FENCE_FRAME_SAMPLE_TOLERANCE_SECONDS: float = 0.6
    FENCE_GIMBAL_MIN_YAW_DEG: float = -170.0
    FENCE_GIMBAL_MAX_YAW_DEG: float = 170.0
    # 平移为空时直接复用 NAV_LIDAR_MOUNT_X/Y/Z；用户确认云台和相机
    # 安装姿态均朝向 base_footprint 正前方，因此安装角和相机偏移默认 0。
    FENCE_GIMBAL_MOUNT_X_M: float | None = None
    FENCE_GIMBAL_MOUNT_Y_M: float | None = None
    FENCE_GIMBAL_MOUNT_Z_M: float | None = None
    FENCE_GIMBAL_MOUNT_ROLL_DEG: float = 0.0
    FENCE_GIMBAL_MOUNT_PITCH_DEG: float = 0.0
    FENCE_GIMBAL_MOUNT_YAW_DEG: float = 0.0
    # Z2-Mini 已有控制代码确认相对 yaw 正值朝机器狗右侧；地图 y 正值朝左。
    FENCE_GIMBAL_YAW_SIGN: float = -1.0
    FENCE_GIMBAL_PITCH_SIGN: float = 1.0
    FENCE_CAMERA_OFFSET_X_M: float = 0.0
    FENCE_CAMERA_OFFSET_Y_M: float = 0.0
    FENCE_CAMERA_OFFSET_Z_M: float = 0.0
    FENCE_CAMERA_ROLL_DEG: float = 0.0
    FENCE_CAMERA_PITCH_DEG: float = 0.0
    FENCE_CAMERA_YAW_DEG: float = 0.0
    # 内参为空时根据 AI_FRAME_WIDTH/HEIGHT、现有自动跟踪水平 FOV 和
    # Z2-Mini 实时 zoom 推导；实机标定值仍可在这里覆盖。
    FENCE_CAMERA_FX_PX: float | None = None
    FENCE_CAMERA_FY_PX: float | None = None
    FENCE_CAMERA_CX_PX: float | None = None
    FENCE_CAMERA_CY_PX: float | None = None
    FENCE_CAMERA_CALIBRATED_ZOOM_RATIO: float | None = None

    # 雷达、可见光、热成像近似时间同步与三维目标融合。
    # 默认关闭，必须先写入完整标定文件并确认三路设备时间来自同一时钟域。
    MULTISENSOR_ENABLED: bool = False
    MULTISENSOR_CALIBRATION_PATH: str = "./data/multisensor_calibration.json"
    MULTISENSOR_SYNC_TOLERANCE_MS: float = 80.0
    MULTISENSOR_SAMPLE_MAX_AGE_SECONDS: float = 2.0
    MULTISENSOR_QUEUE_SIZE: int = 30
    # 原始 Livox CustomMsg，而不是已变换到 map 的 /lio/cloud_world。
    MULTISENSOR_LIDAR_TOPIC: str = "/livox/lidar"
    MULTISENSOR_LIDAR_MAX_POINTS: int = 20000
    MULTISENSOR_MIN_TARGET_POINTS: int = 5
    MULTISENSOR_CLUSTER_GAP_M: float = 0.35
    # 当前版本只在标定云台姿态附近输出坐标，避免把静态外参误用于转动后的相机。
    MULTISENSOR_GIMBAL_TOLERANCE_DEG: float = 1.0
    MULTISENSOR_ZOOM_TOLERANCE_RATIO: float = 0.02
    MULTISENSOR_GIMBAL_POLL_HZ: float = 2.0

    # ==================== 导航巡逻 / PCD 点云地图 Demo ====================
    PCD_MAP_ROOT: str = '/home/jetson/superlio/Super-LIO/src/super_lio/map'
    SCENE_MAP_ROOT: str = '/home/jetson/Projects/Maps'
    PCD_FRAME_ID: str = 'map'
    PCD_PREVIEW_DEFAULT_POINTS: int = 100000
    PCD_PREVIEW_MAX_POINTS: int = 200000
    # 主 3D 场景采用空间密度约束，而不是整图点数上限。
    PCD_SCENE_PREVIEW_VOXEL_SIZE_M: float = 0.15
    PCD_SCENE_PREVIEW_POINTS_PER_VOXEL: int = 2
    PCD_SCENE_PREVIEW_CACHE_DIR: str = './data/pcd_scene_preview_cache'
    PCD_SCENE_PREVIEW_CACHE_MAX_ENTRIES: int = 4
    # Jetson 友好的分层点云缓存。源点云只在缓存构建阶段顺序扫描，
    # 页面运行时仅按视野读取几十 KB 到数 MB 的瓦片。
    PCD_SCENE_TILE_CACHE_DIR: str = './data/pcd_scene_tile_cache'
    PCD_SCENE_TILE_SIZE_M: float = 16.0
    PCD_SCENE_TILE_BALANCED_VOXEL_SIZE_M: float = 0.07
    PCD_SCENE_TILE_BALANCED_POINTS_PER_VOXEL: int = 1
    PCD_SCENE_TILE_PERFORMANCE_VOXEL_SIZE_M: float = 0.10
    PCD_SCENE_TILE_PERFORMANCE_POINTS_PER_VOXEL: int = 1
    PCD_SCENE_TILE_MAX_POINTS: int = 65536
    PCD_SCENE_TILE_ROOT_POINTS: int = 160000
    PCD_SCENE_TILE_BUILD_CHUNK_POINTS: int = 400000
    PCD_SCENE_TILE_CACHE_MAX_SCENES: int = 2
    PCD_SCENE_TILE_CACHE_MAX_BYTES: int = 12 * 1024 * 1024 * 1024
    NAV_WAYPOINT_STORE_DIR: str = './data/nav_waypoints'
    NAV_FENCE_STORE_DIR: str = './data/nav_fences'
    NAV_LOCALIZATION_STORE_DIR: str = './data/nav_localization'
    NAV_RUNTIME_DIR: str = './data/nav_runtime'
    NAV_TASK_STORE_DIR: str = './data/nav_tasks'
    NAV_WAYPOINT_GROUND_SNAP_MAX_DISTANCE_M: float = 1.0
    NAV_WAYPOINT_GROUND_SNAP_NEIGHBORS: int = 24
    # 雷达在机器人 base_footprint 坐标系中的安装位姿（T_base_footprint_lidar）。
    # 平移单位为米，姿态单位为度；俯仰角为正表示雷达朝前下倾。
    # 建图和定位启动时会同时用于 LIO odom_robo 与 base_link -> base_footprint TF。
    # The Mid360 is mounted about 0.425 m ahead of B2's planar rotation
    # centre.  Keeping this at zero puts base_footprint below the sensor and
    # makes an in-place body turn look like a large XY translation.
    NAV_LIDAR_MOUNT_X_M: float = 0.425
    NAV_LIDAR_MOUNT_Y_M: float = 0.0
    NAV_LIDAR_MOUNT_Z_M: float = 0.90
    NAV_LIDAR_MOUNT_ROLL_DEG: float = 0.0
    NAV_LIDAR_MOUNT_PITCH_DEG: float = 19.48
    NAV_LIDAR_MOUNT_YAW_DEG: float = 0.0
    # 建图保存成功后自动创建/更新“原点”导航点。
    # 优先使用建图启动后捕获到的初始 TF/位姿；读不到时用这里的 z/yaw 兜底。
    NAV_ORIGIN_WAYPOINT_Z: float = -0.83
    NAV_ORIGIN_WAYPOINT_YAW: float = 0.0
    NAV_AUTO_TRACK_DURING_NAV_ENABLED: bool = False
    NAV_AUTO_TRACK_AUTO_ENABLE: bool = False
    NAV_AUTO_TRACK_RESUME_TIMEOUT_S: float = 3.0
    NAV_AUTO_TRACK_REQUIRE_FRESH_TF: bool = True
    NAV_CONTROL_GATEWAY_ENABLED: bool = True

    # ==================== ROS2 导航状态订阅转发 ====================
    ROS_NAV_ENABLED: bool = True
    ROS_NAV_POSE_TOPIC: str = '/amcl_pose'
    ROS_NAV_POSE_TYPE: str = 'TF'
    ROS_NAV_FRAME_ID: str = 'map'
    ROS_NAV_BASE_FRAME_ID: str = 'base_footprint'
    # Reject cached TF transforms whose ROS timestamp no longer advances.
    ROS_NAV_TF_MAX_AGE_SECONDS: float = 3.0
    ROS_NAV_TF_WARNING_INTERVAL_SECONDS: float = 300.0
    ROS_NAV_BROADCAST_HZ: float = 10.0
    ROS_NAV_PAGE_OPEN_TOPIC: str = '/lidar_start'
    ROS_NAV_START_TOPIC: str = '/nav_start'
    # /nav_start is the inspection-task execution gate. A single go-to is
    # replaced directly by a fresh clicked_point + goal_yaw and never toggles it.
    ROS_NAV_TASK_START_TOPIC: str = '/nav_task_start'
    ROS_NAV_AUTO_TRACK_CONTROL_TOPIC: str = '/nav/task/auto_track_control'
    ROS_NAV_GOAL_TOPIC: str = '/goal_pose'
    ROS_NAV_GOAL_XYZ_TOPIC: str = '/clicked_point'
    ROS_NAV_GOAL_YAW_TOPIC: str = 'goal_yaw'
    # global_planner 对 clicked_point 做 3D 半径搜索。单点目标必须携带导航点
    # 保存的显式同层 ground z；缺失/非有限 z 会被拒绝，绝不默认成 0。
    ROS_NAV_GOAL_Z_SEARCH_OFFSET_M: float = 0.0
    ROS_NAV_GLOBAL_PATH_TOPIC: str = '/global_path'
    ROS_NAV_EXECUTION_PATH_TOPIC: str = '/scan/execution_path'
    ROS_NAV_STOP_TOPIC: str = '/nav_stop'
    ROS_NAV_INITIAL_POSE_TOPIC: str = '/initialpose'
    ROS_NAV_MAPPING_CLOUD_FORWARD_ENABLED: bool = True
    ROS_NAV_MAPPING_CLOUD_TOPIC: str = '/lio/cloud_world'
    ROS_NAV_MAPPING_TOPIC: str = '/mapping_start'
    ROS_NAV_STATUS_TOPIC: str = '/nav_status'
    # global_planner 的逐代规划状态（queued/planning/path_ready/failed/rejected）。
    # elapsed_seconds 仅用于展示；BotDog 不据此设置规划超时。
    ROS_NAV_PLANNING_STATUS_TOPIC: str = '/nav/planning_status'
    # 动态避障监控器的状态 topic；持续阻断超过阈值秒数后推送 ALERT_RAISED。
    ROS_NAV_OBSTACLE_STATUS_TOPIC: str = '/nav/obstacle_status'
    NAV_OBSTACLE_ALERT_SECONDS: float = 15.0
    # SCAN 当前会在原目标内持续局部重规划，不会因短时失败丢弃目标。
    # 应用层重发同一 goal 会创建新规划代次、暂时解除旧代次的 safety hold，
    # 实机表现为被挡后反复启停和左右摇摆，因此默认禁止自动重发。
    NAV_OBSTACLE_AUTO_REGOAL_ENABLED: bool = False
    NAV_OBSTACLE_REGOAL_SECONDS: float = 25.0
    NAV_OBSTACLE_REGOAL_COOLDOWN_SECONDS: float = 30.0
    NAV_OBSTACLE_REGOAL_MAX_ATTEMPTS: int = 3

    # 阶段 6：网页控制服务配置
    # 适配器类型：simulation（仅打印日志）| mavlink（真实硬件）
    CONTROL_ADAPTER_TYPE: str = 'unitree_b2'
    # Watchdog 超时（ms）：超过此时间未收到命令自动执行 stop
    CONTROL_WATCHDOG_TIMEOUT_MS: int = 1500
    # 最小命令间隔（ms）：防止前端过快发命令（stop 命令跳过此限制）
    CONTROL_CMD_RATE_LIMIT_MS: int = 50
    # SafetySupervisor 是否在底层 DISCONNECTED 时阻止运动命令。
    # 开发调试可设为 false，真机部署建议保持 true。
    SAFETY_BLOCK_MOTION_WHEN_DISCONNECTED: bool = True

    # ==================== 黄色区域识别参数 ====================
    # HSV 色调范围（OpenCV H: 0-180，纯黄约 25-35）
    ZONE_YELLOW_H_LOW: int = 14
    ZONE_YELLOW_H_HIGH: int = 42
    # 饱和度范围（越高越排除灰白色）
    ZONE_YELLOW_S_LOW: int = 25
    ZONE_YELLOW_S_HIGH: int = 220
    # 亮度范围（越高越排除暗色/阴影）
    ZONE_YELLOW_V_LOW: int = 95
    ZONE_YELLOW_V_HIGH: int = 255
    # 黑边验证：外扩环形区域 V 通道 10th percentile 低于此值才算有黑边
    ZONE_BORDER_V_THRESHOLD: int = 70
    # 外扩采样像素宽度（只采紧邻黄色区域的黑边本身，不延伸到地毯）
    ZONE_BORDER_EXPAND_PX: int = 1
    # 面积约束
    ZONE_MIN_AREA_PX: int = 600
    ZONE_MAX_AREA_RATIO: float = 0.25
    # 形状约束
    ZONE_MIN_ASPECT: float = 1.5
    ZONE_MAX_ASPECT: float = 30.0
    ZONE_MIN_SOLIDITY: float = 0.45
    # ROI：跳过画面顶部此比例，只处理含地面的下部（0.35 = 跳过顶 35%）
    ZONE_ROI_TOP_RATIO: float = 0.55
    # 形态学核大小（越大填孔越强，也越慢）
    ZONE_MORPH_KERNEL_SIZE: int = 32
    # quality 权重（三者之和建议为 1.0）
    ZONE_W_AREA: float = 0.25
    ZONE_W_SOLID: float = 0.2
    ZONE_W_BORDER: float = 0.55
    # 中心黑色汉字检测：中心区裁剪比例（0.5 = 取四边形内接矩形的中心 50% 面积）
    ZONE_CENTER_CROP_RATIO: float = 0.55
    # 汉字像素暗度阈值：V 通道低于此值才算黑色像素
    ZONE_CENTER_BLACK_V_THRESHOLD: int = 85
    # 中心区内暗像素占比下限，超过此比例认为有汉字
    ZONE_CENTER_BLACK_MIN_RATIO: float = 0.08
    # 检测到汉字时的 quality 奖励分（叠加在 0-1 质量分之上）
    ZONE_CENTER_TEXT_BONUS: float = 0.2

    # ==================== Canvas 区域绘制配置 ====================
    ZONE_DRAW_SAVED_FILL_RGBA: str = "rgba(220,40,40,0.18)"
    ZONE_DRAW_SAVED_STROKE_RGBA: str = "rgba(255,60,60,0.75)"
    ZONE_DRAW_SAVED_LINE_WIDTH: float = 1.5
    ZONE_DRAW_ACTIVE_STROKE_RGBA: str = "rgba(0,255,120,0.85)"
    ZONE_DRAW_ACTIVE_LINE_WIDTH: float = 1.5
    ZONE_DRAW_POINT_RADIUS: int = 4
    ZONE_DRAW_DASH_ON: int = 5
    ZONE_DRAW_DASH_OFF: int = 4
    ZONE_DRAW_TOOLBAR_BOTTOM_PX: int = 140
    ZONE_DRAW_CANVAS_Z_INDEX: int = 5
    ZONE_DRAW_TOOLBAR_Z_INDEX: int = 50

    # 驱离任务配置
    GUARD_MISSION_ENABLED: bool = False
    GUARD_CONFIRM_TIME_S: float = 1.5           # 入侵确认时间（秒）
    GUARD_CLEAR_TIME_S: float = 3.0             # 清空确认时间（秒）
    GUARD_MIN_DURATION_S: float = 3.0           # 最短驱离持续时间
    GUARD_DEPLOY_DURATION_S: float = 10.0       # 前往驱离点的前进时间（秒），独立于返回时长
    GUARD_RETURN_DURATION_S: float = 10.0       # 返回起点的后退时间（秒），独立于前往时长
    GUARD_COOLDOWN_S: float = 5.0             # 两次出动间的冷却时间
    GUARD_MAX_DURATION_S: float = 120.0        # 单次驱离最大持续时间
    GUARD_DEPLOY_SETTLE_S: float = 2.0         # 起立后稳定等待时间
    GUARD_RETURN_SETTLE_S: float = 2.0         # 蹲坐后稳定等待时间
    GUARD_ALERT_AUDIO_PATH: str = 'assets/13282.wav'   # 警告音频文件路径
    GUARD_CLEAR_MIN_CONF: float = 0.4          # 清空判定最小有效置信度
    GUARD_CLEAR_MIN_AREA: int = 2000           # 清空判定最小有效目标面积（px）
    GUARD_VISUAL_TIMEOUT_S: float = 5.0        # 视觉链路健康超时（秒）
    GUARD_ZONE_MEMORY_FRAMES: int = 20         # 区域丢失后最多复用上次位置的帧数（应对人站上去遮挡）
    GUARD_ZONE_LOST_RETURN_S: float = 3.0     # ADVANCING 中区域彻底看不到超过此秒数直接返航

    
    # ==== 新增：视觉伺服 / 锚点跟踪配置 ====
    GUARD_ANCHOR_MIN_QUALITY: float = 0.6        # 锚点跟踪最小稳定质量限度（部分 Tracker 需要）
    GUARD_ANCHOR_LOST_TIMEOUT_S: float = 2.0     # 连续追踪丢失多少秒则认为完全跟丢
    GUARD_MAX_ADVANCE_TIME_S: float = 15.0       # 最大推进保护时间（撞墙防止）
    GUARD_MAX_VIEW_RATIO: float = 0.9           # 前进贴脸保护率（目标宽/高到达屏幕尺寸90%则急刹）
    GUARD_ZONE_EDGE_MARGIN_RATIO: float = 0.08   # 区域边缘裕量：bbox 任意边距屏幕边缘小于此比例时禁止前进
    GUARD_OVERLAP_CLEAR_RATIO: float = 0.1      # 人大面积离开锚点框判定的人框在锚点里的重叠比例上限
    
    GUARD_RETURN_POS_TOLERANCE_PX: int = 60      # 退时允许的 X 位移中心误差 (px)
    GUARD_RETURN_AREA_TOLERANCE_RATIO: float = 0.5 # 退时允许的物理纵深面积误差 (0.15 代表返回到了起始大小的 115% 以内)
    GUARD_RETURN_STABLE_FRAMES: int = 15         # 返航完成需连续满足条件的帧数
    GUARD_RETURN_AREA_STOP_RATIO: float = 0.02   # 区域面积占屏幕比例低于此值触发停止（0.10 = 10%）
    GUARD_RETURN_AREA_STABLE_FRAMES: int = 10    # 面积 < 阈值需连续满足的帧数才停止（防单帧误判，建议 5~20）
    GUARD_YAW_DEADBAND_PX: int = 120              # 驱离视觉伺服偏航死区（像素）
    GUARD_COMMAND_RATE_LIMIT_MS: int = 100       # 驱离命令发送最小间隔（ms）

    # 阶段 7：自动跟踪配置
    # 默认禁用，由前端点击「开始巡检」时调用 /api/v1/auto-track/enable 启用
    AUTO_TRACK_ENABLED: bool = False
    AUTO_TRACK_COMMAND_INTERVAL_MS: int = 100     # 自动命令发送最小间隔（ms），从200缩短到100提升灵敏度
    AUTO_TRACK_TARGET_HOLD_SECONDS: float = 3.0   # 目标最短保持时间（s）
    AUTO_TRACK_OUT_OF_ZONE_FRAMES: int = 10       # 连续出区帧数触发停止阈值
    AUTO_TRACK_LOST_TIMEOUT_FRAMES: int = 30      # 目标丢失超时帧数
    AUTO_TRACK_VIDEO_LOST_GRACE_SECONDS: float = 8.0  # 视频流短断宽限时间，期间不释放跟踪/导航联动
    AUTO_TRACK_OVERLAY_INTERVAL_SECONDS: float = 0.1  # TRACK_OVERLAY 广播限频，避免慢前端反压 AI 拉流
    AUTO_TRACK_YAW_DEADBAND_PX: int = 100          # 水平偏航死区（像素），从80缩短到40提升转向灵敏度
    AUTO_TRACK_FORWARD_AREA_RATIO: float = 0.3   # 面积达到该比例后先停止前进
    AUTO_TRACK_ANCHOR_Y_STOP_RATIO: float = 0.95  # 锚点纵向停止比（0.90 即留出底部 10% 作为停止区）
    AUTO_TRACK_STOP_SNAPSHOT_ENABLED: bool = True  # 跟踪停止时是否补拍终止证据图
    AUTO_TRACK_YAW_PULSE_MS: float = 0.0           # 脉冲转向时长（ms），0=禁用，推荐80~150ms
    AUTO_TRACK_VX: float = 0.4                    # 自动跟踪前进/后退速度（m/s）
    AUTO_TRACK_VYAW: float = 0.35                  # 自动跟踪偏航转速（rad/s），需高于 B2 实机偏航死区
    # 云台视觉伺服：先让相机保持目标，再让机身追随相机视线。
    AUTO_TRACK_GIMBAL_ENABLED: bool = True
    # 初始对准保持 5°；跟踪阶段使用更宽的 8° 外圈并连续确认，避免边界抖动。
    AUTO_TRACK_GIMBAL_BODY_DEADBAND_DEG: float = 8.0
    AUTO_TRACK_GIMBAL_FORWARD_DEADBAND_DEG: float = 5.0
    AUTO_TRACK_GIMBAL_REALIGN_FRAMES: int = 3
    AUTO_TRACK_GIMBAL_HORIZONTAL_FOV_DEG: float = 60.0
    AUTO_TRACK_GIMBAL_SERVO_GAIN: float = 0.75
    AUTO_TRACK_GIMBAL_PIXEL_DEADBAND_PX: int = 45
    AUTO_TRACK_GIMBAL_COMMAND_INTERVAL_MS: float = 80.0
    AUTO_TRACK_GIMBAL_MIN_BODY_VYAW: float = 0.35

    # 宇树 B2 硬件适配器配置
    UNITREE_NETWORK_IFACE: str = 'eno1'       # 连接 B2 的网卡名（eth0/enp2s0/Ethernet）
    UNITREE_B2_VX: float = 0.3                # 前进/后退速度（m/s）
    UNITREE_B2_VYAW: float = 0.5              # 偏航转速（rad/s）

    # 驱离模式专用速度（独立于手动遥控速度，降低以提高稳定性）
    GUARD_VX: float = 0.3                    # 驱离前进/后退速度（m/s），默认 0.15
    GUARD_VYAW: float = 0.25                  # 驱离偏航转速（rad/s），默认 0.25


    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parent / ".env"),
        env_file_encoding="utf-8",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
