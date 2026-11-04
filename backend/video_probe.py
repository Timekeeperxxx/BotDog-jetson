"""Read-only RTSP/network preflight shared by the AI reader and video pipeline."""
from __future__ import annotations

import ipaddress
import json
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
from urllib.parse import urlsplit


@dataclass(frozen=True)
class NetworkResult:
    ready: bool
    detail: str


@dataclass(frozen=True)
class ProbeResult:
    ready: bool
    detail: str
    network_available: bool


def inspect_source_network(url: str, *, sysfs_root: Path = Path("/sys/class/net")) -> NetworkResult:
    host = urlsplit(url).hostname
    if not host:
        raise ValueError("RTSP URL has no host")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        try:
            address = ipaddress.ip_address(socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)[0][4][0])
        except socket.gaierror as exc:
            return NetworkResult(False, f"camera DNS lookup failed: {exc}")
    if address.is_loopback:
        return NetworkResult(True, "local video relay")
    try:
        route = subprocess.run(["ip", "-j", "route", "get", str(address)],
                               capture_output=True, text=True, timeout=2, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return NetworkResult(False, f"unable to inspect camera route: {exc}")
    if route.returncode != 0:
        return NetworkResult(False, "camera network has no route")
    try:
        routes = json.loads(route.stdout)
    except json.JSONDecodeError:
        return NetworkResult(False, "camera route inspection returned invalid JSON")
    if not isinstance(routes, list) or not routes or not isinstance(routes[0], dict) or "dev" not in routes[0]:
        return NetworkResult(False, "camera route has no network interface")
    device = routes[0]["dev"]
    try:
        carrier = (sysfs_root / device / "carrier").read_text().strip()
    except OSError as exc:
        return NetworkResult(False, f"unable to inspect camera link {device}: {exc}")
    if carrier != "1":
        return NetworkResult(False, f"camera link {device} has no carrier (standby)")
    return NetworkResult(True, f"camera link {device} is up")


def probe_recovery_access(url: str, *, port: int, timeout_seconds: float) -> NetworkResult:
    network = inspect_source_network(url)
    if not network.ready:
        return network
    try:
        with socket.create_connection((urlsplit(url).hostname, port), timeout=timeout_seconds):
            pass  # Connection only: do not authenticate or send any camera command.
    except OSError as exc:
        return NetworkResult(False, f"camera maintenance port is unreachable: {exc}")
    return NetworkResult(True, "camera maintenance port is reachable")


def probe_rtsp_video(
    url: str,
    *,
    timeout_seconds: float,
    ffprobe_executable: str = "ffprobe",
) -> ProbeResult:
    """Use RTSP DESCRIBE/stream metadata to verify that a video track is ready."""

    network = inspect_source_network(url)
    if not network.ready:
        return ProbeResult(False, network.detail, False)

    command: Sequence[str] = (
        ffprobe_executable,
        "-v",
        "error",
        "-rtsp_transport",
        "tcp",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_type,codec_name,width,height",
        "-of",
        "json",
        url,
    )
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return ProbeResult(False, f"RTSP probe timed out after {timeout_seconds:g}s", True)
    except OSError as exc:
        return ProbeResult(False, f"unable to start ffprobe: {exc}", True)

    if completed.returncode != 0:
        return ProbeResult(False, f"ffprobe exited with status {completed.returncode}", True)

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return ProbeResult(False, "ffprobe returned invalid JSON", True)

    streams = payload.get("streams")
    if not isinstance(streams, list) or not streams:
        return ProbeResult(False, "RTSP source has no video stream", True)

    stream = streams[0]
    if not isinstance(stream, dict) or stream.get("codec_type") != "video":
        return ProbeResult(False, "RTSP source has no video stream", True)

    codec = str(stream.get("codec_name") or "unknown")
    width = stream.get("width")
    height = stream.get("height")
    dimensions = f", {width}x{height}" if width and height else ""
    return ProbeResult(True, f"video ready ({codec}{dimensions})", True)
