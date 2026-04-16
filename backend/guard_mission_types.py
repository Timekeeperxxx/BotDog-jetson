from enum import Enum
from pydantic import BaseModel

class GuardMissionState(str, Enum):
    """机器狗要害区域驱离任务的状态 - 视觉伺服大改版"""
    STANDBY = "STANDBY"                  # 起点待命，蹲坐监控
    LOCK_ANCHOR = "LOCK_ANCHOR"          # 触发警戒，正在锁死背景锚点
    ADVANCING = "ADVANCING"              # 锁定锚点，视觉全自动逼近中
    RETURNING = "RETURNING"              # 锚点闭环返航中
    LOST_ANCHOR = "LOST_ANCHOR"          # 【视觉专有】由于剧烈遮挡丢失了防区大门视野，需要复位
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"  # 人工接管，当前任务已中止
    FAULT = "FAULT"                      # 异常（如流断开、控制命令被拒等）

class AnchorStatusDTO(BaseModel):
    """背景锚点目前的跟踪特征状态"""
    is_tracking: bool
    bounding_box: list[int]  # [x, y, w, h]
    
class GuardStatusDTO(BaseModel):
    """驱离任务当前状态"""
    enabled: bool
    state: GuardMissionState
    intrusion_counter: int
    confirm_frames: int
    clear_counter: int
    clear_frames: int
    guard_duration_s: float
    zone_quality: float = 0.0    # 当前帧区域检测质量 0-1
    zone_lost_frames: int = 0   # 连续丢失帧数
    current_zone_bbox: list[int] | None = None  # 当前区域 bbox [x, y, w, h]
    start_zone_bbox: list[int] | None = None    # 起始区域 bbox [x, y, w, h]（驱离开始时记录）
