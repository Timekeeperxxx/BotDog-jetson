#!/usr/bin/env python3
"""Forward ROS2 /cmd_vel_safe to BotDog with a deterministic UDP heartbeat."""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
from pathlib import Path

BOTDOG_ROOT = Path(__file__).resolve().parents[1]
if str(BOTDOG_ROOT) not in sys.path:
    sys.path.insert(0, str(BOTDOG_ROOT))

import rclpy
from geometry_msgs.msg import Twist
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node

from backend.navigation_velocity_protocol import (
    NAVIGATION_VELOCITY_UDP_HOST,
    NAVIGATION_VELOCITY_UDP_PORT,
    pack_navigation_velocity,
)
from backend.navigation_velocity_heartbeat import NavigationVelocityHeartbeat

DEFAULT_TOPIC = "/cmd_vel_safe"
DEFAULT_SEND_RATE_HZ = 20.0
DEFAULT_COMMAND_TIMEOUT_S = 0.25


def encode_velocity(vx: float, vy: float, vyaw: float) -> bytes:
    return pack_navigation_velocity(vx, vy, vyaw)


class CmdVelRos2UdpSender(Node):
    """ROS-only sender; the BotDog backend remains the sole B2 SDK writer."""

    def __init__(self) -> None:
        super().__init__("cmd_vel_ros2_udp_sender")
        self.declare_parameter("cmd_vel_topic", DEFAULT_TOPIC)
        self.declare_parameter("send_rate_hz", DEFAULT_SEND_RATE_HZ)
        self.declare_parameter("cmd_vel_timeout", DEFAULT_COMMAND_TIMEOUT_S)
        topic = str(self.get_parameter("cmd_vel_topic").value or DEFAULT_TOPIC)
        send_rate_hz = float(self.get_parameter("send_rate_hz").value)
        command_timeout_s = float(self.get_parameter("cmd_vel_timeout").value)
        if not 1.0 <= send_rate_hz <= 100.0:
            raise ValueError("send_rate_hz must be within [1, 100]")
        self._heartbeat = NavigationVelocityHeartbeat(
            command_timeout_s=command_timeout_s,
        )
        self._send_period_s = 1.0 / send_rate_hz
        self._heartbeat_stop_event = threading.Event()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="cmd-vel-udp-heartbeat",
            daemon=True,
        )

        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.connect(
            (NAVIGATION_VELOCITY_UDP_HOST, NAVIGATION_VELOCITY_UDP_PORT)
        )
        self._closed = False
        self._last_velocity_log_at = float("-inf")
        self._last_reason: str | None = None
        self._ready_file = (
            Path(os.environ["BOTDOG_CMD_VEL_READY_FILE"]).resolve()
            if os.environ.get("BOTDOG_CMD_VEL_READY_FILE")
            else None
        )

        self.create_subscription(Twist, topic, self._on_cmd_vel, 10)
        # Keep the safety heartbeat independent from the ROS executor.  The
        # 100 Hz cmd_vel subscription can otherwise starve a ROS timer long
        # enough for the backend's 0.5 s datagram watchdog to stop the robot.
        self._heartbeat_thread.start()
        if self._ready_file is not None:
            self._ready_file.parent.mkdir(parents=True, exist_ok=True)
            self._ready_file.write_text(f"{os.getpid()}\n", encoding="utf-8")

        self.get_logger().info(
            "CMD_VEL_UDP_SENDER_READY "
            f"topic={topic} "
            f"send_rate_hz={send_rate_hz:.1f} "
            f"cmd_vel_timeout={command_timeout_s:.3f}s "
            f"target={NAVIGATION_VELOCITY_UDP_HOST}:{NAVIGATION_VELOCITY_UDP_PORT}"
        )

    def _on_cmd_vel(self, msg: Twist) -> None:
        try:
            self._heartbeat.update(msg.linear.x, msg.linear.y, msg.angular.z)
        except (TypeError, ValueError) as exc:
            self.get_logger().error(f"拒绝非法 cmd_vel：{exc}")

    def _send_heartbeat(self) -> None:
        sample = self._heartbeat.sample()
        try:
            payload = encode_velocity(sample.vx, sample.vy, sample.vyaw)
        except (TypeError, ValueError) as exc:
            self.get_logger().error(f"拒绝非法速度心跳：{exc}")
            return

        try:
            self._socket.send(payload)
        except OSError as exc:
            self.get_logger().error(f"发送 cmd_vel UDP 数据失败：{exc}")
            return

        if sample.reason != self._last_reason:
            previous_reason = self._last_reason
            self._last_reason = sample.reason
            if sample.reason == "command_stale":
                self.get_logger().warning(
                    "CMD_VEL_UDP_HEARTBEAT_ZERO "
                    f"reason={sample.reason} age={sample.command_age_s:.3f}s"
                )
            elif sample.reason == "active" and previous_reason is not None:
                self.get_logger().info("CMD_VEL_UDP_HEARTBEAT_RECOVERED")

        now = time.monotonic()
        if now - self._last_velocity_log_at >= 1.0:
            self._last_velocity_log_at = now
            age_text = (
                "none"
                if sample.command_age_s is None
                else f"{sample.command_age_s:.3f}"
            )
            self.get_logger().info(
                "CMD_VEL_UDP_SAMPLE "
                f"vx={sample.vx:.3f} vy={sample.vy:.3f} "
                f"vyaw={sample.vyaw:.3f} reason={sample.reason} "
                f"age={age_text}"
            )

    def _heartbeat_loop(self) -> None:
        next_send_at = time.monotonic()
        while not self._heartbeat_stop_event.is_set():
            self._send_heartbeat()
            next_send_at += self._send_period_s
            now = time.monotonic()
            if next_send_at < now - self._send_period_s:
                next_send_at = now
            self._heartbeat_stop_event.wait(max(0.0, next_send_at - now))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._heartbeat_stop_event.set()
        if self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=1.0)
        try:
            self._socket.send(encode_velocity(0.0, 0.0, 0.0))
        except OSError:
            pass
        self._socket.close()
        if self._ready_file is not None:
            self._ready_file.unlink(missing_ok=True)


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node: CmdVelRos2UdpSender | None = None
    try:
        node = CmdVelRos2UdpSender()
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if node is not None:
            node.close()
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
