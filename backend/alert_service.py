"""
告警服务模块。

职责边界：
- 处理温度告警事件
- 生成证据记录
- 广播告警消息
- 管理告警生命周期
"""

import asyncio
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from .temperature_monitor import TemperatureAlert
from .logging_config import logger
from .config import settings


@dataclass
class EvidenceRecord:
    """证据记录。"""
    task_id: Optional[int]
    event_type: str
    event_code: str
    severity: str
    message: str
    confidence: float
    file_path: Optional[str]
    gps_lat: Optional[float]
    gps_lon: Optional[float]


class AlertService:
    """
    告警服务。

    功能：
    - 处理温度告警
    - 生成证据记录
    - 存储到数据库
    - 广播告警消息
    """

    def __init__(self, event_broadcaster=None):
        """
        初始化告警服务。

        Args:
            event_broadcaster: 事件广播器实例（可选）
        """
        self._event_broadcaster = event_broadcaster
        self._active_alerts: Dict[str, TemperatureAlert] = {}
        self._evidence_counter = 0

    async def handle_temperature_alert(
        self,
        alert: TemperatureAlert,
        position: Optional[Dict[str, Any]] = None,
        task_id: Optional[int] = None,
        session: Optional[AsyncSession] = None,
    ) -> EvidenceRecord:
        """
        处理温度告警。

        Args:
            alert: 温度告警事件
            position: GPS 位置信息
            task_id: 任务 ID
            session: 数据库会话

        Returns:
            证据记录
        """
        logger.info(f"处理温度告警: {alert.temperature:.1f}°C")

        # 生成证据记录
        evidence = EvidenceRecord(
            task_id=task_id,
            event_type="THERMAL_HIGH",
            event_code="E_THERMAL_HIGH",
            severity="CRITICAL" if alert.temperature > 80 else "WARNING",
            message=f"检测到目标温度过高 ({alert.temperature:.1f}°C)",
            confidence=min(100.0, (alert.temperature / alert.threshold) * 100),
            file_path=None,  # TODO: 实现截图功能
            gps_lat=position.get("lat") if position else None,
            gps_lon=position.get("lon") if position else None,
        )

        # 存储到数据库
        if session:
            try:
                await self._store_evidence(evidence, session)
                logger.info(f"证据记录已保存: {evidence.event_type}")
            except Exception as e:
                logger.error(f"保存证据记录失败: {e}")

        # 广播告警（如果有 WebSocket 连接）
        await self._broadcast_alert(alert, evidence)

        return evidence

    async def _store_evidence(
        self,
        evidence: EvidenceRecord,
        session: AsyncSession,
    ) -> None:
        """
        存储证据到数据库。

        Args:
            evidence: 证据记录
            session: 数据库会话
        """
        from .models import AnomalyEvidence

        db_evidence = AnomalyEvidence(
            task_id=evidence.task_id,
            event_type=evidence.event_type,
            event_code=evidence.event_code,
            severity=evidence.severity,
            message=evidence.message,
            confidence=evidence.confidence,
            file_path=evidence.file_path,
            gps_lat=evidence.gps_lat,
            gps_lon=evidence.gps_lon,
            created_at=datetime.utcnow(),
        )

        session.add(db_evidence)
        await session.commit()

    async def _broadcast_alert(
        self,
        alert: TemperatureAlert,
        evidence: EvidenceRecord,
    ) -> None:
        """
        广播告警消息。

        Args:
            alert: 温度告警
            evidence: 证据记录
        """
        # 使用注入的 broadcaster 实例
        if self._event_broadcaster is None:
            # 回退到全局单例
            from .global_event_broadcaster import get_global_event_broadcaster
            self._event_broadcaster = get_global_event_broadcaster()
            logger.debug(f"使用回退的全局 broadcaster: {id(self._event_broadcaster)}")

        await self._event_broadcaster.broadcast_alert(
            event_type=evidence.event_type,
            event_code=evidence.event_code,
            severity=evidence.severity,
            message=evidence.message,
            evidence_id=None,  # TODO: 从数据库获取
            image_url=evidence.file_path,
            gps_lat=evidence.gps_lat,
            gps_lon=evidence.gps_lon,
            confidence=evidence.confidence,
            temperature=alert.temperature,
            threshold=alert.threshold,
        )

        logger.info(
            f"告警已广播: {evidence.event_code} - {evidence.message}"
        )

    def get_active_alerts(self) -> Dict[str, TemperatureAlert]:
        """
        获取活跃的告警。

        Returns:
            活跃告警字典
        """
        return self._active_alerts.copy()

    def clear_alert(self, alert_id: str) -> None:
        """
        清除告警。

        Args:
            alert_id: 告警 ID
        """
        if alert_id in self._active_alerts:
            del self._active_alerts[alert_id]
            logger.info(f"告警已清除: {alert_id}")


# 全局告警服务实例
_alert_service: Optional[AlertService] = None


def get_alert_service() -> AlertService:
    """
    获取告警服务实例。

    Returns:
        告警服务实例
    """
    global _alert_service
    if _alert_service is None:
        # 尝试获取全局 broadcaster
        try:
            from .global_event_broadcaster import get_global_event_broadcaster
            event_broadcaster = get_global_event_broadcaster()
            logger.debug(f"创建 AlertService，注入 broadcaster ID: {id(event_broadcaster)}")
        except Exception:
            event_broadcaster = None
            logger.debug("创建 AlertService，无 broadcaster")

        _alert_service = AlertService(event_broadcaster=event_broadcaster)
    return _alert_service


def set_alert_service(service: AlertService) -> None:
    """
    设置告警服务实例。

    Args:
        service: 告警服务实例
    """
    global _alert_service
    _alert_service = service
