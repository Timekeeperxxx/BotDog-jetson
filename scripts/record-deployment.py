#!/usr/bin/env python3
"""Record code, model checksums and runtime versions without exporting secrets."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
MODEL_SETTINGS = ("AI_MODEL_PATH", "POSE_MODEL_PATH", "WEAPON_MODEL_PATH", "PACKAGE_MODEL_PATH",
                  "PACKAGE_DETAIL_MODEL_PATH", "WEATHER_MODEL_PATH", "FACE_DETECT_MODEL_PATH", "FACE_RECOGNITION_MODEL_PATH")
SOURCE_DIRS = {"backend", "frontend", "scripts", "tests", "config", "docs", ".github"}
EXCLUDED_DIRS = {"node_modules", "dist", "dist-ai-sync", "__pycache__", ".git"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_source(name: str) -> bool:
    path = Path(name)
    return (bool(path.parts) and (len(path.parts) == 1 or path.parts[0] in SOURCE_DIRS)
            and not any(part in EXCLUDED_DIRS for part in path.parts)
            and not path.name.startswith(".env") and path.suffix not in {".env", ".orig", ".pyc"})


def code_identity(root: Path) -> dict:
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root).decode().strip()
    tracked = set(git("ls-files", "-z").split("\0"))
    untracked = set(git("ls-files", "--others", "--exclude-standard", "-z").split("\0"))
    files = {name: sha256(root / name) for name in sorted(tracked | untracked)
             if is_source(name) and (root / name).is_file() and not (root / name).is_symlink()}
    dirty = set(git("diff", "--name-only", "-z", "HEAD").split("\0")) | untracked
    fingerprint = hashlib.sha256("".join(f"{name}\0{value}\n" for name, value in files.items()).encode()).hexdigest()
    return {"commit": git("rev-parse", "HEAD"), "dirty_source_files": sorted(name for name in dirty if is_source(name)),
            "source_tree_sha256": fingerprint, "source_files": files}


def model_identity(root: Path, configured: dict[str, str]) -> dict:
    result = {}
    for key, value in configured.items():
        if not value:
            result[key] = {"configured": False}
            continue
        path = Path(value)
        path = path if path.is_absolute() else root / path
        if not path.is_file():
            result[key] = {"configured": True, "path": str(path), "available": False}
            continue
        before = path.stat()
        checksum = sha256(path)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise RuntimeError(f"Model changed while hashing: {path}")
        result[key] = {"configured": True, "path": str(path), "available": True,
                       "bytes": after.st_size, "sha256": checksum}
    return result


def configured_models(root: Path) -> dict:
    sys.path.insert(0, str(root))
    from backend.config import settings
    from sqlalchemy.engine import make_url
    values = {name: str(getattr(settings, name)) for name in MODEL_SETTINGS}
    url = make_url(str(settings.DATABASE_URL))
    # The running app restores these values from SQLite after reading .env.
    if url.get_backend_name() == "sqlite" and url.database and Path(url.database).is_file():
        path = Path(url.database).resolve()
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
            has_config = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='system_config'").fetchone()
            if has_config:
                keys = {key.lower(): key for key in values}
                placeholders = ",".join("?" for _ in keys)
                for key, value in db.execute(f"SELECT key,value FROM system_config WHERE key IN ({placeholders})", tuple(keys)):
                    values[keys[key]] = value
    return values


def tool_version(command: list[str]) -> dict:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "error": str(exc)}
    return {"available": completed.returncode == 0, "exit_code": completed.returncode,
            "version": completed.stdout.strip().splitlines()}


def collect_manifest(root: Path) -> dict:
    frontend = root / "frontend/dist"
    l4t = Path("/etc/nv_tegra_release")
    return {"schema_version": 1, "recorded_at": datetime.now(timezone.utc).isoformat(),
            "code": code_identity(root), "models": model_identity(root, configured_models(root)),
            "frontend_files": {str(path.relative_to(frontend)): sha256(path) for path in sorted(frontend.rglob("*"))
                               if path.is_file() and not path.is_symlink()},
            "runtime": {"python": sys.version, "python_executable": sys.executable,
                        "platform": platform.platform(), "machine": platform.machine(),
                        "l4t_release": l4t.read_text().strip() if l4t.exists() else None,
                        "python_packages": dict(sorted((item.metadata["Name"], item.version) for item in metadata.distributions())),
                        "tools": {name: tool_version(command) for name, command in {
                            "node": ["node", "--version"], "npm": ["npm", "--version"], "ffmpeg": ["ffmpeg", "-version"],
                            "gstreamer": ["gst-launch-1.0", "--version"],
                            "nvidia_packages": ["dpkg-query", "-W", "-f=${Package}=${Version}\n", "nvidia-jetpack", "nvidia-l4t-core", "libnvinfer*"]}.items()}}}


def write_manifest(output: Path, manifest: dict) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent, prefix=output.name + ".", delete=False) as target:
            temporary = Path(target.name)
            json.dump(manifest, target, indent=2, ensure_ascii=False)
            target.write("\n")
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = collect_manifest(ROOT)
    write_manifest(args.output, manifest)
    print(json.dumps({"output": str(args.output), "commit": manifest["code"]["commit"],
                      "source_tree_sha256": manifest["code"]["source_tree_sha256"],
                      "models_recorded": len(manifest["models"])}))
