import asyncio
from pathlib import Path
from types import SimpleNamespace

from backend.api.routes import nav as nav_routes
from backend.auth.schemas import AuthUserInternal
from backend.schemas import MappingControlRequest
from backend import services_rosbag_recording as recording_module


class DummyProcess:
    _next_pid = 9000

    def __init__(self):
        self.pid = DummyProcess._next_pid
        DummyProcess._next_pid += 1
        self.returncode = None

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        del timeout
        return self.returncode


def configure_service(monkeypatch, tmp_path: Path):
    script = tmp_path / "record_mapping_sensors.sh"
    script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    monkeypatch.setattr(recording_module, "RECORD_SCRIPT", script)
    monkeypatch.setattr(recording_module, "NAVIGATION_ROOT", tmp_path)
    monkeypatch.setattr(recording_module, "ROSBAG_ROOT", tmp_path / "bags")
    monkeypatch.setattr(recording_module, "LOG_ROOT", tmp_path / "logs")
    monkeypatch.setattr(recording_module.time, "sleep", lambda _: None)


def test_mapping_recording_reuses_lidar_without_starting_driver(monkeypatch, tmp_path):
    configure_service(monkeypatch, tmp_path)
    bag_process = DummyProcess()
    monkeypatch.setattr(recording_module.RosbagRecordingService, "_existing_lidar_topic", staticmethod(
        lambda: ("/livox/lidar", "livox_ros_driver2/msg/CustomMsg")
    ))
    monkeypatch.setattr(recording_module, "_start_livox_driver", lambda: (_ for _ in ()).throw(
        AssertionError("建图中录包不应重复启动雷达驱动")
    ))
    monkeypatch.setattr(recording_module.subprocess, "Popen", lambda *args, **kwargs: bag_process)

    service = recording_module.RosbagRecordingService()
    result = service.start(mapping_active=True)

    assert result["running"] is True
    assert result["lidar_mode"] == "mapping"
    assert result["mapping_active_at_start"] is True


def test_standalone_stop_flushes_bag_before_stopping_owned_lidar(monkeypatch, tmp_path):
    configure_service(monkeypatch, tmp_path)
    bag_process = DummyProcess()
    driver_process = DummyProcess()
    events = []
    monkeypatch.setattr(recording_module.RosbagRecordingService, "_existing_lidar_topic", staticmethod(
        lambda: (None, None)
    ))
    monkeypatch.setattr(recording_module, "_start_livox_driver", lambda: (driver_process, None))
    monkeypatch.setattr(
        recording_module,
        "_wait_for_radar_topic",
        lambda timeout: ({"/livox/lidar": "livox_ros_driver2/msg/CustomMsg"}, "/livox/lidar", "livox_ros_driver2/msg/CustomMsg"),
    )
    monkeypatch.setattr(recording_module.subprocess, "Popen", lambda *args, **kwargs: bag_process)
    monkeypatch.setattr(recording_module.os, "getpgid", lambda pid: pid)

    def fake_killpg(pid, sig):
        events.append("bag-signal")
        bag_process.returncode = 0

    monkeypatch.setattr(recording_module.os, "killpg", fake_killpg)
    monkeypatch.setattr(recording_module, "_stop_livox_driver", lambda process: events.append("driver-stop"))

    service = recording_module.RosbagRecordingService()
    started = service.start(mapping_active=False)
    Path(started["output_dir"]).mkdir(parents=True)
    (Path(started["output_dir"]) / "metadata.yaml").write_text("rosbag2_bagfile_information:\n", encoding="utf-8")
    stopped = service.stop()

    assert started["lidar_mode"] == "owned"
    assert stopped["saved"] is True
    assert events == ["bag-signal", "driver-stop"]


def test_mapping_start_stops_recording_before_starting_mapping(monkeypatch):
    events = []

    class DummyRecordingService:
        def stop_before_mapping_transition(self, *, reason):
            events.append(("recording-stop", reason))
            return {"running": False, "message": "录包已停止"}

    class DummyMappingService:
        def start(self, scene_name):
            events.append(("mapping-start", scene_name))
            return {
                "success": True,
                "enabled": True,
                "running": True,
                "saving": False,
                "saved": False,
                "scene_name": f"Scene1_{scene_name}",
                "map_dir": f"/home/jetson/Projects/Maps/Scene1_{scene_name}",
                "pid": 1234,
                "map_pcd_candidates": [],
                "ground_pcd_candidates": [],
                "pcd_files": [],
                "message": "建图已启动",
            }

    async def no_audit(*args, **kwargs):
        return None

    monkeypatch.setattr("backend.services_mapping.get_mapping_service", lambda: DummyMappingService())
    monkeypatch.setattr(
        "backend.services_rosbag_recording.get_rosbag_recording_service",
        lambda: DummyRecordingService(),
    )
    monkeypatch.setattr("backend.services_radar_health.check_livox_network_preflight", lambda: {"ok": True})
    monkeypatch.setattr(nav_routes, "safe_write_audit_log", no_audit)
    monkeypatch.setattr(nav_routes, "_cancel_pending_auto_track_resume", lambda reason: None)
    monkeypatch.setattr(nav_routes, "_release_navigation_control", lambda: None)

    result = asyncio.run(nav_routes._nav_set_mapping_enabled_locked(
        MappingControlRequest(enabled=True, scene_name="测试"),
        AuthUserInternal(id=1, username="operator", role="operator", token_version=1),
        object(),
    ))

    assert events == [("recording-stop", "mapping_start"), ("mapping-start", "测试")]
    assert result["message"].startswith("已先停止录包；")
