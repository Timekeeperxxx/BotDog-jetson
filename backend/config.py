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
    AI_MODEL_PATH: str = "yolov8n.pt"  # YOLO 模型路径
    AI_CONFIDENCE_THRESHOLD: float = 0.5  # 推理置信度阈值
    AI_TARGET_CLASSES: list[str] = ["person"]  # 目标类别

    # 抓拍存储目录（用于 /api/v1/static）
    SNAPSHOT_DIR: str = "data/snapshots"

    class Config:
        env_file = str(Path(__file__).resolve().parent / ".env")
        env_file_encoding = "utf-8"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

