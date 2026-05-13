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
    calls: list[str] = []

    def fake_popen(command, start_new_session=False, stdout=None, stderr=None, text=None, bufsize=None):
        started.append((command, start_new_session))
        assert stdout == mapping_service_module.subprocess.PIPE
        assert stderr == mapping_service_module.subprocess.PIPE
        assert text is True
        assert bufsize == 1
        return DummyProcess()

    def fake_stop_navigation_processes():
        calls.append("stop_navigation_processes")
        return {"pids": [123, 456]}

    def fake_stop_cmd_vel_script():
        calls.append("stop_cmd_vel_script")
        return {"pid": 789}

    maps_root = tmp_path / "MAPS"
    monkeypatch.setattr(mapping_service_module, "MAPS_ROOT", maps_root)
    monkeypatch.setattr(mapping_service_module, "START_MAPPING_SCRIPT", script)
    monkeypatch.setattr(mapping_service_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(mapping_service_module, "stop_navigation_processes", fake_stop_navigation_processes)
    monkeypatch.setattr(mapping_service_module, "stop_cmd_vel_script", fake_stop_cmd_vel_script)

    service = mapping_service_module.MappingService()
    result = service.start("实验室一楼")

    expected_dir = tmp_path / "MAPS" / "Scene1_实验室一楼"
    assert expected_dir.is_dir()
    assert result["scene_name"] == "Scene1_实验室一楼"
    assert result["map_dir"] == str(expected_dir)
    assert result["enabled"] is True
    assert result["pid"] == 4321
    assert calls == ["stop_navigation_processes", "stop_cmd_vel_script"]
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


def test_scene_number_increments_from_existing_dirs(monkeypatch, tmp_path):
    script = tmp_path / "start_mapping.sh"
    script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")

    maps_root = tmp_path / "MAPS"
    (maps_root / "Scene1_旧场景").mkdir(parents=True)
    (maps_root / "Scene2_别的场景").mkdir(parents=True)

    monkeypatch.setattr(mapping_service_module, "MAPS_ROOT", maps_root)
    monkeypatch.setattr(mapping_service_module, "START_MAPPING_SCRIPT", script)
    monkeypatch.setattr(mapping_service_module.subprocess, "Popen", lambda *args, **kwargs: DummyProcess())

    service = mapping_service_module.MappingService()
    result = service.start("实验室一楼")

    assert result["scene_name"] == "Scene3_实验室一楼"
    assert result["map_dir"] == str(maps_root / "Scene3_实验室一楼")


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
    assert result["enabled"] is False
    assert result["scene_name"] == "Scene1_实验室一楼"
    assert kills == [(4321, signal.SIGTERM)]


def test_mapping_route_uses_scene_name_and_stop(monkeypatch):
    calls: list[tuple[str, str | None]] = []

    class DummyService:
        def start(self, scene_name: str):
            scene_dir_name = f"Scene1_{scene_name}"
            calls.append(("start", scene_name))
            return {
                "success": True,
                "enabled": True,
                "running": True,
                "scene_name": scene_dir_name,
                "map_dir": f"/home/jetson/Project/BOTDOG/MAPS/{scene_dir_name}",
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

    assert start_result["scene_name"] == "Scene1_实验室一楼"
    assert start_result["map_dir"] == "/home/jetson/Project/BOTDOG/MAPS/Scene1_实验室一楼"
    assert start_result["enabled"] is True
    assert stop_result["enabled"] is False
    assert calls == [("start", "实验室一楼"), ("stop", None)]
