from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

from backend import services_nav_localization
from backend.repositories.json_store import atomic_write_json


def _make_pid_paths(root: Path) -> dict[str, Path]:
    return {
        "livox_pid": root / "livox.pid",
        "relocation_pid": root / "relocation.pid",
        "global_planner_pid": root / "global_planner.pid",
        "p2p_move_base_pid": root / "p2p_move_base.pid",
        "cmd_vel_pid": root / "cmd_vel.pid",
    }


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

    monkeypatch.setattr(services_nav_localization.settings, "NAV_RUNTIME_DIR", str(runtime_root))
    monkeypatch.setattr(services_nav_localization, "_restart_script_path", lambda: script_path)
    monkeypatch.setattr(services_nav_localization, "_project_root", lambda: tmp_path)
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
    assert result["process_pids"]["livox"] == 101
    assert result["process_pids"]["cmd_vel"] == 105
    assert result["message"] == "已启动重启脚本，导航链路 PID 已确认"


def test_restart_script_accepts_prefixed_scene_pcd_files(tmp_path):
    repo_root = Path("/home/jetson/Project/BOTDOG")
    script_path = repo_root / "BotDog" / "scripts" / "restart_navigation_localization.sh"
    runtime_dir = repo_root / "BotDog" / "data" / "nav_runtime"
    fake_home = tmp_path / "home" / "jetson"
    fake_bin = tmp_path / "bin"
    scene_dir = tmp_path / "Scene1_测试"

    scene_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    fake_bin.mkdir(parents=True)
    (scene_dir / "Scene1_half_map.pcd").write_text("", encoding="utf-8")
    (scene_dir / "Scene1_half_ground.pcd").write_text("", encoding="utf-8")

    for pid_name in ("livox", "relocation", "global_planner", "p2p_move_base", "cmd_vel"):
        try:
            (runtime_dir / f"{pid_name}.pid").unlink()
        except FileNotFoundError:
            pass

    superlio_setup = fake_home / "superlio" / "install" / "setup.bash"
    navigation_setup = fake_home / "dddmr_navigation_new_local" / "install" / "setup.bash"
    superlio_setup.parent.mkdir(parents=True, exist_ok=True)
    navigation_setup.parent.mkdir(parents=True, exist_ok=True)
    superlio_setup.write_text("", encoding="utf-8")
    navigation_setup.write_text("", encoding="utf-8")

    fake_ros2 = fake_bin / "ros2"
    fake_ros2.write_text(
        "#!/usr/bin/env bash\n"
        "tail -f /dev/null\n",
        encoding="utf-8",
    )
    fake_ros2.chmod(0o755)

    fake_sleep = fake_bin / "sleep"
    fake_sleep.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_sleep.chmod(0o755)

    fake_cmd_vel_runner = repo_root / "unitree_sdk2_python" / "example" / "scripts" / "cmd_vel.py"
    fake_cmd_vel_runner.parent.mkdir(parents=True, exist_ok=True)
    fake_cmd_vel_runner.write_text(
        "#!/usr/bin/env bash\n"
        "tail -f /dev/null\n",
        encoding="utf-8",
    )
    fake_cmd_vel_runner.chmod(0o755)

    fake_cmd_vel_bootstrap = repo_root / "test_cmd_vel_fixed.sh"
    fake_cmd_vel_bootstrap.write_text(
        "#!/usr/bin/env bash\n"
        "exec /home/jetson/Project/BOTDOG/unitree_sdk2_python/example/scripts/cmd_vel.py\n",
        encoding="utf-8",
    )
    fake_cmd_vel_bootstrap.chmod(0o755)

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    proc = subprocess.Popen(
        ["bash", str(script_path), str(scene_dir)],
        cwd=str(repo_root),
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
            runtime_dir / "cmd_vel.pid",
        ]

        while time.time() < deadline:
            if all(path.exists() for path in expected_pid_files):
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
        assert "Scene1_half_map.pcd" in output
        assert "当前 ground.pcd: " in output
        assert "Scene1_half_ground.pcd" in output
        for path in expected_pid_files:
            assert path.exists()
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            pass
        for path in (
            fake_cmd_vel_bootstrap,
            fake_cmd_vel_runner,
            fake_ros2,
            fake_sleep,
            runtime_dir / "livox.pid",
            runtime_dir / "relocation.pid",
            runtime_dir / "global_planner.pid",
            runtime_dir / "p2p_move_base.pid",
            runtime_dir / "cmd_vel.pid",
        ):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
