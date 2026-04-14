from enum import Enum
from pydantic import BaseModel

class GuardMissionState(str, Enum):
    """机器狗要害区域驱离任务的状态"""
    STANDBY = "STANDBY"                  # 起点待命，蹲坐监控
    DEPLOYING = "DEPLOYING"              # 起立并前往驱离点
    GUARDING = "GUARDING"                # 驱离点播放警告音驱离
    RETURNING = "RETURNING"              # 返回起点（不检测，不允许再次触发）
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"  # 人工接管，当前任务已中止
    FAULT = "FAULT"                      # 异常（如流断开、控制命令被拒等）

class GuardStatusDTO(BaseModel):
    """驱离任务当前状态"""
    enabled: bool
    state: GuardMissionState
    intrusion_counter: int
    confirm_frames: int
    clear_counter: int
    clear_frames: int
    guard_duration_s: float
