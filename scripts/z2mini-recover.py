#!/usr/bin/env python3
"""Recover the Z2-Mini image pipeline through its maintenance console."""

from __future__ import annotations

import argparse
import socket
import time
from dataclasses import dataclass
from typing import Iterable


LOGIN_PROMPT = b"login: "
SHELL_PROMPT = b"# "
RECOVERY_OK = b"__BOTDOG_RECOVERY_OK__"
RECOVERY_FAILED = b"__BOTDOG_RECOVERY_FAILED__"
RECOVERY_UNSUPPORTED = b"__BOTDOG_RECOVERY_UNSUPPORTED__"
RECOVERY_MARKERS = (RECOVERY_OK, RECOVERY_FAILED, RECOVERY_UNSUPPORTED)

# These commands are deliberately fixed rather than accepted from the command
# line. The camera exposes a passwordless maintenance console on its dedicated
# Ethernet link, so the watchdog may only restart the vendor image service or
# reboot the camera. Redirecting the noisy image process to /dev/null is
# intentional: inheriting /dev/console can block the process during a broken
# cold start. A successful shell exit is not sufficient, so the command also
# verifies both vendor processes and the RTSP listener after startup.
RECOVERY_COMMAND = (
    b"if [ -x /opt/bin/gcu/ipc/camera_gcu.sh ]; then "
    b"cd /opt/bin/gcu/ipc && "
    b"./camera_gcu.sh >/dev/null 2>&1; "
    b"sleep 8; "
    b"if pidof main >/dev/null 2>&1 && "
    b"pidof gb_control >/dev/null 2>&1 && "
    b"netstat -lnt 2>/dev/null | grep -q ':554[[:space:]]'; then "
    b"printf '__BOTDOG_%s__\\n' RECOVERY_OK; "
    b"else printf '__BOTDOG_%s__\\n' RECOVERY_FAILED; fi; "
    b"else printf '__BOTDOG_%s__\\n' RECOVERY_UNSUPPORTED; fi\r\n"
)
REBOOT_COMMAND = b"sync; reboot\r\n"


@dataclass(frozen=True)
class RecoveryResult:
    recovered: bool
    detail: str


def _answer_telnet_negotiation(connection: socket.socket, payload: bytes) -> None:
    """Decline complete three-byte Telnet option requests in *payload*."""

    # IAC WILL/WONT <option> -> IAC DONT <option>
    # IAC DO/DONT <option>   -> IAC WONT <option>
    responses = bytearray()
    index = 0
    while index + 2 < len(payload):
        if payload[index] != 0xFF:
            index += 1
            continue
        command = payload[index + 1]
        option = payload[index + 2]
        if command in (0xFB, 0xFC):
            responses.extend((0xFF, 0xFE, option))
            index += 3
        elif command in (0xFD, 0xFE):
            responses.extend((0xFF, 0xFC, option))
            index += 3
        else:
            index += 1
    if responses:
        connection.sendall(bytes(responses))


def _read_until_any(
    connection: socket.socket,
    markers: Iterable[bytes],
    *,
    deadline: float,
) -> tuple[bytes, bytes]:
    expected = tuple(markers)
    received = bytearray()
    while True:
        for marker in expected:
            if marker in received:
                return bytes(received), marker

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("camera maintenance console response timed out")
        connection.settimeout(remaining)
        try:
            chunk = connection.recv(4096)
        except socket.timeout as exc:
            raise TimeoutError("camera maintenance console response timed out") from exc
        if not chunk:
            raise ConnectionError("camera maintenance console closed the connection")
        _answer_telnet_negotiation(connection, chunk)
        received.extend(chunk)
        if len(received) > 256 * 1024:
            raise ConnectionError("camera maintenance console returned too much data")


def _wait_for_disconnect(connection: socket.socket, *, deadline: float) -> None:
    """Wait until a reboot closes or resets the maintenance connection."""

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("camera did not disconnect after reboot command")
        connection.settimeout(remaining)
        try:
            chunk = connection.recv(4096)
        except socket.timeout as exc:
            raise TimeoutError("camera did not disconnect after reboot command") from exc
        except OSError:
            # A TCP reset is the normal observable result of the kernel reboot.
            return
        if not chunk:
            return
        _answer_telnet_negotiation(connection, chunk)


def recover_z2mini(
    host: str,
    *,
    port: int = 23,
    timeout_seconds: float = 20.0,
    mode: str = "service",
) -> RecoveryResult:
    """Restart the image service or reboot the camera and verify acceptance."""

    if mode not in {"service", "reboot"}:
        raise ValueError(f"unsupported recovery mode: {mode}")

    command = RECOVERY_COMMAND if mode == "service" else REBOOT_COMMAND

    deadline = time.monotonic() + timeout_seconds
    try:
        connection = socket.create_connection((host, port), timeout=timeout_seconds)
        with connection:
            _read_until_any(connection, (LOGIN_PROMPT,), deadline=deadline)
            connection.sendall(b"root\r\n")
            _read_until_any(connection, (SHELL_PROMPT,), deadline=deadline)
            connection.sendall(command)
            if mode == "reboot":
                _wait_for_disconnect(connection, deadline=deadline)
                marker = None
            else:
                _, marker = _read_until_any(connection, RECOVERY_MARKERS, deadline=deadline)
    except (OSError, TimeoutError, ConnectionError) as exc:
        return RecoveryResult(False, f"camera recovery failed: {exc}")

    if mode == "reboot":
        return RecoveryResult(True, "camera reboot initiated and console disconnected")
    if marker == RECOVERY_OK:
        return RecoveryResult(True, "camera image service and RTSP listener verified")
    if marker == RECOVERY_UNSUPPORTED:
        return RecoveryResult(False, "camera does not expose the factory recovery script")
    return RecoveryResult(False, "camera image service failed post-start verification")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="Z2-Mini maintenance address")
    parser.add_argument("--port", type=int, default=23, help="maintenance Telnet port")
    parser.add_argument("--timeout", type=float, default=20.0, help="overall timeout in seconds")
    parser.add_argument(
        "--mode",
        choices=("service", "reboot"),
        default="service",
        help="restart only the image service or reboot the complete camera",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    if not 1 <= args.port <= 65535:
        raise SystemExit("--port must be between 1 and 65535")
    if args.timeout <= 0:
        raise SystemExit("--timeout must be greater than zero")

    result = recover_z2mini(
        args.host,
        port=args.port,
        timeout_seconds=args.timeout,
        mode=args.mode,
    )
    print(result.detail)
    return 0 if result.recovered else 1


if __name__ == "__main__":
    raise SystemExit(main())
