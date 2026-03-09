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
    evidences: Mapped[list["AnomalyEvidence"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="selectin",
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
    task_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("inspection_tasks.task_id", ondelete="CASCADE"),
        nullable=False,
    )

    event_type: Mapped[str] = mapped_column(String, nullable=False)
    event_code: Mapped[str | None] = mapped_column(String)
    severity: Mapped[str] = mapped_column(String, nullable=False, default="CRITICAL")
    message: Mapped[str | None] = mapped_column(Text)

    confidence: Mapped[float | None] = mapped_column(Float)

    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    image_url: Mapped[str | None] = mapped_column(Text)

    gps_lat: Mapped[float | None] = mapped_column(Float)
    gps_lon: Mapped[float | None] = mapped_column(Float)

    created_at: Mapped[str] = mapped_column(String, nullable=False, default=utc_now_iso)

    task: Mapped[InspectionTask] = relationship(back_populates="evidences")

    __table_args__ = (
        CheckConstraint(
            "severity IN ('INFO', 'WARN', 'ERROR', 'CRITICAL')",
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

