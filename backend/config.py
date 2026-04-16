"""
配置中心。

职责边界：
- 将 `.env` / 环境变量 与 代码中的默认值解耦；
- 为其他模块提供类型安全的 Settings 对象（单例）。
"""

from functools import lru_cache
from pathlib import Path

from pydantic import AnyUrl
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    全局配置，结合 `.env` 与文档 `09_config_matrix.md`、`06_backend_protocol_schema.md`。

    注意：
    - 仅放“真正需要全局”的配置项，避免无节制膨胀；
    - 可与数据库中的 `config` 表组合，实现“默认值在代码、运行值在 DB”的模式。
    """

    # 基础网络配置
    BACKEND_HOST: str = "0.0.0.0"
    BACKEND_PORT: int = 8000

    # MAVLink / 数据库
    MAVLINK_ENDPOINT: str = "udp:127.0.0.1:14550"
    DATABASE_URL: AnyUrl | str = "sqlite+aiosqlite:///./data/botdog.db"

    # 安全配置
    JWT_SECRET: str = "please_change_me"

    # CORS 配置
    CORS_ALLOW_ORIGINS: list[str] = ["*"]
    CORS_ALLOW_CREDENTIALS: bool = False

    # 本地模拟数据 Worker 控制（默认保持当前启用行为）
    SIMULATION_WORKER_ENABLED: bool = True

    # MAVLink 数据源选择（mavlink|simulation）
    # - mavlink: 使用真实 MAVLink 端口
    # - simulation: 使用模拟数据生成器
    MAVLINK_SOURCE: str = "simulation"

    # 配置矩阵中的关键参数（只列当前阶段会用到的）
    HEARTBEAT_TIMEOUT: float = 3.0  # heartbeat_timeout
    TELEMETRY_SAMPLING_HZ: float = 2.0  # 遥测落盘采样频率（Hz）
    TELEMETRY_BROADCAST_HZ: float = 15.0  # 遥测广播频率（Hz）

    # 阶段 4：AI 告警配置
    THERMAL_THRESHOLD: float = 60.0  # 温度阈值（°C）

    # 阶段 5：旁路 AI 识别与抓拍
    AI_ENABLED: bool = True
    AI_RTSP_URL: str = "rtsp://127.0.0.1:8554/cam"
    AI_FRAME_WIDTH: int = 1920
    AI_FRAME_HEIGHT: int = 1080
    AI_FPS: int = 10
    AI_PATROL_SKIP: int = 5  # 巡逻态跳帧（10fps / 5 = 2fps 推理）
    AI_SUSPECT_SKIP: int = 1  # 疑似目标全速推理
    AI_STABLE_HITS: int = 3  # 连续命中阈值
    AI_RESET_MISSES: int = 3  # 连续未命中重置阈值
    AI_COOLDOWN_SECONDS: float = 30.0  # 冷却时间
    AI_SIMULATE_DETECTION: bool = False
    AI_SIMULATE_PROB: float = 0.02
    AI_DEVICE: str = "auto"  # auto / cpu / cuda / cuda:0
    AI_MODEL_PATH: str = "models/yolov8n.pt"  # YOLO 模型路径
    AI_CONFIDENCE_THRESHOLD: float = 0.5  # 推理置信度阈值
    AI_TARGET_CLASSES: list[str] = ["person"]  # 目标类别

    # 抓拍存储目录（用于 /api/v1/static）
    SNAPSHOT_DIR: str = "data/snapshots"

    # 阶段 6：网页控制服务配置
    # 适配器类型：simulation（仅打印日志）| mavlink（真实硬件）
    CONTROL_ADAPTER_TYPE: str = "simulation"
    # Watchdog 超时（ms）：超过此时间未收到命令自动执行 stop
    CONTROL_WATCHDOG_TIMEOUT_MS: int = 500
    # 最小命令间隔（ms）：防止前端过快发命令（stop 命令跳过此限制）
    CONTROL_CMD_RATE_LIMIT_MS: int = 50

    # ==================== 黄色区域识别参数 ====================
    # HSV 色调范围（OpenCV H: 0-180，纯黄约 25-35）
    ZONE_YELLOW_H_LOW: int = 15
    ZONE_YELLOW_H_HIGH: int = 40
    # 饱和度范围（越高越排除灰白色）
    ZONE_YELLOW_S_LOW: int = 80
    ZONE_YELLOW_S_HIGH: int = 255
    # 亮度范围（越高越排除暗色/阴影）
    ZONE_YELLOW_V_LOW: int = 120
    ZONE_YELLOW_V_HIGH: int = 255
    # 黑边验证：外扩环形区域 V 通道 10th percentile 低于此值才算有黑边
    ZONE_BORDER_V_THRESHOLD: int = 40
    # 外扩采样像素宽度（只采紧邻黄色区域的黑边本身，不延伸到地毯）
    ZONE_BORDER_EXPAND_PX: int = 3
    # 面积约束
    ZONE_MIN_AREA_PX: int = 800
    ZONE_MAX_AREA_RATIO: float = 0.50
    # 形状约束
    ZONE_MIN_ASPECT: float = 1.5
    ZONE_MAX_ASPECT: float = 15.0
    ZONE_MIN_SOLIDITY: float = 0.60
    # ROI：跳过画面顶部此比例，只处理含地面的下部（0.35 = 跳过顶 35%）
    ZONE_ROI_TOP_RATIO: float = 0.35
    # 形态学核大小（越大填孔越强，也越慢）
    ZONE_MORPH_KERNEL_SIZE: int = 7
    # quality 权重（三者之和建议为 1.0）
    ZONE_W_AREA: float = 0.30
    ZONE_W_SOLID: float = 0.30
    ZONE_W_BORDER: float = 0.40

    # 驱离任务配置
    GUARD_MISSION_ENABLED: bool = False
    GUARD_CONFIRM_TIME_S: float = 1.5           # 入侵确认时间（秒）
    GUARD_CLEAR_TIME_S: float = 5.0             # 清空确认时间（秒）
    GUARD_MIN_DURATION_S: float = 3.0           # 最短驱离持续时间
    GUARD_DEPLOY_DURATION_S: float = 10.0       # 前往驱离点的前进时间（秒），独立于返回时长
    GUARD_RETURN_DURATION_S: float = 10.0       # 返回起点的后退时间（秒），独立于前往时长
    GUARD_COOLDOWN_S: float = 30.0             # 两次出动间的冷却时间
    GUARD_MAX_DURATION_S: float = 120.0        # 单次驱离最大持续时间
    GUARD_DEPLOY_SETTLE_S: float = 2.0         # 起立后稳定等待时间
    GUARD_RETURN_SETTLE_S: float = 2.0         # 蹲坐后稳定等待时间
    GUARD_ALERT_AUDIO_PATH: str = "assets/13282.wav"   # 警告音频文件路径
    GUARD_CLEAR_MIN_CONF: float = 0.4          # 清空判定最小有效置信度
    GUARD_CLEAR_MIN_AREA: int = 2000           # 清空判定最小有效目标面积（px）
    GUARD_VISUAL_TIMEOUT_S: float = 5.0        # 视觉链路健康超时（秒）
    
    # ==== 新增：视觉伺服 / 锚点跟踪配置 ====
    GUARD_ANCHOR_MIN_QUALITY: float = 0.6        # 锚点跟踪最小稳定质量限度（部分 Tracker 需要）
    GUARD_ANCHOR_LOST_TIMEOUT_S: float = 2.0     # 连续追踪丢失多少秒则认为完全跟丢
    GUARD_MAX_ADVANCE_TIME_S: float = 15.0       # 最大推进保护时间（撞墙防止）
    GUARD_MAX_VIEW_RATIO: float = 0.90           # 前进贴脸保护率（目标宽/高到达屏幕尺寸90%则急刹）
    GUARD_ZONE_EDGE_MARGIN_RATIO: float = 0.08   # 区域边缘裕量：bbox 任意边距屏幕边缘小于此比例时禁止前进
    GUARD_OVERLAP_CLEAR_RATIO: float = 0.10      # 人大面积离开锚点框判定的人框在锚点里的重叠比例上限
    
    GUARD_RETURN_POS_TOLERANCE_PX: int = 60      # 退时允许的 X 位移中心误差 (px)
    GUARD_RETURN_AREA_TOLERANCE_RATIO: float = 0.15 # 退时允许的物理纵深面积误差 (0.15 代表返回到了起始大小的 115% 以内)
    GUARD_RETURN_STABLE_FRAMES: int = 15         # 返航完成需连续满足条件的帧数
    GUARD_RETURN_AREA_STOP_RATIO: float = 0.10   # 区域面积占屏幕比例低于此值触发停止（0.10 = 10%）
    GUARD_RETURN_AREA_STABLE_FRAMES: int = 10    # 面积 < 阈值需连续满足的帧数才停止（防单帧误判，建议 5~20）
    GUARD_YAW_DEADBAND_PX: int = 40              # 驱离视觉伺服偏航死区（像素）
    GUARD_COMMAND_RATE_LIMIT_MS: int = 100       # 驱离命令发送最小间隔（ms）

    # 阶段 7：自动跟踪配置
    # 默认禁用，由前端点击「开始巡检」时调用 /api/v1/auto-track/enable 启用
    AUTO_TRACK_ENABLED: bool = False
    AUTO_TRACK_COMMAND_INTERVAL_MS: int = 100     # 自动命令发送最小间隔（ms），从200缩短到100提升灵敏度
    AUTO_TRACK_TARGET_HOLD_SECONDS: float = 3.0   # 目标最短保持时间（s）
    AUTO_TRACK_OUT_OF_ZONE_FRAMES: int = 10       # 连续出区帧数触发停止阈值
    AUTO_TRACK_LOST_TIMEOUT_FRAMES: int = 30      # 目标丢失超时帧数
    AUTO_TRACK_YAW_DEADBAND_PX: int = 40          # 水平偏航死区（像素），从80缩短到40提升转向灵敏度
    AUTO_TRACK_FORWARD_AREA_RATIO: float = 0.15   # 前进触发的面积比阈值
    AUTO_TRACK_ANCHOR_Y_STOP_RATIO: float = 0.95  # 锚点纵向停止比（0.90 即留出底部 10% 作为停止区）
    AUTO_TRACK_STOP_SNAPSHOT_ENABLED: bool = True  # 跟踪停止时是否补拍终止证据图
    AUTO_TRACK_YAW_PULSE_MS: float = 0.0           # 脉冲转向时长（ms），0=禁用，推荐80~150ms

    # 宇树 B2 硬件适配器配置
    UNITREE_NETWORK_IFACE: str = "eth0"       # 连接 B2 的网卡名（eth0/enp2s0/Ethernet）
    UNITREE_B2_VX: float = 0.3                # 前进/后退速度（m/s）
    UNITREE_B2_VYAW: float = 0.5              # 偏航转速（rad/s）

    # 驱离模式专用速度（独立于手动遥控速度，降低以提高稳定性）
    GUARD_VX: float = 0.15                    # 驱离前进/后退速度（m/s），默认 0.15
    GUARD_VYAW: float = 0.25                  # 驱离偏航转速（rad/s），默认 0.25


    class Config:
        env_file = str(Path(__file__).resolve().parent / ".env")
        env_file_encoding = "utf-8"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

