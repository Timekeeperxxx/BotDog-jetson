"""
自动跟踪类型定义模块。

职责边界：
- 定义跟踪状态枚举 AutoTrackState（7态闭环）
- 定义停止原因枚举 TrackStopReason
- 定义控制拥有者枚举 ControlOwner
- 定义核心数据 DTO：TargetCandidate、ActiveTarget、TrackDecision、DetectionResult

不包含任何业务逻辑，仅定义类型。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ─── 状态枚举 ────────────────────────────────────────────────────────────────

class AutoTrackState(str, Enum):
    """
    自动跟踪7态闭环状态枚举。

    状态转换链：
        DISABLED ──enable()──► IDLE
        IDLE ──发现 person──► DETECTING
        DETECTING ──stable_hits 帧──► FOLLOWING
        FOLLOWING ──丢失 1 帧──► LOST
        LOST ──重发现同 track_id──► FOLLOWING
        LOST ──超时──► IDLE
        FOLLOWING/LOST ──出区/外部停止──► STOPPED
        STOPPED ──自动──► IDLE
        任意 ──人工接管──► PAUSED
    """

    DISABLED   = "DISABLED"    # 功能开关关闭
    IDLE       = "IDLE"        # 无目标，等待
    DETECTING  = "DETECTING"   # 发现候选，正在积累命中帧
    FOLLOWING  = "FOLLOWING"   # 目标锁定，持续发送控制命令
    LOST       = "LOST"        # 短暂丢失，等待重新发现
    STOPPED    = "STOPPED"     # 本轮跟踪终止
    PAUSED     = "PAUSED"      # 人工控制接管暂停


class TrackStopReason(str, Enum):
    """跟踪停止原因枚举。"""

    OUT_OF_ZONE    = "OUT_OF_ZONE"    # 目标出重点区超时
    TARGET_LOST    = "TARGET_LOST"    # 目标丢失超时
    MANUAL         = "MANUAL"         # 人工接管 / 外部调用
    MISSION_ENDED  = "MISSION_ENDED"  # 任务停止
    DISABLED       = "DISABLED"       # 功能关闭
    E_STOP         = "E_STOP"         # 急停
    VIDEO_LOST     = "VIDEO_LOST"     # 视频流断开
    MARKED_KNOWN   = "MARKED_KNOWN"   # 目标被标记为已知人员


class ControlOwner(str, Enum):
    """控制权拥有者枚举（ControlArbiter 使用）。"""

    NONE               = "NONE"
    AUTO_TRACK         = "AUTO_TRACK"
    WEB_MANUAL         = "WEB_MANUAL"
    REMOTE_CONTROLLER  = "REMOTE_CONTROLLER"
    E_STOP             = "E_STOP"


# ─── 数据 DTO ────────────────────────────────────────────────────────────────

@dataclass
class DetectionResult:
    """
    单次检测结果（来自 YOLO track/detect 的输出项）。

    track_id：
        - YOLO track 模式下由 ByteTrack/BoT-SORT 分配，跨帧稳定。
        - predict 降级模式下为 -1。
    """

    bbox: tuple[int, int, int, int]   # (x1, y1, x2, y2)
    confidence: float
    class_name: str = "person"
    track_id: int = -1                # YOLO 分配的稳定跨帧 ID，-1 表示无


@dataclass
class TargetCandidate:
    """
    候选跟踪目标（DETECTING 阶段使用）。

    track_id 优先使用 YOLO 分配的稳定 ID；
    降级时使用帧间 IOU 生成的临时 ID。
    """

    track_id: int
    bbox: tuple[int, int, int, int]          # (x1, y1, x2, y2) 图像像素坐标
    confidence: float
    anchor_point: tuple[int, int]             # 底部中心点 (cx, y2)
    inside_zone: bool
    first_seen_ts: float
    last_seen_ts: float
    stable_hits: int = 0
    is_known_person: bool = False
    manual_ignored: bool = False

    @classmethod
    def from_detection(
        cls,
        track_id: int,
        bbox: tuple[int, int, int, int],
        confidence: float,
        inside_zone: bool,
        ts: float,
    ) -> "TargetCandidate":
        x1, y1, x2, y2 = bbox
        cx = (x1 + x2) // 2
        return cls(
            track_id=track_id,
            bbox=bbox,
            confidence=confidence,
            anchor_point=(cx, y2),
            inside_zone=inside_zone,
            first_seen_ts=ts,
            last_seen_ts=ts,
            stable_hits=1,
        )


@dataclass
class ActiveTarget:
    """当前正在跟踪的活跃目标（FOLLOWING / LOST 阶段使用）。"""

    track_id: int
    bbox: tuple[int, int, int, int]
    anchor_point: tuple[int, int]
    inside_zone: bool
    locked_at: float                              # 进入 FOLLOWING 的时刻
    last_seen_ts: float                           # 最后一次检测到的时刻
    lost_count: int = 0                           # 连续未检测到帧数
    follow_started_at: Optional[float] = None     # 开始跟踪的时刻（与 locked_at 相同）
    out_of_zone_count: int = 0                    # 连续出区帧计数


@dataclass
class TrackDecision:
    """跟踪决策结果（FollowDecisionEngine 输出）。"""

    command: Optional[str] = None     # "left"/"right"/"forward"/"stop"/None (兼容旧接口，现可传 "velocity")
    should_send: bool = False         # 是否实际下发（节流/防抖判断后）
    reason: str = ""
    vx: float = 0.0                   # 线速度（比例控制使用）
    vyaw: float = 0.0                 # 角速度（比例控制使用）
