"""Hold a patrol during manual driving and replan its current waypoint on release."""

from __future__ import annotations

import asyncio
import math
import struct
import time

from .control_arbiter import ControlArbiter
from .logging_config import get_logger
from .nav_bridge_state import get_ros_nav_bridge
from .services_nav_localization_process import get_cmd_vel_estop_status
from .services_nav_state import ROBOT_POSE_STALE_SECONDS, get_robot_pose, get_task_route_phase
from .tracking_types import ControlOwner

RESUME_DELAY_S = 2.5
REMOTE_FRAME_TIMEOUT_S = 0.4
REMOTE_STICK_DEADBAND = 0.05
WEB_MOVEMENT = frozenset({"forward", "backward", "left", "right", "strafe_left", "strafe_right"})
logger = get_logger("手动巡检接管")


def decode_unitree_remote(packet: bytes) -> tuple[bool, bool] | None:
    """Decode stick/D-pad movement and other buttons from B2 LowState."""
    if len(packet) != 40 or not any(packet):
        return None  # The B2 sends an all-zero buffer with no remote input.
    buttons = struct.unpack_from("<H", packet, 2)[0]
    axes = [struct.unpack_from("<f", packet, offset)[0] for offset in (4, 8, 12, 20)]
    if not all(math.isfinite(axis) and abs(axis) <= 1.0 for axis in axes):
        return None
    moving = bool(buttons & 0xF000) or any(abs(axis) > REMOTE_STICK_DEADBAND for axis in axes)
    return moving, bool(buttons & 0x0FFF)


class ManualPatrolResume:
    def __init__(self, arbiter: ControlArbiter, clock=time.monotonic) -> None:
        self._arbiter = arbiter
        self._clock = clock
        self._run_id: str | None = None
        self._unidentified_navigation_held = False
        self._resume_sent = False
        self._resume_inhibited = False
        self._web_generation = 0
        self._web_moving = False
        self._web_ready_at: float | None = None
        self._remote_stamp: float | None = None
        self._remote_centered_since: float | None = None

    @property
    def holds_navigation(self) -> bool:
        return self._run_id is not None or self._unidentified_navigation_held

    def cancel(self) -> None:
        self._run_id = None
        self._unidentified_navigation_held = False
        self._resume_sent = False
        self._resume_inhibited = False
        self._web_generation += 1
        self._web_moving = False
        self._web_ready_at = None

    def web_motion(self) -> None:
        self._web_generation += 1
        self._web_moving = True
        self._web_ready_at = None
        self._pause_patrol()

    def web_stop_requested(self, *, release: bool) -> int | None:
        if release and not self._web_moving:
            return None
        self._web_generation += 1
        self._web_ready_at = None
        if release:
            return self._web_generation
        self._web_moving = False
        if self._resume_sent:
            self._pause_patrol()
        self._resume_inhibited = True
        return None

    def web_stop_confirmed(self, generation: int, *, accepted: bool) -> None:
        if generation != self._web_generation:
            return
        self._web_moving = False
        if accepted:
            self._web_ready_at = self._clock() + RESUME_DELAY_S
        else:
            self._resume_inhibited = True

    def observe_remote(self, stamp: float, decoded: tuple[bool, bool] | None) -> None:
        if stamp == self._remote_stamp:
            return
        if (self._remote_stamp is None or stamp - self._remote_stamp > REMOTE_FRAME_TIMEOUT_S
                or decoded is None):
            self._remote_centered_since = None
        self._remote_stamp = stamp
        if decoded is None:
            return
        moving, other_buttons = decoded
        remote = ControlOwner.REMOTE_CONTROLLER
        if moving or other_buttons:
            if self._arbiter.is_e_stop_active():
                return
            self._remote_centered_since = None
            self._arbiter.request_control(remote)
            self._pause_patrol()
            if other_buttons and not moving:
                self._resume_inhibited = True
        elif self._arbiter.has_request(remote) and self._remote_centered_since is None:
            self._remote_centered_since = stamp

    def _pause_patrol(self) -> None:
        if self._arbiter.is_e_stop_active() or not self._arbiter.has_request(ControlOwner.NAVIGATION):
            return
        if self._run_id is not None and not self._resume_sent:
            return
        phase = get_task_route_phase()
        if (phase is None or (phase[0] != self._run_id
                and phase[1] not in {"planning", "ready", "running"})):
            # Do not return control to a single-point or unknown navigation run.
            self._unidentified_navigation_held = True
            return
        run_id, _ = phase
        self._unidentified_navigation_held = False
        if run_id != self._run_id:
            self._resume_inhibited = False
        self._run_id = run_id
        self._resume_sent = False
        bridge = get_ros_nav_bridge()
        if bridge is None or not bridge.publish_task_manual_control(run_id, paused=True):
            logger.warning("任务导航器未确认可用，保留手动控制：run_id={}", run_id)
            self._resume_inhibited = True
            return
        logger.info("已请求暂停巡检：run_id={}", run_id)

    def _remote_is_released(self, now: float) -> bool:
        if not self._arbiter.has_request(ControlOwner.REMOTE_CONTROLLER):
            return True
        return (self._remote_stamp is not None and self._remote_centered_since is not None
                and now - self._remote_stamp <= REMOTE_FRAME_TIMEOUT_S
                and now - self._remote_centered_since >= RESUME_DELAY_S)

    def tick(self) -> None:
        now = self._clock()
        remote_released = self._remote_is_released(now)
        if self._run_id is not None:
            self._advance_patrol(now, remote_released)
        if (remote_released and (self._run_id is None or self._resume_inhibited)
                and self._arbiter.has_request(ControlOwner.REMOTE_CONTROLLER)):
            self._arbiter.release_control(ControlOwner.REMOTE_CONTROLLER)

    def _advance_patrol(self, now: float, remote_released: bool) -> None:
        phase = get_task_route_phase()
        if (not self._arbiter.has_request(ControlOwner.NAVIGATION)
                or self._arbiter.is_e_stop_active()
                or phase is None or phase[0] != self._run_id
                or phase[1] in {"completed", "failed", "canceled"}):
            self.cancel()
            return
        if self._resume_inhibited or not remote_released or self._web_moving:
            return
        if self._web_ready_at is not None and now < self._web_ready_at:
            return
        if self._arbiter.has_request(ControlOwner.WEB_MANUAL) and self._web_ready_at is None:
            return

        run_id, status = phase
        if status != ("running" if self._resume_sent else "paused"):
            return
        pose = get_robot_pose()
        ros_stamp = pose.get("ros_timestamp") if pose is not None else None
        if (get_cmd_vel_estop_status()["active"] or ros_stamp is None
                or not 0 <= time.time() - ros_stamp <= ROBOT_POSE_STALE_SECONDS):
            logger.warning("定位或急停状态阻止自动续跑：run_id={}", run_id)
            self._resume_inhibited = True
            if self._resume_sent:
                bridge = get_ros_nav_bridge()
                if bridge is not None:
                    bridge.publish_task_manual_control(run_id, paused=True)
            return

        if self._resume_sent:
            self.cancel()
            self._arbiter.release_control(ControlOwner.WEB_MANUAL)
            self._arbiter.release_control(ControlOwner.REMOTE_CONTROLLER)
            logger.info("已从当前航点恢复巡检：run_id={}", run_id)
            return

        bridge = get_ros_nav_bridge()
        if bridge is None or not bridge.publish_task_manual_control(run_id, paused=False):
            logger.warning("巡检恢复指令未发出，保留手动控制：run_id={}", run_id)
            self._resume_inhibited = True
            return
        self._resume_sent = True

    async def run(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            self.tick()
            await asyncio.sleep(0.05)


_manual_patrol_resume: ManualPatrolResume | None = None


def set_manual_patrol_resume(service: ManualPatrolResume | None) -> None:
    global _manual_patrol_resume
    _manual_patrol_resume = service


def get_manual_patrol_resume() -> ManualPatrolResume | None:
    return _manual_patrol_resume
