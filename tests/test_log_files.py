from __future__ import annotations

from pathlib import Path

from backend import services_log_files


def test_log_listing_discovers_nested_logs_without_allowing_escape(tmp_path: Path, monkeypatch) -> None:
    logs_dir = tmp_path / "logs"
    (logs_dir / "ros" / "run-1").mkdir(parents=True)
    (logs_dir / "backend.log").write_text("backend\n", encoding="utf-8")
    (logs_dir / "mediamtx.log").write_text("media\n", encoding="utf-8")
    (logs_dir / "ros" / "run-1" / "launch.log").write_text("ros\n", encoding="utf-8")
    (logs_dir / "custom.log").write_text("custom\n", encoding="utf-8")
    (logs_dir / "not-a-log.txt").write_text("secret\n", encoding="utf-8")
    (logs_dir / "worker.pid").write_text("123\n", encoding="utf-8")
    (logs_dir / "frame.jpg").write_bytes(b"image")
    (logs_dir / "backend.log.zip").write_bytes(b"archive")

    outside = tmp_path / "outside.log"
    outside.write_text("outside\n", encoding="utf-8")
    (logs_dir / "escaped.log").symlink_to(outside)

    monkeypatch.setattr(services_log_files, "get_logs_dir", lambda: logs_dir)

    items = services_log_files.list_log_files()
    categories = {item["name"]: item["category"] for item in items}

    assert categories == {
        "backend.log": "backend",
        "mediamtx.log": "video",
        "ros/run-1/launch.log": "navigation",
        "custom.log": "other",
    }


def test_tail_preserves_multiline_log_order(tmp_path: Path, monkeypatch) -> None:
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    path = logs_dir / "backend.log"
    path.write_text("first\ntraceback line 1\ntraceback line 2\nlast\n", encoding="utf-8")
    monkeypatch.setattr(services_log_files, "get_logs_dir", lambda: logs_dir)

    result = services_log_files.tail_log_file("backend.log", lines=3)

    assert result == {
        "name": "backend.log",
        "lines": ["traceback line 1", "traceback line 2", "last"],
        "line_count": 3,
        "truncated": True,
    }


def test_tail_rejects_non_log_and_parent_traversal(tmp_path: Path, monkeypatch) -> None:
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    (logs_dir / "notes.txt").write_text("notes\n", encoding="utf-8")
    monkeypatch.setattr(services_log_files, "get_logs_dir", lambda: logs_dir)

    for name in ("notes.txt", "../outside.log"):
        try:
            services_log_files.tail_log_file(name)
        except FileNotFoundError:
            pass
        else:
            raise AssertionError(f"{name} should not be readable")
