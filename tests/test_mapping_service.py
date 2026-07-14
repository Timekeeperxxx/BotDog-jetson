from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

from backend.api.routes import nav as nav_routes
from backend.auth.schemas import AuthUserInternal
from backend import services_mapping as mapping_service_module
from backend.services_nav_waypoints import list_waypoints
from backend.schemas import MappingControlRequest


@pytest.fixture(autouse=True)
def isolate_video_pipeline(monkeypatch, tmp_path):
    monkeypatch.setattr(mapping_service_module, "VIDEO_PIPELINE_SCRIPT", tmp_path / "missing-run-pipeline.sh")
    monkeypatch.setattr(mapping_service_module, "VIDEO_PIPELINE_PID_FILES", ())


class DummyProcess:
    def __init__(self, pid: int = 4321) -> None:
        self.pid = pid
        self.returncode = None

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = 0
        return 0


class TimeoutOnceProcess(DummyProcess):
    def __init__(self, pid: int = 4321) -> None:
        super().__init__(pid=pid)
        self.wait_calls: list[float | int | None] = []

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        if len(self.wait_calls) == 1:
            raise mapping_service_module.subprocess.TimeoutExpired(cmd="start_mapping.sh", timeout=timeout)
        self.returncode = 0
        return 0


class TimeoutTwiceProcess(DummyProcess):
    def __init__(self, pid: int = 4321) -> None:
        super().__init__(pid=pid)
        self.wait_calls: list[float | int | None] = []

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        if len(self.wait_calls) <= 2:
            raise mapping_service_module.subprocess.TimeoutExpired(cmd="start_mapping.sh", timeout=timeout)
        self.returncode = 0
        return 0


def test_runtime_interferers_keep_video_pipeline_running(monkeypatch, tmp_path):
    pipeline_script = tmp_path / "run-pipeline.sh"
    pipeline_script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    pid_file = tmp_path / "mediamtx.pid"
    pid_file.write_text("12345\n", encoding="utf-8")
    run_calls: list[list[str]] = []
    popen_calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        run_calls.append(command)

        class Result:
            returncode = 0

        return Result()

    def fake_popen(command, **kwargs):
        popen_calls.append(command)
        return DummyProcess()

    monkeypatch.setattr(mapping_service_module, "VIDEO_PIPELINE_SCRIPT", pipeline_script)
    monkeypatch.setattr(mapping_service_module, "VIDEO_PIPELINE_PID_FILES", (pid_file,))
    monkeypatch.setattr(mapping_service_module.MappingService, "_is_pid_running", staticmethod(lambda pid: pid == 12345))
    monkeypatch.setattr(mapping_service_module.subprocess, "run", fake_run)
    monkeypatch.setattr(mapping_service_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr("backend.auto_track_service.get_auto_track_service", lambda: None)
    monkeypatch.setattr("backend.guard_mission_service.get_guard_mission_service", lambda: None)

    state = mapping_service_module.MappingService._pause_runtime_interferers()
    mapping_service_module.MappingService._resume_runtime_interferers(state)

    assert state["video_pipeline_restore_needed"] is False
    assert run_calls == []
    assert popen_calls == []


def test_start_mapping_creates_directory_and_launches_script(monkeypatch, tmp_path):
    script = tmp_path / "start_mapping.sh"
    script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")

    started: list[tuple[list[str], bool]] = []
    calls: list[str] = []
    tracker_calls: list[str] = []
    guard_enabled_state = {"enabled": True}

    class DummyBridge:
        def clear_accumulated_cloud(self):
            calls.append("clear_accumulated_cloud")

        def reset_mapping_cloud_subscription(self):
            calls.append("reset_mapping_cloud_subscription")
            return True

    class DummyAutoTrackService:
        def get_status(self):
            return {"enabled": True, "paused": False}

        def pause(self):
            tracker_calls.append("auto_track.pause")

        def resume(self):
            tracker_calls.append("auto_track.resume")

    class DummyGuardMissionService:
        @property
        def enabled(self):
            return guard_enabled_state["enabled"]

        @enabled.setter
        def enabled(self, value):
            guard_enabled_state["enabled"] = bool(value)
            tracker_calls.append(f"guard.enabled={bool(value)}")

    def fake_popen(command, start_new_session=False, stdout=None, stderr=None, text=None, bufsize=None):
        started.append((command, start_new_session))
        assert stdout == mapping_service_module.subprocess.DEVNULL
        assert stderr == mapping_service_module.subprocess.DEVNULL
        map_dir = Path(command[2])
        mapping_service_module.mapping_ready_flag_path(map_dir).write_text("ready\n", encoding="utf-8")
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
    monkeypatch.setattr(mapping_service_module, "clear_robot_pose", lambda: calls.append("clear_robot_pose"))
    monkeypatch.setattr(mapping_service_module, "clear_global_path", lambda: calls.append("clear_global_path"))
    monkeypatch.setattr(
        mapping_service_module,
        "set_navigation_idle",
        lambda message: calls.append(f"set_navigation_idle:{message}"),
    )
    monkeypatch.setattr(mapping_service_module, "get_ros_nav_bridge", lambda: DummyBridge())
    monkeypatch.setattr(
        "backend.auto_track_service.get_auto_track_service",
        lambda: DummyAutoTrackService(),
    )
    monkeypatch.setattr(
        "backend.guard_mission_service.get_guard_mission_service",
        lambda: DummyGuardMissionService(),
    )

    service = mapping_service_module.MappingService()
    result = service.start("实验室一楼")

    expected_dir = tmp_path / "MAPS" / "Scene1_实验室一楼"
    assert expected_dir.is_dir()
    assert result["scene_name"] == "Scene1_实验室一楼"
    assert result["map_dir"] == str(expected_dir)
    assert result["enabled"] is True
    assert result["pid"] == 4321
    assert result["message"] == "建图已进入 ground 生成阶段"
    assert calls == [
        "stop_navigation_processes",
        "stop_cmd_vel_script",
        "clear_robot_pose",
        "clear_global_path",
        "set_navigation_idle:开始建图，导航状态已重置",
        "clear_accumulated_cloud",
        "reset_mapping_cloud_subscription",
    ]
    assert started == [(["bash", str(script), str(expected_dir)], True)]
    assert tracker_calls == ["auto_track.pause", "guard.enabled=False"]
    assert guard_enabled_state["enabled"] is False


def test_mapping_service_rejects_duplicate_start(monkeypatch, tmp_path):
    script = tmp_path / "start_mapping.sh"
    script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")

    monkeypatch.setattr(mapping_service_module, "MAPS_ROOT", tmp_path / "MAPS")
    monkeypatch.setattr(mapping_service_module, "START_MAPPING_SCRIPT", script)

    def fake_popen(command, *args, **kwargs):
        mapping_service_module.mapping_ready_flag_path(Path(command[2])).write_text("ready\n", encoding="utf-8")
        return DummyProcess()

    monkeypatch.setattr(mapping_service_module.subprocess, "Popen", fake_popen)

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

    def fake_popen(command, *args, **kwargs):
        mapping_service_module.mapping_ready_flag_path(Path(command[2])).write_text("ready\n", encoding="utf-8")
        return DummyProcess()

    monkeypatch.setattr(mapping_service_module.subprocess, "Popen", fake_popen)

    service = mapping_service_module.MappingService()
    result = service.start("实验室一楼")

    assert result["scene_name"] == "Scene3_实验室一楼"
    assert result["map_dir"] == str(maps_root / "Scene3_实验室一楼")


def test_stop_mapping_sends_sigint_to_mapping_script(monkeypatch, tmp_path):
    script = tmp_path / "start_mapping.sh"
    script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")

    kills: list[tuple[int, signal.Signals]] = []
    tracker_calls: list[str] = []
    guard_enabled_state = {"enabled": False}

    class DummyAutoTrackService:
        def get_status(self):
            return {"enabled": True, "paused": False}

        def pause(self):
            tracker_calls.append("auto_track.pause")

        def resume(self):
            tracker_calls.append("auto_track.resume")

    class DummyGuardMissionService:
        @property
        def enabled(self):
            return guard_enabled_state["enabled"]

        @enabled.setter
        def enabled(self, value):
            guard_enabled_state["enabled"] = bool(value)
            tracker_calls.append(f"guard.enabled={bool(value)}")

    monkeypatch.setattr(mapping_service_module, "MAPS_ROOT", tmp_path / "MAPS")
    monkeypatch.setattr(mapping_service_module, "START_MAPPING_SCRIPT", script)

    def fake_popen(command, *args, **kwargs):
        mapping_service_module.mapping_ready_flag_path(Path(command[2])).write_text("ready\n", encoding="utf-8")
        return DummyProcess()

    monkeypatch.setattr(mapping_service_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(mapping_service_module.os, "kill", lambda pid, sig: kills.append((pid, sig)))
    monkeypatch.setattr(mapping_service_module, "stop_navigation_processes", lambda: {"pids": []})
    monkeypatch.setattr(mapping_service_module, "stop_cmd_vel_script", lambda: {"pid": None})
    monkeypatch.setattr(
        "backend.auto_track_service.get_auto_track_service",
        lambda: DummyAutoTrackService(),
    )
    monkeypatch.setattr(
        "backend.guard_mission_service.get_guard_mission_service",
        lambda: DummyGuardMissionService(),
    )

    service = mapping_service_module.MappingService()
    service.start("实验室一楼")
    result = service.stop()

    assert result["running"] is False
    assert result["enabled"] is False
    assert result["scene_name"] == "Scene1_实验室一楼"
    assert kills == [(4321, signal.SIGINT)]
    assert tracker_calls == ["auto_track.pause", "auto_track.resume"]


def test_stop_mapping_creates_origin_waypoint_after_saved(monkeypatch, tmp_path):
    script = tmp_path / "start_mapping.sh"
    script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")

    maps_root = tmp_path / "MAPS"
    waypoint_root = tmp_path / "waypoints"
    kills: list[tuple[int, signal.Signals]] = []

    monkeypatch.setattr(mapping_service_module, "MAPS_ROOT", maps_root)
    monkeypatch.setattr(mapping_service_module, "START_MAPPING_SCRIPT", script)
    monkeypatch.setattr("backend.services_pcd_maps.settings.SCENE_MAP_ROOT", str(maps_root))
    monkeypatch.setattr("backend.services_nav_waypoints.settings.NAV_WAYPOINT_STORE_DIR", str(waypoint_root))
    monkeypatch.setattr("backend.services_nav_waypoints.settings.NAV_ORIGIN_WAYPOINT_Z", -0.83)
    monkeypatch.setattr("backend.services_nav_waypoints.settings.NAV_ORIGIN_WAYPOINT_YAW", 0.0)

    def fake_popen(command, *args, **kwargs):
        map_dir = Path(command[2])
        map_dir.mkdir(parents=True, exist_ok=True)
        mapping_service_module.mapping_ready_flag_path(map_dir).write_text("ready\n", encoding="utf-8")
        (map_dir / "map.pcd").write_text("map\n", encoding="utf-8")
        (map_dir / "ground.pcd").write_text("ground\n", encoding="utf-8")
        return DummyProcess()

    monkeypatch.setattr(mapping_service_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(mapping_service_module.os, "kill", lambda pid, sig: kills.append((pid, sig)))
    monkeypatch.setattr(mapping_service_module, "stop_navigation_processes", lambda: {"pids": []})
    monkeypatch.setattr(mapping_service_module, "stop_cmd_vel_script", lambda: {"pid": None})

    service = mapping_service_module.MappingService()
    start_result = service.start("实验室一楼")
    result = service.stop()

    waypoint_data = list_waypoints(start_result["scene_name"])
    origin = waypoint_data["items"][0]

    assert result["saved"] is True
    assert result["origin_waypoint"] == origin
    assert result["origin_waypoint_error"] is None
    assert result["message"] == "地图已保存：map.pcd x1，ground.pcd x1，已自动添加原点导航点"
    assert origin["name"] == "原点"
    assert origin["x"] == 0.0
    assert origin["y"] == 0.0
    assert origin["z"] == -0.83
    assert origin["yaw"] == 0.0
    assert origin["frame_id"] == "map"
    assert kills == [(4321, signal.SIGINT)]


def test_stop_mapping_creates_origin_waypoint_from_initial_pose(monkeypatch, tmp_path):
    script = tmp_path / "start_mapping.sh"
    script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")

    maps_root = tmp_path / "MAPS"
    waypoint_root = tmp_path / "waypoints"

    monkeypatch.setattr(mapping_service_module, "MAPS_ROOT", maps_root)
    monkeypatch.setattr(mapping_service_module, "START_MAPPING_SCRIPT", script)
    monkeypatch.setattr("backend.services_pcd_maps.settings.SCENE_MAP_ROOT", str(maps_root))
    monkeypatch.setattr("backend.services_nav_waypoints.settings.NAV_WAYPOINT_STORE_DIR", str(waypoint_root))
    monkeypatch.setattr(
        mapping_service_module.MappingService,
        "_capture_initial_origin_pose",
        classmethod(
            lambda cls: {
                "x": 1.25,
                "y": -0.5,
                "z": -0.72,
                "yaw": 0.35,
                "frame_id": "map",
                "source": "test-initial-tf",
            }
        ),
    )

    def fake_popen(command, *args, **kwargs):
        map_dir = Path(command[2])
        map_dir.mkdir(parents=True, exist_ok=True)
        mapping_service_module.mapping_ready_flag_path(map_dir).write_text("ready\n", encoding="utf-8")
        (map_dir / "map.pcd").write_text("map\n", encoding="utf-8")
        (map_dir / "ground.pcd").write_text("ground\n", encoding="utf-8")
        return DummyProcess()

    monkeypatch.setattr(mapping_service_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(mapping_service_module.os, "kill", lambda pid, sig: None)
    monkeypatch.setattr(mapping_service_module, "stop_navigation_processes", lambda: {"pids": []})
    monkeypatch.setattr(mapping_service_module, "stop_cmd_vel_script", lambda: {"pid": None})

    service = mapping_service_module.MappingService()
    start_result = service.start("初始坐标场景")
    result = service.stop()

    waypoint_data = list_waypoints(start_result["scene_name"])
    origin = waypoint_data["items"][0]

    assert result["saved"] is True
    assert origin["name"] == "原点"
    assert origin["x"] == 1.25
    assert origin["y"] == -0.5
    assert origin["z"] == -0.72
    assert origin["yaw"] == 0.35


def test_stop_mapping_waits_longer_than_script_cleanup_before_force_kill(monkeypatch, tmp_path):
    script = tmp_path / "start_mapping.sh"
    script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")

    kills: list[tuple[int, signal.Signals]] = []
    process = TimeoutTwiceProcess()

    class InlineThread:
        def __init__(self, target=None, args=(), kwargs=None, daemon=None):
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}

        def start(self):
            if self._target is not None:
                self._target(*self._args, **self._kwargs)

    monkeypatch.setattr(mapping_service_module, "MAPS_ROOT", tmp_path / "MAPS")
    monkeypatch.setattr(mapping_service_module, "START_MAPPING_SCRIPT", script)

    def fake_popen(command, *args, **kwargs):
        mapping_service_module.mapping_ready_flag_path(Path(command[2])).write_text("ready\n", encoding="utf-8")
        return process

    monkeypatch.setattr(mapping_service_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(mapping_service_module.os, "kill", lambda pid, sig: kills.append((pid, sig)))
    monkeypatch.setattr(mapping_service_module.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(mapping_service_module.os, "killpg", lambda pgid, sig: kills.append((pgid, sig)))
    monkeypatch.setattr(mapping_service_module, "stop_navigation_processes", lambda: {"pids": []})
    monkeypatch.setattr(mapping_service_module, "stop_cmd_vel_script", lambda: {"pid": None})

    service = mapping_service_module.MappingService()
    service.start("实验室一楼")
    service.stop()

    assert process.wait_calls == [
        mapping_service_module.MAPPING_STOP_WAIT_TIMEOUT_SECONDS,
        10,
        mapping_service_module.MAPPING_STOP_FORCE_KILL_WAIT_SECONDS,
    ]
    assert kills == [
        (4321, signal.SIGINT),
        (4321, signal.SIGTERM),
        (4321, signal.SIGKILL),
    ]


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


def test_start_mapping_waits_for_ground_ready_flag(monkeypatch, tmp_path):
    script = tmp_path / "start_mapping.sh"
    script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")

    process = DummyProcess()
    sleep_calls: list[float] = []

    def fake_popen(command, *args, **kwargs):
        return process

    real_sleep = mapping_service_module.time.sleep

    def fake_sleep(seconds: float):
        sleep_calls.append(seconds)
        if len(sleep_calls) == 2:
            ready_flag = mapping_service_module.mapping_ready_flag_path(tmp_path / "MAPS" / "Scene1_实验室一楼")
            ready_flag.parent.mkdir(parents=True, exist_ok=True)
            ready_flag.write_text("ready\n", encoding="utf-8")
        real_sleep(0)

    monkeypatch.setattr(mapping_service_module, "MAPS_ROOT", tmp_path / "MAPS")
    monkeypatch.setattr(mapping_service_module, "START_MAPPING_SCRIPT", script)
    monkeypatch.setattr(mapping_service_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(mapping_service_module.time, "sleep", fake_sleep)
    monkeypatch.setattr(mapping_service_module, "stop_navigation_processes", lambda: {"pids": []})
    monkeypatch.setattr(mapping_service_module, "stop_cmd_vel_script", lambda: {"pid": None})

    service = mapping_service_module.MappingService()
    result = service.start("实验室一楼")

    assert result["message"] == "建图已进入 ground 生成阶段"
    assert sleep_calls == [
        mapping_service_module.MAPPING_START_READY_POLL_INTERVAL_SECONDS,
        mapping_service_module.MAPPING_START_READY_POLL_INTERVAL_SECONDS,
    ]


def test_start_mapping_fails_if_ground_never_starts(monkeypatch, tmp_path):
    script = tmp_path / "start_mapping.sh"
    script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")

    process = DummyProcess()
    killpg_calls: list[tuple[int, signal.Signals]] = []
    sleep_calls: list[float] = []

    class DummyBridge:
        def __init__(self) -> None:
            self.cleared = 0

        def clear_accumulated_cloud(self):
            self.cleared += 1

    bridge = DummyBridge()

    def fake_popen(command, *args, **kwargs):
        return process

    def fake_wait(timeout=None):
        process.returncode = 0
        return 0

    def fake_sleep(seconds: float):
        sleep_calls.append(seconds)

    monkeypatch.setattr(mapping_service_module, "MAPS_ROOT", tmp_path / "MAPS")
    monkeypatch.setattr(mapping_service_module, "START_MAPPING_SCRIPT", script)
    monkeypatch.setattr(mapping_service_module, "MAPPING_START_READY_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr(mapping_service_module, "MAPPING_START_READY_POLL_INTERVAL_SECONDS", 0.5)
    monkeypatch.setattr(mapping_service_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(mapping_service_module.time, "sleep", fake_sleep)
    monkeypatch.setattr(mapping_service_module.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(mapping_service_module.os, "killpg", lambda pgid, sig: killpg_calls.append((pgid, sig)))
    monkeypatch.setattr(process, "wait", fake_wait)
    monkeypatch.setattr(mapping_service_module, "stop_navigation_processes", lambda: {"pids": []})
    monkeypatch.setattr(mapping_service_module, "stop_cmd_vel_script", lambda: {"pid": None})
    monkeypatch.setattr(mapping_service_module, "get_ros_nav_bridge", lambda: bridge)

    service = mapping_service_module.MappingService()

    with pytest.raises(mapping_service_module.MappingError, match="ground 生成尚未开始"):
        service.start("实验室一楼")

    assert bridge.cleared == 1
    assert killpg_calls == [(4321, signal.SIGINT)]
    assert len(sleep_calls) >= 2
    assert set(sleep_calls) == {0.5}


def test_start_mapping_wrapper_waits_for_unified_runtime_readiness():
    botdog_root = Path(__file__).resolve().parents[1]
    wrapper = (botdog_root / "scripts" / "start_mapping.sh").read_text(encoding="utf-8")
    adapter = (
        botdog_root.parent / "Navigation" / "adapters" / "legacy_scripts" / "start_mapping.sh"
    ).read_text(encoding="utf-8")
    launch = (
        botdog_root.parent / "Navigation" / "src" / "nav_bringup" / "launch" / "mapping.launch.py"
    ).read_text(encoding="utf-8")

    assert 'source "$SCRIPT_DIR/navigation_adapter_common.sh"' in wrapper
    assert "run_navigation_adapter start_mapping.sh" in wrapper
    assert "ros2 launch nav_bringup mapping.launch.py" in adapter
    assert 'READY_FILE="$MAP_DIR/.ground_generation_started"' in adapter
    assert "RUN_LOG_OFFSET" in adapter
    assert 'mapping_log_has "publish use livox custom format"' in adapter
    assert 'mapping_log_has "Map init done"' in adapter
    assert "ros2 service type /save_terrain_map" in adapter
    assert 'date \'+%Y-%m-%d %H:%M:%S\' > "$READY_FILE"' in adapter
    assert 'package="livox_ros_driver2"' in launch
    assert 'executable="super_lio_node"' in launch
    assert 'executable="nav_terrain_analysis"' in launch
    assert 'executable="nav_save_terrain_map"' in launch


def test_start_mapping_adapter_uses_current_workspace_and_absolute_map_dir():
    botdog_root = Path(__file__).resolve().parents[1]
    navigation_root = botdog_root.parent / "Navigation"
    adapter = (navigation_root / "adapters" / "legacy_scripts" / "start_mapping.sh").read_text(encoding="utf-8")
    common = (navigation_root / "adapters" / "legacy_scripts" / "common.sh").read_text(encoding="utf-8")
    launch = (navigation_root / "src" / "nav_bringup" / "launch" / "mapping.launch.py").read_text(encoding="utf-8")

    assert "source_navigation_env" in adapter
    assert '"map_dir:=$MAP_DIR"' in adapter
    assert '"livox_config_path:=$LIVOX_CONFIG_PATH"' in adapter
    assert 'ROBOT_NAV_WS="${ROBOT_NAV_WS:-$(cd "$SCRIPT_DIR/../.." && pwd)}"' in common
    assert 'source "$ROBOT_NAV_WS/install/setup.bash"' in common
    assert '"lio.map.save_map_dir": map_dir' in launch


def test_start_mapping_adapter_requests_save_before_stopping_launch():
    botdog_root = Path(__file__).resolve().parents[1]
    navigation_root = botdog_root.parent / "Navigation"
    adapter = (navigation_root / "adapters" / "legacy_scripts" / "start_mapping.sh").read_text(encoding="utf-8")
    common = (navigation_root / "adapters" / "legacy_scripts" / "common.sh").read_text(encoding="utf-8")

    save_call = 'request_save_terrain_map "$LOG_FILE"'
    superlio_stop_call = 'kill -INT "$superlio_pid"'
    launch_stop_call = 'signal_launch_tree INT'
    assert save_call in adapter
    assert superlio_stop_call in adapter
    assert launch_stop_call in adapter
    assert adapter.index(save_call) < adapter.index(superlio_stop_call)
    assert adapter.index(superlio_stop_call) < adapter.index(launch_stop_call)
    assert 'timeout 45s ros2 service call /save_terrain_map' in common
    assert 'setsid ros2 launch nav_bringup mapping.launch.py' in adapter
    assert 'find_launch_descendant "super_lio_node"' in adapter
    assert 'wait_for_process_exit "$superlio_pid" "$SUPERLIO_SAVE_TIMEOUT_SECONDS"' in adapter
    assert "CLEANING_UP=1" in adapter
    assert "trap - INT TERM EXIT" in adapter
    assert 'wait "$LAUNCH_PID"' in adapter


def test_start_mapping_adapter_gracefully_saves_map_on_sigint(tmp_path):
    botdog_root = Path(__file__).resolve().parents[1]
    adapter = botdog_root.parent / "Navigation" / "adapters" / "legacy_scripts" / "start_mapping.sh"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    map_dir = tmp_path / "maps" / "Scene1_test"
    log_dir = tmp_path / "logs"
    runtime_dir = tmp_path / "runtime"
    fake_workspace = tmp_path / "navigation"
    fake_workspace.mkdir()
    setup_file = tmp_path / "setup.bash"
    setup_file.write_text("true\n", encoding="utf-8")

    superlio_node = fake_bin / "super_lio_node"
    superlio_node.write_text(
        """#!/usr/bin/python3
import signal
import sys
import time
from pathlib import Path

map_dir = Path(sys.argv[1])

def save_map(signum, frame):
    (map_dir / "map.pcd").write_text("FAKE_PCD\\n", encoding="utf-8")
    raise SystemExit(0)

signal.signal(signal.SIGINT, save_map)
signal.signal(signal.SIGTERM, save_map)
while True:
    time.sleep(0.1)
""",
        encoding="utf-8",
    )
    worker_node = fake_bin / "mapping_worker"
    worker_node.write_text(
        """#!/usr/bin/python3
import signal
import time

def stop(signum, frame):
    raise SystemExit(0)

signal.signal(signal.SIGINT, stop)
signal.signal(signal.SIGTERM, stop)
while True:
    time.sleep(0.1)
""",
        encoding="utf-8",
    )
    fake_ros2 = fake_bin / "ros2"
    fake_ros2.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
case "${1:-} ${2:-}" in
  "service type")
    printf 'std_srvs/srv/Trigger\n'
    ;;
  "service call")
    printf 'FAKE_GROUND_PCD\n' > "$FAKE_MAP_DIR/terrain_map_test_ground.pcd"
    printf 'response: success=True\n'
    ;;
  "launch nav_bringup")
    printf 'livox/lidar publish use livox custom format\n'
    printf '[SuperLIO]: Map init done\n'
    "$FAKE_SUPERLIO_NODE" "$FAKE_MAP_DIR" &
    superlio_pid=$!
    "$FAKE_MAPPING_WORKER" &
    worker_pid=$!
    wait "$superlio_pid"
    wait "$worker_pid"
    ;;
  *)
    printf 'unexpected fake ros2 call: %s\n' "$*" >&2
    exit 2
    ;;
esac
""",
        encoding="utf-8",
    )
    for executable in (superlio_node, worker_node, fake_ros2):
        executable.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "NAV_ENV_FILE": "/dev/null",
            "ROS2_SETUP_FILE": str(setup_file),
            "ROBOT_NAV_WS": str(fake_workspace),
            "ROBOT_NAV_MAP_ROOT": str(tmp_path / "maps"),
            "ROBOT_NAV_LOG_ROOT": str(log_dir),
            "ROBOT_NAV_RUNTIME_ROOT": str(runtime_dir),
            "NAV_FASTDDS_PROFILE": str(tmp_path / "missing-fastdds.xml"),
            "LIVOX_HOST_IP": "192.168.123.222",
            "FAKE_MAP_DIR": str(map_dir),
            "FAKE_SUPERLIO_NODE": str(superlio_node),
            "FAKE_MAPPING_WORKER": str(worker_node),
            "MAPPING_READY_TIMEOUT_SECONDS": "5",
            "SUPERLIO_SAVE_TIMEOUT_SECONDS": "5",
            "LAUNCH_STOP_TIMEOUT_SECONDS": "3",
            "LAUNCH_TERM_TIMEOUT_SECONDS": "1",
        }
    )

    process = subprocess.Popen(
        ["bash", str(adapter), str(map_dir)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    ready_file = map_dir / ".ground_generation_started"
    deadline = time.monotonic() + 8
    while not ready_file.exists() and process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)

    try:
        assert ready_file.exists(), process.communicate(timeout=1)[0]
        stop_started_at = time.monotonic()
        process.send_signal(signal.SIGINT)
        output, _ = process.communicate(timeout=10)
        stop_elapsed = time.monotonic() - stop_started_at
    finally:
        if process.poll() is None:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            process.wait(timeout=2)

    assert process.returncode == 0, output
    assert stop_elapsed < 8, output
    assert (map_dir / "map.pcd").read_text(encoding="utf-8") == "FAKE_PCD\n"
    assert (map_dir / "terrain_map_test_ground.pcd").is_file()
    assert output.count("正在按顺序保存 terrain_map 和 SuperLIO map.pcd") == 1
    assert "请求 SuperLIO 优雅退出并保存 map.pcd" in output
    assert "SuperLIO 地图已保存" in output
    assert "发送 SIGTERM" not in output
    assert "发送 SIGKILL" not in output
