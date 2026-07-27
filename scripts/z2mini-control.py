#!/usr/bin/env python3
"""Minimal Xianfei Z2-Mini GCU control client.

The camera's private protocol uses a request/response exchange over TCP 2332.
Only the OSD command is exposed here so pipeline startup cannot accidentally
change gimbal attitude or another camera setting.
"""

from __future__ import annotations

import argparse
import socket
import sys
import time


PROTOCOL_VERSION = 0x02
OSD_COMMAND = 0x73
OSD_STATE_MASK = 1 << 13
CRC_TABLE = (
    0x0000,
    0x1021,
    0x2042,
    0x3063,
    0x4084,
    0x50A5,
    0x60C6,
    0x70E7,
    0x8108,
    0x9129,
    0xA14A,
    0xB16B,
    0xC18C,
    0xD1AD,
    0xE1CE,
    0xF1EF,
)


class GcuProtocolError(RuntimeError):
    """Raised when the GCU returns an invalid or unsuccessful response."""


def crc16(data: bytes) -> int:
    crc = 0
    for value in data:
        index = (crc >> 12) ^ (value >> 4)
        crc = ((crc << 4) & 0xFFFF) ^ CRC_TABLE[index]
        index = (crc >> 12) ^ (value & 0x0F)
        crc = ((crc << 4) & 0xFFFF) ^ CRC_TABLE[index]
    return crc


def build_packet(command: int, parameter: int | None = None, *, request_status: bool = False) -> bytes:
    command_data = bytes((command,)) if parameter is None else bytes((command, parameter))
    packet_length = 69 + len(command_data) + 2
    frame = bytearray(69)
    frame[0:2] = b"\xA8\xE5"
    frame[2:4] = packet_length.to_bytes(2, "little")
    frame[4] = PROTOCOL_VERSION
    if request_status:
        frame[30] = 0x01
    body = bytes(frame) + command_data
    return body + crc16(body).to_bytes(2, "big")


def receive_packet(connection: socket.socket) -> bytes:
    response = bytearray()
    while len(response) < 4:
        chunk = connection.recv(1024)
        if not chunk:
            raise GcuProtocolError("GCU closed the connection before returning a header")
        response.extend(chunk)

    packet_length = int.from_bytes(response[2:4], "little")
    if packet_length < 72 or packet_length > 4096:
        raise GcuProtocolError(f"GCU returned an invalid packet length: {packet_length}")

    while len(response) < packet_length:
        chunk = connection.recv(packet_length - len(response))
        if not chunk:
            raise GcuProtocolError("GCU closed the connection before returning a complete packet")
        response.extend(chunk)

    packet = bytes(response[:packet_length])
    if packet[0:2] != b"\x8A\x5E":
        raise GcuProtocolError(f"unexpected GCU response header: {packet[0:2].hex(' ')}")
    expected_crc = int.from_bytes(packet[-2:], "big")
    actual_crc = crc16(packet[:-2])
    if actual_crc != expected_crc:
        raise GcuProtocolError(
            f"GCU response CRC mismatch: received {expected_crc:04x}, calculated {actual_crc:04x}"
        )
    return packet


def exchange(host: str, port: int, packet: bytes, timeout: float) -> bytes:
    with socket.create_connection((host, port), timeout=timeout) as connection:
        connection.settimeout(timeout)
        connection.sendall(packet)
        return receive_packet(connection)


def set_osd(host: str, port: int, enabled: bool, timeout: float) -> None:
    # The GCU executes a repeated command code only once, even if its parameter
    # changes. A null command must therefore precede every OSD setting.
    exchange(host, port, build_packet(0x00), timeout)

    # Xianfei's packet examples define 0x01 as OSD on and 0x00 as OSD off.
    response = exchange(host, port, build_packet(OSD_COMMAND, int(enabled)), timeout)
    feedback = response[69:-2]
    if feedback != bytes((OSD_COMMAND, 0x00)):
        raise GcuProtocolError(f"OSD command failed, feedback: {feedback.hex(' ') or '<empty>'}")

    # Request the camera status sub-frame and verify bit B13, rather than
    # treating the command acknowledgement alone as proof that the UI changed.
    status_response = exchange(
        host,
        port,
        build_packet(0x00, request_status=True),
        timeout,
    )
    if status_response[37] != 0x01:
        raise GcuProtocolError("GCU did not return the requested camera status sub-frame")
    camera_status = int.from_bytes(status_response[64:66], "little")
    actual_enabled = bool(camera_status & OSD_STATE_MASK)
    if actual_enabled != enabled:
        raise GcuProtocolError(
            f"OSD state verification failed: expected {'on' if enabled else 'off'}, "
            f"camera reports {'on' if actual_enabled else 'off'}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Set Xianfei Z2-Mini camera OSD state")
    parser.add_argument("--host", required=True, help="Z2-Mini IP address")
    parser.add_argument("--port", type=int, default=2332, help="GCU TCP control port (default: 2332)")
    parser.add_argument("--osd", choices=("on", "off"), required=True, help="desired OSD state")
    parser.add_argument("--timeout", type=float, default=2.0, help="socket timeout in seconds")
    parser.add_argument("--retries", type=int, default=1, help="number of attempts")
    parser.add_argument("--retry-delay", type=float, default=1.0, help="seconds between attempts")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.retries < 1:
        print("ERROR: --retries must be at least 1", file=sys.stderr)
        return 2
    if args.timeout <= 0 or args.retry_delay < 0:
        print("ERROR: timeout must be positive and retry delay cannot be negative", file=sys.stderr)
        return 2

    desired_enabled = args.osd == "on"
    for attempt in range(1, args.retries + 1):
        try:
            set_osd(args.host, args.port, desired_enabled, args.timeout)
            print(f"Z2-Mini OSD {args.osd}: verified")
            return 0
        except (OSError, GcuProtocolError) as error:
            if attempt == args.retries:
                print(
                    f"ERROR: unable to set Z2-Mini OSD {args.osd} after "
                    f"{args.retries} attempt(s): {error}",
                    file=sys.stderr,
                )
                return 1
            time.sleep(args.retry_delay)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
