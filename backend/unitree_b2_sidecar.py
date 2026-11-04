"""Isolated Unitree B2 SportClient process.

The Unitree SDK owns a CycloneDDS participant.  Keeping it in the FastAPI
process (which also owns ROS 2 publishers/subscribers and telemetry DDS
callbacks) can make SportClient RPC calls return success while the B2 never
enters velocity mode.  The previously working dddmr bridge avoided that by
running SportClient in a dedicated process.  This module restores that process
boundary while the parent retains command arbitration and safety checks.
"""

from __future__ import annotations

import logging
import os
import time
from multiprocessing.connection import Connection
from typing import Any

logger = logging.getLogger(__name__)


def _clean_ros_environment() -> None:
    """Remove ROS middleware settings before importing the Unitree SDK."""
    exact = {
        "RMW_IMPLEMENTATION",
        "FASTRTPS_DEFAULT_PROFILES_FILE",
        "FASTDDS_DEFAULT_PROFILES_FILE",
        "CYCLONEDDS_URI",
        "AMENT_PREFIX_PATH",
        "COLCON_PREFIX_PATH",
        "CMAKE_PREFIX_PATH",
        "ROS_LOCALHOST_ONLY",
    }
    for key in list(os.environ):
        if key in exact or key.startswith("ROS_"):
            os.environ.pop(key, None)


def _reply(connection: Connection, payload: dict[str, Any]) -> None:
    # A failed reply means the parent channel is gone: exit through final stop.
    connection.send(payload)


def run_unitree_b2_sidecar(
    connection: Connection,
    network_interface: str,
    default_vx: float,
    default_vy: float,
    default_vyaw: float,
) -> None:
    """Own the sole B2 SportClient used for commands in this process."""
    _clean_ros_environment()
    client = None
    initialized = False
    ready_sent = False
    shutdown_requested = False
    try:
        from unitree_sdk2py.b2.sport.sport_client import SportClient
        from unitree_sdk2py.core.channel import ChannelFactoryInitialize

        ChannelFactoryInitialize(0, network_interface)
        client = SportClient()
        client.SetTimeout(1.5)
        client.Init()
        initialized = True
        _reply(
            connection,
            {
                "ready": True,
                "pid": os.getpid(),
                "sequence": "isolated_dddmr_sport_client",
            },
        )
        ready_sent = True

        while True:
            command = connection.recv()
            kind = command[0] if isinstance(command, tuple) else command
            if kind == "_STOP_AND_QUIT_":
                shutdown_requested = True
                break

            try:
                if kind == "_PREPARE_NAVIGATION_":
                    # Match the old working dddmr bridge: do not call StandUp,
                    # BalanceStand or SwitchMoveMode before the first Move.
                    reply = {"ok": True, "success": True, "sequence": "isolated_dddmr_direct_move"}
                else:
                    ret = _execute_command(client, kind, command, default_vx, default_vy, default_vyaw)
                    reply = {"ok": ret == 0, "return": ret}
            except Exception as exc:  # noqa: BLE001
                reply = {"ok": False, "error": str(exc)}
            # Keep channel failures outside the SDK error handler. Never consume
            # another command after a failed reply.
            _reply(connection, reply)
    except (EOFError, OSError) as exc:
        logger.error("B2 控制管道断开，执行退出前 StopMove：%s", type(exc).__name__)
    except Exception as exc:  # noqa: BLE001
        logger.exception("B2 控制子进程失败")
        if not ready_sent:
            try:
                _reply(connection, {"ready": False, "error": str(exc), "pid": os.getpid()})
            except (EOFError, OSError):
                logger.error("B2 初始化失败信息无法送达：控制管道已断开")
    finally:
        if initialized:
            # Once initialized, every exit (EOF, failed reply, exception, or
            # normal shutdown) attempts the terminal stop exactly once.
            try:
                ret = client.StopMove()
                stop_reply = {"ok": ret == 0, "return": ret}
                if ret != 0:
                    logger.critical("B2 退出前 StopMove 失败：return=%s", ret)
            except Exception as exc:  # noqa: BLE001
                logger.exception("B2 退出前 StopMove 异常")
                stop_reply = {"ok": False, "error": str(exc)}
            if shutdown_requested:
                try:
                    _reply(connection, stop_reply)
                except (EOFError, OSError):
                    logger.error("B2 最终停止结果无法送达：控制管道已断开")
        try:
            connection.close()
        except OSError:
            logger.exception("关闭 B2 控制管道失败")


def _execute_command(client, kind, command, default_vx, default_vy, default_vyaw):
    """Run one SDK call; the caller alone owns replies and terminal cleanup."""
    if kind == "velocity":
        _, vx, vy, vyaw = command
        ret = client.Move(float(vx), float(vy), float(vyaw))
    elif kind == "forward":
        ret = client.Move(default_vx, 0.0, 0.0)
    elif kind == "backward":
        ret = client.Move(-default_vx, 0.0, 0.0)
    elif kind == "left":
        ret = client.Move(0.0, 0.0, default_vyaw)
    elif kind == "right":
        ret = client.Move(0.0, 0.0, -default_vyaw)
    elif kind == "strafe_left":
        ret = client.Move(0.0, default_vy, 0.0)
    elif kind == "strafe_right":
        ret = client.Move(0.0, -default_vy, 0.0)
    elif kind == "stop":
        # Soft stop requested by the product: keep sport mode
        # alive and continuously command all velocity axes to 0.
        ret = client.Move(0.0, 0.0, 0.0)
    elif kind == "stand":
        ret = client.BalanceStand()
    elif kind == "sit":
        client.Move(0.0, 0.0, 0.0)
        time.sleep(0.3)
        ret = client.StandDown()
    else:
        raise ValueError(f"unknown command: {kind}")
    return ret
