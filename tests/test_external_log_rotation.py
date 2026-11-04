import getpass
import grp
import gzip
import importlib.util
import os
from pathlib import Path
import subprocess
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("prune_logs", ROOT / "scripts/prune-log-archives.py")
prune = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prune)


@pytest.fixture
def rule(tmp_path):
    (tmp_path / "logs").mkdir()
    text = (ROOT / "scripts/botdog-logrotate.conf").read_text()
    text = text.replace("@BOTDOG_PROJECT_DIR@", str(tmp_path)).replace("@BOTDOG_USER@", getpass.getuser()).replace("@BOTDOG_GROUP@", grp.getgrgid(os.getgid()).gr_name)
    path = tmp_path / "rotate.conf"
    path.write_text(text)
    return path


def test_copytruncate_keeps_open_writer_and_compresses_original_content(rule):
    log = rule.parent / "logs/ffmpeg.log"
    content = bytes(range(256)) * 256
    log.write_bytes(content)
    inode = log.stat().st_ino
    with log.open("ab") as writer:
        subprocess.run(["logrotate", "--force", "--state", str(rule.parent / "status"), str(rule)], check=True, capture_output=True)
        assert log.stat().st_ino == inode and log.stat().st_size == 0
        writer.write(b"still writing\n")
    assert log.read_bytes() == b"still writing\n"
    with gzip.open(str(log) + ".1.gz", "rb") as archive:
        assert archive.read() == content


def test_total_budget_removes_oldest_archives_but_keeps_active_file(rule):
    active = rule.parent / "logs/ffmpeg.log"
    active.write_bytes(b"a" * 20)
    archives = [Path(str(active) + f".{number}.gz") for number in (1, 2, 3)]
    for age, path in enumerate(archives):
        path.write_bytes(b"x" * 80)
        os.utime(path, (time.time() - age * 10, time.time() - age * 10))
    result = prune.enforce_budget(rule, max_bytes=120, max_age_days=14)
    assert result["bytes_after"] == 100
    assert archives[0].exists() and not archives[1].exists() and not archives[2].exists()
    assert active.read_bytes() == b"a" * 20


def test_age_limit_protects_python_logs_symlinks_and_manual_backups(rule):
    directory = rule.parent / "logs"
    expired = directory / "ffmpeg.log.1.gz"
    expired.write_bytes(b"old")
    old = time.time() - 15 * 86400
    os.utime(expired, (old, old))
    protected = [directory / name for name in ("backend.log.1.gz", "ffmpeg.log.2.backup", "ffmpeg.log")]
    for path in protected:
        path.write_bytes(b"keep")
    outside = rule.parent / "outside.txt"
    outside.write_bytes(b"outside")
    (directory / "ffmpeg.log.3.gz").symlink_to(outside)
    prune.enforce_budget(rule, max_bytes=1024, max_age_days=14)
    assert not expired.exists()
    assert all(path.read_bytes() == b"keep" for path in protected)
    assert outside.read_bytes() == b"outside"


def test_oversized_active_log_fails_without_deleting_archives(rule):
    active = rule.parent / "logs/ffmpeg.log"
    active.write_bytes(b"a" * 100)
    archive = Path(str(active) + ".1.gz")
    archive.write_bytes(b"history")
    with pytest.raises(RuntimeError, match="rotation must run first"):
        prune.enforce_budget(rule, max_bytes=50, max_age_days=14)
    assert archive.read_bytes() == b"history"


def test_directory_symlink_cannot_remove_archives_outside_project_logs(rule):
    outside = rule.parent / "outside"
    outside.mkdir()
    archive = outside / "node.log.1.gz"
    archive.write_bytes(b"outside history")
    (rule.parent / "logs/ros").symlink_to(outside, target_is_directory=True)
    result = prune.enforce_budget(rule, max_bytes=1, max_age_days=14)
    assert result["bytes_after"] == 0
    assert archive.read_bytes() == b"outside history"
