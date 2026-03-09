"""
遥测队列管理器。

职责边界：
- 管理遥测数据的两个内部队列（广播队列 + 落盘队列）
- 提供高频数据降采样逻辑（避免数据库写入过频）
- 维护 WebSocket 客户端连接池
- 协调多个消费者（广播 Worker + 落盘 Worker）
"""

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional, Set

from backend.logging_config import logger
from backend.mavlink_dto import TelemetrySnapshotDTO


@dataclass
class TelemetryQueueManager:
    """
    遥测队列管理器。

    功能：
    - 接收 MAVLink 解析的遥测数据
    - 维护滑动窗口，实现降采样
    - 提供广播队列供 WebSocket 使用
    - 提供落盘队列供数据库 Worker 使用
    """

    sampling_interval: float = 0.5  # 降采样间隔（秒），默认 2Hz
    broadcast_queue_size: int = 100  # 广播队列大小
    persistence_queue_size: int = 1000  # 落盘队列大小

    # 内部队列
    _broadcast_queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=100))
    _persistence_queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=1000))

    # 滑动窗口用于降采样
    _snapshot_buffer: deque = field(default_factory=lambda: deque(maxlen=50))

    # WebSocket 客户端连接池
    _ws_clients: Set[Any] = field(default_factory=set)

    # 时间戳记录（用于降采样）
    _last_broadcast_time: float = 0.0
    _last_persistence_time: float = 0.0

    def add_telemetry(self, snapshot: TelemetrySnapshotDTO) -> None:
        """
        添加遥测快照到缓冲区。

        Args:
            snapshot: 遥测快照数据
        """
        self._snapshot_buffer.append((time.monotonic(), snapshot))

    async def get_next_broadcast_snapshot(self) -> TelemetrySnapshotDTO:
        """
        从广播队列获取下一个快照（用于 WebSocket 广播）。

        Returns:
            遥测快照数据

        Raises:
            asyncio.CancelledError: 任务被取消
        """
        return await self._broadcast_queue.get()

    async def get_next_persistence_snapshot(self) -> TelemetrySnapshotDTO:
        """
        从落盘队列获取下一个快照（用于数据库写入）。

        Returns:
            遥测快照数据

        Raises:
            asyncio.CancelledError: 任务被取消
        """
        return await self._persistence_queue.get()

    def add_ws_client(self, ws: Any) -> None:
        """
        添加 WebSocket 客户端到连接池。

        Args:
            ws: WebSocket 连接对象
        """
        self._ws_clients.add(ws)
        logger.info(f"WebSocket 客户端已加入，当前连接数: {len(self._ws_clients)}")

    def remove_ws_client(self, ws: Any) -> None:
        """
        从连接池移除 WebSocket 客户端。

        Args:
            ws: WebSocket 连接对象
        """
        if ws in self._ws_clients:
            self._ws_clients.remove(ws)
            logger.info(f"WebSocket 客户端已断开，当前连接数: {len(self._ws_clients)}")

    def get_ws_clients(self) -> Set[Any]:
        """获取当前所有 WebSocket 客户端。"""
        return self._ws_clients.copy()

    async def start_sampling_task(self, stop_event: asyncio.Event) -> None:
        """
        启动降采样任务。

        该任务会定期从缓冲区提取最新快照，放入对应的队列。

        Args:
            stop_event: 停止事件
        """
        logger.info(f"遥测降采样任务已启动，间隔: {self.sampling_interval}s")

        while not stop_event.is_set():
            try:
                await asyncio.sleep(self.sampling_interval)
                await self._process_samples()
            except asyncio.CancelledError:
                logger.info("遥测降采样任务已停止")
                break
            except Exception as exc:  # noqa: BLE001
                logger.exception("遥测降采样任务异常: {}", exc)

    async def _process_samples(self) -> None:
        """
        处理采样逻辑。

        从缓冲区提取最新快照，并放入广播队列和落盘队列。
        """
        current_time = time.monotonic()

        # 过滤过期数据（超过 1 秒的丢弃）
        valid_samples = [
            (ts, snapshot)
            for ts, snapshot in self._snapshot_buffer
            if current_time - ts < 1.0
        ]

        if not valid_samples:
            return

        # 取最新的快照
        latest_ts, latest_snapshot = valid_samples[-1]

        # 广播队列：高频采样（约 15Hz）
        if current_time - self._last_broadcast_time >= 0.067:  # 1/15 ≈ 0.067s
            await self._put_to_broadcast_queue(latest_snapshot)
            self._last_broadcast_time = current_time

        # 落盘队列：低频采样（可配置，默认 2Hz）
        if current_time - self._last_persistence_time >= self.sampling_interval:
            await self._put_to_persistence_queue(latest_snapshot)
            self._last_persistence_time = current_time

    async def _put_to_broadcast_queue(self, snapshot: TelemetrySnapshotDTO) -> None:
        """
        放入广播队列。

        如果队列满，丢弃最旧的数据。
        """
        try:
            self._broadcast_queue.put_nowait(snapshot)
        except asyncio.QueueFull:
            # 队列满，丢弃最旧的数据
            try:
                self._broadcast_queue.get_nowait()
                self._broadcast_queue.put_nowait(snapshot)
            except asyncio.QueueEmpty:
                pass

    async def _put_to_persistence_queue(self, snapshot: TelemetrySnapshotDTO) -> None:
        """
        放入落盘队列。

        如果队列满，丢弃最旧的数据。
        """
        try:
            self._persistence_queue.put_nowait(snapshot)
        except asyncio.QueueFull:
            # 队列满，丢弃最旧的数据
            try:
                self._persistence_queue.get_nowait()
                self._persistence_queue.put_nowait(snapshot)
            except asyncio.QueueEmpty:
                pass


# 全局遥测队列管理器单例（供 Worker 在无法直接注入时兜底获取）
_telemetry_queue_manager: Optional[TelemetryQueueManager] = None


def set_telemetry_queue_manager(queue_manager: TelemetryQueueManager) -> None:
    """
    设置全局遥测队列管理器。

    Args:
        queue_manager: 由应用生命周期创建的 TelemetryQueueManager 实例
    """
    global _telemetry_queue_manager
    _telemetry_queue_manager = queue_manager


def get_telemetry_queue_manager() -> TelemetryQueueManager:
    """
    获取全局遥测队列管理器。

    Returns:
        TelemetryQueueManager 实例
    """
    global _telemetry_queue_manager

    if _telemetry_queue_manager is None:
        _telemetry_queue_manager = TelemetryQueueManager()

    return _telemetry_queue_manager
