"""Loopback-only navigation velocity ingress for the single B2 adapter."""

from __future__ import annotations

import asyncio
import math
import socket
import struct
import threading
import time
from collections.abc import Callable
from typing import Any

from .control_arbiter import ControlArbiter
from .control_service import ControlService
from .logging_config import get_logger
from .tracking_types import ControlOwner


NAVIGATION_VELOCITY_UDP_HOST = "127.0.0.1"
NAVIGATION_VELOCITY_UDP_PORT = 52345
NAVIGATION_VELOCITY_TIMEOUT_S = 0.5
NAVIGATION_VELOCITY_PACKET = struct.Struct("ddd")

DATAGRAM_ACCEPTED = "accepted"
DATAGRAM_REJECTED_SOURCE = "rejected_source"
DATAGRAM_REJECTED_SIZE = "rejected_size"
DATAGRAM_REJECTED_VALUE = "rejected_value"
DATAGRAM_REJECTED_OWNER = "rejected_owner"
DATAGRAM_REJECTED_CONTROL = "rejected_control"

_STOP_ON_NAVIGATION_DEPARTURE = frozenset(
    {ControlOwner.NONE, ControlOwner.E_STOP}
)

logger = get_logger("NavigationVelocityUDP")


class NavigationVelocityUdpService:
    """Receive ROS velocity samples without creating another SportClient."""

    def __init__(
        self,
        *,
        control_service: ControlService,
        control_arbiter: ControlArbiter,
        host: str = NAVIGATION_VELOCITY_UDP_HOST,
        port: int = NAVIGATION_VELOCITY_UDP_PORT,
        timeout_s: float = NAVIGATION_VELOCITY_TIMEOUT_S,
        clock: Callable[[], float] = time.monotonic,
        poll_interval_s: float = 0.02,
    ) -> None:
        if host != NAVIGATION_VELOCITY_UDP_HOST:
            raise ValueError("navigation velocity UDP must bind to 127.0.0.1")
        if not 0 < port <= 65535:
            raise ValueError("navigation velocity UDP port is invalid")
        if timeout_s <= 0:
            raise ValueError("navigation velocity timeout must be positive")
        if poll_interval_s <= 0:
            raise ValueError("navigation velocity poll interval must be positive")

        self._control_service = control_service
        self._control_arbiter = control_arbiter
        self._host = host
        self._port = port
        self._timeout_s = timeout_s
        self._clock = clock
        self._poll_interval_s = min(poll_interval_s, timeout_s / 2.0)

        self._socket: socket.socket | None = None
        self._bound = threading.Event()
        self._running = False
        self._closed = False
        self._last_error: str | None = None

        self._stream_active = False
        self._last_datagram_at: float | None = None
        self._pending_departure_stop: ControlOwner | None = None

        self._received_count = 0
        self._accepted_count = 0
        self._rejected_count = 0
        self._stop_count = 0

        self._control_arbiter.add_owner_change_listener(self._on_owner_change)

    @property
    def is_ready(self) -> bool:
        return self._bound.is_set() and self._socket is not None

    def bind(self) -> None:
        """Bind synchronously so app startup can guarantee listener readiness."""
        if self.is_ready:
            return
        if self._closed:
            raise RuntimeError("navigation velocity UDP service is closed")

        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_socket.setblocking(False)
        try:
            udp_socket.bind((self._host, self._port))
        except Exception as exc:
            udp_socket.close()
            self._last_error = str(exc)
            raise

        self._socket = udp_socket
        self._bound.set()
        self._last_error = None
        logger.info(
            "Navigation velocity UDP listener bound: {}:{}",
            self._host,
            self._port,
        )

    async def run(self, stop_event: asyncio.Event) -> None:
        """Run the receive loop until application shutdown."""
        self.bind()
        udp_socket = self._socket
        if udp_socket is None:
            raise RuntimeError("navigation velocity UDP socket is unavailable")

        self._running = True
        loop = asyncio.get_running_loop()
        try:
            while not stop_event.is_set():
                await self.poll_safety()
                try:
                    # Python 3.10's selector loop has sock_recv(), but not
                    # sock_recvfrom(). The socket itself is loopback-bound.
                    payload = await asyncio.wait_for(
                        loop.sock_recv(udp_socket, 4096),
                        timeout=self._poll_interval_s,
                    )
                except asyncio.TimeoutError:
                    continue
                await self.handle_datagram(payload)
        except asyncio.CancelledError:
            raise
        except OSError as exc:
            if not stop_event.is_set():
                self._last_error = str(exc)
                logger.exception("Navigation velocity UDP receive failed: {}", exc)
                raise
        finally:
            self._running = False
            self.close()

    async def handle_datagram(
        self,
        payload: bytes,
        *,
        source: tuple[str, int] | None = None,
    ) -> str:
        """Validate and dispatch one datagram; callable directly in unit tests."""
        self._received_count += 1
        await self.poll_safety()

        if source is not None and source[0] != NAVIGATION_VELOCITY_UDP_HOST:
            self._rejected_count += 1
            return DATAGRAM_REJECTED_SOURCE

        if len(payload) != NAVIGATION_VELOCITY_PACKET.size:
            self._rejected_count += 1
            return DATAGRAM_REJECTED_SIZE

        try:
            vx, vy, vyaw = NAVIGATION_VELOCITY_PACKET.unpack(payload)
        except struct.error:
            self._rejected_count += 1
            return DATAGRAM_REJECTED_SIZE

        if not all(math.isfinite(value) for value in (vx, vy, vyaw)):
            self._rejected_count += 1
            return DATAGRAM_REJECTED_VALUE

        if self._control_arbiter.owner != ControlOwner.NAVIGATION:
            self._rejected_count += 1
            return DATAGRAM_REJECTED_OWNER

        accepted = await self._control_service.send_navigation_velocity(vx, vy, vyaw)
        if not accepted:
            self._rejected_count += 1
            return DATAGRAM_REJECTED_CONTROL

        self._last_datagram_at = self._clock()
        self._stream_active = True
        self._pending_departure_stop = None
        self._accepted_count += 1
        return DATAGRAM_ACCEPTED

    async def poll_safety(self) -> None:
        """Apply owner transitions, E-stop, and the velocity stream timeout."""
        await self._flush_pending_departure_stop()

        owner = self._control_arbiter.owner
        if not self._stream_active:
            return

        if self._control_service.is_e_stop_active() or owner == ControlOwner.E_STOP:
            self._deactivate_stream()
            await self._send_stop_once("e_stop")
            return

        if owner != ControlOwner.NAVIGATION:
            self._deactivate_stream()
            if owner in _STOP_ON_NAVIGATION_DEPARTURE:
                await self._send_stop_once(f"owner_{owner.value.lower()}")
            return

        if self._last_datagram_at is None:
            return
        if self._clock() - self._last_datagram_at >= self._timeout_s:
            self._deactivate_stream()
            await self._send_stop_once("datagram_timeout")

    def close(self) -> None:
        """Close the listener and detach the owner observer."""
        if self._closed:
            return
        self._closed = True
        self._control_arbiter.remove_owner_change_listener(self._on_owner_change)
        udp_socket = self._socket
        self._socket = None
        self._bound.clear()
        if udp_socket is not None:
            udp_socket.close()
        logger.info("Navigation velocity UDP listener stopped")

    def get_status(self) -> dict[str, Any]:
        return {
            "ready": self.is_ready,
            "running": self._running,
            "host": self._host,
            "port": self._port,
            "timeout_s": self._timeout_s,
            "stream_active": self._stream_active,
            "owner": self._control_arbiter.owner.value,
            "received_count": self._received_count,
            "accepted_count": self._accepted_count,
            "rejected_count": self._rejected_count,
            "stop_count": self._stop_count,
            "last_error": self._last_error,
        }

    def _on_owner_change(
        self,
        previous: ControlOwner,
        current: ControlOwner,
    ) -> None:
        if previous == ControlOwner.NAVIGATION and current != ControlOwner.NAVIGATION:
            had_active_stream = self._stream_active
            self._deactivate_stream()
            if had_active_stream and current in _STOP_ON_NAVIGATION_DEPARTURE:
                self._pending_departure_stop = current
            else:
                self._pending_departure_stop = None
            return

        if (
            self._pending_departure_stop is not None
            and current not in _STOP_ON_NAVIGATION_DEPARTURE
        ):
            self._pending_departure_stop = None

    async def _flush_pending_departure_stop(self) -> None:
        pending_owner = self._pending_departure_stop
        if pending_owner is None:
            return
        self._pending_departure_stop = None

        current_owner = self._control_arbiter.owner
        if current_owner not in _STOP_ON_NAVIGATION_DEPARTURE:
            return
        await self._send_stop_once(f"owner_{current_owner.value.lower()}")

    async def _send_stop_once(self, reason: str) -> None:
        self._stop_count += 1
        if reason in {"e_stop", "owner_e_stop"}:
            logger.warning(
                "Hard-stopping navigation velocity stream for system E-stop: reason={}",
                reason,
            )
            await self._control_service.force_stop()
            return

        logger.warning(
            "Soft-stopping stale navigation velocity stream with zero velocity: reason={}",
            reason,
        )
        accepted = await self._control_service.send_navigation_velocity(0.0, 0.0, 0.0)
        if not accepted:
            logger.error(
                "Failed to send zero velocity for stale navigation stream: reason={}",
                reason,
            )

    def _deactivate_stream(self) -> None:
        self._stream_active = False
        self._last_datagram_at = None


_navigation_velocity_udp_service: NavigationVelocityUdpService | None = None


def set_navigation_velocity_udp_service(
    service: NavigationVelocityUdpService | None,
) -> None:
    global _navigation_velocity_udp_service
    _navigation_velocity_udp_service = service


def get_navigation_velocity_udp_service() -> NavigationVelocityUdpService | None:
    return _navigation_velocity_udp_service


def is_navigation_velocity_udp_ready() -> bool:
    service = get_navigation_velocity_udp_service()
    return service is not None and service.is_ready


def get_navigation_velocity_udp_status() -> dict[str, Any]:
    service = get_navigation_velocity_udp_service()
    if service is None:
        return {
            "ready": False,
            "running": False,
            "host": NAVIGATION_VELOCITY_UDP_HOST,
            "port": NAVIGATION_VELOCITY_UDP_PORT,
            "last_error": "not_started",
        }
    return service.get_status()
