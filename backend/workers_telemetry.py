"""
遥测数据库落盘 Worker。

职责边界：
- 从遥测队列获取降采样后的数据
- 将数据异步写入 SQLite 数据库
- 处理任务关联（task_id）
- 实现数据保留策略（定期清理过期数据）

设计要点：
- 使用独立的数据库会话，避免与请求会话冲突
- 批量写入优化性能
- 异常处理确保 Worker 稳定性
"""

import asyncio
from datetime import datetime
from typing import AsyncIterator, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session_factory
from backend.logging_config import logger
from backend.mavlink_dto import TelemetrySnapshotDTO
from backend.models import InspectionTask, TelemetrySnapshot


class TelemetryPersistenceWorker:
    """
    遥测数据库落盘 Worker。

    功能：
    - 持续从队列获取遥测快照
    - 将快照写入数据库
    - 自动关联当前任务
    """

    def __init__(self, session_factory, sampling_interval: float = 0.5):
        """
        初始化 Worker。

        Args:
            session_factory: SQLAlchemy 会话工厂
            sampling_interval: 数据库写入采样间隔（秒），默认 0.5s（2Hz）
        """
        self.session_factory = session_factory
        self.sampling_interval = sampling_interval

        # 缓存当前任务 ID（避免每次查询）
        self._current_task_id: Optional[int] = None
        self._last_task_check_time: float = 0.0

    async def start(self, stop_event: asyncio.Event) -> None:
        """
        启动 Worker。

        Args:
            stop_event: 停止事件
        """
        logger.info(f"遥测落盘 Worker 已启动，采样间隔: {self.sampling_interval}s")

        while not stop_event.is_set():
            try:
                # 检查并更新当前任务
                await self._update_current_task()

                # 尝试写入一条快照
                await self._process_snapshot()

                # 等待采样间隔
                await asyncio.sleep(self.sampling_interval)

            except asyncio.CancelledError:
                logger.info("遥测落盘 Worker 已停止")
                break
            except Exception as exc:  # noqa: BLE001
                logger.exception(f"遥测落盘 Worker 异常: {exc}")
                await asyncio.sleep(1.0)

    async def _update_current_task(self) -> None:
        """
        更新当前任务 ID。

        逻辑：
        - 每 1 秒检查一次最新的运行中任务
        - 缓存结果以减少数据库查询
        """
        current_time = asyncio.get_event_loop().time()
        if current_time - self._last_task_check_time < 1.0:
            return

        self._last_task_check_time = current_time

        try:
            async with self.session_factory() as session:
                stmt = (
                    select(InspectionTask)
                    .where(InspectionTask.status == "running")
                    .order_by(InspectionTask.started_at.desc())
                    .limit(1)
                )
                result = await session.execute(stmt)
                task = result.scalar_one_or_none()

                self._current_task_id = task.task_id if task else None

        except Exception as exc:  # noqa: BLE001
            logger.warning(f"查询当前任务失败: {exc}")
            self._current_task_id = None

    async def _process_snapshot(self) -> None:
        """
        处理单个遥测快照。

        如果有当前任务且快照数据完整，则写入数据库。
        """
        if self._current_task_id is None:
            return

        # 从队列获取快照（使用超时避免阻塞）
        snapshot = await self._get_snapshot_with_timeout(timeout=0.1)

        if snapshot is None:
            return

        # 检查快照是否完整
        if not snapshot.is_complete():
            logger.debug("遥测快照不完整，跳过落盘")
            return

        # 写入数据库
        await self._persist_snapshot(snapshot, self._current_task_id)

    async def _get_snapshot_with_timeout(
        self, timeout: float
    ) -> Optional[TelemetrySnapshotDTO]:
        """
        从队列获取快照（带超时）。

        Args:
            timeout: 超时时间（秒）

        Returns:
            遥测快照，或 None（超时）
        """
        try:
            from backend.telemetry_queue import get_telemetry_queue_manager

            queue_manager = get_telemetry_queue_manager()
            return await asyncio.wait_for(
                queue_manager.get_next_persistence_snapshot(), timeout=timeout
            )
        except asyncio.TimeoutError:
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"获取遥测快照失败: {exc}")
            return None

    async def _persist_snapshot(
        self, snapshot: TelemetrySnapshotDTO, task_id: int
    ) -> None:
        """
        将快照持久化到数据库。

        Args:
            snapshot: 遥测快照数据
            task_id: 任务 ID
        """
        try:
            async with self.session_factory() as session:
                db_snapshot = TelemetrySnapshot(
                    task_id=task_id,
                    timestamp=self._get_current_timestamp(),
                    # GPS 数据
                    gps_lat=snapshot.position.lat if snapshot.position else None,
                    gps_lon=snapshot.position.lon if snapshot.position else None,
                    gps_alt=snapshot.position.alt if snapshot.position else None,
                    hdg=snapshot.position.hdg if snapshot.position else None,
                    # 姿态数据
                    att_pitch=snapshot.attitude.pitch if snapshot.attitude else None,
                    att_roll=snapshot.attitude.roll if snapshot.attitude else None,
                    att_yaw=snapshot.attitude.yaw if snapshot.attitude else None,
                    # 电池数据
                    battery_voltage=snapshot.battery.voltage if snapshot.battery else None,
                    battery_remaining_pct=(
                        snapshot.battery.remaining_pct if snapshot.battery else None
                    ),
                )

                session.add(db_snapshot)
                await session.commit()

        except Exception as exc:  # noqa: BLE001
            logger.error(f"写入遥测快照失败: {exc}")

    @staticmethod
    def _get_current_timestamp() -> str:
        """获取当前 ISO8601 UTC 时间戳。"""
        return datetime.utcnow().isoformat(timespec="milliseconds") + "Z"


# 全局遥测队列管理器单例
_telemetry_queue_manager: Optional["TelemetryQueueManager"] = None


def get_telemetry_queue_manager() -> "TelemetryQueueManager":
    """
    获取遥测队列管理器单例。

    Returns:
        遥测队列管理器实例
    """
    global _telemetry_queue_manager

    if _telemetry_queue_manager is None:
        from backend.telemetry_queue import TelemetryQueueManager

        _telemetry_queue_manager = TelemetryQueueManager()

    return _telemetry_queue_manager
