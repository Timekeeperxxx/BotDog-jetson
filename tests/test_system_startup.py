from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from pathlib import Path

from backend.api.routes.system import system_startup
from backend.main import _write_startup_summary_snapshot


def test_system_startup_returns_summary_items() -> None:
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                startup_summary={
                    "数据库": ("ready", "数据库连接可用"),
                    "API 服务": ("ready", "地址=http://0.0.0.0:8000"),
                }
            )
        )
    )

    result = asyncio.run(system_startup(request))

    assert result.status == "全部模块正常"
    assert [item.name for item in result.items] == ["数据库", "API 服务"]
    assert result.items[0].status == "ready"
    assert result.items[0].detail == "数据库连接可用"


def test_write_startup_summary_snapshot(tmp_path: Path) -> None:
    generated_at, snapshot_file = _write_startup_summary_snapshot(
        {
            "数据库": ("ready", "数据库连接可用"),
            "API 服务": ("ready", "地址=http://0.0.0.0:8000"),
        },
        tmp_path,
    )

    snapshot_path = Path(snapshot_file)
    assert generated_at
    assert snapshot_path.is_file()

    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert payload["generated_at"] == generated_at
    assert [item["name"] for item in payload["items"]] == ["数据库", "API 服务"]
