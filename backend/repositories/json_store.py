from __future__ import annotations

import json
import os
import re
import threading
import hashlib
from pathlib import Path
from typing import Any

_WRITE_LOCK = threading.Lock()
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default

    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")

    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"

    with _WRITE_LOCK:
        with tmp_path.open("w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)


def safe_json_path_name(name: str) -> str:
    normalized = str(name).strip()
    if not normalized:
        return "unnamed"
    normalized = normalized.replace("/", "_").replace("\\", "_")
    normalized = _SAFE_NAME_RE.sub("_", normalized)
    return normalized.strip("._-") or "unnamed"


def stable_json_path_name(name: str) -> str:
    safe_name = safe_json_path_name(name)
    digest = hashlib.sha1(str(name).encode("utf-8")).hexdigest()[:10]
    return f"{safe_name}_{digest}"
