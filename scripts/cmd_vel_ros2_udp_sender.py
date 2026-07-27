#!/usr/bin/env python3
"""Forward ROS2 /cmd_vel_safe samples to BotDog's loopback UDP ingress."""

from __future__ import annotations

import os
import socket
import sys
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

DEFAULT_TOPIC = "/cmd_vel_safe"


def encode_velocity(vx: float, vy: float, vyaw: float) -> bytes:
    return pack_navigation_velocity(vx, vy, vyaw)


class CmdVelRos2UdpSender(Node):
    """ROS-only sender; the BotDog backend remains the sole B2 SDK writer."""

    def __init__(self) -> None:
        super().__init__("cmd_vel_ros2_udp_sender")
        self.declare_parameter("cmd_vel_topic", DEFAULT_TOPIC)
        topic = str(self.get_parameter("cmd_vel_topic").value or DEFAULT_TOPIC)

        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.connect(
            (NAVIGATION_VELOCITY_UDP_HOST, NAVIGATION_VELOCITY_UDP_PORT)
        )
        self._closed = False
        self._ready_file = (
            Path(os.environ["BOTDOG_CMD_VEL_READY_FILE"]).resolve()
            if os.environ.get("BOTDOG_CMD_VEL_READY_FILE")
            else None
        )

        self.create_subscription(Twist, topic, self._on_cmd_vel, 10)
        if self._ready_file is not None:
            self._ready_file.parent.mkdir(parents=True, exist_ok=True)
            self._ready_file.write_text(f"{os.getpid()}\n", encoding="utf-8")

        self.get_logger().info(
            "CMD_VEL_UDP_SENDER_READY "
            f"topic={topic} "
            f"target={NAVIGATION_VELOCITY_UDP_HOST}:{NAVIGATION_VELOCITY_UDP_PORT}"
        )

    def _on_cmd_vel(self, msg: Twist) -> None:
        try:
            payload = encode_velocity(msg.linear.x, msg.linear.y, msg.angular.z)
        except (TypeError, ValueError) as exc:
            self.get_logger().error(f"拒绝非法 cmd_vel：{exc}")
            return

        try:
            self._socket.send(payload)
        except OSError as exc:
            self.get_logger().error(f"发送 cmd_vel UDP 数据失败：{exc}")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
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
