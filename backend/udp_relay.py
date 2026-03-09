#!/usr/bin/env python3
"""
UDP 零拷贝转发器。

职责边界：
- 从指定网卡接收边缘端 UDP/RTP 视频流
- 转发给本地 WebRTC 模块（不重新编码）
- 统计丢包率和网络延迟
- 支持多客户端转发

部署位置：后端服务器
依赖：asyncio, socket
"""

import asyncio
import logging
import socket
import time
from collections import deque
from typing import Optional, Tuple

from .logging_config import logger
from .config import settings


class UDPRelayStats:
    """
    UDP 转发统计信息。

    跟踪转发器的性能指标。
    """

    def __init__(self, max_samples: int = 100):
        """
        初始化统计信息。

        Args:
            max_samples: 保留的最大样本数
        """
        self.max_samples = max_samples
        self.packets_received = 0
        self.packets_sent = 0
        self.packets_dropped = 0
        self.bytes_transferred = 0
        self._latencies = deque(maxlen=max_samples)
        self._start_time = time.time()

    def record_packet(self, size: int, latency_ms: float) -> None:
        """
        记录数据包信息。

        Args:
            size: 数据包大小（字节）
            latency_ms: 延迟（毫秒）
        """
        self.packets_received += 1
        self.packets_sent += 1
        self.bytes_transferred += size
        self._latencies.append(latency_ms)

    def record_drop(self) -> None:
        """记录丢包。"""
        self.packets_received += 1
        self.packets_dropped += 1

    @property
    def packet_loss_rate(self) -> float:
        """丢包率（百分比）。"""
        if self.packets_received == 0:
            return 0.0
        return (self.packets_dropped / self.packets_received) * 100.0

    @property
    def avg_latency_ms(self) -> float:
        """平均延迟（毫秒）。"""
        if not self._latencies:
            return 0.0
        return sum(self._latencies) / len(self._latencies)

    @property
    def bandwidth_mbps(self) -> float:
        """带宽使用率（Mbps）。"""
        elapsed = time.time() - self._start_time
        if elapsed == 0:
            return 0.0
        return (self.bytes_transferred * 8) / (elapsed * 1_000_000)

    def reset(self) -> None:
        """重置统计信息。"""
        self.packets_received = 0
        self.packets_sent = 0
        self.packets_dropped = 0
        self.bytes_transferred = 0
        self._latencies.clear()
        self._start_time = time.time()

    def get_summary(self) -> dict:
        """
        获取统计摘要。

        Returns:
            统计信息字典
        """
        return {
            "packets_received": self.packets_received,
            "packets_sent": self.packets_sent,
            "packets_dropped": self.packets_dropped,
            "packet_loss_rate": round(self.packet_loss_rate, 2),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "bandwidth_mbps": round(self.bandwidth_mbps, 2),
            "uptime_seconds": round(time.time() - self._start_time, 2),
        }


class UDPRelay:
    """
    UDP 零拷贝转发器。

    从指定网卡的 UDP 端口接收数据，并转发给本地目标端口。
    使用 asyncio 实现高性能非阻塞转发。
    """

    def __init__(
        self,
        listen_port: int,
        bind_address: str,
        target_port: int,
        target_address: str = "127.0.0.1",
        buffer_size: int = 65536,
        enable_stats: bool = True,
        stats_interval: float = 5.0,
    ):
        """
        初始化 UDP 转发器。

        Args:
            listen_port: 监听端口（接收边缘端流）
            bind_address: 绑定地址（硬件网卡 IP）
            target_port: 目标端口（本地 WebRTC 接收端口）
            target_address: 目标地址（默认本地回环）
            buffer_size: UDP 缓冲区大小（字节）
            enable_stats: 是否启用统计
            stats_interval: 统计日志输出间隔（秒）
        """
        self.listen_port = listen_port
        self.bind_address = bind_address
        self.target_port = target_port
        self.target_address = target_address
        self.buffer_size = buffer_size
        self.enable_stats = enable_stats
        self.stats_interval = stats_interval

        self._socket: Optional[socket.socket] = None
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._stats_task: Optional[asyncio.Task] = None
        self.stats = UDPRelayStats() if enable_stats else None

        logger.info(
            f"UDP 转发器已初始化: {bind_address}:{listen_port} -> "
            f"{target_address}:{target_port}"
        )

    async def start(self) -> None:
        """启动转发器。"""
        try:
            # 创建 UDP socket
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, self.buffer_size)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, self.buffer_size)

            # 绑定到指定网卡
            self._socket.bind((self.bind_address, self.listen_port))

            # ⚠️ 不设置非阻塞模式，因为我们在 executor 中使用同步操作
            # self._socket.setblocking(False)

            self._running = True

            # 启动转发任务
            self._task = asyncio.create_task(self._relay_loop())

            # 启动统计任务
            if self.enable_stats:
                self._stats_task = asyncio.create_task(self._stats_loop())

            logger.info(
                f"UDP 转发器已启动: "
                f"监听 {self.bind_address}:{self.listen_port} "
                f"转发到 {self.target_address}:{self.target_port}"
            )

        except Exception as e:
            logger.error(f"UDP 转发器启动失败: {e}")
            raise

    async def stop(self) -> None:
        """停止转发器。"""
        if not self._running:
            return

        self._running = False

        # 取消任务
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        if self._stats_task:
            self._stats_task.cancel()
            try:
                await self._stats_task
            except asyncio.CancelledError:
                pass
            self._stats_task = None

        # 关闭 socket
        if self._socket:
            self._socket.close()
            self._socket = None

        # 输出最终统计
        if self.stats:
            summary = self.stats.get_summary()
            logger.info(
                f"UDP 转发器已停止: "
                f"总转发 {summary['packets_sent']} 包, "
                f"丢包率 {summary['packet_loss_rate']}%, "
                f"平均延迟 {summary['avg_latency_ms']}ms"
            )

    async def _relay_loop(self) -> None:
        """转发主循环。"""
        loop = asyncio.get_event_loop()

        while self._running:
            try:
                # 异步接收数据（使用 run_in_executor 兼容 Python 3.10）
                data, addr = await loop.run_in_executor(
                    None,
                    lambda: self._socket.recvfrom(self.buffer_size)
                )

                if not self._running:
                    break

                # 记录接收时间
                recv_time = time.time()

                # 异步转发（使用 run_in_executor 兼容 Python 3.10）
                await loop.run_in_executor(
                    None,
                    lambda: self._socket.sendto(data, (self.target_address, self.target_port))
                )

                # 记录统计
                if self.stats:
                    latency_ms = (time.time() - recv_time) * 1000.0
                    self.stats.record_packet(len(data), latency_ms)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"UDP 转发错误: {e}, 类型: {type(e).__name__}")
                import traceback
                logger.debug(f"UDP 转发错误堆栈:\n{traceback.format_exc()}")
                if self.stats:
                    self.stats.record_drop()
                # 短暂休眠避免 CPU 占用
                await asyncio.sleep(0.01)

    async def _stats_loop(self) -> None:
        """统计日志循环。"""
        while self._running:
            try:
                await asyncio.sleep(self.stats_interval)
                if self.stats:
                    summary = self.stats.get_summary()
                    logger.info(
                        f"UDP 转发统计: "
                        f"接收 {summary['packets_received']} 包, "
                        f"转发 {summary['packets_sent']} 包, "
                        f"丢失 {summary['packets_dropped']} 包 "
                        f"({summary['packet_loss_rate']}%), "
                        f"延迟 {summary['avg_latency_ms']}ms, "
                        f"带宽 {summary['bandwidth_mbps']}Mbps"
                    )
            except asyncio.CancelledError:
                break

    @property
    def is_running(self) -> bool:
        """转发器是否运行中。"""
        return self._running


class UDPRelayManager:
    """
    UDP 转发器管理器。

    管理多个 UDP 转发器实例，支持动态添加和删除转发规则。
    """

    def __init__(self):
        """初始化管理器。"""
        self._relays: dict[str, UDPRelay] = {}
        self._lock = asyncio.Lock()

    async def add_relay(
        self,
        name: str,
        listen_port: int,
        bind_address: str,
        target_port: int,
        target_address: str = "127.0.0.1",
        **kwargs,
    ) -> UDPRelay:
        """
        添加转发器。

        Args:
            name: 转发器名称
            listen_port: 监听端口
            bind_address: 绑定地址
            target_port: 目标端口
            target_address: 目标地址
            **kwargs: 其他转发器参数

        Returns:
            UDPRelay 实例
        """
        async with self._lock:
            if name in self._relays:
                raise ValueError(f"转发器已存在: {name}")

            relay = UDPRelay(
                listen_port=listen_port,
                bind_address=bind_address,
                target_port=target_port,
                target_address=target_address,
                **kwargs,
            )

            await relay.start()
            self._relays[name] = relay
            return relay

    async def remove_relay(self, name: str) -> None:
        """
        移除转发器。

        Args:
            name: 转发器名称
        """
        async with self._lock:
            relay = self._relays.pop(name, None)
            if relay:
                await relay.stop()

    async def stop_all(self) -> None:
        """停止所有转发器。"""
        async with self._lock:
            for relay in self._relays.values():
                await relay.stop()
            self._relays.clear()

    def get_relay(self, name: str) -> Optional[UDPRelay]:
        """
        获取转发器。

        Args:
            name: 转发器名称

        Returns:
            UDPRelay 实例或 None
        """
        return self._relays.get(name)

    def get_all_stats(self) -> dict[str, dict]:
        """
        获取所有转发器的统计信息。

        Returns:
            统计信息字典
        """
        stats = {}
        for name, relay in self._relays.items():
            if relay.stats:
                stats[name] = relay.stats.get_summary()
        return stats
