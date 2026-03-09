"""
MAVLink 网关数据传输对象（DTO）。

职责边界：
- 定义内部使用的遥测数据结构
- 作为 MAVLink 报文与 WebSocket 消息之间的中间表示
- 提供类型安全的数据访问接口
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class AttitudeDTO:
    """
    姿态数据传输对象。

    对应 MAVLink 消息：
    - ATTITUDE (#30): pitch, roll, yaw (弧度)
    """

    pitch: float  # 俯仰角（弧度，-π ~ π）
    roll: float   # 横滚角（弧度，-π ~ π）
    yaw: float    # 偏航角（弧度，0 ~ 2π）


@dataclass(frozen=True)
class PositionDTO:
    """
    位置数据传输对象。

    对应 MAVLink 消息：
    - GLOBAL_POSITION_INT (#33): lat, lon, alt, hdg
    """

    lat: float   # 纬度（度，-90 ~ 90）
    lon: float   # 经度（度，-180 ~ 180）
    alt: float   # 相对高度（米）
    hdg: float   # 航向角（度，0 ~ 360）


@dataclass(frozen=True)
class BatteryDTO:
    """
    电池状态数据传输对象。

    对应 MAVLink 消息：
    - SYS_STATUS (#1): battery_remaining
    - BATTERY_STATUS (#1): voltage, current
    """

    voltage: float         # 电压（伏特）
    remaining_pct: int     # 剩余电量百分比（0-100）


@dataclass(frozen=True)
class SystemStatusDTO:
    """
    系统状态数据传输对象。

    对应 MAVLink 消息：
    - HEARTBEAT (#0): type, autopilot, base_mode
    """

    armed: bool           # 是否已解锁（电机可运行）
    mode: str             # 飞行模式（如 "STABILIZE", "AUTO" 等）
    mavlink_connected: bool  # MAVLink 链路是否连通


@dataclass
class TelemetrySnapshotDTO:
    """
    遥测快照数据传输对象。

    用途：
    - 整合姿态、位置、电池等完整遥测数据
    - 作为 WebSocket 广播的消息载荷
    - 作为数据库落盘的输入数据
    """

    attitude: Optional[AttitudeDTO] = None
    position: Optional[PositionDTO] = None
    battery: Optional[BatteryDTO] = None
    system_status: Optional[SystemStatusDTO] = None

    def is_complete(self) -> bool:
        """
        判断快照是否包含完整的遥测数据。

        完整性定义：
        - 至少包含姿态或位置数据之一
        - 包含电池数据
        - 包含系统状态数据
        """
        return (
            (self.attitude is not None or self.position is not None)
            and self.battery is not None
            and self.system_status is not None
        )


@dataclass(frozen=True)
class ThermalExtDTO:
    """
    热成像扩展数据传输对象。

    对应 MAVLink 消息：
    - NAMED_VALUE_FLOAT (#251): name="T_MAX", value=温度值
    """

    t_max: float  # 最高温度（摄氏度）
    timestamp: float  # Unix 时间戳（秒）
