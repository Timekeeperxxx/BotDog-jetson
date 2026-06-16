from __future__ import annotations

import asyncio
import signal
from pathlib import Path

import pytest

from backend.api.routes import nav as nav_routes
from backend.auth.schemas import AuthUserInternal
from backend import services_mapping as mapping_service_module
from backend.services_nav_waypoints import list_waypoints
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


def test_start_mapping_creates_directory_and_launches_script(monkeypatch, tmp_path):
    script = tmp_path / "start_mapping.sh"
    script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")

    started: list[tuple[list[str], bool]] = []
    calls: list[str] = []
    tracker_calls: list[str] = []
    guard_enabled_state = {"enabled": True}

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
    assert calls == ["stop_navigation_processes", "stop_cmd_vel_script"]
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


def test_start_mapping_script_waits_for_superlio_before_terrain_analysis():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "start_mapping.sh"
    content = script_path.read_text(encoding="utf-8")

    superlio_line = 'start_isolated_process ros2 launch super_lio Livox_mid360.py rviz:=false enable_pgo:=false save_map_dir:="$SUPERLIO_SAVE_MAP_DIR" map_name:="map.pcd"'
    livox_line = 'start_isolated_process ros2 launch livox_ros_driver2 msg_MID360_launch.py'
    terrain_line = 'start_isolated_process ros2 launch terrain_analysis terrain_analysis_with_save.launch map_dir:="$MAP_DIR"'

    assert "start_isolated_process() {" in content
    assert superlio_line in content
    assert livox_line in content
    assert terrain_line in content
    assert 'setsid "$@" >> "$DEBUG_LOG" 2>&1 &' in content
    assert 'MAPPING_READY_FLAG="$MAP_DIR/.ground_generation_started"' in content
    assert 'wait_for_log_pattern "livox/lidar publish use livox custom format" 30 "$LIVOX_PID" "Livox 开始发布点云/IMU"' in content
    assert 'wait_with_abort 5 "$LIVOX_PID" "IMU 静止预热"' in content
    assert 'wait_for_log_pattern "Map init done" 60 "$SUPERLIO_PID" "SuperLIO 完成地图初始化"' in content
    assert content.index(livox_line) < content.index('wait_for_log_pattern "livox/lidar publish use livox custom format" 30 "$LIVOX_PID" "Livox 开始发布点云/IMU"')
    assert content.index('wait_for_log_pattern "livox/lidar publish use livox custom format" 30 "$LIVOX_PID" "Livox 开始发布点云/IMU"') < content.index('wait_with_abort 5 "$LIVOX_PID" "IMU 静止预热"')
    assert content.index('wait_with_abort 5 "$LIVOX_PID" "IMU 静止预热"') < content.index(superlio_line)
    assert content.index(superlio_line) < content.index('wait_for_log_pattern "Map init done" 60 "$SUPERLIO_PID" "SuperLIO 完成地图初始化"')
    assert content.index('wait_for_log_pattern "Map init done" 60 "$SUPERLIO_PID" "SuperLIO 完成地图初始化"') < content.index(terrain_line)
    assert 'printf \'%s\\n\' "$(date \'+%Y-%m-%d %H:%M:%S\')" > "$MAPPING_READY_FLAG"' in content
    assert 'wait_for_log_pattern() {' in content
    assert 'wait_with_abort() {' in content


def test_start_mapping_script_uses_superlio_relative_save_dir():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "start_mapping.sh"
    content = script_path.read_text(encoding="utf-8")

    assert 'SUPERLIO_ROOT_DIR="${SUPERLIO_ROOT_DIR:-$HOME/superlio/Super-LIO-ros2/src/super_lio}"' in content
    assert 'RELATIVE_MAP_DIR="$(realpath --relative-to="$SUPERLIO_ROOT_DIR" "$MAP_DIR" 2>/dev/null || true)"' in content
    assert 'echo "SuperLIO 保存目录参数：$SUPERLIO_SAVE_MAP_DIR"' in content
    assert 'source install/setup.bash' in content
    assert "unset CYCLONEDDS_HOME" in content
    assert "unset CYCLONEDDS_URI" in content
    assert "export ROS_DOMAIN_ID=0" in content
    assert '_remove_path_segment LD_LIBRARY_PATH "/home/jetson/cyclonedds-0.10x/install/lib"' in content
    assert '_remove_path_segment LD_LIBRARY_PATH "/home/jetson/Project/BOTDOG/BotDog/.venv/lib/python3.10/site-packages/cv2/../../lib64"' in content
    assert '_remove_path_segment PYTHONPATH "/home/jetson/Project/BOTDOG/BotDog"' in content
    assert '_prepend_path_segment LD_LIBRARY_PATH "/usr/local/cuda-12.6/lib64"' in content
    assert '_prepend_path_segment LD_LIBRARY_PATH "/usr/local/lib"' in content
    assert '_prepend_path_segment PYTHONPATH "/usr/local/lib/python3.10/site-packages/"' in content


def test_start_mapping_script_waits_for_superlio_save_on_shutdown():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "start_mapping.sh"
    content = script_path.read_text(encoding="utf-8")

    assert "SIGINT super_lio_node" in content
    assert "SIGINT super_lio 进程组" in content
    assert 'while [ $waited -lt 2000 ] && kill -0 "$superlio_node_pid" 2>/dev/null; do' in content
    assert "super_lio_node 2000s 未退出，SIGKILL" in content
