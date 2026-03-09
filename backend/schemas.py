"""
Pydantic 模型层（I/O 契约）。

职责边界：
- 与 HTTP/WS 接口的入参与出参一一对应；
- 不直接依赖 ORM 模型，避免 API 层与持久化层强耦合。
"""

from datetime import datetime
from typing import Optional, Literal, Any

from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="milliseconds") + "Z"


class SystemHealthResponse(BaseModel):
    status: str = Field(..., description="整体健康状态：healthy/degraded/offline")
    mavlink_connected: bool = Field(..., description="MAVLink 底层链路是否连通")
    uptime: float = Field(..., description="服务运行秒数")


class SessionStartRequest(BaseModel):
    task_name: str = Field(..., min_length=1, max_length=255, description="任务名称")


class SessionInfo(BaseModel):
    task_id: int
    task_name: str
    status: str
    started_at: str
    ended_at: Optional[str] = None


class SessionStartResponse(SessionInfo):
    ...


class SessionStopRequest(BaseModel):
    task_id: int = Field(..., ge=1, description="需要停止的任务 ID")


class SessionStopResponse(SessionInfo):
    ...


class LogEntry(BaseModel):
    log_id: int
    level: str
    module: str
    message: str
    task_id: Optional[int] = None
    created_at: str


class LogsPage(BaseModel):
    items: list[LogEntry]


class EvidenceItem(BaseModel):
    evidence_id: int
    task_id: int
    event_type: str
    event_code: Optional[str] = None
    severity: str
    message: Optional[str] = None
    confidence: Optional[float] = None
    file_path: str
    image_url: Optional[str] = None
    gps_lat: Optional[float] = None
    gps_lon: Optional[float] = None
    created_at: str


class EvidenceListResponse(BaseModel):
    items: list[EvidenceItem]


class ManualControlDTO(BaseModel):
    """
    手动控制指令数据传输对象。

    用于前端发送控制指令到后端。
    """
    x: int = Field(..., ge=-1000, le=1000, description="前进/后退 (-1000~1000)")
    y: int = Field(..., ge=-1000, le=1000, description="左右平移 (-1000~1000)")
    z: int = Field(..., ge=-1000, le=1000, description="上下控制 (-1000~1000)")
    r: int = Field(..., ge=-1000, le=1000, description="偏航转向 (-1000~1000)")


class ControlAckDTO(BaseModel):
    """
    控制指令确认数据传输对象。

    后端回复前端控制指令的确认消息。
    """
    ack_cmd: str = Field(..., description="确认的指令类型")
    result: str = Field(..., description="结果：ACCEPTED/REJECTED_LOW_BATTERY/REJECTED_E_STOP/RATE_LIMITED")
    latency_ms: float = Field(..., description="处理延迟（毫秒）")


class EStopResponse(BaseModel):
    """
    急停指令响应。
    """
    success: bool = Field(..., description="急停是否成功触发")
    timestamp: str = Field(..., description="触发时间")
    message: str = Field(..., description="响应消息")


class EStopResetResponse(BaseModel):
    """
    急停重置响应。
    """
    success: bool = Field(..., description="重置是否成功")
    timestamp: str = Field(..., description="重置时间")
    message: str = Field(..., description="响应消息")
    state_after: str = Field(..., description="重置后的系统状态")


# 阶段 3：WebRTC 视频流相关 DTO


class WebRTCSignalingMessage(BaseModel):
    """
    WebRTC 信令消息。

    用于 SDP/ICE 候选交换。
    """
    msg_type: Literal["offer", "answer", "ice_candidate"] = Field(
        ..., description="消息类型"
    )
    payload: dict[str, Any] = Field(..., description="载荷数据")


class VideoStatusDTO(BaseModel):
    """
    视频流状态数据传输对象。
    """
    status: Literal["connected", "disconnected", "error"] = Field(
        ..., description="连接状态"
    )
    client_id: str = Field(..., description="客户端 ID")
    resolution: Optional[str] = Field(None, description="视频分辨率")
    bitrate: Optional[int] = Field(None, description="码率（bps）")
    framerate: Optional[int] = Field(None, description="帧率")
    error: Optional[str] = Field(None, description="错误信息")

