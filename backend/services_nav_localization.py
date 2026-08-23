from __future__ import annotations

import os
import re
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from .config import settings
from .logging_config import get_logger
from .lidar_mount import lidar_mount_environment, lidar_mount_log_values
from .repositories.json_store import atomic_write_json, read_json
from .services_nav_localization_process import (
    _cmd_vel_estop_path,
    _cmd_vel_pid_path,
    _find_cmd_vel_pids,
    _find_cmd_vel_test_publisher_pids,
    _find_pids_by_needles,
    _is_pid_alive,
    _kill_pid_tree,
    _named_pid_path,
    _navigation_ready_path,
    _read_cmd_vel_pid,
    _read_pid_file,
    _runtime_dir,
    _wait_for_pid_file,
    _wait_for_pid_files,
    get_cmd_vel_estop_status,
    get_relocation_process_status,
    set_cmd_vel_estop,
)
from .services_nav_localization_scene import (
    delete_scene_localization_data,
    load_current_scene,
    save_current_scene,
    save_localization_pose,
)
from .services_radar_health import check_livox_network_preflight


nav_logger = get_logger("导航定位服务")
_restart_proc: subprocess.Popen[str] | None = None
_restart_lock = threading.Lock()
INITIALPOSE_WAIT_LOG_MARKER = "Waiting for initial pose from topic"
INITIALPOSE_FRAME_COUNT_PATTERN = re.compile(r"init_frame_count=(\d+)")
RELOCATION_DIRECT_POSE_MARKER = "Using initial pose from topic directly, skipping NDT/ICP"
RELOCATION_ICP_SUCCESS_MARKER = "Global ICP Converged Succeed"
RELOCATION_ICP_FAIL_MARKER = "Global ICP Converged Fail"
NAV_PROCESS_NEEDLES: dict[str, list[str]] = {
    "navigation": [
        "ros2 launch nav_bringup navigation.launch.py",
    ],
    "livox": [
        "ros2 launch livox_ros_driver2 msg_MID360_launch.py",
        "/home/jetson/superlio/install/livox_ros_driver2/lib/livox_ros_driver2/livox_ros_driver2_node",
        "/Navigation/install/livox_ros_driver2/lib/livox_ros_driver2/livox_ros_driver2_node",
    ],
    "relocation": [
        "ros2 run super_lio relocation_node",
        "/home/jetson/superlio/install/super_lio/lib/super_lio/relocation_node",
        "/Navigation/install/nav_lio/lib/nav_lio/relocation_node",
    ],
    "global_planner": [
        "ros2 launch global_planner path_planning_with_polygon.launch",
        "/home/jetson/dddmr_navigation_new_local/install/global_planner/lib/global_planner/global_planner_node",
        "/Navigation/install/nav_planner/lib/nav_planner/global_planner_node",
    ],
    "p2p_move_base": [
        "ros2 launch p2p_move_base go2_localization_launch.py",
        "/home/jetson/dddmr_navigation_new_local/install/p2p_move_base/lib/p2p_move_base/p2p_move_base_node",
        "/home/jetson/dddmr_navigation_new_local/install/p2p_move_base/lib/p2p_move_base/clicked2goal.py",
    ],
    "scan_planner": [
        "/Navigation/install/scan_planner/lib/scan_planner/scan_planner_node",
    ],
    "scan_controller": [
        "/Navigation/install/scan_planner/lib/scan_planner/closed_loop_controller",
    ],
    "dynamic_avoidance": [
        "/Navigation/install/nav_planner/lib/nav_planner/dynamic_avoidance_monitor.py",
    ],
    "nav_status_monitor": [
        "/Navigation/install/nav_planner/lib/nav_planner/waypoint_progress_monitor.py",
    ],
    "waypoint_navigator": [
        "/Navigation/install/nav_planner/lib/nav_planner/waypoint_navigator_from_json.py",
    ],
}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _restart_script_path() -> Path:
    return _project_root() / "scripts" / "restart_navigation_localization.sh"


def _cmd_vel_script_path() -> Path:
    return _project_root() / "scripts" / "start_cmd_vel_udp_sender.sh"


def _restart_log_path() -> Path:
    logs_dir = _project_root() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir / "restart_navigation_localization.log"


def get_restart_log_offset() -> int:
    path = _restart_log_path()
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def wait_for_initialpose_log(offset: int = 0, timeout_s: float = 45.0) -> dict[str, Any]:
    path = _restart_log_path()
    deadline = time.time() + max(0.1, timeout_s)
    safe_offset = max(0, int(offset))
    min_init_frames = max(0, int(os.environ.get("NAV_INITIALPOSE_READY_MIN_INIT_FRAMES", "50")))

    while time.time() < deadline:
        try:
            current_size = path.stat().st_size
            read_offset = safe_offset if current_size >= safe_offset else 0
            with path.open("r", encoding="utf-8", errors="ignore") as log_file:
                log_file.seek(read_offset)
                content = log_file.read()
                next_offset = log_file.tell()
        except FileNotFoundError:
            content = ""
            next_offset = 0

        if INITIALPOSE_WAIT_LOG_MARKER in content:
            init_frame_counts = [
                int(match.group(1))
                for match in INITIALPOSE_FRAME_COUNT_PATTERN.finditer(content)
            ]
            max_init_frame_count = max(init_frame_counts, default=0)
            if max_init_frame_count < min_init_frames:
                time.sleep(0.25)
                continue

            return {
                "ready": True,
                "marker": INITIALPOSE_WAIT_LOG_MARKER,
                "offset": next_offset,
                "init_frame_count": max_init_frame_count,
                "message": f"Super-LIO 已稳定等待 initialpose，初始化帧数 {max_init_frame_count}",
            }

        time.sleep(0.25)

    return {
        "ready": False,
        "marker": INITIALPOSE_WAIT_LOG_MARKER,
        "offset": get_restart_log_offset(),
        "message": "等待 Super-LIO initialpose 日志超时",
    }


def _tail_restart_log(max_bytes: int = 256_000) -> str:
    path = _restart_log_path()
    try:
        size = path.stat().st_size
        with path.open("r", encoding="utf-8", errors="ignore") as log_file:
            if size > max_bytes:
                log_file.seek(size - max_bytes)
            return log_file.read()
    except FileNotFoundError:
        return ""


def _restart_startup_error_since(offset: int) -> str | None:
    path = _restart_log_path()
    try:
        size = path.stat().st_size
        read_offset = max(0, int(offset)) if size >= offset else 0
        with path.open("r", encoding="utf-8", errors="ignore") as log_file:
            log_file.seek(read_offset)
            content = log_file.read()
    except FileNotFoundError:
        return None

    messages: list[str] = []
    marker = "[Navigation][错误]"
    for line in content.splitlines():
        marker_index = line.find(marker)
        if marker_index < 0:
            continue
        message = line[marker_index + len(marker):].strip()
        if message and message not in messages:
            messages.append(message)
    return "；".join(messages[-3:]) or None


def inspect_relocation_initialization(timeout_s: float = 2.0) -> dict[str, Any]:
    deadline = time.time() + max(0.0, timeout_s)
    content = ""

    while True:
        content = _tail_restart_log()
        if RELOCATION_DIRECT_POSE_MARKER in content:
            return {
                "mode": "direct_pose",
                "matched_map": False,
                "message": "Super-LIO 当前直接使用 initialpose 初始化，未执行 NDT/ICP 地图匹配",
            }
        if RELOCATION_ICP_SUCCESS_MARKER in content:
            return {
                "mode": "scan_match",
                "matched_map": True,
                "message": "Super-LIO 已完成 NDT/ICP 地图匹配",
            }
        if RELOCATION_ICP_FAIL_MARKER in content:
            return {
                "mode": "scan_match_failed",
                "matched_map": False,
                "message": "Super-LIO NDT/ICP 地图匹配失败",
            }

        if time.time() >= deadline:
            break
        time.sleep(0.2)

    return {
        "mode": "unknown",
        "matched_map": None,
        "message": "尚未从 Super-LIO 日志确认重定位匹配模式",
    }


def diagnose_recent_navigation_failure(max_log_age_s: float = 60.0) -> dict[str, Any] | None:
    """Classify the latest planner failure from the restart log.

    p2p_move_base reports many planner failures as a generic nav_status
    "failed". The global_planner launch output carries the actionable cause.
    Keep this parser conservative so stale logs do not overwrite fresh status.
    """
    path = _restart_log_path()
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        return None

    if time.time() - mtime > max_log_age_s:
        return None

    content = _tail_restart_log()
    if not content:
        return None

    specific_checks: list[tuple[str, tuple[str, ...], str]] = [
        (
            "GLOBAL_PLANNER_STATIC_LAYER_NOT_READY",
            (
                "Received the request before static layer is ready",
                "Received clicked goal before static layer is ready",
            ),
            "global_planner 静态地图层还没加载完成，请等待导航链路 ready 后再下发目标。",
        ),
        (
            "GLOBAL_PLANNER_GOAL_NOT_ON_GROUND",
            ("Goal is not found.",),
            "目标点不在 global_planner 的地面点云附近：请把导航点放到地面点云上，或重新保存更贴近地面的点位。",
        ),
        (
            "GLOBAL_PLANNER_START_NOT_ON_GROUND",
            ("Start is not found.",),
            "机器狗当前位置不在 global_planner 的地面点云附近：请检查重定位/TF 是否落在当前地图地面上。",
        ),
        (
            "GLOBAL_PLANNER_TF_LOOKUP_FAILED",
            ("Failed to transform pointcloud:",),
            "global_planner 获取机器狗 TF 失败：请检查 map 到 base_footprint/base_link 的 TF 是否稳定。",
        ),
    ]
    generic_checks: list[tuple[str, tuple[str, ...], str]] = [
        (
            "GLOBAL_PLANNER_NO_CONNECTED_PATH",
            ("No path found from:",),
            "目标点和机器狗当前位置之间没有可连通路径：可能是地面图断裂、下采样过稀或障碍/边界阻断。",
        ),
    ]

    matches: list[tuple[int, str, str, str]] = []
    for code, needles, message in [*specific_checks, *generic_checks]:
        for needle in needles:
            index = content.rfind(needle)
            if index >= 0:
                matches.append((index, code, message, needle))

    if not matches:
        return None

    specific_codes = {code for code, _, _ in specific_checks}
    specific_matches = [match for match in matches if match[1] in specific_codes]
    candidates = specific_matches or matches
    _, code, message, needle = max(candidates, key=lambda item: item[0])
    return {
        "error_code": code,
        "message": message,
        "evidence": needle,
    }


def _pump_restart_output(proc: subprocess.Popen[str], log_path: Path) -> None:
    with log_path.open("a", encoding="utf-8") as log_file:
        assert proc.stdout is not None
        for line in proc.stdout:
            log_file.write(line)
            log_file.flush()

    try:
        proc.stdout.close()  # type: ignore[union-attr]
    except Exception:
        pass


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


def _pid_matches_needles(pid: int | None, needles: list[str]) -> bool | None:
    if pid is None or pid <= 0:
        return False
    try:
        command = (Path("/proc") / str(pid) / "cmdline").read_bytes().replace(b"\0", b" ").decode(
            "utf-8", errors="replace"
        )
    except FileNotFoundError:
        return None
    except Exception:
        return None
    if not command.strip():
        return None
    return any(needle in command for needle in needles)


def _is_nav_process_alive(name: str, pid: int | None) -> bool:
    needles = NAV_PROCESS_NEEDLES.get(name, [])
    if _is_pid_alive(pid) and _pid_matches_needles(pid, needles) is not False:
        return True
    return len(_find_pids_by_needles(needles)) > 0


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


def _inspect_navigation_ready_marker(scene: dict[str, Any]) -> tuple[bool, list[str]]:
    path = _navigation_ready_path()
    errors: list[str] = []

    if not path.exists():
        return False, ["navigation_ready 标记未生成，导航定位子进程尚未全部启动"]

    marker = read_json(path, None)
    if not isinstance(marker, dict) or marker.get("ready") is not True:
        return False, ["navigation_ready 标记格式非法"]

    expected_fields = ("scene_dir", "map_pcd", "ground_pcd", "planground_pcd")
    for field in expected_fields:
        expected = str(scene.get(field) or "")
        actual = str(marker.get(field) or "")
        if not expected:
            continue
        if not actual:
            errors.append(f"navigation_ready 标记缺少字段: {field}")
        elif Path(actual).expanduser() != Path(expected).expanduser():
            errors.append(f"navigation_ready 标记与当前场景不一致: {field}")

    return len(errors) == 0, errors


def _build_restart_health(scene: dict[str, Any], child_pids: dict[str, int | None]) -> dict[str, Any]:
    scene_dir = Path(str(scene.get("scene_dir") or "")).expanduser()
    map_pcd = Path(str(scene.get("map_pcd") or "")).expanduser()
    ground_pcd = Path(str(scene.get("ground_pcd") or "")).expanduser()
    planground_pcd_raw = str(scene.get("planground_pcd") or "").strip()
    planground_pcd = Path(planground_pcd_raw).expanduser() if planground_pcd_raw else None

    scene_ok = scene_dir.exists() and scene_dir.is_dir()
    map_pcd_ok = map_pcd.exists()
    ground_pcd_ok = ground_pcd.exists()
    planground_pcd_ok = bool(planground_pcd and planground_pcd.exists())

    unified_mode = "navigation_pid" in child_pids or "scan_planner_pid" in child_pids
    navigation_ok = _is_nav_process_alive("navigation", child_pids.get("navigation_pid")) if unified_mode else None
    livox_ok = _is_nav_process_alive("livox", child_pids.get("livox_pid"))
    relocation_ok = _is_nav_process_alive("relocation", child_pids.get("relocation_pid"))
    global_planner_ok = _is_nav_process_alive("global_planner", child_pids.get("global_planner_pid"))
    p2p_move_base_ok = (
        _is_nav_process_alive("p2p_move_base", child_pids.get("p2p_move_base_pid"))
        if not unified_mode
        else None
    )
    scan_planner_ok = (
        _is_nav_process_alive("scan_planner", child_pids.get("scan_planner_pid"))
        if unified_mode
        else None
    )
    scan_controller_ok = (
        _is_nav_process_alive("scan_controller", child_pids.get("scan_controller_pid"))
        if unified_mode
        else None
    )
    dynamic_avoidance_ok = (
        _is_nav_process_alive("dynamic_avoidance", child_pids.get("dynamic_avoidance_pid"))
        if unified_mode
        else None
    )
    nav_status_monitor_ok = (
        _is_nav_process_alive("nav_status_monitor", child_pids.get("nav_status_monitor_pid"))
        if unified_mode
        else None
    )
    waypoint_navigator_ok = (
        _is_nav_process_alive("waypoint_navigator", child_pids.get("waypoint_navigator_pid"))
        if unified_mode
        else None
    )
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
    if not planground_pcd_ok:
        warnings.append("footprint_fill.pcd 缺失，已跳过该辅助图层")
    if not livox_ok:
        errors.append("livox 未就绪")
    if not relocation_ok:
        errors.append("relocation 未就绪")
    if not global_planner_ok:
        errors.append("global_planner 未就绪")
    if unified_mode:
        if not navigation_ok:
            errors.append("Navigation 统一 launch 未就绪")
        if not scan_planner_ok:
            errors.append("SCAN planner 未就绪")
        if not scan_controller_ok:
            errors.append("SCAN controller 未就绪")
        if not dynamic_avoidance_ok:
            errors.append("动态避障安全监控未就绪")
        if not nav_status_monitor_ok:
            errors.append("导航状态监控未就绪")
        if not waypoint_navigator_ok:
            errors.append("任务航点执行器未就绪")
    elif not p2p_move_base_ok:
        errors.append("p2p_move_base 未就绪")

    cmd_vel_test_publisher_pids = _find_cmd_vel_test_publisher_pids()
    cmd_vel_test_publisher_running = len(cmd_vel_test_publisher_pids) > 0
    if cmd_vel_test_publisher_running:
        warnings.append("检测到 cmd_vel 测试发布器残留，请先停止，否则可能导致机器狗异常移动")

    navigation_ready_marker_ok, marker_errors = _inspect_navigation_ready_marker(scene)
    errors.extend(marker_errors)

    ready_marker = read_json(_navigation_ready_path(), {}) if navigation_ready_marker_ok else {}
    navigation_runtime_marker_ok = bool(
        isinstance(ready_marker, dict) and ready_marker.get("stage") == "running"
    )
    if navigation_ready_marker_ok and not navigation_runtime_marker_ok:
        warnings.append("定位进程已启动，等待 initialpose")

    startup_ready = (
        scene_ok
        and map_pcd_ok
        and ground_pcd_ok
        and livox_ok
        and relocation_ok
        and global_planner_ok
        and navigation_ready_marker_ok
        and not cmd_vel_test_publisher_running
    )
    if unified_mode:
        startup_ready = bool(
            startup_ready
            and navigation_ok
            and scan_planner_ok
            and scan_controller_ok
            and dynamic_avoidance_ok
            and nav_status_monitor_ok
            and waypoint_navigator_ok
        )
    else:
        startup_ready = bool(startup_ready and p2p_move_base_ok)

    navigation_ready = bool(
        startup_ready
        and navigation_runtime_marker_ok
        and tf_ok is True
    )

    health = {
        "scene_ok": scene_ok,
        "scene_id": scene.get("scene_id"),
        "scene_dir": str(scene_dir),
        "map_pcd_ok": map_pcd_ok,
        "map_pcd": str(map_pcd),
        "ground_pcd_ok": ground_pcd_ok,
        "ground_pcd": str(ground_pcd),
        "planground_pcd_ok": planground_pcd_ok,
        "planground_pcd": str(planground_pcd) if planground_pcd else None,
        "runtime_mode": "navigation_scan" if unified_mode else "legacy_p2p",
        "navigation_ok": navigation_ok,
        "livox_ok": livox_ok,
        "relocation_ok": relocation_ok,
        "global_planner_ok": global_planner_ok,
        "p2p_move_base_ok": p2p_move_base_ok,
        "scan_planner_ok": scan_planner_ok,
        "scan_controller_ok": scan_controller_ok,
        "dynamic_avoidance_ok": dynamic_avoidance_ok,
        "nav_status_monitor_ok": nav_status_monitor_ok,
        "waypoint_navigator_ok": waypoint_navigator_ok,
        "cmd_vel_test_publisher_running": cmd_vel_test_publisher_running,
        "cmd_vel_running": cmd_vel_running,
        "cmd_vel_pid": cmd_vel_pid,
        "navigation_ready_marker_ok": navigation_ready_marker_ok,
        "navigation_runtime_marker_ok": navigation_runtime_marker_ok,
        "navigation_ready_marker": str(_navigation_ready_path()),
        "tf_ok": tf_ok,
        "warnings": warnings,
        "errors": errors,
    }

    return {
        "health": health,
        "startup_ready": startup_ready,
        "navigation_ready": navigation_ready,
        "warnings": warnings,
        "errors": errors,
    }


def assert_navigation_runtime_ready() -> dict[str, Any]:
    scene = load_current_scene(strict=False)
    child_pids = {
        "navigation_pid": _read_pid_file(_named_pid_path("navigation")),
        "livox_pid": _read_pid_file(_named_pid_path("livox")),
        "relocation_pid": _read_pid_file(_named_pid_path("relocation")),
        "global_planner_pid": _read_pid_file(_named_pid_path("global_planner")),
        "scan_planner_pid": _read_pid_file(_named_pid_path("scan_planner")),
        "scan_controller_pid": _read_pid_file(_named_pid_path("scan_controller")),
        "dynamic_avoidance_pid": _read_pid_file(_named_pid_path("dynamic_avoidance")),
        "nav_status_monitor_pid": _read_pid_file(_named_pid_path("nav_status_monitor")),
        "waypoint_navigator_pid": _read_pid_file(_named_pid_path("waypoint_navigator")),
        "cmd_vel_pid": _read_cmd_vel_pid(),
    }
    health_result = _build_restart_health(scene, child_pids)
    if not health_result["navigation_ready"]:
        details = list(health_result["errors"] or health_result["warnings"] or ["导航链路未就绪"])
        raise RuntimeError("导航链路未就绪，禁止发布目标点: " + "；".join(details))
    return health_result


def wait_navigation_runtime_ready(timeout_s: float | None = None, poll_interval_s: float = 0.25) -> dict[str, Any]:
    """Wait briefly for nav runtime files/processes to settle before rejecting a goal."""
    if timeout_s is None:
        timeout_s = float(os.environ.get("NAV_RUNTIME_READY_WAIT_S", "5.0"))

    deadline = time.monotonic() + max(0.0, timeout_s)
    interval = max(0.05, poll_interval_s)
    last_error: RuntimeError | None = None

    while True:
        try:
            return assert_navigation_runtime_ready()
        except RuntimeError as exc:
            last_error = exc

        if time.monotonic() >= deadline:
            break
        time.sleep(interval)

    if last_error is not None:
        raise last_error
    raise RuntimeError("导航链路未就绪，禁止发布目标点: readiness 检查未返回结果")


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


def start_cmd_vel_script() -> dict[str, Any]:
    pid_file = _cmd_vel_pid_path()
    log_file = _runtime_dir() / "cmd_vel.log"
    ready_file = _runtime_dir() / "cmd_vel_sender.ready"
    script_path = _cmd_vel_script_path()
    estop_result = get_cmd_vel_estop_status()
    if bool(estop_result.get("active")):
        reason = str(estop_result.get("reason") or "未提供原因")
        raise RuntimeError(f"急停钳制仍处于激活状态，拒绝启动导航速度桥：{reason}")

    if settings.CONTROL_ADAPTER_TYPE == "unitree_b2":
        from .control_service import get_control_service
        from .navigation_velocity_udp import (
            get_navigation_velocity_udp_status,
            is_navigation_velocity_udp_ready,
        )

        control_service = get_control_service()
        adapter_status = control_service.get_adapter_status() if control_service is not None else None
        if not adapter_status or not bool(adapter_status.get("ready")):
            raise RuntimeError(f"Unitree B2 单写入适配器未就绪：{adapter_status}")
        if not is_navigation_velocity_udp_ready():
            status = get_navigation_velocity_udp_status()
            raise RuntimeError(f"BotDog 单写入速度接收器未就绪：{status}")

    existing_pid = _read_cmd_vel_pid()
    if _is_pid_alive(existing_pid):
        return {
            "success": True,
            "running": True,
            "pid": existing_pid,
            "pid_file": str(pid_file),
            "log_file": str(log_file),
            "ready": True,
            "ready_wait_s": 0.0,
            "estop": estop_result,
            "message": "cmd_vel 桥接已在运行",
        }

    stale_pids = _find_cmd_vel_pids()
    if stale_pids:
        stop_cmd_vel_script()

    if not script_path.exists():
        raise RuntimeError(f"cmd_vel 启动脚本不存在: {script_path}")
    if not script_path.is_file():
        raise RuntimeError(f"cmd_vel 启动脚本不是文件: {script_path}")

    log_file.parent.mkdir(parents=True, exist_ok=True)
    ready_file.unlink(missing_ok=True)
    env = os.environ.copy()
    env["BOTDOG_CMD_VEL_ESTOP_FILE"] = str(_cmd_vel_estop_path())
    env["BOTDOG_CMD_VEL_READY_FILE"] = str(ready_file)
    with log_file.open("a", encoding="utf-8") as stdout:
        proc = subprocess.Popen(
            ["bash", str(script_path)],
            stdout=stdout,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            cwd=str(_project_root()),
            env=env,
        )

    wait_started_at = time.monotonic()
    ready = False
    while time.monotonic() - wait_started_at < 5.0:
        if proc.poll() is not None:
            raise RuntimeError(f"cmd_vel 桥接启动失败，请查看 {log_file}")
        if ready_file.exists():
            ready = True
            break
        time.sleep(0.2)

    if not ready:
        _kill_pid_tree(proc.pid, signal.SIGTERM)
        raise RuntimeError(f"cmd_vel 桥接启动超时，请查看 {log_file}")

    atomic_write_json(pid_file, proc.pid)
    ready_wait_s = round(time.monotonic() - wait_started_at, 2)
    nav_logger.info("cmd_vel 桥接已启动：pid={} log={}", proc.pid, log_file)
    return {
        "success": True,
        "running": True,
        "pid": proc.pid,
        "pid_file": str(pid_file),
        "log_file": str(log_file),
        "ready": ready,
        "ready_wait_s": ready_wait_s,
        "estop": estop_result,
        "message": f"cmd_vel ROS2→UDP sender 已启动并等待 {ready_wait_s:.1f}s",
    }


def stop_navigation_processes() -> dict[str, Any]:
    pid_specs = [
        ("navigation_adapter", _named_pid_path("navigation_adapter"), ["restart_navigation_localization.sh"]),
        ("navigation", _named_pid_path("navigation"), ["ros2 launch nav_bringup navigation.launch.py"]),
        ("livox", _named_pid_path("livox"), ["ros2 launch livox_ros_driver2 msg_MID360_launch.py", "livox_ros_driver2_node"]),
        ("relocation", _named_pid_path("relocation"), ["ros2 launch super_lio relocation.py", "relocation_node"]),
        ("global_planner", _named_pid_path("global_planner"), ["ros2 launch global_planner path_planning_with_polygon.launch", "global_planner_node"]),
        ("pcl_publisher", _named_pid_path("pcl_publisher"), ["/nav_bringup/nav_pcd_map_publisher"]),
        ("p2p_move_base", _named_pid_path("p2p_move_base"), ["ros2 launch p2p_move_base go2_localization_launch.py", "clicked2goal.py", "p2p_move_base"]),
        ("scan_planner", _named_pid_path("scan_planner"), ["scan_planner_node"]),
        ("scan_controller", _named_pid_path("scan_controller"), ["closed_loop_controller"]),
        ("scan_path_adapter", _named_pid_path("scan_path_adapter"), ["/nav_bringup/scan_initial_path_adapter.py"]),
        ("scan_tf_pose", _named_pid_path("scan_tf_pose"), ["/nav_bringup/scan_tf_pose_publisher.py"]),
        ("dynamic_avoidance", _named_pid_path("dynamic_avoidance"), ["dynamic_avoidance_monitor.py"]),
        ("nav_status_monitor", _named_pid_path("nav_status_monitor"), ["waypoint_progress_monitor.py"]),
        ("waypoint_navigator", _named_pid_path("waypoint_navigator"), ["waypoint_navigator_from_json.py"]),
        ("static_base_tf", _named_pid_path("static_base_tf"), ["__node:=static_tf_base_link_to_base_footprint"]),
    ]

    target_pids: list[int] = []

    for process_name, pid_path, needles in pid_specs:
        pid = _read_pid_file(pid_path)
        pid_matches = _pid_matches_needles(pid, needles)
        if pid is not None and pid_matches is not False:
            target_pids.append(pid)
            continue
        if pid is not None:
            nav_logger.warning("忽略已复用的导航 PID：name={} pid={} path={}", process_name, pid, pid_path)
            pid_path.unlink(missing_ok=True)

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
        _navigation_ready_path().unlink(missing_ok=True)
        atomic_write_json(
            _runtime_dir() / "navigation_status.json",
            {"running": False, "stage": "stopped"},
        )
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

    _navigation_ready_path().unlink(missing_ok=True)
    atomic_write_json(
        _runtime_dir() / "navigation_status.json",
        {"running": False, "stage": "stopped"},
    )

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

    radar_preflight = check_livox_network_preflight()
    if not radar_preflight.get("ok"):
        message = str(radar_preflight.get("message") or "雷达连接异常")
        nav_logger.warning("导航定位启动前雷达检查失败：{}", message)
        raise RuntimeError(message)

    with _restart_lock:
        scene = load_current_scene(strict=False)
        log_offset = get_restart_log_offset()
        previous_navigation_pid = _read_pid_file(_named_pid_path("navigation"))
        nav_logger.info("收到导航定位重启请求，准备清理旧进程并启动脚本")
        nav_logger.info("准备重启导航定位")
        _stop_restart_proc(_restart_proc)

        log_path = _restart_log_path()
        nav_logger.info("准备重启导航定位，脚本路径：{}，日志路径：{}", script_path, log_path)
        nav_logger.info("启动 relocation，map_file={}", scene["map_pcd"])
        nav_logger.info(
            "启动 global_planner，map_dir={}，ground_dir={}，planground_dir={}",
            scene["map_pcd"],
            scene["ground_pcd"],
            scene.get("planground_pcd"),
        )

        try:
            process_env = lidar_mount_environment()
            mount_values = lidar_mount_log_values()
        except ValueError as exc:
            raise RuntimeError(f"雷达安装标定无效，拒绝启动导航定位：{exc}") from exc
        nav_logger.info("导航定位使用雷达安装标定：{}", mount_values)

        try:
            _restart_proc = subprocess.Popen(
                ["bash", str(script_path), scene["scene_dir"]],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
                cwd=str(_project_root()),
                env=process_env,
            )
        except Exception:
            raise

        output_thread: threading.Thread | None = None
        if _restart_proc.stdout is not None:
            output_thread = threading.Thread(
                target=_pump_restart_output,
                args=(_restart_proc, log_path),
                daemon=True,
                name="restart-localization-log-pump",
            )
            output_thread.start()

        # 上一轮 adapter/launch 可能仍在退出。若直接读取 PID 文件，会把旧 PID
        # 和旧 navigation_ready.json 当成本轮结果返回给前端。等待 navigation.pid
        # 完成轮换后，再收集本轮子进程 PID。
        if previous_navigation_pid is not None:
            rotation_deadline = time.monotonic() + 30.0
            navigation_pid_path = _named_pid_path("navigation")
            while time.monotonic() < rotation_deadline:
                if _restart_proc.poll() is not None:
                    break
                current_navigation_pid = _read_pid_file(navigation_pid_path)
                if (
                    current_navigation_pid is not None
                    and current_navigation_pid != previous_navigation_pid
                ):
                    break
                time.sleep(0.2)

        pid_files = {
            "navigation_pid": _named_pid_path("navigation"),
            "livox_pid": _named_pid_path("livox"),
            "relocation_pid": _named_pid_path("relocation"),
            "global_planner_pid": _named_pid_path("global_planner"),
            "scan_planner_pid": _named_pid_path("scan_planner"),
            "scan_controller_pid": _named_pid_path("scan_controller"),
            "dynamic_avoidance_pid": _named_pid_path("dynamic_avoidance"),
            "nav_status_monitor_pid": _named_pid_path("nav_status_monitor"),
            "waypoint_navigator_pid": _named_pid_path("waypoint_navigator"),
        }
        child_pids = _wait_for_pid_files(
            pid_files,
            timeout_s=20.0,
            abort_if=lambda: _restart_proc.poll() is not None,
        )
        unified_mode = "navigation_pid" in child_pids or "scan_planner_pid" in child_pids
        if unified_mode:
            default_ready_wait_s = float(os.environ.get("NAV_READY_TIMEOUT_SECONDS", "120")) + 10.0
            ready_deadline = time.monotonic() + float(
                os.environ.get("NAV_RESTART_READY_WAIT_S", str(default_ready_wait_s))
            )
            while not _navigation_ready_path().exists() and time.monotonic() < ready_deadline:
                if _restart_proc.poll() is not None:
                    break
                time.sleep(0.25)
            for name, pid_path in pid_files.items():
                child_pids[name] = _read_pid_file(pid_path)
        child_pids["cmd_vel_pid"] = _read_cmd_vel_pid()
        health_result = _build_restart_health(scene, child_pids)
        startup_ready = bool(health_result["startup_ready"])
        navigation_ready = bool(health_result["navigation_ready"])
        warnings = list(health_result["warnings"] or [])
        errors = list(health_result["errors"] or [])
        restart_running = _restart_proc.poll() is None
        if not restart_running:
            startup_ready = False
            navigation_ready = False
            if output_thread is not None:
                output_thread.join(timeout=1.0)
            startup_error = _restart_startup_error_since(log_offset)
            errors = [startup_error or "导航重启脚本已提前退出"]
            error_message = errors[0]
            nav_logger.error("导航定位重启失败：{}", error_message)
            raise RuntimeError(error_message)
        health_result["health"]["restart_running"] = restart_running
        health_result["health"]["errors"] = errors
        if navigation_ready:
            message = "已启动重启脚本，导航可用"
        elif startup_ready:
            message = "导航定位进程已启动，等待 initialpose"
        else:
            details = errors or warnings or ["健康状态未确认"]
            message = "已启动重启脚本，但导航不可用：" + "；".join(details)

        nav_logger.info("已启动导航定位重启脚本：pid={}", _restart_proc.pid)
        return {
            "success": restart_running,
            "running": restart_running,
            "pid": _restart_proc.pid,
            "scene_id": scene["scene_id"],
            "scene_dir": scene["scene_dir"],
            "map_pcd": scene["map_pcd"],
            "ground_pcd": scene["ground_pcd"],
            "planground_pcd": scene["planground_pcd"],
            **child_pids,
            "cmd_vel_running": health_result["health"]["cmd_vel_running"],
            "startup_ready": startup_ready,
            "navigation_ready": navigation_ready,
            "process_pids": {
                "navigation": child_pids.get("navigation_pid"),
                "livox": child_pids["livox_pid"],
                "relocation": child_pids["relocation_pid"],
                "global_planner": child_pids["global_planner_pid"],
                "p2p_move_base": child_pids.get("p2p_move_base_pid"),
                "scan_planner": child_pids.get("scan_planner_pid"),
                "scan_controller": child_pids.get("scan_controller_pid"),
                "dynamic_avoidance": child_pids.get("dynamic_avoidance_pid"),
                "nav_status_monitor": child_pids.get("nav_status_monitor_pid"),
                "waypoint_navigator": child_pids.get("waypoint_navigator_pid"),
                "cmd_vel": child_pids["cmd_vel_pid"],
            },
            "health": health_result["health"],
            "warnings": warnings,
            "errors": errors,
            "message": message,
            "initialpose_wait_log_offset": log_offset,
        }
