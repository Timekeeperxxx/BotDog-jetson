#!/usr/bin/env python3
"""Probe camera connectivity/video without starting a decoder or recovery action."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.video_probe import ProbeResult, probe_rtsp_video, inspect_source_network, probe_recovery_access


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--network-only", action="store_true")
    parser.add_argument("--recovery-port", type=int)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")
    if args.recovery_port is not None:
        result = probe_recovery_access(args.url, port=args.recovery_port, timeout_seconds=args.timeout)
        print(result.detail)
        return 0 if result.ready else 2
    if args.network_only:
        result = inspect_source_network(args.url)
        print(result.detail)
        return 0 if result.ready else 2
    result = probe_rtsp_video(args.url, timeout_seconds=args.timeout, ffprobe_executable=args.ffprobe)
    print(result.detail)
    return 0 if result.ready else (1 if result.network_available else 2)


if __name__ == "__main__":
    raise SystemExit(main())
