from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import threading
import time
import types
from pathlib import Path

import pytest
from fastapi import HTTPException

from backend import services_nav_localization
from backend.api.routes import nav as nav_routes
from backend.auth.schemas import AuthUserInternal
from backend.repositories.json_store import atomic_write_json
from backend.schemas import LocalizationRestartResponse
from backend.services_nav_state import get_nav_state
from backend.services_ros_nav import RosNavBridge


@pytest.fixture(autouse=True)
def _connected_navigation_radar(monkeypatch):
    monkeypatch.setattr(
        services_nav_localization,
        "check_livox_network_preflight",
        lambda: {"ok": True, "message": "雷达物理链路正常"},
    )


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
            "stage": "running",
            "scene_dir": str(scene_dir),
            "map_pcd": str(scene_dir / "map.pcd"),
            "ground_pcd": str(scene_dir / "ground.pcd"),
            "planground_pcd": str(scene_dir / "terrain_base_footprint_fill.pcd"),
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


def test_wait_for_pid_files_stops_when_restart_script_exits(tmp_path):
    pid_paths = _make_pid_paths(tmp_path)
    started_at = time.monotonic()

    result = services_nav_localization._wait_for_pid_files(
        pid_paths,
        timeout_s=5.0,
        abort_if=lambda: True,
    )

    assert all(pid is None for pid in result.values())
    assert time.monotonic() - started_at < 0.5


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


def test_restart_startup_error_only_returns_current_navigation_root_cause(monkeypatch, tmp_path):
    log_path = tmp_path / "restart_navigation_localization.log"
    old_content = "[Navigation][错误] 上一轮错误\n"
    log_path.write_text(
        old_content
        + "[Navigation] map.pcd 格式检查通过\n"
        + "[Navigation][错误] PCD 动态内存预检：预计导航峰值=8.00 GiB\n"
        + "[Navigation][错误] 导航启动需要至少 12.00 GiB 可用内存\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(services_nav_localization, "_restart_log_path", lambda: log_path)

    message = services_nav_localization._restart_startup_error_since(len(old_content))

    assert message is not None
    assert "上一轮错误" not in message
    assert "预计导航峰值=8.00 GiB" in message
    assert "导航启动需要至少 12.00 GiB" in message


@pytest.mark.parametrize(
    "log_line,error_code,message_part",
    [
        (
            "Received the request before static layer is ready\n",
            "GLOBAL_PLANNER_STATIC_LAYER_NOT_READY",
            "静态地图层还没加载完成",
        ),
        (
            "Goal is not found.\nUsing vertical search to find a goal on the ground.\n",
            "GLOBAL_PLANNER_GOAL_NOT_ON_GROUND",
            "目标点不在 global_planner 的地面点云附近",
        ),
        (
            "Start is not found.\n",
            "GLOBAL_PLANNER_START_NOT_ON_GROUND",
            "机器狗当前位置不在 global_planner 的地面点云附近",
        ),
        (
            "No path found from: 10 to 42\n",
            "GLOBAL_PLANNER_NO_CONNECTED_PATH",
            "没有可连通路径",
        ),
        (
            "Failed to transform pointcloud: lookupTransform failed\n",
            "GLOBAL_PLANNER_TF_LOOKUP_FAILED",
            "获取机器狗 TF 失败",
        ),
    ],
)
def test_diagnose_recent_navigation_failure_classifies_planner_logs(monkeypatch, tmp_path, log_line, error_code, message_part):
    log_path = tmp_path / "restart_navigation_localization.log"
    log_path.write_text(log_line, encoding="utf-8")
    monkeypatch.setattr(services_nav_localization, "_restart_log_path", lambda: log_path)

    result = services_nav_localization.diagnose_recent_navigation_failure(max_log_age_s=60)

    assert result is not None
    assert result["error_code"] == error_code
    assert message_part in result["message"]


def test_diagnose_recent_navigation_failure_ignores_stale_logs(monkeypatch, tmp_path):
    log_path = tmp_path / "restart_navigation_localization.log"
    log_path.write_text("Goal is not found.\n", encoding="utf-8")
    old_time = time.time() - 3600
    os.utime(log_path, (old_time, old_time))
    monkeypatch.setattr(services_nav_localization, "_restart_log_path", lambda: log_path)

    result = services_nav_localization.diagnose_recent_navigation_failure(max_log_age_s=60)

    assert result is None


def test_diagnose_recent_navigation_failure_prefers_specific_goal_error_over_generic_no_path(monkeypatch, tmp_path):
    log_path = tmp_path / "restart_navigation_localization.log"
    log_path.write_text(
        "Goal is not found.\n"
        "Using vertical search to find a goal on the ground.\n"
        "No path found from: 10 to 42\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(services_nav_localization, "_restart_log_path", lambda: log_path)

    result = services_nav_localization.diagnose_recent_navigation_failure(max_log_age_s=60)

    assert result is not None
    assert result["error_code"] == "GLOBAL_PLANNER_GOAL_NOT_ON_GROUND"


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


def test_initialpose_ready_reports_missing_backend_publisher():
    class DummyPublisher:
        def get_subscription_count(self) -> int:
            return 1

    class DummyNode:
        def count_subscribers(self, topic: str) -> int:
            assert topic == "/initialpose"
            return 1

        def count_publishers(self, topic: str) -> int:
            assert topic == "/initialpose"
            return 0

    bridge = RosNavBridge.__new__(RosNavBridge)
    bridge._node = DummyNode()
    bridge._initial_pose_publisher = DummyPublisher()

    result = bridge.wait_for_initial_pose_subscribers(timeout_s=0.1)

    assert result["ready"] is False
    assert result["subscriber_count"] == 1
    assert result["backend_publisher_count"] == 0
    assert "后端 /initialpose publisher 未进入 ROS graph" in result["message"]


def test_ros_nav_pause_clears_node_and_publishers(monkeypatch):
    destroyed = []

    class DummyNode:
        def destroy_node(self) -> None:
            destroyed.append(True)

    bridge = RosNavBridge.__new__(RosNavBridge)
    bridge._paused = False
    bridge._node = DummyNode()
    bridge._publisher_lock = threading.RLock()
    bridge._pause_event = threading.Event()
    bridge._tf_buffer = object()
    bridge._tf_listener = object()
    bridge._nav_start_publisher = object()
    bridge._nav_task_start_publisher = object()
    bridge._cmd_vel_publisher = object()
    bridge._goal_xyz_publisher = object()
    bridge._goal_yaw_publisher = object()
    bridge._global_path_subscription = object()
    bridge._nav_status_subscription = object()
    bridge._estop_publisher = object()
    bridge._initial_pose_publisher = object()
    bridge._cloud_subscription = object()
    monkeypatch.setattr(bridge, "_use_tf_pose", lambda: True)
    monkeypatch.setattr(bridge, "_tf_source", lambda: "tf:map->base_footprint")

    bridge._pause_ros_node_for_mapping()

    assert destroyed == [True]
    assert bridge._paused is True
    assert bridge._pause_event.is_set()
    assert bridge._node is None
    assert bridge._initial_pose_publisher is None
    assert bridge._nav_task_start_publisher is None


def test_ros_nav_resume_recreates_node_and_resets_tf_state(monkeypatch):
    bridge = RosNavBridge.__new__(RosNavBridge)
    bridge._paused = True
    bridge._node = None
    bridge._rclpy = object()
    bridge._pause_event = threading.Event()
    bridge._pause_event.set()
    bridge._tf_available = True
    bridge._tf_wait_started_at = 123.0
    bridge._last_tf_lookup_at = 456.0
    monkeypatch.setattr(bridge, "_create_ros_node", lambda: "tf:map->base_footprint")

    bridge._resume_ros_node_after_mapping()

    assert bridge._paused is False
    assert not bridge._pause_event.is_set()
    assert bridge._tf_available is False
    assert bridge._tf_wait_started_at == 0.0
    assert bridge._last_tf_lookup_at == 0.0
    localization_status = get_nav_state()["localization_status"]
    assert localization_status["status"] == "initializing"
    assert localization_status["source"] == "tf:map->base_footprint"
    assert localization_status["message"] == "建图已结束，导航定位恢复中"


def test_ros_nav_resume_without_rclpy_unpauses_and_raises():
    bridge = RosNavBridge.__new__(RosNavBridge)
    bridge._paused = True
    bridge._node = None
    bridge._rclpy = None

    with pytest.raises(RuntimeError, match="rclpy 未初始化"):
        bridge._resume_ros_node_after_mapping()

    assert bridge._paused is False


def test_ros_nav_lifecycle_rejects_unknown_command():
    bridge = RosNavBridge.__new__(RosNavBridge)

    with pytest.raises(ValueError, match="未知 ROS2 导航节点生命周期操作"):
        bridge._handle_lifecycle_command("restart")


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
    (scene_dir / "terrain_base_footprint_fill.pcd").write_text("", encoding="utf-8")
    script_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    atomic_write_json(
        runtime_root / "current_scene.json",
        {
            "scene_id": "Scene1_测试",
            "scene_dir": str(scene_dir),
            "map_pcd": str(scene_dir / "map.pcd"),
            "ground_pcd": str(scene_dir / "ground.pcd"),
            "planground_pcd": str(scene_dir / "terrain_base_footprint_fill.pcd"),
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
        lambda paths, timeout_s=20.0, abort_if=None: {
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
    process_env = popen_calls[0]["kwargs"]["env"]
    assert process_env["NAV_LIDAR_MOUNT_Z_M"] == "0.9"
    assert process_env["NAV_LIDAR_MOUNT_PITCH_DEG"] == "19.48"
    assert process_env["NAV_LIDAR_MOUNT_X_M"] == "0.0"
    assert result["pid"] == 999
    assert result["scene_id"] == "Scene1_测试"
    assert str(result["map_pcd"]).endswith("map.pcd")
    assert str(result["ground_pcd"]).endswith("ground.pcd")
    assert str(result["planground_pcd"]).endswith("terrain_base_footprint_fill.pcd")
    assert result["navigation_ready"] is True
    assert result["health"]["scene_ok"] is True
    assert result["health"]["map_pcd_ok"] is True
    assert result["health"]["ground_pcd_ok"] is True
    assert result["health"]["planground_pcd_ok"] is True
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


def test_restart_navigation_localization_rejects_disconnected_radar_before_launch(monkeypatch, tmp_path):
    script_path = tmp_path / "restart_navigation_localization.sh"
    script_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    monkeypatch.setattr(services_nav_localization, "_restart_script_path", lambda: script_path)
    monkeypatch.setattr(
        services_nav_localization,
        "check_livox_network_preflight",
        lambda: {
            "ok": False,
            "message": "雷达未连接：网卡 eno1 未建立物理链路，请检查 Livox MID360 供电和网线",
        },
    )

    def unexpected_popen(*_args, **_kwargs):
        raise AssertionError("雷达预检失败后不应启动导航子进程")

    monkeypatch.setattr(services_nav_localization.subprocess, "Popen", unexpected_popen)

    with pytest.raises(RuntimeError, match="网卡 eno1 未建立物理链路"):
        services_nav_localization.restart_navigation_localization()


def test_restart_navigation_localization_marks_missing_ground_unavailable(monkeypatch, tmp_path):
    scene_root = tmp_path / "MAPS"
    scene_dir = scene_root / "Scene1_测试"
    runtime_root = tmp_path / "data" / "nav_runtime"
    script_path = tmp_path / "restart_navigation_localization.sh"

    scene_dir.mkdir(parents=True)
    runtime_root.mkdir(parents=True)
    (scene_dir / "map.pcd").write_text("", encoding="utf-8")
    (scene_dir / "terrain_base_footprint_fill.pcd").write_text("", encoding="utf-8")
    script_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    atomic_write_json(
        runtime_root / "current_scene.json",
        {
            "scene_id": "Scene1_测试",
            "scene_dir": str(scene_dir),
            "map_pcd": str(scene_dir / "map.pcd"),
            "ground_pcd": str(scene_dir / "ground.pcd"),
            "planground_pcd": str(scene_dir / "terrain_base_footprint_fill.pcd"),
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
        lambda paths, timeout_s=20.0, abort_if=None: {
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
    (scene_dir / "terrain_base_footprint_fill.pcd").write_text("", encoding="utf-8")
    script_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    atomic_write_json(
        runtime_root / "current_scene.json",
        {
            "scene_id": "Scene1_测试",
            "scene_dir": str(scene_dir),
            "map_pcd": str(scene_dir / "map.pcd"),
            "ground_pcd": str(scene_dir / "ground.pcd"),
            "planground_pcd": str(scene_dir / "terrain_base_footprint_fill.pcd"),
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
        lambda paths, timeout_s=20.0, abort_if=None: {
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
    (scene_dir / "terrain_base_footprint_fill.pcd").write_text("", encoding="utf-8")
    script_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    atomic_write_json(
        runtime_root / "current_scene.json",
        {
            "scene_id": "Scene1_测试",
            "scene_dir": str(scene_dir),
            "map_pcd": str(scene_dir / "map.pcd"),
            "ground_pcd": str(scene_dir / "ground.pcd"),
            "planground_pcd": str(scene_dir / "terrain_base_footprint_fill.pcd"),
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
        lambda paths, timeout_s=20.0, abort_if=None: {
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


def test_unified_navigation_scan_health_requires_complete_control_chain(monkeypatch, tmp_path):
    scene_dir = tmp_path / "Scene23_多楼层"
    runtime_root = tmp_path / "runtime"
    scene_dir.mkdir()
    runtime_root.mkdir()
    for name in ("map.pcd", "ground.pcd", "footprint_fill.pcd"):
        (scene_dir / name).write_bytes(b"pcd")

    scene = {
        "scene_id": scene_dir.name,
        "scene_dir": str(scene_dir),
        "map_pcd": str(scene_dir / "map.pcd"),
        "ground_pcd": str(scene_dir / "ground.pcd"),
        "planground_pcd": str(scene_dir / "footprint_fill.pcd"),
    }
    atomic_write_json(
        runtime_root / "navigation_ready.json",
        {
            "ready": True,
            "stage": "running",
            **{key: scene[key] for key in ("scene_dir", "map_pcd", "ground_pcd", "planground_pcd")},
        },
    )
    monkeypatch.setattr(services_nav_localization.settings, "NAV_RUNTIME_DIR", str(runtime_root))
    monkeypatch.setattr(services_nav_localization, "_is_nav_process_alive", lambda name, pid: pid is not None)
    monkeypatch.setattr(services_nav_localization, "_find_cmd_vel_test_publisher_pids", lambda: [])
    monkeypatch.setattr(services_nav_localization, "_inspect_tf_health", lambda: (True, [], []))

    pids = {
        "navigation_pid": 100,
        "livox_pid": 101,
        "relocation_pid": 102,
        "global_planner_pid": 103,
        "scan_planner_pid": 104,
        "scan_controller_pid": 105,
        "dynamic_avoidance_pid": 106,
        "nav_status_monitor_pid": 107,
        "waypoint_navigator_pid": 108,
        "cmd_vel_pid": None,
    }
    result = services_nav_localization._build_restart_health(scene, pids)

    assert result["navigation_ready"] is True
    assert result["health"]["runtime_mode"] == "navigation_scan"
    assert result["health"]["p2p_move_base_ok"] is None
    assert result["errors"] == []

    marker = services_nav_localization.read_json(runtime_root / "navigation_ready.json", {})
    marker["stage"] = "awaiting_initialpose"
    atomic_write_json(runtime_root / "navigation_ready.json", marker)
    result = services_nav_localization._build_restart_health(scene, pids)

    assert result["startup_ready"] is True
    assert result["navigation_ready"] is False
    assert result["health"]["navigation_runtime_marker_ok"] is False
    assert "定位进程已启动，等待 initialpose" in result["warnings"]

    marker["stage"] = "running"
    atomic_write_json(runtime_root / "navigation_ready.json", marker)

    pids["scan_controller_pid"] = None
    result = services_nav_localization._build_restart_health(scene, pids)

    assert result["navigation_ready"] is False
    assert result["health"]["scan_controller_ok"] is False
    assert "SCAN controller 未就绪" in result["errors"]

    pids["scan_controller_pid"] = 105
    pids["waypoint_navigator_pid"] = None
    result = services_nav_localization._build_restart_health(scene, pids)

    assert result["navigation_ready"] is False
    assert result["health"]["waypoint_navigator_ok"] is False
    assert "任务航点执行器未就绪" in result["errors"]


def test_navigation_ready_marker_rejects_previous_scene(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    current_scene = tmp_path / "current"
    current_scene.mkdir()
    scene = {
        "scene_dir": str(current_scene),
        "map_pcd": str(current_scene / "map.pcd"),
        "ground_pcd": str(current_scene / "ground.pcd"),
        "planground_pcd": "",
    }
    atomic_write_json(
        runtime_root / "navigation_ready.json",
        {
            "ready": True,
            "scene_dir": str(tmp_path / "old"),
            "map_pcd": str(tmp_path / "old" / "map.pcd"),
            "ground_pcd": str(tmp_path / "old" / "ground.pcd"),
        },
    )
    monkeypatch.setattr(services_nav_localization.settings, "NAV_RUNTIME_DIR", str(runtime_root))

    ready, errors = services_nav_localization._inspect_navigation_ready_marker(scene)

    assert ready is False
    assert any("当前场景不一致" in error for error in errors)


def test_global_planner_health_falls_back_to_node_process_when_launch_pid_exited(monkeypatch, tmp_path):
    scene_dir = tmp_path / "Scene1_测试"
    runtime_root = tmp_path / "data" / "nav_runtime"
    scene_dir.mkdir(parents=True)
    runtime_root.mkdir(parents=True)
    (scene_dir / "map.pcd").write_text("", encoding="utf-8")
    (scene_dir / "ground.pcd").write_text("", encoding="utf-8")
    (scene_dir / "terrain_base_footprint_fill.pcd").write_text("", encoding="utf-8")
    atomic_write_json(
        runtime_root / "current_scene.json",
        {
            "scene_id": "Scene1_测试",
            "scene_dir": str(scene_dir),
            "map_pcd": str(scene_dir / "map.pcd"),
            "ground_pcd": str(scene_dir / "ground.pcd"),
            "planground_pcd": str(scene_dir / "terrain_base_footprint_fill.pcd"),
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


def _navigation_adapter_sources() -> tuple[str, str, str]:
    botdog_root = Path(__file__).resolve().parents[1]
    project_root = botdog_root.parent
    wrapper = (botdog_root / "scripts" / "restart_navigation_localization.sh").read_text(encoding="utf-8")
    wrapper_common = (botdog_root / "scripts" / "navigation_adapter_common.sh").read_text(encoding="utf-8")
    adapter = (
        project_root / "Navigation" / "adapters" / "legacy_scripts" / "restart_navigation_localization.sh"
    ).read_text(encoding="utf-8")
    return wrapper, wrapper_common, adapter


def test_restart_script_prefers_exact_scene_pcd_files():
    wrapper, wrapper_common, adapter = _navigation_adapter_sources()

    assert 'source "$SCRIPT_DIR/navigation_adapter_common.sh"' in wrapper
    assert "run_navigation_adapter restart_navigation_localization.sh" in wrapper
    assert 'BOTDOG_NAV_WS="${BOTDOG_NAV_WS:-$PROJECT_ROOT/Navigation}"' in wrapper_common
    assert 'prepare_ros_log_dir "$adapter_name"' in wrapper_common
    assert 'session_type="navigation"' in wrapper_common
    assert 'ROS_LOG_RETENTION_DAYS="${ROS_LOG_RETENTION_DAYS:-14}"' in wrapper_common
    assert 'find_scene_pcd_file "$SCENE_DIR" "map.pcd" "map.pcd"' in adapter
    assert 'find_scene_pcd_file "$SCENE_DIR" "ground.pcd" "*ground.pcd"' in adapter
    assert '"footprint_fill.pcd|fill_footpoint.pcd"' in adapter
    assert "navigation_failure_message" in adapter
    assert "ros2 topic echo /livox/lidar --once" in adapter
    assert "--no-daemon --spin-time 2" in adapter
    assert 'NAV_READY_TIMEOUT_SECONDS="${NAV_READY_TIMEOUT_SECONDS:-120}"' in adapter


def test_restart_navigation_script_resets_backend_python_and_qt_env():
    botdog_root = Path(__file__).resolve().parents[1]
    common = (
        botdog_root.parent / "Navigation" / "adapters" / "legacy_scripts" / "common.sh"
    ).read_text(encoding="utf-8")

    assert "reset_navigation_overlay_env" in common
    assert "unset VIRTUAL_ENV PYTHONHOME" in common
    assert "unset PYTHONPATH LD_LIBRARY_PATH PKG_CONFIG_PATH CPATH CPLUS_INCLUDE_PATH" in common
    assert 'source "$ROS2_SETUP_FILE"' in common
    assert 'source "$ROBOT_NAV_WS/install/setup.bash"' in common
    assert 'LIVOX_LIDAR_IP="${LIVOX_LIDAR_IP:-192.168.123.179}"' in common
    assert 'RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_fastrtps_cpp}"' in common


def test_restart_navigation_script_uses_single_instance_and_unified_nodes():
    _, _, adapter = _navigation_adapter_sources()
    botdog_root = Path(__file__).resolve().parents[1]
    common = (
        botdog_root.parent / "Navigation" / "adapters" / "legacy_scripts" / "common.sh"
    ).read_text(encoding="utf-8")
    stop_adapter = (
        botdog_root.parent
        / "Navigation"
        / "adapters"
        / "legacy_scripts"
        / "stop_navigation.sh"
    ).read_text(encoding="utf-8")

    assert 'flock -n 9' in adapter
    assert 'navigation_adapter.pid' in adapter
    assert 'stop_pid_file "$PID_FILE" "旧导航定位链路"' in adapter
    assert 'rm -f "$READY_FILE" "$ROBOT_NAV_RUNTIME_ROOT/p2p_move_base.pid"' in adapter
    assert "ros2 launch nav_bringup navigation.launch.py" in adapter
    assert '"$ROBOT_NAV_WS/install/scan_planner/lib/scan_planner/scan_planner_node"' in adapter
    assert '"$ROBOT_NAV_WS/install/scan_planner/lib/scan_planner/closed_loop_controller"' in adapter
    assert '"$ROBOT_NAV_WS/install/nav_planner/lib/nav_planner/dynamic_avoidance_monitor.py"' in adapter
    assert '"$ROBOT_NAV_WS/install/nav_planner/lib/nav_planner/waypoint_navigator_from_json.py"' in adapter
    assert '"enable_waypoint_navigator:=$NAV_ENABLE_WAYPOINT_NAVIGATOR"' in adapter
    assert '"waypoint_navigator_start_topic:=/nav_task_start"' in adapter
    assert '"waypoints_file:=$NAV_TASK_RUNTIME_FILE"' in adapter
    assert "p2p_move_base go2_localization_launch.py" not in adapter
    assert "pgrep -f" not in adapter
    assert "stop_navigation_runtime_residuals 5" in adapter
    assert "assert_single_navigation_runtime" in adapter
    assert "navigation_runtime_process_patterns" in common
    assert "nav_pcd_map_publisher" in common
    assert "nav_pcd_map_publisher.py" not in common
    assert "scan_initial_path_adapter.py" in common
    assert "scan_tf_pose_publisher.py" in common
    assert "waypoint_navigator_from_json.py" in common
    assert "__node:=static_tf_base_link_to_base_footprint" in common
    assert "stop_navigation_runtime_residuals 5" in stop_adapter


def test_restart_navigation_script_scopes_ready_and_guards_pcd_memory():
    _, wrapper_common, adapter = _navigation_adapter_sources()
    botdog_root = Path(__file__).resolve().parents[1]
    common = (
        botdog_root.parent / "Navigation" / "adapters" / "legacy_scripts" / "common.sh"
    ).read_text(encoding="utf-8")

    assert "RUN_LOG_MARKER" in adapter
    assert "run_log_has" in adapter
    assert 'index($0, marker) { in_current_run = 1; next }' in adapter
    assert "RUN_LOG_OFFSET" not in adapter
    assert "Published static graph with" in adapter
    assert '\\"run_id\\":\\"$RUN_ID\\"' in adapter
    assert 'validate_navigation_pcd_input "$MAP_PCD" "map.pcd"' in adapter
    assert 'validate_navigation_pcd_input "$GROUND_PCD" "ground.pcd"' in adapter
    assert "validate_navigation_pcd_memory_budget" in adapter
    assert "NAV_PCD_MEMORY_RESERVE_BYTES" in common
    assert "MemAvailable:" in common
    assert "NAV_MAX_RAW_PCD_BYTES" not in common
    assert "NAV_MAX_RAW_PCD_POINTS" not in common
    assert 'NAV_ENABLE_SCAN_PLANNER="${NAV_ENABLE_SCAN_PLANNER:-true}"' in wrapper_common
    assert 'NAV_ENABLE_DYNAMIC_AVOIDANCE="${NAV_ENABLE_DYNAMIC_AVOIDANCE:-true}"' in wrapper_common


@pytest.mark.parametrize(
    ("available_kib", "expected_code", "expected_message"),
    [
        (10 * 1024 * 1024, 0, "检查通过"),
        (6 * 1024 * 1024, 1, "导航启动需要至少"),
    ],
)
def test_navigation_pcd_memory_budget_uses_current_available_memory(
    tmp_path: Path,
    available_kib: int,
    expected_code: int,
    expected_message: str,
):
    botdog_root = Path(__file__).resolve().parents[1]
    common_path = (
        botdog_root.parent / "Navigation" / "adapters" / "legacy_scripts" / "common.sh"
    )
    pcd_template = """# .PCD v0.7 - Point Cloud Data file format
VERSION 0.7
FIELDS x y z intensity
SIZE 4 4 4 4
TYPE F F F F
COUNT 1 1 1 1
WIDTH {points}
HEIGHT 1
POINTS {points}
DATA binary
"""
    map_pcd = tmp_path / "map.pcd"
    ground_pcd = tmp_path / "ground.pcd"
    footprint_pcd = tmp_path / "footprint_fill.pcd"
    map_pcd.write_text(pcd_template.format(points=27_377_647), encoding="ascii")
    ground_pcd.write_text(pcd_template.format(points=3_993_965), encoding="ascii")
    footprint_pcd.write_text(pcd_template.format(points=331_955), encoding="ascii")
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(
        f"MemTotal:       {16 * 1024 * 1024} kB\n"
        f"MemAvailable:   {available_kib} kB\n",
        encoding="ascii",
    )

    env = os.environ.copy()
    env.update(
        {
            "NAV_ENV_FILE": str(tmp_path / "missing.env"),
            "NAV_MEMINFO_FILE": str(meminfo),
            "ROBOT_NAV_MAP_ROOT": str(tmp_path / "maps"),
            "ROBOT_NAV_LOG_ROOT": str(tmp_path / "logs"),
            "ROBOT_NAV_RUNTIME_ROOT": str(tmp_path / "runtime"),
        }
    )
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; validate_navigation_pcd_memory_budget "$2" "$3" "$4"',
            "pcd-memory-test",
            str(common_path),
            str(map_pcd),
            str(ground_pcd),
            str(footprint_pcd),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == expected_code
    assert expected_message in result.stdout + result.stderr


def test_navigation_uses_cpp_pcd_publisher_without_fixed_input_limits():
    botdog_root = Path(__file__).resolve().parents[1]
    bringup = botdog_root.parent / "Navigation" / "src" / "nav_bringup"
    publisher = (bringup / "src" / "nav_pcd_map_publisher.cpp").read_text(encoding="utf-8")
    launch = (bringup / "launch" / "planning.launch.py").read_text(encoding="utf-8")
    config = (bringup / "config" / "global_planner.yaml").read_text(encoding="utf-8")

    assert 'executable="nav_pcd_map_publisher"' in launch
    assert "PointCloud voxel_downsample" in publisher
    assert "PointCloud2 build_message" in publisher
    assert "std::unordered_map<VoxelKey" in publisher
    assert "每次只保留当前层" in publisher
    downsample = publisher.index("voxel_downsample(*raw_cloud")
    bridge = publisher.index("bridge_planground_gaps(downsampled_cloud")
    serialize = publisher.index("build_message(downsampled_cloud")
    assert downsample < bridge < serialize
    assert "max_input_bytes" not in config
    assert "max_input_points" not in config


def test_global_planner_start_connection_matches_hybrid_cloud_resolution():
    botdog_root = Path(__file__).resolve().parents[1]
    planner_config = (
        botdog_root.parent
        / "Navigation"
        / "src"
        / "nav_bringup"
        / "config"
        / "global_planner.yaml"
    ).read_text(encoding="utf-8")

    # B2 full-footprint support must use the dense 0.10 m ground cloud.
    # Hybrid search owns a separate coarse copy, whose output is validated
    # edge-by-edge against that dense support surface.
    assert "ground_down_sample: 0.1" in planner_config
    assert "hybrid_downsample_leaf_size: 0.20" in planner_config
    assert "a_star_expanding_radius: 0.2" in planner_config
    assert "planground_search_radius: 0.2" in planner_config
    assert "hybrid_max_ground_bridge_length: 0.25" in planner_config


def test_hybrid_astar_maps_planning_indices_to_perception_ground():
    botdog_root = Path(__file__).resolve().parents[1]
    planner_source = botdog_root.parent / "Navigation" / "src" / "nav_planner"
    astar = (planner_source / "src" / "a_star_on_pc.cpp").read_text(encoding="utf-8")
    hybrid = (planner_source / "src" / "hybrid_a_star.cpp").read_text(encoding="utf-8")

    assert "getPerceptionGroundIndex" in astar
    assert "get_min_dGraphValue(perception_ground_index)" in astar
    assert "getNodeWeight(perception_ground_index)" in astar
    assert "get_min_dGraphValue(current_expanding_index)" not in astar
    assert "if (start_neighbors.empty())" in hybrid
    assert "reference_path_available" in hybrid
    assert "if (reference_valid && edge_validator_)" in hybrid
    assert "edge_validator_(" in hybrid
    assert "Using validated fill_footprint reference directly" in hybrid


def test_restart_navigation_script_exposes_initialpose_stage_before_runtime_tf():
    _, _, adapter = _navigation_adapter_sources()

    startup_section = adapter.split("ready_waited=0", 1)[1].split(
        "# global planner 静态图", 1
    )[0]
    runtime_section = adapter.split("# global planner 静态图", 1)[1]

    assert '\\"stage\\":\\"awaiting_initialpose\\"' in startup_section
    assert "global_planner_map_ready" not in startup_section
    assert "scan_body_pose_ready" not in startup_section
    assert "global_planner_map_ready && scan_body_pose_ready" in runtime_section
    assert '\\"stage\\":\\"running\\"' in runtime_section


def test_restart_navigation_script_does_not_leak_lock_to_ros_children():
    _, _, adapter = _navigation_adapter_sources()

    assert "setsid ros2 launch nav_bringup navigation.launch.py" in adapter
    assert '"${launch_args[@]}" 9>&-' in adapter
    assert "trap - INT TERM EXIT" in adapter
    assert 'stop_pid_file "$PID_FILE" "导航定位链路" 10' in adapter


def test_restart_navigation_script_omits_empty_optional_go2_launch_args():
    _, _, adapter = _navigation_adapter_sources()

    launch_array = adapter.split("launch_args=(", 1)[1].split("\n)", 1)[0]
    assert '"go2_connection_method:=$NAV_GO2_CONNECTION_METHOD"' not in launch_array
    assert '"go2_ip:=$NAV_GO2_IP"' not in launch_array
    assert '"go2_serial_number:=$NAV_GO2_SERIAL_NUMBER"' not in launch_array
    assert '"go2_aes_128_key:=$NAV_GO2_AES_128_KEY"' not in launch_array
    assert 'if [ "$NAV_ROBOT_MODEL" = "go2_webrtc" ]; then' in adapter
    assert '"go2_connection_method:=$NAV_GO2_CONNECTION_METHOD"' in adapter
    assert 'if [ -n "$NAV_GO2_IP" ]; then' in adapter
    assert 'launch_args+=("go2_ip:=$NAV_GO2_IP")' in adapter
    assert 'if [ -n "$NAV_GO2_SERIAL_NUMBER" ]; then' in adapter
    assert 'launch_args+=("go2_serial_number:=$NAV_GO2_SERIAL_NUMBER")' in adapter
    assert 'if [ -n "$NAV_GO2_AES_128_KEY" ]; then' in adapter
    assert 'launch_args+=("go2_aes_128_key:=$NAV_GO2_AES_128_KEY")' in adapter


def test_start_cmd_vel_rejects_persistent_estop_without_clearing_it(monkeypatch, tmp_path):
    runtime_root = tmp_path / "nav_runtime"
    monkeypatch.setattr(services_nav_localization.settings, "NAV_RUNTIME_DIR", str(runtime_root))

    services_nav_localization.set_cmd_vel_estop(True, "test_estop")

    with pytest.raises(RuntimeError, match="急停钳制仍处于激活状态"):
        services_nav_localization.start_cmd_vel_script()

    status = services_nav_localization.get_cmd_vel_estop_status()
    assert status["active"] is True
    assert status["reason"] == "test_estop"


def test_ros_nav_bridge_does_not_install_process_signal_handlers(monkeypatch):
    init_calls: list[dict[str, object]] = []
    signal_options = types.SimpleNamespace(NO=object())
    fake_rclpy = types.ModuleType("rclpy")
    fake_rclpy.init = lambda **kwargs: init_calls.append(kwargs)
    fake_rclpy.try_shutdown = lambda: None
    fake_signals = types.ModuleType("rclpy.signals")
    fake_signals.SignalHandlerOptions = signal_options
    monkeypatch.setitem(sys.modules, "rclpy", fake_rclpy)
    monkeypatch.setitem(sys.modules, "rclpy.signals", fake_signals)

    bridge = RosNavBridge.__new__(RosNavBridge)
    bridge._rclpy = None
    bridge._stop_event = threading.Event()
    bridge._stop_event.set()
    bridge._create_ros_node = lambda: None
    bridge._destroy_ros_node = lambda _reason: None

    bridge._run()

    assert init_calls == [
        {"args": None, "signal_handler_options": signal_options.NO},
    ]
