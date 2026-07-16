from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.api.routes import system as system_routes
from backend.schemas import SystemActionRequest
from backend.services_system import read_disk_snapshot, read_memory_snapshot


def test_read_memory_snapshot_uses_mem_available(tmp_path) -> None:
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(
        "\n".join(
            [
                "MemTotal:       8000000 kB",
                "MemFree:        1000000 kB",
                "MemAvailable:   2500000 kB",
                "Buffers:         100000 kB",
                "Cached:          500000 kB",
                "SwapTotal:      2000000 kB",
                "SwapFree:       1500000 kB",
            ]
        ),
        encoding="utf-8",
    )

    result = read_memory_snapshot(meminfo)

    assert result["total_bytes"] == 8_000_000 * 1024
    assert result["available_bytes"] == 2_500_000 * 1024
    assert result["used_bytes"] == 5_500_000 * 1024
    assert result["usage_percent"] == 68.8
    assert result["swap_used_bytes"] == 500_000 * 1024


def test_read_disk_snapshot_returns_real_filesystem_usage(tmp_path) -> None:
    result = read_disk_snapshot(tmp_path)

    assert result["path"] == str(tmp_path)
    assert result["total_bytes"] > 0
    assert result["used_bytes"] + result["free_bytes"] == result["total_bytes"]
    assert 0 <= result["usage_percent"] <= 100


@pytest.mark.asyncio
async def test_system_resources_returns_snapshot(monkeypatch) -> None:
    expected = {
        "hostname": "botdog-test",
        "memory": {"total_bytes": 1},
        "disk": {"total_bytes": 2},
    }
    monkeypatch.setattr(system_routes, "get_host_resource_snapshot", lambda: expected)

    result = await system_routes.system_resources(SimpleNamespace(username="viewer"))

    assert result == expected


@pytest.mark.asyncio
async def test_system_action_rejects_wrong_confirmation() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await system_routes.execute_system_action(
            "restart-backend",
            SystemActionRequest(confirmation="错误确认"),
            user=SimpleNamespace(username="admin", role="admin"),
            db=object(),
        )

    assert exc_info.value.status_code == 400
    assert "确认文本不匹配" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_system_action_audits_and_schedules_backend_restart(monkeypatch) -> None:
    command = ("/usr/bin/systemctl", "restart", "botdog-backend.service")
    audit_calls: list[dict] = []
    schedule_calls: list[tuple[str, tuple[str, ...]]] = []

    monkeypatch.setattr(system_routes, "ensure_system_action_available", lambda _: command)
    monkeypatch.setattr(
        system_routes,
        "schedule_system_action",
        lambda action, scheduled_command: schedule_calls.append((action, scheduled_command)) or True,
    )

    async def fake_audit(_db, **kwargs) -> None:
        audit_calls.append(kwargs)

    monkeypatch.setattr(system_routes, "safe_write_audit_log", fake_audit)

    result = await system_routes.execute_system_action(
        "restart-backend",
        SystemActionRequest(confirmation="重启后端"),
        user=SimpleNamespace(username="admin", role="admin"),
        db=object(),
    )

    assert result.success is True
    assert result.scheduled is True
    assert schedule_calls == [("restart-backend", command)]
    assert audit_calls[0]["level"] == "WARNING"
    assert "system.restart-backend" in audit_calls[0]["message"]
