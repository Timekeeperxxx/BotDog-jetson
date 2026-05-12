from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import settings
from .logging_config import get_logger, trim_log_file_tail
from .repositories.json_store import atomic_write_json, read_json, safe_json_path_name
from .services_pcd_maps import find_scene_pcd_files, resolve_scene_ground_path, resolve_scene_path


nav_logger = get_logger("导航定位服务")
_restart_proc: subprocess.Popen[str] | None = None
_restart_lock = threading.Lock()


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="milliseconds") + "Z"


def _store_dir() -> Path:
    path = Path(settings.NAV_LOCALIZATION_STORE_DIR).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _runtime_dir() -> Path:
    path = Path(settings.NAV_RUNTIME_DIR).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _restart_script_path() -> Path:
    return _project_root() / "scripts" / "restart_navigation_localization.sh"


def _restart_log_path() -> Path:
    logs_dir = _project_root() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir / "restart_navigation_localization.log"


def _current_scene_path() -> Path:
    return _runtime_dir() / "current_scene.json"


def _cmd_vel_pid_path() -> Path:
    return _runtime_dir() / "cmd_vel.pid"


def _named_pid_path(name: str) -> Path:
    return _runtime_dir() / f"{name}.pid"


def _pump_restart_output(proc: subprocess.Popen[str], log_path: Path) -> None:
    with log_path.open("a", encoding="utf-8") as log_file:
        assert proc.stdout is not None
        for line in proc.stdout:
            log_file.write(line)
            log_file.flush()
            trim_log_file_tail(log_path)

    try:
        proc.stdout.close()  # type: ignore[union-attr]
    except Exception:
        pass


def _safe_pose_file(map_id: str) -> Path:
    resolve_scene_ground_path(map_id)
    return _store_dir() / f"{safe_json_path_name(map_id)}.json"


def save_localization_pose(payload: dict[str, Any]) -> dict[str, Any]:
    map_id = str(payload["map_id"])
    path = _safe_pose_file(map_id)

    pose = {
        "map_id": map_id,
        "x": float(payload["x"]),
        "y": float(payload["y"]),
        "yaw": float(payload.get("yaw", 0.0)),
        "frame_id": str(payload.get("frame_id") or settings.PCD_FRAME_ID),
        "updated_at": _utc_now_iso(),
    }

    if pose["frame_id"] != settings.PCD_FRAME_ID:
        raise ValueError(f"frame_id 必须是 {settings.PCD_FRAME_ID}")

    atomic_write_json(path, pose)

    return pose


def save_current_scene(scene_id: str) -> dict[str, Any]:
    scene_path = resolve_scene_path(scene_id)
    files = find_scene_pcd_files(scene_path)
    map_pcd = files["wall"]
    ground_pcd = files["ground"]

    if map_pcd is None:
        nav_logger.error("场景缺少 map.pcd：{}", scene_path)
        raise FileNotFoundError(f"场景缺少 map.pcd: {scene_id}")
    if ground_pcd is None:
        nav_logger.error("场景缺少 ground.pcd：{}", scene_path)
        raise FileNotFoundError(f"场景缺少 ground.pcd: {scene_id}")

    payload = {
        "scene_id": scene_path.name,
        "scene_dir": str(scene_path),
        "map_pcd": str(map_pcd),
        "ground_pcd": str(ground_pcd),
        "updated_at": _utc_now_iso(),
    }

    path = _current_scene_path()
    atomic_write_json(path, payload)

    nav_logger.info("当前选择导航场景：{}", payload["scene_id"])
    nav_logger.info("当前场景 map.pcd：{}", payload["map_pcd"])
    nav_logger.info("当前场景 ground.pcd：{}", payload["ground_pcd"])

    return payload


def load_current_scene(strict: bool = True) -> dict[str, Any]:
    path = _current_scene_path()
    if not path.exists():
        raise FileNotFoundError(f"当前场景运行态文件不存在: {path}")

    data = read_json(path, None)

    if not isinstance(data, dict):
        raise ValueError("current_scene.json 格式非法")

    scene_id = str(data.get("scene_id") or "").strip()
    scene_dir_raw = str(data.get("scene_dir") or "").strip()
    map_pcd_raw = str(data.get("map_pcd") or "").strip()
    ground_pcd_raw = str(data.get("ground_pcd") or "").strip()

    if not scene_id:
        raise ValueError("current_scene.json 缺少 scene_id")
    if not scene_dir_raw:
        raise ValueError("current_scene.json 缺少 scene_dir")
    if not map_pcd_raw:
        raise ValueError("current_scene.json 缺少 map_pcd")
    if not ground_pcd_raw:
        raise ValueError("current_scene.json 缺少 ground_pcd")

    scene_dir = Path(scene_dir_raw).expanduser()
    map_pcd = Path(map_pcd_raw).expanduser()
    ground_pcd = Path(ground_pcd_raw).expanduser()

    if strict:
        if not scene_dir.exists() or not scene_dir.is_dir():
            raise FileNotFoundError(f"场景目录不存在: {scene_dir}")
        if not map_pcd.exists():
            raise FileNotFoundError(f"场景缺少 map.pcd: {map_pcd}")
        if not ground_pcd.exists():
            raise FileNotFoundError(f"场景缺少 ground.pcd: {ground_pcd}")

    return {
        "scene_id": scene_id,
        "scene_dir": str(scene_dir),
        "map_pcd": str(map_pcd),
        "ground_pcd": str(ground_pcd),
        "updated_at": str(data.get("updated_at") or ""),
        "scene_ok": scene_dir.exists() and scene_dir.is_dir(),
        "map_pcd_ok": map_pcd.exists(),
        "ground_pcd_ok": ground_pcd.exists(),
    }


def _stop_restart_proc(proc: subprocess.Popen[str] | None) -> None:
    if proc is None or proc.poll() is not None:
        return

    try:
        pgid = os.getpgid(proc.pid)
        nav_logger.info("检测到旧的导航定位重启脚本进程，准备终止：pid={}", proc.pid)
        os.killpg(pgid, signal.SIGTERM)
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            nav_logger.warning("旧的导航定位重启脚本未能及时退出，发送 SIGKILL：pid={}", proc.pid)
            os.killpg(pgid, signal.SIGKILL)
            proc.wait(timeout=5)
    except ProcessLookupError:
        pass
    except Exception as exc:
        nav_logger.warning("终止旧的导航定位重启脚本失败：{}", exc)


def _read_cmd_vel_pid() -> int | None:
    path = _cmd_vel_pid_path()
    if not path.exists():
        return None

    try:
        raw = path.read_text(encoding="utf-8").strip()
        pid = int(raw)
        return pid if pid > 0 else None
    except Exception as exc:
        nav_logger.warning("读取 cmd_vel PID 文件失败：{}，path={}", exc, path)
        return None


def _read_pid_file(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8").strip()
        pid = int(raw)
        return pid if pid > 0 else None
    except Exception as exc:
        nav_logger.warning("读取 PID 文件失败：{}，path={}", exc, path)
        return None


def _wait_for_pid_file(path: Path, timeout_s: float = 30.0) -> int | None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        pid = _read_pid_file(path)
        if pid is not None:
            return pid
        time.sleep(0.2)
    return None


def _wait_for_pid_files(paths: dict[str, Path], timeout_s: float = 20.0) -> dict[str, int | None]:
    deadline = time.time() + timeout_s
    result: dict[str, int | None] = {name: None for name in paths}

    while time.time() < deadline:
        for name, path in paths.items():
            if result[name] is None:
                result[name] = _read_pid_file(path)

        if all(pid is not None for pid in result.values()):
            break

        time.sleep(0.2)

    return result


def _is_pid_alive(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False

    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except Exception:
        return False


def _find_pids_by_needles(needles: list[str]) -> list[int]:
    pids: list[int] = []

    for needle in needles:
        try:
            result = subprocess.run(
                ["pgrep", "-af", needle],
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception as exc:
            nav_logger.warning("搜索进程失败：needle={} err={}", needle, exc)
            continue

        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            pid_text = line.split(maxsplit=1)[0]
            try:
                pids.append(int(pid_text))
            except ValueError:
                continue

    return sorted(set(pids))


def _find_cmd_vel_pids() -> list[int]:
    return _find_pids_by_needles([
        "/home/jetson/Project/BOTDOG/unitree_sdk2_python/example/scripts/cmd_vel.py",
    ])


def _find_cmd_vel_test_publisher_pids() -> list[int]:
    return _find_pids_by_needles([
        "test_cmd_vel_publisher.py",
        "cmd_vel_publisher",
        "test_ros2_cmd_vel_bridge.py",
    ])


def _inspect_tf_health() -> tuple[bool | None, list[str], list[str]]:
    warnings: list[str] = []
    errors: list[str] = []

    try:
        from .services_nav_state import get_nav_state

        nav_state = get_nav_state()
        robot_pose = nav_state.get("robot_pose") or {}
        localization_status = nav_state.get("localization_status") or {}

        robot_frame = str(robot_pose.get("frame_id") or "").strip()
        localization_source = str(localization_status.get("source") or "").strip()
        localization_status_name = str(localization_status.get("status") or "").strip().lower()

        if robot_frame == settings.ROS_NAV_FRAME_ID:
            return True, warnings, errors
        if localization_source.startswith("tf:") and localization_status_name == "ok":
            return True, warnings, errors
        if localization_source.startswith("tf:") and localization_status_name in {"error", "failed"}:
            errors.append("TF 未就绪")
            return False, warnings, errors

        warnings.append("TF 状态未确认，需等待 /nav_status 或 robot_pose 验证")
        return None, warnings, errors
    except Exception as exc:
        warnings.append(f"TF 状态未确认：{exc}")
        return None, warnings, errors


def _build_restart_health(scene: dict[str, Any], child_pids: dict[str, int | None]) -> dict[str, Any]:
    scene_dir = Path(str(scene.get("scene_dir") or "")).expanduser()
    map_pcd = Path(str(scene.get("map_pcd") or "")).expanduser()
    ground_pcd = Path(str(scene.get("ground_pcd") or "")).expanduser()

    scene_ok = scene_dir.exists() and scene_dir.is_dir()
    map_pcd_ok = map_pcd.exists()
    ground_pcd_ok = ground_pcd.exists()

    livox_ok = _is_pid_alive(child_pids.get("livox_pid"))
    relocation_ok = _is_pid_alive(child_pids.get("relocation_pid"))
    global_planner_ok = _is_pid_alive(child_pids.get("global_planner_pid"))
    p2p_move_base_ok = _is_pid_alive(child_pids.get("p2p_move_base_pid"))
    cmd_vel_pid = child_pids.get("cmd_vel_pid")
    cmd_vel_running = _is_pid_alive(cmd_vel_pid)

    tf_ok, tf_warnings, tf_errors = _inspect_tf_health()

    warnings: list[str] = list(tf_warnings)
    errors: list[str] = list(tf_errors)

    if not scene_ok:
        errors.append("场景目录不存在")
    if not map_pcd_ok:
        errors.append("map.pcd 缺失")
    if not ground_pcd_ok:
        errors.append("ground.pcd 缺失")
    if not livox_ok:
        errors.append("livox 未就绪")
    if not relocation_ok:
        errors.append("relocation 未就绪")
    if not global_planner_ok:
        errors.append("global_planner 未就绪")
    if not p2p_move_base_ok:
        errors.append("p2p_move_base 未就绪")

    cmd_vel_test_publisher_pids = _find_cmd_vel_test_publisher_pids()
    cmd_vel_test_publisher_running = len(cmd_vel_test_publisher_pids) > 0
    if cmd_vel_test_publisher_running:
        warnings.append("检测到 cmd_vel 测试发布器残留，请先停止，否则可能导致机器狗异常移动")

    navigation_ready = (
        scene_ok
        and map_pcd_ok
        and ground_pcd_ok
        and livox_ok
        and relocation_ok
        and global_planner_ok
        and p2p_move_base_ok
        and not cmd_vel_test_publisher_running
        and tf_ok is not False
    )

    health = {
        "scene_ok": scene_ok,
        "scene_id": scene.get("scene_id"),
        "scene_dir": str(scene_dir),
        "map_pcd_ok": map_pcd_ok,
        "map_pcd": str(map_pcd),
        "ground_pcd_ok": ground_pcd_ok,
        "ground_pcd": str(ground_pcd),
        "livox_ok": livox_ok,
        "relocation_ok": relocation_ok,
        "global_planner_ok": global_planner_ok,
        "p2p_move_base_ok": p2p_move_base_ok,
        "cmd_vel_test_publisher_running": cmd_vel_test_publisher_running,
        "cmd_vel_running": cmd_vel_running,
        "cmd_vel_pid": cmd_vel_pid,
        "tf_ok": tf_ok,
        "warnings": warnings,
        "errors": errors,
    }

    return {
        "health": health,
        "navigation_ready": navigation_ready,
        "warnings": warnings,
        "errors": errors,
    }


def _kill_pid_tree(pid: int, sig: int) -> None:
    try:
        children = subprocess.run(
            ["pgrep", "-P", str(pid)],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.split()
    except Exception:
        children = []

    for child in children:
        try:
            child_pid = int(child)
        except ValueError:
            continue
        _kill_pid_tree(child_pid, sig)

    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        pass
    except Exception as exc:
        nav_logger.warning("向 cmd_vel 进程发送信号失败：pid={} sig={} err={}", pid, sig, exc)


def stop_cmd_vel_script() -> dict[str, Any]:
    pid_file = _cmd_vel_pid_path()
    pids: list[int] = []

    pid = _read_cmd_vel_pid()
    if pid is not None:
        pids.append(pid)

    if not pids:
        pids.extend(_find_cmd_vel_pids())

    if not pids:
        nav_logger.info("未找到后台 cmd_vel 脚本残留")
        return {
            "success": True,
            "running": False,
            "pid": None,
            "pid_file": str(pid_file),
            "message": "未找到 cmd_vel 后台脚本",
        }

    unique_pids = sorted(set(pids))
    nav_logger.warning("准备停止后台 cmd_vel 脚本：pids={}", unique_pids)

    for pid_value in unique_pids:
        _kill_pid_tree(pid_value, signal.SIGTERM)

    deadline = time.time() + 3.0
    while time.time() < deadline:
        still_running = []
        for pid_value in unique_pids:
            try:
                os.kill(pid_value, 0)
                still_running.append(pid_value)
            except ProcessLookupError:
                continue
            except Exception:
                continue
        if not still_running:
            break
        time.sleep(0.2)

    for pid_value in unique_pids:
        _kill_pid_tree(pid_value, signal.SIGKILL)

    try:
        pid_file.unlink(missing_ok=True)
    except Exception as exc:
        nav_logger.warning("清理 cmd_vel PID 文件失败：{}，path={}", exc, pid_file)

    return {
        "success": True,
        "running": False,
        "pid": unique_pids[0],
        "pid_file": str(pid_file),
        "message": "已停止后台 cmd_vel 脚本",
    }


def stop_navigation_processes() -> dict[str, Any]:
    pid_specs = [
        ("livox", _named_pid_path("livox"), ["ros2 launch livox_ros_driver2 msg_MID360_launch.py", "livox_ros_driver2_node"]),
        ("relocation", _named_pid_path("relocation"), ["ros2 launch super_lio relocation.py", "relocation_node"]),
        ("global_planner", _named_pid_path("global_planner"), ["ros2 launch global_planner path_planning_with_polygon.launch", "global_planner_node"]),
        ("p2p_move_base", _named_pid_path("p2p_move_base"), ["ros2 launch p2p_move_base go2_localization_launch.py", "clicked2goal.py", "p2p_move_base"]),
    ]

    target_pids: list[int] = []

    for _, pid_path, needles in pid_specs:
        pid = _read_pid_file(pid_path)
        if pid is not None:
            target_pids.append(pid)
            continue

        for needle in needles:
            try:
                result = subprocess.run(
                    ["pgrep", "-af", needle],
                    capture_output=True,
                    text=True,
                    check=False,
                )
            except Exception as exc:
                nav_logger.warning("搜索导航进程失败：needle={} err={}", needle, exc)
                continue

            for line in result.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                pid_text = line.split(maxsplit=1)[0]
                try:
                    target_pids.append(int(pid_text))
                except ValueError:
                    continue

    unique_pids = sorted(set(target_pids))
    if not unique_pids:
        nav_logger.info("未找到需要停止的导航后台进程")
        return {
            "success": True,
            "running": False,
            "pids": [],
            "message": "未找到导航后台进程",
        }

    nav_logger.warning("准备停止导航后台进程：pids={}", unique_pids)
    for pid_value in unique_pids:
        _kill_pid_tree(pid_value, signal.SIGTERM)

    deadline = time.time() + 3.0
    while time.time() < deadline:
        still_running = []
        for pid_value in unique_pids:
            try:
                os.kill(pid_value, 0)
                still_running.append(pid_value)
            except ProcessLookupError:
                continue
            except Exception:
                continue
        if not still_running:
            break
        time.sleep(0.2)

    for pid_value in unique_pids:
        _kill_pid_tree(pid_value, signal.SIGKILL)

    for _, pid_path, _ in pid_specs:
        try:
            pid_path.unlink(missing_ok=True)
        except Exception as exc:
            nav_logger.warning("清理 PID 文件失败：{}，path={}", exc, pid_path)

    return {
        "success": True,
        "running": False,
        "pids": unique_pids,
        "message": "已停止导航后台进程",
    }


def restart_navigation_localization() -> dict[str, Any]:
    global _restart_proc

    script_path = _restart_script_path()
    if not script_path.exists():
        raise FileNotFoundError(f"重启脚本不存在: {script_path}")
    if not script_path.is_file():
        raise FileNotFoundError(f"重启脚本不是文件: {script_path}")

    with _restart_lock:
        scene = load_current_scene(strict=False)
        nav_logger.info("收到导航定位重启请求，准备清理旧进程并启动脚本")
        nav_logger.info("准备重启导航定位")
        _stop_restart_proc(_restart_proc)

        log_path = _restart_log_path()
        nav_logger.info("准备重启导航定位，脚本路径：{}，日志路径：{}", script_path, log_path)
        nav_logger.info("启动 relocation，map_file={}", scene["map_pcd"])
        nav_logger.info(
            "启动 global_planner，map_dir={}，ground_dir={}",
            scene["map_pcd"],
            scene["ground_pcd"],
        )

        try:
            _restart_proc = subprocess.Popen(
                ["bash", str(script_path), scene["scene_dir"]],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
                cwd=str(_project_root()),
            )
        except Exception:
            raise

        if _restart_proc.stdout is not None:
            threading.Thread(
                target=_pump_restart_output,
                args=(_restart_proc, log_path),
                daemon=True,
                name="restart-localization-log-pump",
            ).start()

        pid_files = {
            "livox_pid": _named_pid_path("livox"),
            "relocation_pid": _named_pid_path("relocation"),
            "global_planner_pid": _named_pid_path("global_planner"),
            "p2p_move_base_pid": _named_pid_path("p2p_move_base"),
            "cmd_vel_pid": _cmd_vel_pid_path(),
        }
        child_pids = _wait_for_pid_files(pid_files, timeout_s=20.0)
        health_result = _build_restart_health(scene, child_pids)
        navigation_ready = bool(health_result["navigation_ready"])
        warnings = list(health_result["warnings"] or [])
        errors = list(health_result["errors"] or [])
        if navigation_ready:
            message = "已启动重启脚本，导航可用"
        else:
            details = errors or warnings or ["健康状态未确认"]
            message = "已启动重启脚本，但导航不可用：" + "；".join(details)

        nav_logger.info("已启动导航定位重启脚本：pid={}", _restart_proc.pid)
        return {
            "success": True,
            "running": True,
            "pid": _restart_proc.pid,
            "scene_id": scene["scene_id"],
            "scene_dir": scene["scene_dir"],
            "map_pcd": scene["map_pcd"],
            "ground_pcd": scene["ground_pcd"],
            **child_pids,
            "cmd_vel_running": health_result["health"]["cmd_vel_running"],
            "navigation_ready": navigation_ready,
            "process_pids": {
                "livox": child_pids["livox_pid"],
                "relocation": child_pids["relocation_pid"],
                "global_planner": child_pids["global_planner_pid"],
                "p2p_move_base": child_pids["p2p_move_base_pid"],
                "cmd_vel": child_pids["cmd_vel_pid"],
            },
            "health": health_result["health"],
            "warnings": warnings,
            "errors": errors,
            "message": message,
        }
