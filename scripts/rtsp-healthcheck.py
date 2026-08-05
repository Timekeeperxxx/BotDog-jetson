#!/usr/bin/env python3
"""Return success only when an RTSP URL exposes a decodable video stream."""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class ProbeResult:
    ready: bool
    detail: str


def probe_rtsp_video(
    url: str,
    *,
    timeout_seconds: float,
    ffprobe_executable: str = "ffprobe",
) -> ProbeResult:
    """Use RTSP DESCRIBE/stream metadata to verify that a video track is ready."""

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
        return ProbeResult(False, f"RTSP probe timed out after {timeout_seconds:g}s")
    except OSError as exc:
        return ProbeResult(False, f"unable to start ffprobe: {exc}")

    if completed.returncode != 0:
        return ProbeResult(False, f"ffprobe exited with status {completed.returncode}")

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return ProbeResult(False, "ffprobe returned invalid JSON")

    streams = payload.get("streams")
    if not isinstance(streams, list) or not streams:
        return ProbeResult(False, "RTSP source has no video stream")

    stream = streams[0]
    if not isinstance(stream, dict) or stream.get("codec_type") != "video":
        return ProbeResult(False, "RTSP source has no video stream")

    codec = str(stream.get("codec_name") or "unknown")
    width = stream.get("width")
    height = stream.get("height")
    dimensions = f", {width}x{height}" if width and height else ""
    return ProbeResult(True, f"video ready ({codec}{dimensions})")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="RTSP URL to probe")
    parser.add_argument("--timeout", type=float, default=8.0, help="probe timeout in seconds")
    parser.add_argument("--ffprobe", default="ffprobe", help="ffprobe executable")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    if args.timeout <= 0:
        raise SystemExit("--timeout must be greater than zero")

    result = probe_rtsp_video(
        args.url,
        timeout_seconds=args.timeout,
        ffprobe_executable=args.ffprobe,
    )
    print(result.detail)
    return 0 if result.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
