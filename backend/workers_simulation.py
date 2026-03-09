"""
本地模拟数据闭环 Worker。

职责：
- 周期性生成遥测样本，写入 `telemetry_snapshots`；
- 以较低概率生成一条异常证据写入 `anomaly_evidence`；
- 仅在开发/演示环境启用，真实环境应由 MAVLink 网关与 AI 告警替代。
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime
from typing import Dict

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_session_factory
from .logging_config import logger
from .models import AnomalyEvidence, InspectionTask, TelemetrySnapshot
from .services_telemetry import generate_fake_sample


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="milliseconds") + "Z"


async def _get_latest_running_task(session: AsyncSession) -> InspectionTask | None:
    stmt: Select[tuple[InspectionTask]] = (
        select(InspectionTask)
        .where(InspectionTask.status == "running")
        .order_by(InspectionTask.started_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def simulation_worker(stop_event: asyncio.Event) -> None:
    """
    模拟数据 Worker。

    行为：
    - 若无 running 状态任务，则空转等待；
    - 按固定间隔生成一条遥测快照写入 DB；
    - 以小概率（默认 5%）写入一条异常证据，便于前端联调。
    """

    session_factory = get_session_factory()
    seq: int = 0

    logger.info("模拟数据Worker已启动")
    try:
        while not stop_event.is_set():
            async with session_factory() as session:
                task = await _get_latest_running_task(session)
                if task is None:
                    # 无运行中的任务，稍后重试
                    await asyncio.sleep(1.0)
                    continue

                seq += 1
                sample = generate_fake_sample(seq)

                # 写入遥测快照
                snapshot = TelemetrySnapshot(
                    task_id=task.task_id,
                    timestamp=_utc_now_iso(),
                    gps_lat=sample.lat,
                    gps_lon=sample.lon,
                    gps_alt=sample.alt,
                    hdg=sample.hdg,
                    att_pitch=sample.pitch,
                    att_roll=sample.roll,
                    att_yaw=sample.yaw,
                    battery_voltage=sample.voltage,
                    battery_remaining_pct=sample.remaining_pct,
                )
                session.add(snapshot)

                # 5% 概率写入一条模拟异常证据
                if random.random() < 0.05:
                    evidence = AnomalyEvidence(
                        task_id=task.task_id,
                        event_type="thermal_high",
                        event_code="E_THERMAL_HIGH",
                        severity="CRITICAL",
                        message="模拟高温告警（Fake Data）",
                        confidence=0.98,
                        file_path="/data/snapshots/FAKE/fake_img.jpg",
                        image_url="/api/v1/static/snapshots/FAKE/fake_img.jpg",
                        gps_lat=sample.lat,
                        gps_lon=sample.lon,
                    )
                    session.add(evidence)

                await session.commit()

            await asyncio.sleep(0.5)  # 2Hz 写入频率
    except asyncio.CancelledError:
        logger.info("模拟数据Worker已取消")
    except Exception as exc:  # noqa: BLE001
        logger.exception("模拟数据Worker错误: {}", exc)
    finally:
        logger.info("模拟数据Worker已停止")

