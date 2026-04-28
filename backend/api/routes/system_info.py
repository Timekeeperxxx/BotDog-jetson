"""系统信息路由。"""

from urllib.parse import urlparse

from fastapi import APIRouter

from ...config import settings

router = APIRouter(tags=["system_info"])


@router.get("/api/v1/system-info")
async def get_system_info() -> dict:
    """
    返回系统关键硬件参数（只读，来源于 .env 静态配置）。

    这些参数通常由硬件拓扑决定，不支持运行时修改。
    前端用于在「后台管理 > 系统信息」中只读展示，方便现场排查。
    """
    mediamtx_host = "127.0.0.1"
    try:
        parsed = urlparse(settings.AI_RTSP_URL)
        if parsed.hostname:
            mediamtx_host = parsed.hostname
    except Exception:
        pass

    return {
        "groups": [
            {
                "group": "机器人连接",
                "icon": "robot",
                "items": [
                    {
                        "key": "unitree_network_iface",
                        "label": "宇树 B2 网卡名",
                        "value": settings.UNITREE_NETWORK_IFACE,
                        "note": "OrangePi 上连接机器狗的物理网卡，用 `ip addr` 查看",
                        "env_key": "UNITREE_NETWORK_IFACE",
                    },
                    {
                        "key": "unitree_b2_ip",
                        "label": "宇树 B2 默认 IP",
                        "value": "192.168.123.161",
                        "note": "B2 机器人的固定出厂 IP，不可更改",
                        "env_key": "—",
                    },
                    {
                        "key": "control_adapter",
                        "label": "控制适配器类型",
                        "value": settings.CONTROL_ADAPTER_TYPE,
                        "note": "unitree_b2=真实硬件，simulation=仅打印日志",
                        "env_key": "CONTROL_ADAPTER_TYPE",
                    },
                ],
            },
            {
                "group": "视频 / 图传",
                "icon": "video",
                "items": [
                    {
                        "key": "ai_rtsp_url",
                        "label": "AI 推理 RTSP 地址",
                        "value": settings.AI_RTSP_URL,
                        "note": "AI Worker 从此地址拉取视频帧进行推理",
                        "env_key": "AI_RTSP_URL",
                    },
                    {
                        "key": "mediamtx_rtsp_port",
                        "label": "MediaMTX RTSP 端口",
                        "value": f"{mediamtx_host}:8554",
                        "note": "摄像头推流到此地址（如 ffmpeg/OBS 的推流目标）",
                        "env_key": "—",
                    },
                    {
                        "key": "mediamtx_whep_port",
                        "label": "MediaMTX WHEP 端口",
                        "value": f"{mediamtx_host}:8889",
                        "note": "前端 WebRTC 播放地址的主机和端口",
                        "env_key": "—",
                    },
                    {
                        "key": "hm30_sky_ip",
                        "label": "HM30 天空端 IP",
                        "value": "192.168.0.2",
                        "note": "HM30 图传天空端的默认管理地址（连接后可访问 Web 配置页）",
                        "env_key": "—",
                    },
                    {
                        "key": "hm30_ground_ip",
                        "label": "HM30 地面端 IP",
                        "value": "192.168.0.3",
                        "note": "HM30 图传地面端的默认管理地址",
                        "env_key": "—",
                    },
                ],
            },
            {
                "group": "后端服务",
                "icon": "server",
                "items": [
                    {
                        "key": "backend_host",
                        "label": "后端监听地址",
                        "value": f"{settings.BACKEND_HOST}:{settings.BACKEND_PORT}",
                        "note": "前端通过此地址访问 API 和 WebSocket",
                        "env_key": "BACKEND_HOST / BACKEND_PORT",
                    },
                    {
                        "key": "mavlink_endpoint",
                        "label": "MAVLink 端点",
                        "value": settings.MAVLINK_ENDPOINT,
                        "note": "MAVLink 数据来源（udp=模拟/真实飞控）",
                        "env_key": "MAVLINK_ENDPOINT",
                    },
                    {
                        "key": "mavlink_source",
                        "label": "MAVLink 数据源",
                        "value": settings.MAVLINK_SOURCE,
                        "note": "mavlink=真实硬件，simulation=内置模拟器",
                        "env_key": "MAVLINK_SOURCE",
                    },
                ],
            },
        ]
    }
