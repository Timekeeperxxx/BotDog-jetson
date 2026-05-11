"""
Pydantic 模型层（I/O 契约）。

职责边界：
- 与 HTTP/WS 接口的入参与出参一一对应；
- 不直接依赖 ORM 模型，避免 API 层与持久化层强耦合。
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="milliseconds") + "Z"


class SystemHealthResponse(BaseModel):
    status: str = Field(..., description="整体健康状态：healthy/degraded/offline")
    mavlink_connected: bool = Field(..., description="MAVLink 底层链路是否连通")
    uptime: float = Field(..., description="服务运行秒数")


class SystemSafetyResponse(BaseModel):
    safe_to_move: bool = Field(..., description="当前是否允许执行运动命令")
    reasons: list[str] = Field(default_factory=list, description="阻止运动的原因列表")
    system_state: str = Field(..., description="当前系统状态机状态")
    control_adapter_ready: bool = Field(..., description="控制适配器是否就绪")


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


class LogFileInfo(BaseModel):
    name: str
    size_bytes: int
    modified_at: str
    lines_hint: int | None = None


class LogFilesPage(BaseModel):
    items: list[LogFileInfo]


class LogFileTailPage(BaseModel):
    name: str
    lines: list[str]
    line_count: int
    truncated: bool


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
    result: str = Field(..., description="结果：ACCEPTED/REJECTED_LOW_BATTERY/REJECTED_E_STOP/REJECTED_SAFETY_BLOCKED/RATE_LIMITED/REJECTED_ADAPTER_NOT_READY/REJECTED_ADAPTER_ERROR")
    latency_ms: float = Field(..., description="处理延迟（毫秒）")
    safety_reason: str | None = Field(default=None, description="SafetySupervisor 的主拒绝原因")
    safety_reasons: list[str] = Field(default_factory=list, description="SafetySupervisor 的详细拒绝原因列表")


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


class PcdSceneFileDTO(BaseModel):
    name: str
    size_bytes: int
    modified_at: str


class PcdSceneItemDTO(BaseModel):
    id: str
    name: str
    path: str
    modified_at: str
    wall: PcdSceneFileDTO | None = None
    ground: PcdSceneFileDTO | None = None
    ready: bool = False
    navigable: bool = False
    message: str | None = None


class PcdSceneListResponse(BaseModel):
    root: str
    items: list[PcdSceneItemDTO]


class PcdSceneDeleteResponse(BaseModel):
    success: bool = Field(..., description="是否删除成功")
    scene_id: str = Field(..., description="场景 ID")
    deleted_path: str = Field(..., description="已删除的场景目录")
    message: str = Field(..., description="响应消息")


class NavCurrentSceneResponse(BaseModel):
    scene_id: str
    scene_dir: str
    map_pcd: str
    ground_pcd: str
    updated_at: str


class PcdSceneLayerMetadataDTO(BaseModel):
    name: str
    size_bytes: int
    modified_at: str
    frame_id: str = "map"
    type: str = "pcd"
    point_count: int
    fields: list[str]
    data_type: str
    bounds: PcdBoundsDTO | None = None
    supported: bool = True
    message: str | None = None


class PcdSceneMetadataFilesDTO(BaseModel):
    wall: PcdSceneLayerMetadataDTO | None = None
    ground: PcdSceneLayerMetadataDTO | None = None


class PcdSceneMetadataResponse(BaseModel):
    scene_id: str
    name: str
    frame_id: str = "map"
    type: str = "scene_pcd"
    point_count: int
    fields: list[str]
    data_type: str
    files: PcdSceneMetadataFilesDTO
    bounds: PcdBoundsDTO
    supported: bool = True
    message: str | None = None


class PcdScenePreviewLayerDTO(BaseModel):
    role: str
    file_name: str
    points: list[list[float]]
    bounds: PcdBoundsDTO


class PcdScenePreviewLayersDTO(BaseModel):
    ground: PcdScenePreviewLayerDTO | None = None
    wall: PcdScenePreviewLayerDTO | None = None


class PcdScenePreviewResponse(BaseModel):
    scene_id: str
    frame_id: str = "map"
    layers: PcdScenePreviewLayersDTO
    bounds: PcdBoundsDTO


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


class LocalizationPoseSetRequest(BaseModel):
    map_id: str = Field(..., min_length=1)
    x: float
    y: float
    yaw: float = 0.0
    frame_id: str = "map"


class LocalizationPoseDTO(BaseModel):
    map_id: str
    x: float
    y: float
    yaw: float
    frame_id: str
    updated_at: str


class LocalizationRestartResponse(BaseModel):
    success: bool = Field(..., description="是否已成功发起重启")
    running: bool = Field(..., description="重启脚本是否仍在运行")
    pid: int | None = Field(default=None, description="重启脚本进程 PID")
    scene_id: str | None = Field(default=None, description="当前场景 ID")
    scene_dir: str | None = Field(default=None, description="当前场景目录")
    map_pcd: str | None = Field(default=None, description="当前场景 map.pcd 路径")
    ground_pcd: str | None = Field(default=None, description="当前场景 ground.pcd 路径")
    livox_pid: int | None = Field(default=None, description="Livox 驱动 PID")
    relocation_pid: int | None = Field(default=None, description="Super-LIO PID")
    global_planner_pid: int | None = Field(default=None, description="global_planner PID")
    p2p_move_base_pid: int | None = Field(default=None, description="p2p_move_base PID")
    cmd_vel_pid: int | None = Field(default=None, description="cmd_vel PID")
    cmd_vel_running: bool = Field(default=False, description="cmd_vel 脚本是否已拉起")
    navigation_ready: bool = Field(default=False, description="导航链路是否已恢复")
    process_pids: dict[str, int | None] = Field(default_factory=dict, description="子进程 PID 摘要")
    message: str = Field(..., description="响应消息")


class MappingControlRequest(BaseModel):
    enabled: bool
    scene_name: str | None = Field(default=None, max_length=100, description="建图场景名称")


class MappingControlResponse(BaseModel):
    success: bool
    enabled: bool
    running: bool = False
    scene_name: str | None = None
    map_dir: str | None = None
    pid: int | None = None
    message: str | None = None


class NavTaskStepDTO(BaseModel):
    type: str
    label: str
    mapId: str | None = None
    mode: str | None = None
    waypointId: str | None = None
    waypointName: str | None = None
    x: float | None = None
    y: float | None = None
    z: float | None = None
    yaw: float | None = None
    frameId: str | None = None


class NavTaskDefinitionDTO(BaseModel):
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1, max_length=255)
    mapId: str = Field(..., min_length=1)
    sceneId: str | None = Field(default=None, min_length=1)
    mapName: str = Field(..., min_length=1)
    createdAt: str = Field(..., min_length=1)
    steps: list[NavTaskStepDTO] = Field(default_factory=list)


class NavTaskListResponse(BaseModel):
    items: list[NavTaskDefinitionDTO]


class NavTaskUpsertRequest(BaseModel):
    task: NavTaskDefinitionDTO


class NavTaskExecuteNavStartDTO(BaseModel):
    success: bool
    topic: str
    data: bool


class NavWaypointGoToGoalDTO(BaseModel):
    success: bool
    xyz_topic: str
    yaw_topic: str
    waypoint_id: str | None = None
    x: float
    y: float
    z: float
    yaw: float
    frame_id: str


class NavWaypointGoToResponse(BaseModel):
    success: bool
    topic: str
    waypoint_id: str
    xyz_topic: str
    yaw_topic: str
    goal: NavWaypointGoToGoalDTO
    message: str | None = None


class NavTaskExecuteResponse(BaseModel):
    success: bool
    task_id: str
    topic: str
    data: bool
    nav_start: NavTaskExecuteNavStartDTO
    message: str
    runtime_file: str | None = None
    runtime_task: dict[str, Any] | None = None


class NavTaskStopResponse(BaseModel):
    success: bool
    task_id: str
    topic: str
    data: bool
    nav_start: NavTaskExecuteNavStartDTO
    message: str


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


class GlobalPathPointDTO(BaseModel):
    x: float
    y: float
    z: float = 0.0


class GlobalPathDTO(BaseModel):
    frame_id: str
    points: list[GlobalPathPointDTO]
    timestamp: float | None = None


class NavStateResponse(BaseModel):
    robot_pose: RobotPoseDTO | None = None
    navigation_status: NavigationStatusDTO
    localization_status: LocalizationStatusDTO
    global_path: GlobalPathDTO | None = None
