from __future__ import annotations

import asyncio
import signal

import pytest

from backend.api.routes import nav as nav_routes
from backend.auth.schemas import AuthUserInternal
from backend import services_mapping as mapping_service_module
from backend.schemas import MappingControlRequest


class DummyProcess:
    def __init__(self, pid: int = 4321) -> None:
        self.pid = pid
        self.returncode = None

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = 0
        return 0


def test_start_mapping_creates_directory_and_launches_script(monkeypatch, tmp_path):
    script = tmp_path / "start_mapping.sh"
    script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")

    started: list[tuple[list[str], bool]] = []

    def fake_popen(command, start_new_session=False):
        started.append((command, start_new_session))
        return DummyProcess()

    monkeypatch.setattr(mapping_service_module, "MAPS_ROOT", tmp_path / "MAPS")
    monkeypatch.setattr(mapping_service_module, "START_MAPPING_SCRIPT", script)
    monkeypatch.setattr(mapping_service_module.subprocess, "Popen", fake_popen)

    service = mapping_service_module.MappingService()
    result = service.start("实验室一楼")

    expected_dir = tmp_path / "MAPS" / "实验室一楼"
    assert expected_dir.is_dir()
    assert result["scene_name"] == "实验室一楼"
    assert result["map_dir"] == str(expected_dir)
    assert result["pid"] == 4321
    assert started == [(["bash", str(script), str(expected_dir)], True)]


def test_mapping_service_rejects_duplicate_start(monkeypatch, tmp_path):
    script = tmp_path / "start_mapping.sh"
    script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")

    monkeypatch.setattr(mapping_service_module, "MAPS_ROOT", tmp_path / "MAPS")
    monkeypatch.setattr(mapping_service_module, "START_MAPPING_SCRIPT", script)
    monkeypatch.setattr(mapping_service_module.subprocess, "Popen", lambda *args, **kwargs: DummyProcess())

    service = mapping_service_module.MappingService()
    service.start("实验室一楼")

    with pytest.raises(mapping_service_module.MappingError, match="建图已在进行中"):
        service.start("另一个场景")


def test_stop_mapping_kills_process_group(monkeypatch, tmp_path):
    script = tmp_path / "start_mapping.sh"
    script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")

    kills: list[tuple[int, signal.Signals]] = []

    monkeypatch.setattr(mapping_service_module, "MAPS_ROOT", tmp_path / "MAPS")
    monkeypatch.setattr(mapping_service_module, "START_MAPPING_SCRIPT", script)
    monkeypatch.setattr(mapping_service_module.subprocess, "Popen", lambda *args, **kwargs: DummyProcess())
    monkeypatch.setattr(mapping_service_module.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(mapping_service_module.os, "killpg", lambda pgid, sig: kills.append((pgid, sig)))

    service = mapping_service_module.MappingService()
    service.start("实验室一楼")
    result = service.stop()

    assert result["running"] is False
    assert result["scene_name"] == "实验室一楼"
    assert kills == [(4321, signal.SIGTERM)]


def test_mapping_route_uses_scene_name_and_stop(monkeypatch):
    calls: list[tuple[str, str | None]] = []

    class DummyService:
        def start(self, scene_name: str):
            calls.append(("start", scene_name))
            return {
                "success": True,
                "enabled": True,
                "running": True,
                "scene_name": scene_name,
                "map_dir": f"/home/jetson/Project/BOTDOG/MAPS/{scene_name}",
                "pid": 4321,
                "message": "建图脚本已启动",
            }

        def stop(self):
            calls.append(("stop", None))
            return {
                "success": True,
                "enabled": False,
                "running": False,
                "scene_name": None,
                "map_dir": None,
                "pid": None,
                "message": "当前没有正在运行的建图进程",
            }

    async def fake_audit_log(*args, **kwargs):
        return None

    monkeypatch.setattr(mapping_service_module, "get_mapping_service", lambda: DummyService())
    monkeypatch.setattr(nav_routes, "safe_write_audit_log", fake_audit_log)
    start_result = asyncio.run(
        nav_routes.nav_set_mapping_enabled(
            MappingControlRequest(enabled=True, scene_name="实验室一楼"),
            user=AuthUserInternal(id=1, username="operator", role="operator", token_version=1),
            db=object(),
        )
    )
    stop_result = asyncio.run(
        nav_routes.nav_set_mapping_enabled(
            MappingControlRequest(enabled=False),
            user=AuthUserInternal(id=1, username="operator", role="operator", token_version=1),
            db=object(),
        )
    )

    assert start_result["scene_name"] == "实验室一楼"
    assert start_result["map_dir"] == "/home/jetson/Project/BOTDOG/MAPS/实验室一楼"
    assert stop_result["enabled"] is False
    assert calls == [("start", "实验室一楼"), ("stop", None)]
