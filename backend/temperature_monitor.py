"""
温度监控模块。

职责边界：
- 监听 MAVLink 温度数据（NAMED_VALUE_FLOAT）
- 检测温度异常（T_MAX > threshold）
- 触发告警事件
- 与告警服务解耦
"""

import asyncio
from typing import Callable, Optional
from dataclasses import dataclass
from datetime import datetime

from .logging_config import logger
from .config import settings


@dataclass
class TemperatureAlert:
    """温度告警事件。"""
    timestamp: float
    temperature: float
    threshold: float
    source: str = "T_MAX"


class TemperatureMonitor:
    """
    温度监控器。

    功能：
    - 监控 MAVLink 消息中的温度值
    - 检测温度异常
    - 触发告警回调
    """

    def __init__(
        self,
        threshold: Optional[float] = None,
        on_alert: Optional[Callable[[TemperatureAlert], None]] = None,
    ):
        """
        初始化温度监控器。

        Args:
            threshold: 温度阈值，默认从配置读取
            on_alert: 告警回调函数
        """
        self._threshold = threshold or settings.THERMAL_THRESHOLD
        self._on_alert = on_alert
        self._current_temperature: Optional[float] = None
        self._last_alert_time: Optional[float] = None
        self._alert_cooldown = 10.0  # 告警冷却时间（秒）

    @property
    def threshold(self) -> float:
        """获取温度阈值。"""
        return self._threshold

    @threshold.setter
    def threshold(self, value: float) -> None:
        """设置温度阈值。"""
        if value != self._threshold:
            logger.info(f"温度阈值已更新: {self._threshold}°C -> {value}°C")
            self._threshold = value

    @property
    def current_temperature(self) -> Optional[float]:
        """获取当前温度。"""
        return self._current_temperature

    def update_temperature(self, name: str, value: float) -> None:
        """
        更新温度值。

        Args:
            name: 参数名称（如 "T_MAX"）
            value: 温度值
        """
        # 只处理 T_MAX 参数
        if name != "T_MAX":
            return

        self._current_temperature = value

        # 检查是否超过阈值
        if value > self._threshold:
            self._check_and_trigger_alert(value)

    def _check_and_trigger_alert(self, temperature: float) -> None:
        """
        检查并触发告警。

        Args:
            temperature: 当前温度值
        """
        current_time = asyncio.get_event_loop().time()

        # 检查冷却时间
        if self._last_alert_time is not None:
            elapsed = current_time - self._last_alert_time
            if elapsed < self._alert_cooldown:
                logger.debug(
                    f"温度告警冷却中，剩余 {self._alert_cooldown - elapsed:.1f} 秒"
                )
                return

        # 触发告警
        alert = TemperatureAlert(
            timestamp=current_time,
            temperature=temperature,
            threshold=self._threshold,
        )

        logger.warning(
            f"温度异常检测: {temperature:.1f}°C > {self._threshold:.1f}°C"
        )

        if self._on_alert:
            try:
                self._on_alert(alert)
            except Exception as e:
                logger.error(f"温度告警回调失败: {e}")

        self._last_alert_time = current_time

    def reset_cooldown(self) -> None:
        """重置告警冷却时间。"""
        self._last_alert_time = None
        logger.info("温度告警冷却已重置")

    def get_status(self) -> dict:
        """
        获取监控器状态。

        Returns:
            状态字典
        """
        return {
            "threshold": self._threshold,
            "current_temperature": self._current_temperature,
            "last_alert_time": self._last_alert_time,
            "in_cooldown": (
                self._last_alert_time is not None
                and (asyncio.get_event_loop().time() - self._last_alert_time)
                < self._alert_cooldown
            ),
        }
