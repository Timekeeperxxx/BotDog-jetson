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

    # 阶段 2：控制通道配置
    CONTROL_RATE_LIMIT_HZ: float = 20.0  # 控制指令限流（Hz）
    CONTROL_DEADZONE: int = 50  # 摇杆死区（0-1000）

    # 阶段 3：视频流配置
    VIDEO_WATCHDOG_TIMEOUT_S: float = 5.0  # 视频看门狗超时（秒）
    VIDEO_RESOLUTION: str = "1920x1080"  # 1080p 分辨率
    VIDEO_BITRATE: int = 8000000  # 8 Mbps
    VIDEO_FRAMERATE: int = 30  # 帧率（降低到 30fps 以兼容更多相机）
    VIDEO_UDP_PORT: int = 19856  # UDP 视频接收端口（图传端口）

    # 视频延迟优化配置（超低延迟优化）
    VIDEO_RTSP_LATENCY_MS: int = 30  # RTSP rtspsrc 缓冲延迟（毫秒），LAN 推荐 20-50ms
    VIDEO_RTP_JITTER_MS: int = 0  # RTP jitterbuffer 延迟（毫秒），0=禁用（rtspsrc 自带 buffer，避免双重缓冲）
    VIDEO_QUEUE_MAXSIZE: int = 1  # Python 队列最大帧数，极限低延迟
    VIDEO_LATENCY_PRESET: str = "low"  # 延迟预设：stable(100/100/30), low(50/0/15), ultralow(20/0/10)

    # UDP 视频流转发器配置（已禁用 - video_track_native 直接监听 UDP）
    UDP_RELAY_ENABLED: bool = False  # 禁用 UDP 转发器
    UDP_RELAY_LISTEN_PORT: int = 5000  # 转发器监听端口（边缘端推送到此端口）
    UDP_RELAY_BIND_ADDRESS: str = "192.168.144.30"  # 转发器绑定地址
    UDP_RELAY_TARGET_ADDRESS: str = "127.0.0.1"  # 转发目标地址（本地 WebRTC）
    UDP_RELAY_BUFFER_SIZE: int = 65536  # UDP 缓冲区大小（字节）
    UDP_RELAY_ENABLE_STATS: bool = True  # 启用统计
    UDP_RELAY_STATS_INTERVAL: float = 5.0  # 统计日志输出间隔（秒）

    # 相机 RTSP 配置
    CAMERA_RTSP_URL: str = "rtsp://192.168.144.25:8554/main.264"  # 相机 RTSP 地址

    # 网络接口名称配置
    HARDWARE_INTERFACE: str = "ens33"  # 硬件网卡名称（用于图传连接）

    # WebRTC 配置
    VIDEO_BACKEND_MODE: str = "aiortc"  # aiortc | webrtcbin
    WEBRTC_GST_WS_PATH: str = "/ws/webrtc-gst"  # webrtcbin runner 连接入口
    WEBRTC_ICE_SERVERS: list[str] = ["stun:stun.l.google.com:19302", "stun:stun1.l.google.com:19302"]  # STUN/TURN 服务器列表

    # 阶段 4：AI 告警配置
    THERMAL_THRESHOLD: float = 60.0  # 温度阈值（°C）

    class Config:
        env_file = str(Path(__file__).resolve().parent.parent / ".env")
        env_file_encoding = "utf-8"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

