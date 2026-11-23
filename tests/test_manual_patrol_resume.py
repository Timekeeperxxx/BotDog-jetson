import struct
import time

import pytest

from backend import manual_patrol_resume as module
from backend.control_arbiter import ControlArbiter
from backend.tracking_types import ControlOwner


class Patrol:
    def __init__(self, monkeypatch):
        self.time = 10.0
        self.phase = ("run-a", "running")
        self.commands = []
        self.pose_valid = True
        self.estop = False
        self.navigator_ready = True
        self.arbiter = ControlArbiter()
        self.arbiter.request_control(ControlOwner.NAVIGATION)
        self.service = module.ManualPatrolResume(self.arbiter, lambda: self.time)
        monkeypatch.setattr(module, "get_ros_nav_bridge", lambda: self)
        monkeypatch.setattr(module, "get_task_route_phase", lambda: self.phase)
        monkeypatch.setattr(module, "get_robot_pose", lambda: (
            {"ros_timestamp": time.time()} if self.pose_valid else None))
        monkeypatch.setattr(module, "get_cmd_vel_estop_status", lambda: {"active": self.estop})

    def publish_task_manual_control(self, run_id, *, paused):
        if not self.navigator_ready:
            return False
        self.commands.append((run_id, paused))
        self.phase = (run_id, "paused" if paused else "ready")
        return True

    def web_move(self):
        self.arbiter.request_control(ControlOwner.WEB_MANUAL)
        self.service.web_motion()

    def web_release(self, accepted=True):
        generation = self.service.web_stop_requested(release=True)
        self.service.web_stop_confirmed(generation, accepted=accepted)

    def step(self, delta):
        self.time += delta
        self.service.tick()

    def remote(self, moving, buttons=False):
        self.service.observe_remote(self.time, (moving, buttons))

    def center(self, count):
        for _ in range(count):
            self.time += 0.1
            self.remote(False)
            self.service.tick()


@pytest.fixture
def patrol(monkeypatch):
    return Patrol(monkeypatch)


def test_web_release_waits_for_both_delay_and_fresh_path(patrol):
    patrol.web_move()
    patrol.step(5)
    assert patrol.commands == [("run-a", True)]
    patrol.web_release()
    patrol.step(2.49)
    assert patrol.commands == [("run-a", True)]
    patrol.step(0.02)
    assert patrol.commands == [("run-a", True), ("run-a", False)]
    assert patrol.arbiter.owner == ControlOwner.WEB_MANUAL
    assert patrol.service.holds_navigation
    patrol.phase = ("run-a", "running")
    patrol.step(0.01)
    assert patrol.arbiter.owner == ControlOwner.NAVIGATION
    assert not patrol.service.holds_navigation


def test_motion_during_resume_repauses_same_run(patrol):
    patrol.web_move()
    patrol.web_release()
    patrol.step(2.6)
    patrol.web_move()
    assert patrol.commands == [("run-a", True), ("run-a", False), ("run-a", True)]
    assert patrol.arbiter.owner == ControlOwner.WEB_MANUAL
    patrol.step(3)
    assert len(patrol.commands) == 3


def test_older_stop_confirmation_cannot_release_new_motion(patrol):
    patrol.web_move()
    generation = patrol.service.web_stop_requested(release=True)
    patrol.web_move()
    patrol.service.web_stop_confirmed(generation, accepted=True)
    patrol.step(3)
    assert patrol.commands == [("run-a", True)]


@pytest.mark.parametrize("blocker", ["manual_stop", "failed_stop", "pose", "estop", "changed_run", "ended_task"])
def test_explicit_stops_and_invalid_state_do_not_resume(patrol, blocker):
    patrol.web_move()
    if blocker == "manual_stop":
        patrol.service.web_stop_requested(release=False)
    elif blocker == "failed_stop":
        patrol.web_release(accepted=False)
    else:
        patrol.web_release()
        if blocker == "pose":
            patrol.pose_valid = False
        elif blocker == "estop":
            patrol.estop = True
        elif blocker == "changed_run":
            patrol.phase = ("run-b", "running")
        else:
            patrol.arbiter.release_control(ControlOwner.NAVIGATION)
    patrol.step(3)
    assert patrol.commands == [("run-a", True)]


def test_remote_requires_continuous_valid_centering_and_both_inputs_released(patrol):
    patrol.remote(True)
    assert patrol.arbiter.owner == ControlOwner.REMOTE_CONTROLLER
    patrol.center(10)
    patrol.step(3)  # No fresh remote frames.
    assert patrol.commands == [("run-a", True)]
    patrol.web_move()
    patrol.center(28)
    assert patrol.commands == [("run-a", True)]
    patrol.web_release()
    patrol.center(28)
    assert patrol.commands == [("run-a", True), ("run-a", False)]
    patrol.phase = ("run-a", "running")
    patrol.center(1)
    assert patrol.arbiter.owner == ControlOwner.NAVIGATION


def test_remote_loss_and_failed_pause_keep_old_velocity_blocked(patrol):
    patrol.navigator_ready = False
    patrol.remote(True)
    patrol.step(3)
    assert patrol.arbiter.owner == ControlOwner.REMOTE_CONTROLLER
    patrol.center(28)
    assert patrol.service.holds_navigation
    assert patrol.commands == []


def test_stale_pose_after_replan_requests_pause_and_blocks_velocity(patrol):
    patrol.remote(True)
    patrol.center(28)
    assert patrol.commands == [("run-a", True), ("run-a", False)]
    patrol.phase = ("run-a", "running")
    patrol.pose_valid = False
    patrol.center(1)
    assert patrol.commands == [("run-a", True), ("run-a", False), ("run-a", True)]
    assert patrol.service.holds_navigation


def test_unitree_b2_lowstate_joystick_axes_and_absence():
    packet = bytearray(40)
    assert module.decode_unitree_remote(bytes(packet)) is None
    packet[:2] = b"\xfe\xef"
    assert module.decode_unitree_remote(bytes(packet)) == (False, False)
    struct.pack_into("<f", packet, 20, -0.21)
    assert module.decode_unitree_remote(bytes(packet)) == (True, False)
    struct.pack_into("<f", packet, 20, 0)
    struct.pack_into("<H", packet, 2, 0x0002)
    assert module.decode_unitree_remote(bytes(packet)) == (False, True)
    struct.pack_into("<H", packet, 2, 0x1000)
    assert module.decode_unitree_remote(bytes(packet)) == (True, False)
    struct.pack_into("<f", packet, 4, float("nan"))
    assert module.decode_unitree_remote(bytes(packet)) is None


def test_remote_release_does_not_restart_unidentified_navigation(patrol):
    patrol.phase = None
    patrol.remote(True)
    patrol.center(28)
    assert patrol.service.holds_navigation
    assert patrol.commands == []
    patrol.service.cancel()
    assert not patrol.service.holds_navigation
