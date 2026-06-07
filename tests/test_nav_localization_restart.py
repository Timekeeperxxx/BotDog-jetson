from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import time
from pathlib import Path

import pytest
from fastapi import HTTPException

from backend import services_nav_localization
from backend.api.routes import nav as nav_routes
from backend.auth.schemas import AuthUserInternal
from backend.repositories.json_store import atomic_write_json
from backend.schemas import LocalizationRestartResponse
from backend.services_ros_nav import RosNavBridge


def _make_pid_paths(root: Path) -> dict[str, Path]:
    return {
        "livox_pid": root / "livox.pid",
        "relocation_pid": root / "relocation.pid",
        "global_planner_pid": root / "global_planner.pid",
        "p2p_move_base_pid": root / "p2p_move_base.pid",
        "cmd_vel_pid": root / "cmd_vel.pid",
    }


def _write_navigation_ready_marker(runtime_root: Path, scene_dir: Path) -> None:
    atomic_write_json(
        runtime_root / "navigation_ready.json",
        {
            "ready": True,
            "scene_dir": str(scene_dir),
            "map_pcd": str(scene_dir / "map.pcd"),
            "ground_pcd": str(scene_dir / "ground.pcd"),
        },
    )


def test_wait_for_pid_files_reads_all_files(tmp_path):
    pid_paths = _make_pid_paths(tmp_path)
    values = {
        "livox_pid": 101,
        "relocation_pid": 102,
        "global_planner_pid": 103,
        "p2p_move_base_pid": 104,
        "cmd_vel_pid": 105,
    }

    for name, path in pid_paths.items():
        path.write_text(f"{values[name]}\n", encoding="utf-8")

    result = services_nav_localization._wait_for_pid_files(pid_paths, timeout_s=0.5)

    assert result == values


def test_wait_for_pid_files_returns_none_for_missing_files(tmp_path):
    pid_paths = _make_pid_paths(tmp_path)
    pid_paths["livox_pid"].write_text("101\n", encoding="utf-8")

    result = services_nav_localization._wait_for_pid_files(pid_paths, timeout_s=0.2)

    assert result["livox_pid"] == 101
    assert result["relocation_pid"] is None
    assert result["global_planner_pid"] is None
    assert result["p2p_move_base_pid"] is None
    assert result["cmd_vel_pid"] is None


def test_localization_restart_response_preserves_initialpose_log_offset():
    response = LocalizationRestartResponse(
        success=True,
        running=True,
        pid=999,
        livox_pid=101,
        relocation_pid=102,
        global_planner_pid=103,
        p2p_move_base_pid=104,
        cmd_vel_pid=105,
        message="已启动重启脚本，导航可用",
        initialpose_wait_log_offset=12345,
    )

    assert response.model_dump()["initialpose_wait_log_offset"] == 12345


def test_inspect_relocation_initialization_detects_direct_pose(monkeypatch, tmp_path):
    log_path = tmp_path / "restart_navigation_localization.log"
    log_path.write_text(
        "Using initial pose from topic directly, skipping NDT/ICP...\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(services_nav_localization, "_restart_log_path", lambda: log_path)

    result = services_nav_localization.inspect_relocation_initialization(timeout_s=0)

    assert result["mode"] == "direct_pose"
    assert result["matched_map"] is False
    assert "未执行 NDT/ICP" in result["message"]


def test_inspect_relocation_initialization_detects_icp_success(monkeypatch, tmp_path):
    log_path = tmp_path / "restart_navigation_localization.log"
    log_path.write_text(
        "Global ICP Converged Succeed! FitnessScore: 0.42\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(services_nav_localization, "_restart_log_path", lambda: log_path)

    result = services_nav_localization.inspect_relocation_initialization(timeout_s=0)

    assert result["mode"] == "scan_match"
    assert result["matched_map"] is True
    assert "地图匹配" in result["message"]


def test_inspect_relocation_initialization_unknown_without_marker(monkeypatch, tmp_path):
    log_path = tmp_path / "restart_navigation_localization.log"
    log_path.write_text("Waiting for initial pose from topic\n", encoding="utf-8")
    monkeypatch.setattr(services_nav_localization, "_restart_log_path", lambda: log_path)

    result = services_nav_localization.inspect_relocation_initialization(timeout_s=0)

    assert result["mode"] == "unknown"
    assert result["matched_map"] is None


def test_wait_for_initialpose_log_waits_for_stable_init_frames(monkeypatch, tmp_path):
    log_path = tmp_path / "restart_navigation_localization.log"
    monkeypatch.setattr(services_nav_localization, "_restart_log_path", lambda: log_path)
    monkeypatch.setenv("NAV_INITIALPOSE_READY_MIN_INIT_FRAMES", "50")

    log_path.write_text(
        "kf_init() called. flg_get_init_guess_=false init_frame_count=9 imu_cout=190\n"
        "Waiting for initial pose from topic (/initialpose)...\n",
        encoding="utf-8",
    )
    result = services_nav_localization.wait_for_initialpose_log(offset=0, timeout_s=0.1)
    assert result["ready"] is False

    log_path.write_text(
        "kf_init() called. flg_get_init_guess_=false init_frame_count=9 imu_cout=190\n"
        "Waiting for initial pose from topic (/initialpose)...\n"
        "kf_init() called. flg_get_init_guess_=false init_frame_count=50 imu_cout=1030\n",
        encoding="utf-8",
    )
    result = services_nav_localization.wait_for_initialpose_log(offset=0, timeout_s=0.5)
    assert result["ready"] is True
    assert result["init_frame_count"] == 50


def test_initialpose_ready_route_waits_for_ros_subscriber(monkeypatch):
    subscriber_waits: list[float] = []

    class DummyBridge:
        def wait_for_initial_pose_subscribers(self, timeout_s: float) -> dict[str, object]:
            subscriber_waits.append(timeout_s)
            return {
                "ready": True,
                "topic": "/initialpose",
                "subscriber_count": 1,
                "graph_count": 1,
                "matched_count": 0,
                "message": "/initialpose 已匹配订阅者 1 个",
            }

    def fake_wait_for_initialpose_log(offset: int, timeout_s: float) -> dict[str, object]:
        assert offset == 7
        assert timeout_s == 3.0
        return {
            "ready": True,
            "marker": "Waiting for initial pose from topic",
            "offset": 99,
            "message": "Super-LIO 已稳定等待 initialpose",
        }

    monkeypatch.setattr(services_nav_localization, "wait_for_initialpose_log", fake_wait_for_initialpose_log)
    monkeypatch.setattr(
        services_nav_localization,
        "get_relocation_process_status",
        lambda: {"running": True, "pid": 123, "message": "Super-LIO relocation 进程运行中"},
    )
    monkeypatch.setattr(nav_routes, "get_ros_nav_bridge", lambda: DummyBridge())

    result = asyncio.run(
        nav_routes.nav_wait_initialpose_ready(
            offset=7,
            timeout_s=3.0,
            user=AuthUserInternal(id=1, username="admin", role="operator", token_version=1),
        )
    )

    assert result["ready"] is True
    assert result["initialpose_topic"] == "/initialpose"
    assert result["initialpose_subscriber_count"] == 1
    assert result["initialpose_graph_subscriber_count"] == 1
    assert result["initialpose_matched_subscriber_count"] == 0
    assert result["relocation_pid"] == 123
    assert result["relocation_running"] is True
    assert subscriber_waits == [3.0]


def test_initialpose_ready_route_rejects_without_ros_subscriber(monkeypatch):
    class DummyBridge:
        def wait_for_initial_pose_subscribers(self, timeout_s: float) -> dict[str, object]:
            return {
                "ready": False,
                "topic": "/initialpose",
                "subscriber_count": 0,
                "graph_count": 0,
                "matched_count": 0,
                "message": "/initialpose 暂无订阅者",
            }

    monkeypatch.setattr(
        services_nav_localization,
        "wait_for_initialpose_log",
        lambda offset, timeout_s: {
            "ready": True,
            "marker": "Waiting for initial pose from topic",
            "offset": 99,
            "message": "Super-LIO 已稳定等待 initialpose",
        },
    )
    monkeypatch.setattr(
        services_nav_localization,
        "get_relocation_process_status",
        lambda: {"running": True, "pid": 123, "message": "Super-LIO relocation 进程运行中"},
    )
    monkeypatch.setattr(nav_routes, "get_ros_nav_bridge", lambda: DummyBridge())

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            nav_routes.nav_wait_initialpose_ready(
                offset=0,
                timeout_s=2.0,
                user=AuthUserInternal(id=1, username="admin", role="operator", token_version=1),
            )
        )

    assert exc_info.value.status_code == 504
    assert exc_info.value.detail == "/initialpose 暂无订阅者"


def test_initialpose_ready_route_rejects_when_relocation_process_exited(monkeypatch):
    class DummyBridge:
        def wait_for_initial_pose_subscribers(self, timeout_s: float) -> dict[str, object]:
            raise AssertionError("subscriber check should not run when relocation is down")

    monkeypatch.setattr(
        services_nav_localization,
        "wait_for_initialpose_log",
        lambda offset, timeout_s: {
            "ready": True,
            "marker": "Waiting for initial pose from topic",
            "offset": 99,
            "message": "Super-LIO 已稳定等待 initialpose",
        },
    )
    monkeypatch.setattr(
        services_nav_localization,
        "get_relocation_process_status",
        lambda: {"running": False, "pid": 12192, "message": "Super-LIO relocation 进程未运行，pid=12192"},
    )
    monkeypatch.setattr(nav_routes, "get_ros_nav_bridge", lambda: DummyBridge())

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            nav_routes.nav_wait_initialpose_ready(
                offset=0,
                timeout_s=2.0,
                user=AuthUserInternal(id=1, username="admin", role="operator", token_version=1),
            )
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Super-LIO relocation 进程未运行，pid=12192"


def test_initialpose_subscriber_count_uses_ros_graph_when_matched_count_is_zero():
    class DummyPublisher:
        def get_subscription_count(self) -> int:
            return 0

    class DummyNode:
        def count_subscribers(self, topic: str) -> int:
            assert topic == "/initialpose"
            return 1

    bridge = RosNavBridge.__new__(RosNavBridge)
    bridge._node = DummyNode()
    bridge._initial_pose_publisher = DummyPublisher()

    counts = bridge.get_initial_pose_subscription_counts()

    assert counts == {
        "graph_count": 1,
        "matched_count": 0,
        "subscriber_count": 1,
    }


def test_restart_navigation_localization_uses_scene_dir_and_returns_pids(monkeypatch, tmp_path):
    scene_root = tmp_path / "MAPS"
    scene_dir = scene_root / "Scene1_测试"
    runtime_root = tmp_path / "data" / "nav_runtime"
    logs_root = tmp_path / "logs"
    script_path = tmp_path / "restart_navigation_localization.sh"

    scene_dir.mkdir(parents=True)
    runtime_root.mkdir(parents=True)
    logs_root.mkdir(parents=True)
    (scene_dir / "map.pcd").write_text("", encoding="utf-8")
    (scene_dir / "ground.pcd").write_text("", encoding="utf-8")
    script_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    atomic_write_json(
        runtime_root / "current_scene.json",
        {
            "scene_id": "Scene1_测试",
            "scene_dir": str(scene_dir),
            "map_pcd": str(scene_dir / "map.pcd"),
            "ground_pcd": str(scene_dir / "ground.pcd"),
            "updated_at": "2026-05-11T00:00:00.000Z",
        },
    )
    _write_navigation_ready_marker(runtime_root, scene_dir)

    monkeypatch.setattr(services_nav_localization.settings, "NAV_RUNTIME_DIR", str(runtime_root))
    monkeypatch.setattr(services_nav_localization, "_restart_script_path", lambda: script_path)
    monkeypatch.setattr(services_nav_localization, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(services_nav_localization, "_is_pid_alive", lambda pid: pid is not None)
    monkeypatch.setattr(services_nav_localization, "_find_cmd_vel_test_publisher_pids", lambda: [])
    monkeypatch.setattr(services_nav_localization, "_inspect_tf_health", lambda: (True, [], []))
    monkeypatch.setattr(
        services_nav_localization,
        "_wait_for_pid_files",
        lambda paths, timeout_s=20.0: {
            "livox_pid": 101,
            "relocation_pid": 102,
            "global_planner_pid": 103,
            "p2p_move_base_pid": 104,
            "cmd_vel_pid": 105,
        },
    )
    monkeypatch.setattr(services_nav_localization, "_restart_proc", None)

    popen_calls: list[dict[str, object]] = []

    class DummyProc:
        pid = 999
        stdout = None

        def poll(self):
            return None

    def fake_popen(args, **kwargs):
        popen_calls.append({"args": args, "kwargs": kwargs})
        return DummyProc()

    monkeypatch.setattr(services_nav_localization.subprocess, "Popen", fake_popen)

    result = services_nav_localization.restart_navigation_localization()

    assert popen_calls
    assert popen_calls[0]["args"] == ["bash", str(script_path), str(scene_dir)]
    assert result["pid"] == 999
    assert result["scene_id"] == "Scene1_测试"
    assert str(result["map_pcd"]).endswith("map.pcd")
    assert str(result["ground_pcd"]).endswith("ground.pcd")
    assert result["navigation_ready"] is True
    assert result["health"]["scene_ok"] is True
    assert result["health"]["map_pcd_ok"] is True
    assert result["health"]["ground_pcd_ok"] is True
    assert result["health"]["livox_ok"] is True
    assert result["health"]["relocation_ok"] is True
    assert result["health"]["global_planner_ok"] is True
    assert result["health"]["p2p_move_base_ok"] is True
    assert result["health"]["cmd_vel_test_publisher_running"] is False
    assert result["health"]["tf_ok"] is True
    assert result["warnings"] == []
    assert result["errors"] == []
    assert result["process_pids"]["livox"] == 101
    assert result["process_pids"]["cmd_vel"] is None
    assert result["health"]["cmd_vel_running"] is False
    assert result["message"] == "已启动重启脚本，导航可用"


def test_restart_navigation_localization_marks_missing_ground_unavailable(monkeypatch, tmp_path):
    scene_root = tmp_path / "MAPS"
    scene_dir = scene_root / "Scene1_测试"
    runtime_root = tmp_path / "data" / "nav_runtime"
    script_path = tmp_path / "restart_navigation_localization.sh"

    scene_dir.mkdir(parents=True)
    runtime_root.mkdir(parents=True)
    (scene_dir / "map.pcd").write_text("", encoding="utf-8")
    script_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    atomic_write_json(
        runtime_root / "current_scene.json",
        {
            "scene_id": "Scene1_测试",
            "scene_dir": str(scene_dir),
            "map_pcd": str(scene_dir / "map.pcd"),
            "ground_pcd": str(scene_dir / "ground.pcd"),
            "updated_at": "2026-05-11T00:00:00.000Z",
        },
    )
    _write_navigation_ready_marker(runtime_root, scene_dir)

    monkeypatch.setattr(services_nav_localization.settings, "NAV_RUNTIME_DIR", str(runtime_root))
    monkeypatch.setattr(services_nav_localization, "_restart_script_path", lambda: script_path)
    monkeypatch.setattr(services_nav_localization, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(services_nav_localization, "_is_pid_alive", lambda pid: pid is not None)
    monkeypatch.setattr(services_nav_localization, "_find_cmd_vel_test_publisher_pids", lambda: [])
    monkeypatch.setattr(services_nav_localization, "_inspect_tf_health", lambda: (True, [], []))
    monkeypatch.setattr(
        services_nav_localization,
        "_wait_for_pid_files",
        lambda paths, timeout_s=20.0: {
            "livox_pid": 101,
            "relocation_pid": 102,
            "global_planner_pid": 103,
            "p2p_move_base_pid": 104,
            "cmd_vel_pid": 105,
        },
    )
    monkeypatch.setattr(services_nav_localization, "_restart_proc", None)

    class DummyProc:
        pid = 999
        stdout = None

        def poll(self):
            return None

    monkeypatch.setattr(services_nav_localization.subprocess, "Popen", lambda *args, **kwargs: DummyProc())

    result = services_nav_localization.restart_navigation_localization()

    assert result["health"]["scene_ok"] is True
    assert result["health"]["map_pcd_ok"] is True
    assert result["health"]["ground_pcd_ok"] is False
    assert result["navigation_ready"] is False
    assert "ground.pcd 缺失" in result["errors"]
    assert "ground.pcd 缺失" in result["message"]


def test_restart_navigation_localization_detects_cmd_vel_test_publisher_residual(monkeypatch, tmp_path):
    scene_root = tmp_path / "MAPS"
    scene_dir = scene_root / "Scene1_测试"
    runtime_root = tmp_path / "data" / "nav_runtime"
    script_path = tmp_path / "restart_navigation_localization.sh"

    scene_dir.mkdir(parents=True)
    runtime_root.mkdir(parents=True)
    (scene_dir / "map.pcd").write_text("", encoding="utf-8")
    (scene_dir / "ground.pcd").write_text("", encoding="utf-8")
    script_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    atomic_write_json(
        runtime_root / "current_scene.json",
        {
            "scene_id": "Scene1_测试",
            "scene_dir": str(scene_dir),
            "map_pcd": str(scene_dir / "map.pcd"),
            "ground_pcd": str(scene_dir / "ground.pcd"),
            "updated_at": "2026-05-11T00:00:00.000Z",
        },
    )
    _write_navigation_ready_marker(runtime_root, scene_dir)

    monkeypatch.setattr(services_nav_localization.settings, "NAV_RUNTIME_DIR", str(runtime_root))
    monkeypatch.setattr(services_nav_localization, "_restart_script_path", lambda: script_path)
    monkeypatch.setattr(services_nav_localization, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(services_nav_localization, "_is_pid_alive", lambda pid: pid is not None)
    monkeypatch.setattr(services_nav_localization, "_find_cmd_vel_test_publisher_pids", lambda: [7777])
    monkeypatch.setattr(services_nav_localization, "_inspect_tf_health", lambda: (True, [], []))
    monkeypatch.setattr(
        services_nav_localization,
        "_wait_for_pid_files",
        lambda paths, timeout_s=20.0: {
            "livox_pid": 101,
            "relocation_pid": 102,
            "global_planner_pid": 103,
            "p2p_move_base_pid": 104,
            "cmd_vel_pid": 105,
        },
    )
    monkeypatch.setattr(services_nav_localization, "_restart_proc", None)

    class DummyProc:
        pid = 999
        stdout = None

        def poll(self):
            return None

    monkeypatch.setattr(services_nav_localization.subprocess, "Popen", lambda *args, **kwargs: DummyProc())

    result = services_nav_localization.restart_navigation_localization()

    assert result["health"]["cmd_vel_test_publisher_running"] is True
    assert result["navigation_ready"] is False
    assert any("cmd_vel 测试发布器残留" in warning for warning in result["warnings"])
    assert "cmd_vel 测试发布器残留" in result["message"]


def test_find_cmd_vel_test_publisher_pids_ignores_generic_cmd_vel_publisher(monkeypatch):
    seen_needles: list[str] = []

    class DummyCompletedProcess:
        stdout = ""

    def fake_run(args, **kwargs):
        seen_needles.append(args[-1])
        if args[-1] == "cmd_vel_publisher":
            return DummyCompletedProcess()
        if "test_cmd_vel_publisher.py" in args[-1]:
            return type("Completed", (), {"stdout": "1234 python backend/scripts/test_cmd_vel_publisher.py"})()
        return DummyCompletedProcess()

    monkeypatch.setattr(services_nav_localization.subprocess, "run", fake_run)

    pids = services_nav_localization._find_cmd_vel_test_publisher_pids()

    assert "cmd_vel_publisher" not in seen_needles
    assert pids == [1234]


def test_restart_navigation_localization_marks_missing_pid_false(monkeypatch, tmp_path):
    scene_root = tmp_path / "MAPS"
    scene_dir = scene_root / "Scene1_测试"
    runtime_root = tmp_path / "data" / "nav_runtime"
    script_path = tmp_path / "restart_navigation_localization.sh"

    scene_dir.mkdir(parents=True)
    runtime_root.mkdir(parents=True)
    (scene_dir / "map.pcd").write_text("", encoding="utf-8")
    (scene_dir / "ground.pcd").write_text("", encoding="utf-8")
    script_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    atomic_write_json(
        runtime_root / "current_scene.json",
        {
            "scene_id": "Scene1_测试",
            "scene_dir": str(scene_dir),
            "map_pcd": str(scene_dir / "map.pcd"),
            "ground_pcd": str(scene_dir / "ground.pcd"),
            "updated_at": "2026-05-11T00:00:00.000Z",
        },
    )

    monkeypatch.setattr(services_nav_localization.settings, "NAV_RUNTIME_DIR", str(runtime_root))
    monkeypatch.setattr(services_nav_localization, "_restart_script_path", lambda: script_path)
    monkeypatch.setattr(services_nav_localization, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(services_nav_localization, "_find_cmd_vel_test_publisher_pids", lambda: [])
    monkeypatch.setattr(services_nav_localization, "_find_pids_by_needles", lambda needles: [])
    monkeypatch.setattr(services_nav_localization, "_inspect_tf_health", lambda: (True, [], []))
    monkeypatch.setattr(
        services_nav_localization,
        "_wait_for_pid_files",
        lambda paths, timeout_s=20.0: {
            "livox_pid": 101,
            "relocation_pid": 102,
            "global_planner_pid": 103,
            "p2p_move_base_pid": 104,
            "cmd_vel_pid": 105,
        },
    )
    monkeypatch.setattr(services_nav_localization, "_restart_proc", None)

    class DummyProc:
        pid = 999
        stdout = None

        def poll(self):
            return None

    monkeypatch.setattr(services_nav_localization.subprocess, "Popen", lambda *args, **kwargs: DummyProc())
    monkeypatch.setattr(services_nav_localization, "_is_pid_alive", lambda pid: pid not in {103})

    result = services_nav_localization.restart_navigation_localization()

    assert result["health"]["global_planner_ok"] is False
    assert result["navigation_ready"] is False
    assert any("global_planner 未就绪" in error for error in result["errors"])


def test_global_planner_health_falls_back_to_node_process_when_launch_pid_exited(monkeypatch, tmp_path):
    scene_dir = tmp_path / "Scene1_测试"
    runtime_root = tmp_path / "data" / "nav_runtime"
    scene_dir.mkdir(parents=True)
    runtime_root.mkdir(parents=True)
    (scene_dir / "map.pcd").write_text("", encoding="utf-8")
    (scene_dir / "ground.pcd").write_text("", encoding="utf-8")
    atomic_write_json(
        runtime_root / "current_scene.json",
        {
            "scene_id": "Scene1_测试",
            "scene_dir": str(scene_dir),
            "map_pcd": str(scene_dir / "map.pcd"),
            "ground_pcd": str(scene_dir / "ground.pcd"),
            "updated_at": "2026-05-11T00:00:00.000Z",
        },
    )
    _write_navigation_ready_marker(runtime_root, scene_dir)

    monkeypatch.setattr(services_nav_localization.settings, "NAV_RUNTIME_DIR", str(runtime_root))
    monkeypatch.setattr(services_nav_localization, "_is_pid_alive", lambda pid: pid not in {103})
    monkeypatch.setattr(services_nav_localization, "_find_cmd_vel_test_publisher_pids", lambda: [])
    monkeypatch.setattr(services_nav_localization, "_inspect_tf_health", lambda: (True, [], []))

    def fake_find_pids_by_needles(needles):
        joined = "\n".join(needles)
        if "global_planner_node" in joined:
            return [2203]
        return []

    monkeypatch.setattr(services_nav_localization, "_find_pids_by_needles", fake_find_pids_by_needles)

    result = services_nav_localization._build_restart_health(
        services_nav_localization.load_current_scene(strict=False),
        {
            "livox_pid": 101,
            "relocation_pid": 102,
            "global_planner_pid": 103,
            "p2p_move_base_pid": 104,
            "cmd_vel_pid": None,
        },
    )

    assert result["health"]["global_planner_ok"] is True
    assert result["navigation_ready"] is True


def test_wait_navigation_runtime_ready_retries_transient_global_planner_not_ready(monkeypatch):
    calls = {"count": 0}

    def fake_assert_navigation_runtime_ready():
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("导航链路未就绪，禁止发布目标点: global_planner 未就绪")
        return {"navigation_ready": True}

    monkeypatch.setattr(
        services_nav_localization,
        "assert_navigation_runtime_ready",
        fake_assert_navigation_runtime_ready,
    )

    result = services_nav_localization.wait_navigation_runtime_ready(timeout_s=0.5, poll_interval_s=0.01)

    assert result["navigation_ready"] is True
    assert calls["count"] == 2


def test_wait_navigation_runtime_ready_raises_last_error_after_timeout(monkeypatch):
    calls = {"count": 0}

    def fake_assert_navigation_runtime_ready():
        calls["count"] += 1
        raise RuntimeError("导航链路未就绪，禁止发布目标点: global_planner 未就绪")

    monkeypatch.setattr(
        services_nav_localization,
        "assert_navigation_runtime_ready",
        fake_assert_navigation_runtime_ready,
    )

    with pytest.raises(RuntimeError, match="global_planner 未就绪"):
        services_nav_localization.wait_navigation_runtime_ready(timeout_s=0.03, poll_interval_s=0.01)

    assert calls["count"] >= 2


def test_restart_script_prefers_exact_scene_pcd_files(tmp_path):
    real_repo_root = Path(__file__).resolve().parents[1]
    project_root = tmp_path / "Project" / "BOTDOG"
    botdog_root = project_root / "BotDog"
    script_dir = botdog_root / "scripts"
    runtime_dir = botdog_root / "data" / "nav_runtime"
    fake_home = tmp_path / "home" / "jetson"
    fake_bin = tmp_path / "bin"
    scene_dir = tmp_path / "Scene1_测试"
    script_path = script_dir / "restart_navigation_localization.sh"

    script_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    scene_dir.mkdir(parents=True)
    fake_bin.mkdir(parents=True)
    (scene_dir / "map.pcd").write_text("", encoding="utf-8")
    (scene_dir / "ground.pcd").write_text("", encoding="utf-8")
    (scene_dir / "Scene1_half_map.pcd").write_text("", encoding="utf-8")
    (scene_dir / "Scene1_half_ground.pcd").write_text("", encoding="utf-8")
    script_path.write_text(
        (real_repo_root / "scripts" / "restart_navigation_localization.sh").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    script_path.chmod(0o755)

    superlio_setup = fake_home / "superlio" / "install" / "setup.bash"
    navigation_setup = fake_home / "dddmr_navigation_new_local" / "install" / "setup.bash"
    ros2_setup = tmp_path / "opt" / "ros" / "humble" / "setup.bash"
    superlio_root = fake_home / "superlio" / "Super-LIO-ros2" / "src" / "super_lio"
    superlio_setup.parent.mkdir(parents=True, exist_ok=True)
    navigation_setup.parent.mkdir(parents=True, exist_ok=True)
    ros2_setup.parent.mkdir(parents=True, exist_ok=True)
    superlio_root.mkdir(parents=True, exist_ok=True)
    superlio_setup.write_text("", encoding="utf-8")
    navigation_setup.write_text("", encoding="utf-8")
    ros2_setup.write_text("", encoding="utf-8")

    fake_ros2 = fake_bin / "ros2"
    fake_ros2.write_text(
        "#!/usr/bin/env bash\n"
        "if [ \"${1:-}\" = \"topic\" ] && [ \"${2:-}\" = \"echo\" ]; then\n"
        "  echo 'data: ok'\n"
        "  exit 0\n"
        "fi\n"
        "tail -f /dev/null\n",
        encoding="utf-8",
    )
    fake_ros2.chmod(0o755)

    fake_sleep = fake_bin / "sleep"
    fake_sleep.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_sleep.chmod(0o755)

    fake_cmd_vel_bootstrap = project_root / "test_cmd_vel_fixed.sh"
    fake_cmd_vel_bootstrap.write_text(
        "#!/usr/bin/env bash\n"
        "exec python -c 'import time; time.sleep(60)'\n",
        encoding="utf-8",
    )
    fake_cmd_vel_bootstrap.chmod(0o755)

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["ROS2_SETUP_FILE"] = str(ros2_setup)

    proc = subprocess.Popen(
        ["bash", str(script_path), str(scene_dir)],
        cwd=str(project_root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        preexec_fn=os.setsid,
    )

    try:
        deadline = time.time() + 15.0
        expected_pid_files = [
            runtime_dir / "livox.pid",
            runtime_dir / "relocation.pid",
            runtime_dir / "global_planner.pid",
            runtime_dir / "p2p_move_base.pid",
        ]
        ready_file = runtime_dir / "navigation_ready.json"

        while time.time() < deadline:
            if all(path.exists() for path in expected_pid_files) and ready_file.exists():
                break
            if proc.poll() is not None:
                break
            time.sleep(0.1)

        output = ""
        try:
            proc_group = os.getpgid(proc.pid)
            os.killpg(proc_group, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except Exception:
            pass

        try:
            output, _ = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                pass
            output, _ = proc.communicate(timeout=5)

        assert "当前 map.pcd: " in output
        assert str(scene_dir / "map.pcd") in output
        assert "当前 ground.pcd: " in output
        assert str(scene_dir / "ground.pcd") in output
        for path in expected_pid_files:
            assert path.exists()
        assert ready_file.exists()
        assert not (runtime_dir / "cmd_vel.pid").exists()
        assert "跳过 cmd_vel 硬件桥接启动" in output
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            pass
        for path in (
            fake_cmd_vel_bootstrap,
            fake_ros2,
            fake_sleep,
        ):
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def test_restart_navigation_script_resets_backend_python_and_qt_env():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "restart_navigation_localization.sh"
    content = script_path.read_text(encoding="utf-8")

    assert 'ROS2_SETUP_FILE="${ROS2_SETUP_FILE:-/opt/ros/humble/setup.bash}"' in content
    assert 'source_ros_setup "$ROS2_SETUP_FILE"' in content
    assert "unset QT_PLUGIN_PATH" in content
    assert "unset QT_QPA_PLATFORM_PLUGIN_PATH" in content
    assert "unset QT_QPA_PLATFORM" in content
    assert "unset CYCLONEDDS_HOME" in content
    assert "unset CYCLONEDDS_URI" in content
    assert '_remove_path_segment LD_LIBRARY_PATH "/home/jetson/cyclonedds-0.10x/install/lib"' in content
    assert '_remove_path_segment LD_LIBRARY_PATH "/home/jetson/Project/BOTDOG/BotDog/.venv/lib/python3.10/site-packages/cv2/../../lib64"' in content
    assert '_remove_path_segment PYTHONPATH "/home/jetson/Project/BOTDOG/BotDog"' in content
    assert '_prepend_path_segment PYTHONPATH "/usr/local/lib/python3.10/site-packages/"' in content


def test_restart_navigation_script_uses_real_time_and_cleans_local_navigation_nodes():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "restart_navigation_localization.sh"
    content = script_path.read_text(encoding="utf-8")

    assert '"local_map_builder"' in content
    assert '"/home/jetson/dddmr_navigation_new_local/install/p2p_move_base/lib/p2p_move_base/p2p_move_base_node"' in content
    assert '"/home/jetson/dddmr_navigation_new_local/install/dddmr_local_map/lib/dddmr_local_map/local_map_builder"' in content
    assert "ros2 run super_lio relocation_node" in content
    assert '-p "lio.map.save_map_dir:=$relative_map_dir"' in content
    assert '-p "lio.map.map_name:=$map_name"' in content
    assert "wait_for_navigation_maps" in content
    assert "navigation_ready.json" in content
    assert '"map_dir:=$MAP_PCD" "ground_dir:=$GROUND_PCD"' in content
    assert 'p2p_move_base go2_localization_launch.py "启动 P2P move base 定位导航..." P2P_MOVE_BASE_PID p2p_move_base.pid "use_sim:=false"' in content


def test_restart_navigation_script_retries_livox_topic_waits():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "restart_navigation_localization.sh"
    content = script_path.read_text(encoding="utf-8")

    assert 'timeout 5s ros2 topic echo "$topic" --once' in content
    assert '仍在等待 $label 数据：$topic' in content
    assert 'wait_for_topic_once /livox/imu "${NAV_LIVOX_IMU_WAIT_TIMEOUT_S:-30}" "Livox IMU"' in content
    assert 'wait_for_topic_once /livox/lidar "${NAV_LIVOX_LIDAR_WAIT_TIMEOUT_S:-60}" "Livox LiDAR"' in content
