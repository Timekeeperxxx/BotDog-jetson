"""
领域模型（ORM 实体）。

设计原则：
- 一张表对应一个模型，命名与 `docs/14_database_schema.md` / `db/schema.sql` 对齐；
- 只承载领域数据与约束，不包含跨聚合的业务流程逻辑（高内聚、低耦合）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utc_now_iso() -> str:
    """统一的 UTC ISO8601 时间戳生成，便于日志与客户端对齐。"""
    return datetime.utcnow().isoformat(timespec="milliseconds") + "Z"


class InspectionTask(Base):
    __tablename__ = "inspection_tasks"

    task_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="running",
    )
    started_at: Mapped[str] = mapped_column(String, nullable=False)
    ended_at: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=utc_now_iso)
    updated_at: Mapped[str] = mapped_column(String, nullable=False, default=utc_now_iso)

    # 任务下的所有遥测快照（降采样留存），只在任务维度删除时级联清理
    telemetry_snapshots: Mapped[list["TelemetrySnapshot"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    # 任务下的所有异常证据记录
    # 注意：证据使用 SET NULL 外键策略，删除任务后证据保留（task_id 置空）
    # 因此不使用 delete-orphan cascade，避免级联清除历史取证
    evidences: Mapped[list["AnomalyEvidence"]] = relationship(
        back_populates="task",
        cascade="save-update, merge",
        lazy="selectin",
        passive_deletes=True,
    )
    # 与任务相关的审计日志；删除任务时日志保留，仅 task_id 置空
    logs: Mapped[list["OperationLog"]] = relationship(
        back_populates="task",
        cascade="save-update",
        lazy="selectin",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'stopped', 'failed')",
            name="ck_inspection_tasks_status",
        ),
    )


class TelemetrySnapshot(Base):
    __tablename__ = "telemetry_snapshots"

    snapshot_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    task_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("inspection_tasks.task_id", ondelete="CASCADE"),
        nullable=False,
    )

    timestamp: Mapped[str] = mapped_column(String, nullable=False)

    gps_lat: Mapped[float | None] = mapped_column(Float)
    gps_lon: Mapped[float | None] = mapped_column(Float)
    gps_alt: Mapped[float | None] = mapped_column(Float)
    hdg: Mapped[float | None] = mapped_column(Float)

    att_pitch: Mapped[float | None] = mapped_column(Float)
    att_roll: Mapped[float | None] = mapped_column(Float)
    att_yaw: Mapped[float | None] = mapped_column(Float)

    battery_voltage: Mapped[float | None] = mapped_column(Float)
    battery_remaining_pct: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[str] = mapped_column(String, nullable=False, default=utc_now_iso)

    task: Mapped[InspectionTask] = relationship(back_populates="telemetry_snapshots")

    __table_args__ = (
        CheckConstraint(
            "battery_remaining_pct IS NULL OR (battery_remaining_pct BETWEEN 0 AND 100)",
            name="ck_telemetry_battery_pct",
        ),
    )


class AnomalyEvidence(Base):
    __tablename__ = "anomaly_evidence"

    evidence_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    # task_id 允许为 NULL：AI 检测可在无巡检任务时触发（独立告警场景）
    # ondelete="SET NULL"：删除任务后证据仍保留，task_id 置空，避免历史取证丢失
    task_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("inspection_tasks.task_id", ondelete="SET NULL"),
        nullable=True,
    )

    event_type: Mapped[str] = mapped_column(String, nullable=False)
    event_code: Mapped[str | None] = mapped_column(String)
    severity: Mapped[str] = mapped_column(String, nullable=False, default="CRITICAL")
    message: Mapped[str | None] = mapped_column(Text)

    confidence: Mapped[float | None] = mapped_column(Float)

    # file_path 允许为 NULL：温度告警无截图文件
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text)

    gps_lat: Mapped[float | None] = mapped_column(Float)
    gps_lon: Mapped[float | None] = mapped_column(Float)

    created_at: Mapped[str] = mapped_column(String, nullable=False, default=utc_now_iso)

    task: Mapped[InspectionTask | None] = relationship(back_populates="evidences")

    __table_args__ = (
        CheckConstraint(
            "severity IN ('INFO', 'WARN', 'WARNING', 'ERROR', 'CRITICAL')",
            name="ck_anomaly_severity",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)",
            name="ck_anomaly_confidence",
        ),
    )


class OperationLog(Base):
    __tablename__ = "operation_logs"

    log_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    level: Mapped[str] = mapped_column(String, nullable=False)
    module: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    task_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("inspection_tasks.task_id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at: Mapped[str] = mapped_column(String, nullable=False, default=utc_now_iso)

    task: Mapped[InspectionTask | None] = relationship(back_populates="logs")

    __table_args__ = (
        CheckConstraint(
            "level IN ('INFO', 'WARN', 'ERROR', 'CRITICAL')",
            name="ck_operation_logs_level",
        ),
        CheckConstraint(
            "module IN ('BACKEND', 'UI', 'MEDIA', 'EDGE')",
            name="ck_operation_logs_module",
        ),
    )


class ConfigEntry(Base):
    __tablename__ = "config"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    value_type: Mapped[str] = mapped_column(String, nullable=False, default="string")
    is_hot_reload: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_by: Mapped[str | None] = mapped_column(String)
    updated_at: Mapped[str] = mapped_column(String, nullable=False, default=utc_now_iso)

    __table_args__ = (
        CheckConstraint(
            "value_type IN ('string', 'int', 'float', 'bool', 'json')",
            name="ck_config_value_type",
        ),
        CheckConstraint(
            "is_hot_reload IN (0, 1)",
            name="ck_config_is_hot_reload",
        ),
    )


class FocusZone(Base):
    """
    重点监控区域。

    坐标语义：图像坐标系（像素），原点为视频帧左上角。
    polygon_json 示例：[[100,200],[300,200],[300,400],[100,400]]

    注意：此区域代表"当前视频画面坐标系中的关注区域"，
    不代表真实世界固定方位或地图坐标。
    """

    __tablename__ = "focus_zones"

    zone_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    zone_name: Mapped[str] = mapped_column(String, nullable=False, default="default")
    enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    polygon_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="图像像素坐标多边形顶点 JSON，与 AI_FRAME_WIDTH x AI_FRAME_HEIGHT 对齐",
    )
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=utc_now_iso)
    updated_at: Mapped[str] = mapped_column(String, nullable=False, default=utc_now_iso)

    __table_args__ = (
        CheckConstraint(
            "enabled IN (0, 1)",
            name="ck_focus_zones_enabled",
        ),
    )


class SessionKnownTarget(Base):
    """
    会话级已知人员标记。

    语义：
    - 每条记录代表本次巡检任务中，操作员标记为"已知人员"的目标
    - track_id 为 AIWorker 帧间 IOU 匹配分配的临时 ID，仅会话级有效
    - 任务结束或系统重启后，这些记录不再被查询（不构成跨任务身份白名单）
    - marked_by 记录谁发起了标记（默认为 operator）

    注意：此表不提供人脸识别或 ReID 能力，阶段 3 仅作人工白名单用途。
    """

    __tablename__ = "session_known_targets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("inspection_tasks.task_id", ondelete="SET NULL"),
        nullable=True,
        comment="关联的巡检任务 ID",
    )
    track_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="AIWorker 分配的帧间临时跟踪 ID（会话级有效）",
    )
    marked_by: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="operator",
        comment="标记发起方（operator/system）",
    )
    reason: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        comment="标记原因（可选）",
    )
    created_at: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=utc_now_iso,
    )


class VideoSource(Base):
    """
    视频源配置。

    存储摄像头的视频流地址（WHEP / RTSP），支持运行时动态管理。
    前端通过 WHEP 地址播放视频流，AI Worker 通过 RTSP 地址拉取推理帧。

    字段说明：
    - name: 唯一标识符，如 "cam1"、"cam2"
    - label: 人类可读标签，如 "USB 主摄像头"、"图传摄像头"
    - source_type: 视频源类型（whep / rtsp / usb）
    - whep_url: WHEP 播放地址，供前端 WebRTC 播放器使用
    - rtsp_url: RTSP 拉流地址，供 AI 推理模块使用
    - is_primary: 是否为主画面（仅允许一个）
    - is_ai_source: 是否为 AI 推理数据源（仅允许一个）
    """

    __tablename__ = "video_sources"

    source_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False,
        comment="唯一标识符，如 cam1、cam2",
    )
    label: Mapped[str] = mapped_column(
        String(100), nullable=False,
        comment="人类可读标签，如 USB 主摄像头",
    )
    source_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="whep",
        comment="视频源类型：whep / rtsp / usb",
    )
    whep_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
        comment="WHEP 播放地址（前端用）",
    )
    rtsp_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
        comment="RTSP 拉流地址（AI 推理用）",
    )
    enabled: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1,
        comment="是否启用：0=禁用，1=启用",
    )
    is_primary: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="是否为主画面：0=否，1=是",
    )
    is_ai_source: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="是否为 AI 推理源：0=否，1=是",
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="显示排序序号",
    )
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=utc_now_iso)
    updated_at: Mapped[str] = mapped_column(String, nullable=False, default=utc_now_iso)

    __table_args__ = (
        CheckConstraint("enabled IN (0, 1)", name="ck_video_sources_enabled"),
        CheckConstraint("is_primary IN (0, 1)", name="ck_video_sources_is_primary"),
        CheckConstraint("is_ai_source IN (0, 1)", name="ck_video_sources_is_ai_source"),
        CheckConstraint(
            "source_type IN ('whep', 'rtsp', 'usb')",
            name="ck_video_sources_source_type",
        ),
    )


class NetworkInterface(Base):
    """
    网口配置。

    存储系统网络接口的名称、IP 地址等元信息，用于后端服务
    在连接机器人或摄像头时选择正确的网卡。

    注意：仅存储配置信息，不执行操作系统级别的网口启停命令。

    字段说明：
    - name: 唯一标识符，如 "robot_link"
    - label: 人类可读标签，如 "连接宇树 B2 的网口"
    - iface_name: 系统网卡名，如 "enP3p49s0"、"eth0"
    - ip_address: 静态 IP 地址
    - purpose: 用途分类（robot / camera / other）
    """

    __tablename__ = "network_interfaces"

    iface_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False,
        comment="唯一标识符，如 robot_link",
    )
    label: Mapped[str] = mapped_column(
        String(100), nullable=False,
        comment="人类可读标签，如 连接宇树 B2 的网口",
    )
    iface_name: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="系统网卡名，如 enP3p49s0、eth0",
    )
    ip_address: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
        comment="静态 IP 地址",
    )
    purpose: Mapped[str] = mapped_column(
        String(50), nullable=False, default="other",
        comment="用途分类：robot / camera / other",
    )
    enabled: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1,
        comment="是否启用：0=禁用，1=启用",
    )
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=utc_now_iso)
    updated_at: Mapped[str] = mapped_column(String, nullable=False, default=utc_now_iso)

    __table_args__ = (
        CheckConstraint("enabled IN (0, 1)", name="ck_network_interfaces_enabled"),
        CheckConstraint(
            "purpose IN ('robot', 'camera', 'other')",
            name="ck_network_interfaces_purpose",
        ),
    )
