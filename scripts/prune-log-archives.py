#!/usr/bin/env python3
"""Enforce the total budget of logs selected by the installed logrotate rule.

Only numbered logrotate archives may be deleted. Active files and Loguru's
timestamped archives are never truncated or removed here.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from pathlib import Path
import re
import shlex
import time


def enforce_budget(config: Path, max_bytes: int, max_age_days: int) -> dict:
    if max_bytes <= 0 or max_age_days <= 0:
        raise ValueError("Log budget and retention must be positive")
    header, separator, _ = config.read_text().partition("{")
    patterns = shlex.split(header, comments=True)
    if not separator or not patterns:
        raise ValueError("Missing log paths in logrotate configuration")
    log_root = Path(os.path.commonpath(patterns)).resolve()
    if log_root.name != "logs":
        raise ValueError("BotDog rule must select files in one project logs directory")
    active, archives = set(), set()
    for pattern in patterns:
        active.update(Path(name) for name in glob.glob(pattern))
        archives.update(Path(name) for name in glob.glob(pattern + ".[0-9]*")
                        if re.search(r"\.log\.[1-9][0-9]*(?:\.gz)?$", name))
    def contained_files(paths):
        return {path.resolve() for path in paths if path.is_file() and not path.is_symlink()
                and path.resolve().is_relative_to(log_root)}
    active = contained_files(active)
    archives = contained_files(archives)
    active_bytes = sum(path.stat().st_size for path in active)
    if active_bytes > max_bytes:
        raise RuntimeError(f"Active logs use {active_bytes} bytes, above budget {max_bytes}; rotation must run first")
    ordered = sorted(((path, path.stat()) for path in archives), key=lambda item: (item[1].st_mtime, str(item[0])))
    total = active_bytes + sum(info.st_size for _, info in ordered)
    before = total
    cutoff = time.time() - max_age_days * 86400
    removed = []
    for path, info in ordered:
        if info.st_mtime < cutoff or total > max_bytes:
            path.unlink()
            total -= info.st_size
            removed.append(str(path))
    return {"bytes_before": before, "bytes_after": total, "max_bytes": max_bytes,
            "active_bytes": active_bytes, "removed_archives": removed}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--max-bytes", type=int, default=1024 ** 3)
    parser.add_argument("--max-age-days", type=int, default=14)
    args = parser.parse_args()
    print(json.dumps(enforce_budget(args.config, args.max_bytes, args.max_age_days)))
