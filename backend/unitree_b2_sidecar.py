"""Isolated Unitree B2 SportClient process.

The Unitree SDK owns a CycloneDDS participant.  Keeping it in the FastAPI
process (which also owns ROS 2 publishers/subscribers and telemetry DDS
callbacks) can make SportClient RPC calls return success while the B2 never
enters velocity mode.  The previously working dddmr bridge avoided that by
running SportClient in a dedicated process.  This module restores that process
boundary while the parent retains command arbitration and safety checks.
"""

from __future__ import annotations

import os
import time
from multiprocessing.connection import Connection
from typing import Any


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
    try:
        connection.send(payload)
    except (BrokenPipeError, EOFError, OSError):
        pass


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
    try:
        from unitree_sdk2py.b2.sport.sport_client import SportClient
        from unitree_sdk2py.core.channel import ChannelFactoryInitialize

        ChannelFactoryInitialize(0, network_interface)
        client = SportClient()
        client.SetTimeout(1.5)
        client.Init()
        _reply(
            connection,
            {
                "ready": True,
                "pid": os.getpid(),
                "sequence": "isolated_dddmr_sport_client",
            },
        )

        while True:
            try:
                command = connection.recv()
            except (EOFError, OSError):
                break

            try:
                kind = command[0] if isinstance(command, tuple) else command
                if kind == "_STOP_AND_QUIT_":
                    # Process shutdown is a true terminal stop. Runtime/nav
                    # stops use Move(0, 0, 0) below and remain soft stops.
                    ret = client.StopMove()
                    _reply(connection, {"ok": ret == 0, "return": ret})
                    break

                if kind == "_PREPARE_NAVIGATION_":
                    # Match the old working dddmr bridge: do not call StandUp,
                    # BalanceStand or SwitchMoveMode before the first Move.
                    _reply(
                        connection,
                        {
                            "ok": True,
                            "success": True,
                            "sequence": "isolated_dddmr_direct_move",
                        },
                    )
                    continue

                if kind == "velocity":
                    _, vx, vy, vyaw = command
                    ret = client.Move(float(vx), float(vy), float(vyaw))
                    _reply(connection, {"ok": ret == 0, "return": ret})
                    continue

                if kind == "forward":
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
                    _reply(connection, {"ok": False, "error": f"unknown command: {kind}"})
                    continue
                _reply(connection, {"ok": ret == 0, "return": ret})
            except Exception as exc:  # noqa: BLE001
                _reply(connection, {"ok": False, "error": str(exc)})
    except Exception as exc:  # noqa: BLE001
        _reply(connection, {"ready": False, "error": str(exc), "pid": os.getpid()})
    finally:
        try:
            connection.close()
        except OSError:
            pass
