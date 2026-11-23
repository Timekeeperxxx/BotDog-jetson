"""Read the existing GT-01 service and expose its current alarms to BotDog."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field, FiniteFloat, model_validator

GAS_READINGS_URL = "http://127.0.0.1:8787/api/gases"
FRESH_MAX_AGE_SECONDS = 180
CHANNEL_NAMES = {"ph3": "磷化氢（PH₃）", "co2": "二氧化碳（CO₂）", "o2": "氧气（O₂）", "dust": "粉尘"}
STATUS_LABELS = {
    0: "预热中", 2: "数据错误", 3: "传感器故障", 4: "预警", 5: "低报",
    6: "高报", 7: "访问故障", 8: "超量程", 9: "需要标定", 10: "超时",
    11: "STEL报警", 12: "TWA报警", 15: "通信故障",
}
CONCENTRATION_STATUS_CODES = {1, 4, 5, 6, 8, 11, 12}


class GasMonitorError(RuntimeError):
    pass


class SensorReading(BaseModel):
    value: FiniteFloat
    unit: str = Field(min_length=1)
    decimals: int = Field(ge=0, le=3)
    low_alarm: FiniteFloat
    high_alarm: FiniteFloat
    status_code: int
    cached: bool
    age_seconds: FiniteFloat = Field(ge=0)
    sampled_at: datetime

    @model_validator(mode="after")
    def validate_thresholds(self) -> SensorReading:
        if self.high_alarm <= self.low_alarm:
            raise ValueError("气体设备报警阈值无效")
        return self


class SensorSnapshot(BaseModel):
    read_at: datetime
    gases: dict[Literal["ph3", "co2", "o2"], SensorReading]
    dust: SensorReading | None


class GasAlarm(BaseModel):
    channel: str
    severity: Literal["WARNING", "CRITICAL"]
    kind: Literal["concentration", "sensor"]
    message: str
    stale: bool


class GasMonitorSnapshot(BaseModel):
    read_at: datetime
    alerts: list[GasAlarm]


def reading_alarm(channel: str, reading: SensorReading) -> GasAlarm | None:
    name = CHANNEL_NAMES[channel]
    stale = reading.cached or reading.age_seconds > FRESH_MAX_AGE_SECONDS
    code = reading.status_code
    if code not in CONCENTRATION_STATUS_CODES:
        label = STATUS_LABELS.get(code, f"未知状态（{code}）")
        return GasAlarm(channel=channel, severity="WARNING", kind="sensor", stale=stale,
                        message=f"{name} · {label}" + (" · 数据已过期" if stale else ""))

    severity: Literal["WARNING", "CRITICAL"] | None = None
    label = ""
    if code in {6, 8, 11, 12}:
        severity, label = "CRITICAL", STATUS_LABELS[code]
    elif code in {4, 5}:
        severity, label = "WARNING", STATUS_LABELS[code]

    if channel == "o2" and reading.value <= reading.low_alarm:
        severity, label = "CRITICAL", "低于下限"
    elif reading.value >= reading.high_alarm:
        severity, label = "CRITICAL", "超过上限"
    elif channel != "o2" and reading.value >= reading.low_alarm and severity != "CRITICAL":
        severity, label = "WARNING", "低报"

    if severity is not None:
        unit = {"%VOL": "% vol", "mg/m3": "mg/m³"}.get(reading.unit, reading.unit)
        value = f"{reading.value:.{reading.decimals}f} {unit}"
        message = f"{name} {value} · {label}"
        if stale:
            message = f"上次：{message} · 数据已过期"
        return GasAlarm(channel=channel, severity=severity, kind="concentration", message=message, stale=stale)
    if stale:
        return GasAlarm(channel=channel, severity="WARNING", kind="sensor", stale=True,
                        message=f"{name} · 数据已过期")
    return None


def evaluate_snapshot(snapshot: SensorSnapshot) -> GasMonitorSnapshot:
    alerts: list[GasAlarm] = []
    for channel, name in CHANNEL_NAMES.items():
        reading = snapshot.dust if channel == "dust" else snapshot.gases.get(channel)
        if reading is None:
            alerts.append(GasAlarm(channel=channel, severity="WARNING", kind="sensor", stale=True,
                                   message=f"{name} · 无数据"))
        else:
            alarm = reading_alarm(channel, reading)
            if alarm is not None:
                alerts.append(alarm)
    alerts.sort(key=lambda alarm: alarm.severity != "CRITICAL")
    return GasMonitorSnapshot(read_at=snapshot.read_at, alerts=alerts)


def read_gas_monitor() -> GasMonitorSnapshot:
    request = Request(GAS_READINGS_URL, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=3.0) as response:
            payload = json.load(response)
        return evaluate_snapshot(SensorSnapshot.model_validate(payload))
    except HTTPError as exc:
        raise GasMonitorError(f"气体监测服务异常（HTTP {exc.code}）") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise GasMonitorError("无法连接气体监测服务") from exc
    except (ValueError, TypeError) as exc:
        raise GasMonitorError("气体监测数据无效") from exc
