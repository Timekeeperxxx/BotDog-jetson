"""Deterministic heartbeat state for the ROS navigation velocity relay."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class VelocityHeartbeatSample:
    vx: float
    vy: float
    vyaw: float
    reason: str
    command_age_s: float | None


class NavigationVelocityHeartbeat:
    """Hold the latest already-filtered velocity for a short, bounded interval."""

    def __init__(
        self,
        *,
        command_timeout_s: float = 0.25,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not math.isfinite(command_timeout_s) or command_timeout_s <= 0.0:
            raise ValueError("command_timeout_s must be finite and positive")
        self._command_timeout_s = float(command_timeout_s)
        self._clock = clock
        self._latest_velocity = (0.0, 0.0, 0.0)
        self._last_command_at: float | None = None

    @property
    def command_timeout_s(self) -> float:
        return self._command_timeout_s

    def update(self, vx: float, vy: float, vyaw: float) -> None:
        velocity = (float(vx), float(vy), float(vyaw))
        if not all(math.isfinite(value) for value in velocity):
            raise ValueError("navigation velocity contains a non-finite value")
        self._latest_velocity = velocity
        self._last_command_at = self._clock()

    def sample(self) -> VelocityHeartbeatSample:
        now = self._clock()
        if self._last_command_at is None:
            return VelocityHeartbeatSample(0.0, 0.0, 0.0, "awaiting_command", None)

        age = max(0.0, now - self._last_command_at)
        if age >= self._command_timeout_s:
            return VelocityHeartbeatSample(0.0, 0.0, 0.0, "command_stale", age)

        vx, vy, vyaw = self._latest_velocity
        return VelocityHeartbeatSample(vx, vy, vyaw, "active", age)
