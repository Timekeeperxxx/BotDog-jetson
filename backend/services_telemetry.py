"""
遥测服务层。

当前阶段仍使用模拟数据，后续会接入 MAVLink 网关：
- 此模块对上提供统一的“遥测样本”生成接口；
- 对下可以替换为 UDP/串口读取、队列消费等实现，而不影响 WS 层。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from math import sin


@dataclass
class TelemetrySample:
    timestamp: float
    pitch: float
    roll: float
    yaw: float
    lat: float
    lon: float
    alt: float
    hdg: float
    voltage: float
    remaining_pct: int


def generate_fake_sample(seq: int) -> TelemetrySample:
    """
    生成一条可视化效果稍微真实一点的模拟遥测数据。
    后续可由真实 MAVLink 数据源替换。
    """

    now = time.time()
    # 简单的正弦波模拟姿态变化
    pitch = 0.05 * sin(seq / 10)
    roll = -0.05 * sin(seq / 15)
    yaw = 180.0 + 5.0 * sin(seq / 20)

    lat = 39.9 + 0.0001 * sin(seq / 50)
    lon = 116.4 + 0.0001 * sin(seq / 60)
    alt = 1.2 + 0.1 * sin(seq / 30)
    hdg = yaw

    voltage = 84.2
    remaining_pct = max(20, 82 - seq // 600)  # 逐步缓慢下降，但不低于 20%

    return TelemetrySample(
        timestamp=now,
        pitch=pitch,
        roll=roll,
        yaw=yaw,
        lat=lat,
        lon=lon,
        alt=alt,
        hdg=hdg,
        voltage=voltage,
        remaining_pct=remaining_pct,
    )

