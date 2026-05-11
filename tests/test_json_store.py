from __future__ import annotations

from backend.repositories.json_store import atomic_write_json, read_json


def test_atomic_write_json_round_trip_and_utf8(tmp_path):
    path = tmp_path / "nested" / "store.json"
    payload = {"name": "导航任务", "count": 3, "items": [{"label": "中文字段"}]}

    atomic_write_json(path, payload)

    assert read_json(path, {}) == payload
    content = path.read_text(encoding="utf-8")
    assert "导航任务" in content
    assert "\\u5bfc\\u822a" not in content


def test_atomic_write_json_overwrites_cleanly(tmp_path):
    path = tmp_path / "store.json"

    atomic_write_json(path, {"value": 1})
    atomic_write_json(path, {"value": 2, "message": "重写"})

    assert read_json(path, {}) == {"value": 2, "message": "重写"}
    assert path.read_text(encoding="utf-8").strip().startswith("{")
