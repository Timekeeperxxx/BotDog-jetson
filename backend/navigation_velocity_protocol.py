"""Shared wire contract for the loopback navigation velocity channel."""

from __future__ import annotations

import math
import struct


NAVIGATION_VELOCITY_UDP_HOST = "127.0.0.1"
NAVIGATION_VELOCITY_UDP_PORT = 52345
NAVIGATION_VELOCITY_TIMEOUT_S = 0.5
NAVIGATION_VELOCITY_PACKET = struct.Struct("ddd")


def pack_navigation_velocity(vx: float, vy: float, vyaw: float) -> bytes:
    values = (float(vx), float(vy), float(vyaw))
    if not all(math.isfinite(value) for value in values):
        raise ValueError("velocity contains a non-finite value")
    return NAVIGATION_VELOCITY_PACKET.pack(*values)
