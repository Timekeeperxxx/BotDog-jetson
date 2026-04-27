"""
Pydantic 模型层（I/O 契约）。

职责边界：
- 与 HTTP/WS 接口的入参与出参一一对应；
- 不直接依赖 ORM 模型，避免 API 层与持久化层强耦合。
"""

from datetime import datetime
from typing import Optional

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
    task_id: Optional[int] = None    # 可为 NULL：AI/温度告警可在无巡检任务时触发
    event_type: str
    event_code: Optional[str] = None
    severity: str
    message: Optional[str] = None
    confidence: Optional[float] = None
    file_path: Optional[str] = None  # 可为 NULL：温度告警无截图文件
    image_url: Optional[str] = None
    gps_lat: Optional[float] = None
    gps_lon: Optional[float] = None
    created_at: str


class EvidenceListResponse(BaseModel):
    items: list[EvidenceItem]


class EvidenceBulkDeleteRequest(BaseModel):
    evidence_ids: list[int] = Field(..., min_length=1)


class EvidenceDeleteResponse(BaseModel):
    success: bool
    deleted: int
    missing_files: int
    not_found_ids: list[int]


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
    result: str = Field(..., description="结果：ACCEPTED/REJECTED_LOW_BATTERY/REJECTED_E_STOP/RATE_LIMITED/REJECTED_ADAPTER_NOT_READY/REJECTED_ADAPTER_ERROR")
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


class PcdBoundsDTO(BaseModel):
    min_x: float
    max_x: float
    min_y: float
    max_y: float
    min_z: float
    max_z: float


class PcdMapItemDTO(BaseModel):
    id: str
    name: str
    size_bytes: int
    modified_at: str


class PcdMapListResponse(BaseModel):
    root: str
    items: list[PcdMapItemDTO]


class PcdMetadataResponse(BaseModel):
    map_id: str
    name: str
    frame_id: str = "map"
    type: str = "pcd"
    point_count: int
    fields: list[str]
    data_type: str
    bounds: PcdBoundsDTO | None = None
    supported: bool = True
    message: str | None = None


class PcdPreviewResponse(BaseModel):
    map_id: str
    frame_id: str = "map"
    points: list[list[float]]
    bounds: PcdBoundsDTO


class NavWaypointCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    x: float
    y: float
    z: float = 0.0
    yaw: float = 0.0
    frame_id: str = "map"


class NavWaypointDTO(BaseModel):
    id: str
    map_id: str
    name: str
    x: float
    y: float
    z: float
    yaw: float
    frame_id: str
    created_at: str
    updated_at: str


class NavWaypointListResponse(BaseModel):
    items: list[NavWaypointDTO]


class DeleteWaypointResponse(BaseModel):
    success: bool


class RobotPoseDTO(BaseModel):
    x: float
    y: float
    z: float
    yaw: float
    frame_id: str
    source: str
    timestamp: float


class NavigationStatusDTO(BaseModel):
    status: str
    target_waypoint_id: str | None = None
    target_name: str | None = None
    message: str
    timestamp: float | None = None


class LocalizationStatusDTO(BaseModel):
    status: str
    frame_id: str
    source: str | None = None
    message: str
    timestamp: float | None = None


class NavStateResponse(BaseModel):
    robot_pose: RobotPoseDTO | None = None
    navigation_status: NavigationStatusDTO
    localization_status: LocalizationStatusDTO

