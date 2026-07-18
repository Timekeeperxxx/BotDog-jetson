from __future__ import annotations

import os
import re
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path
from typing import Any

from .config import settings
from .lidar_mount import lidar_mount_environment, lidar_mount_log_values
from .logging_config import get_logger
from .nav_bridge_state import get_ros_nav_bridge
from .pcd_reader import normalize_pcd_header, parse_pcd_header
from .services_nav_state import clear_global_path, clear_robot_pose, get_robot_pose, set_navigation_idle
from .services_nav_localization import stop_cmd_vel_script, stop_navigation_processes
from .services_nav_waypoints import upsert_origin_waypoint


mapping_logger = get_logger("建图服务")

MAPS_ROOT = Path("/home/jetson/Project/BOTDOG/MAPS")
START_MAPPING_SCRIPT = Path("/home/jetson/Project/BOTDOG/BotDog/scripts/start_mapping.sh")
VIDEO_PIPELINE_SCRIPT = Path("/home/jetson/Project/BOTDOG/BotDog/scripts/run-pipeline.sh")
VIDEO_PIPELINE_PID_FILES = (
    Path("/home/jetson/Project/BOTDOG/BotDog/logs/mediamtx.pid"),
    Path("/home/jetson/Project/BOTDOG/BotDog/logs/ffmpeg_cam1.pid"),
    Path("/home/jetson/Project/BOTDOG/BotDog/logs/ffmpeg_cam2.pid"),
    Path("/home/jetson/Project/BOTDOG/BotDog/logs/ffmpeg_cam3.pid"),
    Path("/home/jetson/Project/BOTDOG/BotDog/logs/ffmpeg_cam4.pid"),
)
SCENE_DIR_PATTERN = re.compile(r"^Scene(\d+)_")
MAPPING_READY_FLAG_NAME = ".ground_generation_started"
MAPPING_START_READY_TIMEOUT_SECONDS = 60
MAPPING_START_READY_POLL_INTERVAL_SECONDS = 0.5
# 必须长于 terrain 保存 30 分钟上限及后续 SuperLIO/launch 清理时间，
# 否则后端会提前终止脚本，ground 和 footprint 仍然来不及落盘。
MAPPING_STOP_WAIT_TIMEOUT_SECONDS = 1950
MAPPING_STOP_FORCE_KILL_WAIT_SECONDS = 5
# 建图最短运行时间（秒），少于此时间停止时会额外提示
MAPPING_MIN_RUNTIME_SECONDS = 90


class MappingError(RuntimeError):
    """建图流程错误。"""


def _normalize_scene_name(scene_name: str | None) -> str:
    if scene_name is None:
        raise MappingError("请输入场景名称")

    normalized = scene_name.strip()
    if not normalized:
        raise MappingError("请输入场景名称")
    if normalized in {".", ".."}:
        raise MappingError("场景名称非法")
    if "/" in normalized or "\\" in normalized:
        raise MappingError("场景名称不能包含 / 或 \\")
    if ".." in normalized:
        raise MappingError("场景名称不能包含 ..")
    if any(ord(ch) < 32 for ch in normalized):
        raise MappingError("场景名称包含非法控制字符")
    if len(normalized) > 100:
        raise MappingError("场景名称过长")
    return normalized


def resolve_map_dir(scene_name: str) -> Path:
    root = MAPS_ROOT.resolve()
    root.mkdir(parents=True, exist_ok=True)

    map_dir = (root / build_scene_dir_name(scene_name)).resolve()
    if map_dir.parent != root:
        raise MappingError("场景名称非法，禁止访问地图根目录以外的路径")
    return map_dir


def build_scene_dir_name(scene_name: str) -> str:
    root = MAPS_ROOT.resolve()
    root.mkdir(parents=True, exist_ok=True)

    max_scene_index = 0
    for path in root.iterdir():
        if not path.is_dir():
            continue
        match = SCENE_DIR_PATTERN.match(path.name)
        if not match:
            continue
        try:
            max_scene_index = max(max_scene_index, int(match.group(1)))
        except ValueError:
            continue

    next_scene_index = max_scene_index + 1
    return f"Scene{next_scene_index}_{scene_name}"


def mapping_ready_flag_path(map_dir: Path) -> Path:
    return map_dir / MAPPING_READY_FLAG_NAME


@dataclass(slots=True)
class MappingSession:
    scene_name: str
    map_dir: Path
    process: subprocess.Popen[Any]
    started_at: float
    runtime_pause_state: dict[str, bool]
    initial_origin_pose: dict[str, Any]
    saving: bool = False
    stop_requested_at: float | None = None
    completion_event: threading.Event = field(default_factory=threading.Event, repr=False)

    def is_running(self) -> bool:
        return self.process.poll() is None


class MappingService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._session: MappingSession | None = None
        self._last_result: dict[str, Any] | None = None

    @staticmethod
    def _forward_stream(stream: Any, level: str, prefix: str) -> None:
        try:
            for raw_line in iter(stream.readline, ""):
                line = raw_line.rstrip()
                if not line:
                    continue
                if level == "warning":
                    mapping_logger.warning("{}{}", prefix, line)
                else:
                    mapping_logger.info("{}{}", prefix, line)
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def _attach_output_forwarders(self, process: subprocess.Popen[Any]) -> None:
        stdout = getattr(process, "stdout", None)
        stderr = getattr(process, "stderr", None)

        if stdout is not None:
            threading.Thread(
                target=self._forward_stream,
                args=(stdout, "info", "[建图stdout] "),
                daemon=True,
            ).start()
        if stderr is not None:
            threading.Thread(
                target=self._forward_stream,
                args=(stderr, "warning", "[建图stderr] "),
                daemon=True,
            ).start()

    def _cleanup_finished_session_unlocked(self) -> None:
        if self._session is not None and not self._session.saving and not self._session.is_running():
            mapping_logger.info(
                "建图进程已退出：scene_name={}，pid={}，退出码={}",
                self._session.scene_name,
                self._session.process.pid,
                self._session.process.returncode,
            )
            self._session = None

    @staticmethod
    def _stop_process_group(process: subprocess.Popen[Any], reason: str) -> None:
        pid = process.pid
        try:
            pgid = os.getpgid(pid)
        except ProcessLookupError:
            return

        mapping_logger.warning("建图启动未就绪，终止进程组：pid={}，pgid={}，原因={}", pid, pgid, reason)
        for sig, wait_seconds in ((signal.SIGINT, 10), (signal.SIGTERM, 5), (signal.SIGKILL, None)):
            try:
                os.killpg(pgid, sig)
            except ProcessLookupError:
                return

            if wait_seconds is None:
                return

            try:
                process.wait(timeout=wait_seconds)
                return
            except subprocess.TimeoutExpired:
                continue
            except Exception:
                return

    @staticmethod
    def _resume_nav_bridge() -> None:
        try:
            bridge = get_ros_nav_bridge()
            if bridge is not None:
                bridge.resume()
                mapping_logger.info("后端 ROS2 导航节点已恢复")
        except Exception as exc:
            mapping_logger.warning("恢复 ROS2 导航节点失败：{}", exc)

    @staticmethod
    def _fallback_initial_origin_pose() -> dict[str, Any]:
        return {
            "x": 0.0,
            "y": 0.0,
            "z": float(settings.NAV_ORIGIN_WAYPOINT_Z),
            "yaw": float(settings.NAV_ORIGIN_WAYPOINT_YAW),
            "frame_id": settings.PCD_FRAME_ID,
            "source": "config:NAV_ORIGIN_WAYPOINT",
        }

    @staticmethod
    def _normalize_initial_origin_pose(pose: dict[str, Any] | None) -> dict[str, Any] | None:
        if not pose:
            return None
        try:
            x = float(pose["x"])
            y = float(pose["y"])
            z = float(pose["z"])
            yaw = float(pose.get("yaw", settings.NAV_ORIGIN_WAYPOINT_YAW))
        except Exception:
            return None
        if not all(isfinite(value) for value in (x, y, z, yaw)):
            return None
        frame_id = str(pose.get("frame_id") or settings.PCD_FRAME_ID)
        if frame_id != settings.PCD_FRAME_ID:
            mapping_logger.warning(
                "建图初始位姿坐标系不是 {}，忽略：frame_id={} pose={}",
                settings.PCD_FRAME_ID,
                frame_id,
                pose,
            )
            return None
        return {
            "x": x,
            "y": y,
            "z": z,
            "yaw": yaw,
            "frame_id": frame_id,
            "source": pose.get("source") or "nav.robot_pose",
            "source_frame": pose.get("source_frame"),
            "timestamp": pose.get("timestamp"),
        }

    @classmethod
    def _capture_initial_origin_pose(cls) -> dict[str, Any]:
        pose: dict[str, Any] | None = None
        bridge = get_ros_nav_bridge()
        if bridge is not None:
            get_current_robot_pose = getattr(bridge, "get_current_robot_pose", None)
            if callable(get_current_robot_pose):
                try:
                    pose = get_current_robot_pose()
                except Exception as exc:
                    mapping_logger.warning("读取建图初始 ROS 位姿失败：{}", exc)

        captured = cls._normalize_initial_origin_pose(pose or get_robot_pose())
        if captured is not None:
            mapping_logger.info(
                "已捕获建图初始原点位姿：x={} y={} z={} yaw={} source={}",
                captured["x"],
                captured["y"],
                captured["z"],
                captured["yaw"],
                captured.get("source"),
            )
            return captured

        fallback = cls._fallback_initial_origin_pose()
        mapping_logger.warning(
            "未读到建图初始 TF/位姿，使用配置兜底原点：x={} y={} z={} yaw={}",
            fallback["x"],
            fallback["y"],
            fallback["z"],
            fallback["yaw"],
        )
        return fallback

    @staticmethod
    def _pause_runtime_interferers() -> dict[str, bool]:
        state = {
            "auto_track_resume_needed": False,
            "guard_mission_restore_needed": False,
            "video_pipeline_restore_needed": False,
        }

        try:
            from .auto_track_service import get_auto_track_service

            auto_track_service = get_auto_track_service()
            if auto_track_service is not None:
                auto_track_status = auto_track_service.get_status()
                if auto_track_status.get("enabled") and not auto_track_status.get("paused"):
                    auto_track_service.pause()
                    state["auto_track_resume_needed"] = True
                    mapping_logger.info("建图开始前已暂停自动跟踪服务")
        except Exception as exc:
            mapping_logger.warning("暂停自动跟踪服务失败：{}", exc)

        try:
            from .guard_mission_service import get_guard_mission_service

            guard_mission_service = get_guard_mission_service()
            if guard_mission_service is not None and bool(guard_mission_service.enabled):
                guard_mission_service.enabled = False
                state["guard_mission_restore_needed"] = True
                mapping_logger.info("建图开始前已禁用驱离任务服务")
        except Exception as exc:
            mapping_logger.warning("禁用驱离任务服务失败：{}", exc)

        return state

    @staticmethod
    def _is_pid_running(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True

    @classmethod
    def _is_video_pipeline_running(cls) -> bool:
        for pid_file in VIDEO_PIPELINE_PID_FILES:
            try:
                raw_pid = pid_file.read_text(encoding="utf-8").strip()
                if raw_pid and cls._is_pid_running(int(raw_pid)):
                    return True
            except (FileNotFoundError, ValueError):
                continue
            except Exception as exc:
                mapping_logger.debug("读取视频流水线 PID 文件失败：{}，原因={}", pid_file, exc)
        return False

    @classmethod
    def _stop_video_pipeline_for_mapping(cls) -> bool:
        if not VIDEO_PIPELINE_SCRIPT.exists():
            return False
        if not cls._is_video_pipeline_running():
            return False

        try:
            subprocess.run(
                ["bash", str(VIDEO_PIPELINE_SCRIPT), "stop"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=20,
                check=False,
            )
            mapping_logger.info("建图开始前已停止视频流水线，降低 FFmpeg/MediaMTX 对 LIO 的 CPU 抢占")
            return True
        except Exception as exc:
            mapping_logger.warning("停止视频流水线失败，继续建图：{}", exc)
            return False

    @staticmethod
    def _restore_video_pipeline_after_mapping() -> None:
        if not VIDEO_PIPELINE_SCRIPT.exists():
            return

        try:
            subprocess.Popen(
                ["bash", str(VIDEO_PIPELINE_SCRIPT)],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            mapping_logger.info("建图结束后已恢复视频流水线")
        except Exception as exc:
            mapping_logger.warning("恢复视频流水线失败：{}", exc)

    @staticmethod
    def _resume_runtime_interferers(state: dict[str, bool] | None) -> None:
        if not state:
            return

        if state.get("video_pipeline_restore_needed"):
            MappingService._restore_video_pipeline_after_mapping()

        if state.get("guard_mission_restore_needed"):
            try:
                from .guard_mission_service import get_guard_mission_service

                guard_mission_service = get_guard_mission_service()
                if guard_mission_service is not None:
                    guard_mission_service.enabled = True
                    mapping_logger.info("驱离任务服务已恢复到建图前状态")
            except Exception as exc:
                mapping_logger.warning("恢复驱离任务服务失败：{}", exc)

        if state.get("auto_track_resume_needed"):
            try:
                from .auto_track_service import get_auto_track_service

                auto_track_service = get_auto_track_service()
                if auto_track_service is not None:
                    auto_track_service.resume()
                    mapping_logger.info("自动跟踪服务已恢复到建图前状态")
            except Exception as exc:
                mapping_logger.warning("恢复自动跟踪服务失败：{}", exc)

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            self._cleanup_finished_session_unlocked()
            if self._session is None:
                if self._last_result is not None:
                    return dict(self._last_result)
                return {
                    "running": False,
                    "saving": False,
                    "saved": False,
                    "scene_name": None,
                    "map_dir": None,
                    "pid": None,
                    "started_at": None,
                    "map_pcd_candidates": [],
                    "ground_pcd_candidates": [],
                    "pcd_files": [],
                    "message": "建图未运行",
                }

            return {
                "running": not self._session.saving,
                "saving": self._session.saving,
                "saved": False,
                "scene_name": self._session.scene_name,
                "map_dir": str(self._session.map_dir),
                "pid": self._session.process.pid,
                "started_at": self._session.started_at,
                "map_pcd_candidates": [],
                "ground_pcd_candidates": [],
                "pcd_files": [],
                "message": "地图正在保存" if self._session.saving else "建图正在运行",
            }

    def start(self, scene_name: str) -> dict[str, Any]:
        normalized_scene_name = _normalize_scene_name(scene_name)

        with self._lock:
            self._cleanup_finished_session_unlocked()
            if self._session is not None:
                if self._session.saving:
                    raise MappingError("地图保存正在进行中，请等待保存完成")
                raise MappingError("建图已在进行中")

            if not START_MAPPING_SCRIPT.exists():
                raise MappingError(f"建图脚本不存在: {START_MAPPING_SCRIPT}")

            map_dir = resolve_map_dir(normalized_scene_name)
            map_dir.mkdir(parents=True, exist_ok=True)
            ready_flag = mapping_ready_flag_path(map_dir)
            ready_flag.unlink(missing_ok=True)
            runtime_pause_state = {
                "auto_track_resume_needed": False,
                "guard_mission_restore_needed": False,
                "video_pipeline_restore_needed": False,
            }
            mapping_logger.info("开始建图前，准备停止导航相关后台进程")
            nav_stop_result = stop_navigation_processes()
            cmd_vel_stop_result = stop_cmd_vel_script()
            clear_robot_pose()
            clear_global_path()
            set_navigation_idle("开始建图，导航状态已重置")
            mapping_logger.info(
                "导航后台进程停止结果：nav_pids={} cmd_vel_pid={}",
                nav_stop_result.get("pids"),
                cmd_vel_stop_result.get("pid"),
            )

            bridge = get_ros_nav_bridge()
            if bridge is not None:
                bridge.clear_accumulated_cloud()
                mapping_logger.info("建图开始前已清空前端实时建图点云缓存")
            runtime_pause_state = self._pause_runtime_interferers()
            command = ["bash", str(START_MAPPING_SCRIPT), str(map_dir)]
            try:
                process_env = lidar_mount_environment()
                mount_values = lidar_mount_log_values()
            except ValueError as exc:
                self._resume_runtime_interferers(runtime_pause_state)
                raise MappingError(f"雷达安装标定无效，拒绝开始建图：{exc}") from exc
            mapping_logger.info(
                "开始建图：scene_name={}，map_dir={}，command={}，lidar_mount={}",
                normalized_scene_name,
                map_dir,
                " ".join(command),
                mount_values,
            )

            # stdout/stderr 直接丢弃，脚本内部用 tee 和 >> 写入 DEBUG_LOG。
            # 不能用 subprocess.PIPE —— 脚本大量使用 tee 写 stdout，
            # 如果 Python 端 readline 跟不上，tee 阻塞会导致整个建图脚本卡死。
            process = subprocess.Popen(
                command,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=process_env,
            )
            start_wait_deadline = time.monotonic() + MAPPING_START_READY_TIMEOUT_SECONDS
            while time.monotonic() < start_wait_deadline:
                if ready_flag.exists():
                    bridge = get_ros_nav_bridge()
                    if bridge is not None:
                        reset_cloud_subscription = getattr(bridge, "reset_mapping_cloud_subscription", None)
                        if callable(reset_cloud_subscription):
                            if reset_cloud_subscription():
                                mapping_logger.info("建图低频累计点云订阅已重建")
                            else:
                                mapping_logger.warning("建图低频累计点云订阅重建失败，前端可能无实时点云")

                    initial_origin_pose = self._capture_initial_origin_pose()
                    self._session = MappingSession(
                        scene_name=map_dir.name,
                        map_dir=map_dir,
                        process=process,
                        started_at=time.time(),
                        runtime_pause_state=runtime_pause_state,
                        initial_origin_pose=initial_origin_pose,
                    )
                    self._last_result = None
                    mapping_logger.info(
                        "建图已进入 ground 生成阶段：scene_name={}，pid={}，map_dir={}，initial_origin={}",
                        map_dir.name,
                        process.pid,
                        map_dir,
                        initial_origin_pose,
                    )
                    return {
                        "success": True,
                        "enabled": True,
                        "running": True,
                        "scene_name": map_dir.name,
                        "map_dir": str(map_dir),
                        "pid": process.pid,
                        "message": "建图已进入 ground 生成阶段",
                    }

                return_code = process.poll()
                if return_code is not None:
                    self._resume_runtime_interferers(runtime_pause_state)
                    self._resume_nav_bridge()
                    raise MappingError(
                        f"建图启动失败：ground 生成尚未开始，脚本已退出（退出码={return_code}）"
                    )

                time.sleep(MAPPING_START_READY_POLL_INTERVAL_SECONDS)

            self._stop_process_group(process, "等待 ground 生成启动标记超时")
            self._resume_runtime_interferers(runtime_pause_state)
            self._resume_nav_bridge()
            raise MappingError("建图启动超时：ground 生成尚未开始，请查看 start_mapping_debug.log")

    @staticmethod
    def _saving_response(session: MappingSession) -> dict[str, Any]:
        return {
            "success": True,
            "enabled": False,
            "running": False,
            "saving": True,
            "saved": False,
            "scene_name": session.scene_name,
            "map_dir": str(session.map_dir),
            "pid": session.process.pid,
            "started_at": session.started_at,
            "map_pcd_candidates": [],
            "ground_pcd_candidates": [],
            "pcd_files": [],
            "origin_waypoint": None,
            "origin_waypoint_error": None,
            "message": "建图已停止，地图正在后台保存",
        }

    @staticmethod
    def _validate_pcd_file(path: Path) -> tuple[bool, str | None]:
        try:
            size_bytes = path.stat().st_size
            if size_bytes <= 0:
                return False, "文件为空"
            header, data_start_offset = parse_pcd_header(path)
            normalized = normalize_pcd_header(header)
            if normalized["point_count"] <= 0:
                return False, "点数量为 0"
            if normalized["data_type"] not in {"ascii", "binary", "binary_compressed"}:
                return False, f"不支持的 DATA 类型: {normalized['data_type']}"
            if data_start_offset >= size_bytes:
                return False, "PCD 没有点数据"
            return True, None
        except Exception as exc:
            return False, str(exc)

    @classmethod
    def _collect_pcd_files(
        cls,
        map_dir_path: Path,
    ) -> tuple[list[str], list[str], list[dict[str, Any]]]:
        map_pcd_candidates: list[str] = []
        ground_pcd_candidates: list[str] = []
        pcd_files: list[dict[str, Any]] = []

        if not map_dir_path.is_dir():
            return map_pcd_candidates, ground_pcd_candidates, pcd_files

        for fpath in sorted(map_dir_path.rglob("*.pcd")):
            fname = fpath.name
            valid, validation_error = cls._validate_pcd_file(fpath)
            info = {
                "name": fname,
                "path": str(fpath),
                "size_bytes": fpath.stat().st_size if fpath.exists() else 0,
                "valid": valid,
                "validation_error": validation_error,
            }
            pcd_files.append(info)
            if not valid:
                mapping_logger.warning("忽略无效 PCD：{}，原因={}", fpath, validation_error)
                continue

            lower_name = fname.lower()
            if lower_name.endswith("ground.pcd"):
                ground_pcd_candidates.append(fname)
            elif lower_name.endswith("map.pcd"):
                map_pcd_candidates.append(fname)

        return map_pcd_candidates, ground_pcd_candidates, pcd_files

    def stop(self, *, wait: bool = True) -> dict[str, Any]:
        with self._lock:
            self._cleanup_finished_session_unlocked()
            if self._session is None:
                return {
                    "success": True,
                    "enabled": False,
                    "running": False,
                    "saving": False,
                    "saved": False,
                    "scene_name": None,
                    "map_dir": None,
                    "pid": None,
                    "map_pcd_candidates": [],
                    "ground_pcd_candidates": [],
                    "pcd_files": [],
                    "message": "当前没有正在运行的建图进程",
                }

            session = self._session
            if session.saving:
                if not wait:
                    return self._saving_response(session)
                existing_save = True
            else:
                existing_save = False

            if not existing_save:
                process = session.process
                pid = process.pid
                started_at = session.started_at
                elapsed = time.time() - started_at
                session.saving = True
                session.stop_requested_at = time.time()

                mapping_logger.info(
                    "停止建图：向脚本发送 SIGINT，触发 cleanup 按序停止进程...",
                )
                mapping_logger.info(
                    "  脚本 PID={}，已运行={:.0f}s，cleanup 顺序：terrain_analysis -> super_lio -> livox",
                    pid,
                    elapsed,
                )

                try:
                    os.kill(pid, signal.SIGINT)
                except ProcessLookupError:
                    mapping_logger.warning("建图脚本已不存在：pid={}", pid)
                except Exception as exc:
                    mapping_logger.warning("发送 SIGINT 到建图脚本失败：pid={}，原因={}", pid, exc)

        if existing_save:
            wait_timeout = MAPPING_STOP_WAIT_TIMEOUT_SECONDS + 30
            if not session.completion_event.wait(timeout=wait_timeout):
                response = self._saving_response(session)
                response["message"] = f"等待后台地图保存完成超时（{wait_timeout} 秒）"
                return response
            with self._lock:
                return dict(self._last_result) if self._last_result is not None else self._saving_response(session)

        if not wait:
            threading.Thread(
                target=self._finish_stop_safely,
                args=(session,),
                daemon=True,
                name=f"mapping-save-{pid}",
            ).start()
            return self._saving_response(session)

        return self._finish_stop_safely(session)

    def _finish_stop_safely(self, session: MappingSession) -> dict[str, Any]:
        try:
            return self._finish_stop(session)
        except Exception as exc:
            mapping_logger.exception(
                "地图保存收尾失败：scene_name={} pid={}，原因={}",
                session.scene_name,
                session.process.pid,
                exc,
            )
            result = {
                "success": True,
                "enabled": False,
                "running": False,
                "saving": False,
                "saved": False,
                "scene_name": session.scene_name,
                "map_dir": str(session.map_dir),
                "pid": session.process.pid,
                "map_pcd_candidates": [],
                "ground_pcd_candidates": [],
                "pcd_files": [],
                "origin_waypoint": None,
                "origin_waypoint_error": None,
                "message": f"地图保存收尾失败：{exc}",
            }
            self._resume_runtime_interferers(session.runtime_pause_state)
            self._resume_nav_bridge()
            with self._lock:
                self._last_result = dict(result)
                if self._session is session:
                    self._session = None
            return result
        finally:
            session.completion_event.set()

    def _finish_stop(self, session: MappingSession) -> dict[str, Any]:
        process = session.process
        pid = process.pid
        scene_name = session.scene_name
        map_dir = str(session.map_dir)
        map_dir_path = session.map_dir
        started_at = session.started_at
        forced = False
        try:
            process.wait(timeout=MAPPING_STOP_WAIT_TIMEOUT_SECONDS)
            mapping_logger.info("建图脚本已正常退出：pid={}，耗时={:.0f}s", pid, time.time() - started_at)
        except subprocess.TimeoutExpired:
            mapping_logger.warning(
                "建图脚本在 {} 秒内未退出，尝试 SIGTERM -> bash（触发 trap）",
                MAPPING_STOP_WAIT_TIMEOUT_SECONDS,
            )
            try:
                os.kill(pid, signal.SIGTERM)
                process.wait(timeout=10)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                mapping_logger.warning(
                    "脚本仍未退出，使用 SIGKILL 强制终止整个进程组：pgid={}",
                    os.getpgid(pid),
                )
                try:
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=MAPPING_STOP_FORCE_KILL_WAIT_SECONDS)
                except subprocess.TimeoutExpired:
                    mapping_logger.error("建图进程组 SIGKILL 后仍未退出")
                forced = True
        except Exception as exc:
            mapping_logger.exception("等待建图保存进程退出失败：pid={}，原因={}", pid, exc)
            forced = True

        # ── 检查 PCD 文件 ──────────────────────────────────────────────────
        map_pcd_candidates, ground_pcd_candidates, pcd_files = self._collect_pcd_files(map_dir_path)

        saved = len(map_pcd_candidates) > 0 and len(ground_pcd_candidates) > 0
        origin_waypoint: dict[str, Any] | None = None
        origin_waypoint_error: str | None = None
        if saved:
            message = f"地图已保存：map.pcd x{len(map_pcd_candidates)}，ground.pcd x{len(ground_pcd_candidates)}"
            try:
                origin_waypoint = upsert_origin_waypoint(
                    scene_name,
                    x=session.initial_origin_pose.get("x"),
                    y=session.initial_origin_pose.get("y"),
                    z=session.initial_origin_pose.get("z"),
                    yaw=session.initial_origin_pose.get("yaw"),
                )
                message += "，已自动添加原点导航点"
                mapping_logger.info(
                    "建图完成后已自动写入原点导航点：scene_name={} waypoint_id={} x={} y={} z={} yaw={} source={}",
                    scene_name,
                    origin_waypoint.get("id"),
                    origin_waypoint.get("x"),
                    origin_waypoint.get("y"),
                    origin_waypoint.get("z"),
                    origin_waypoint.get("yaw"),
                    session.initial_origin_pose.get("source"),
                )
            except Exception as exc:
                origin_waypoint_error = str(exc)
                message += "，但原点导航点添加失败"
                mapping_logger.warning("建图完成后自动添加原点导航点失败：scene_name={}，原因={}", scene_name, exc)
        elif len(map_pcd_candidates) == 0 and len(ground_pcd_candidates) == 0:
            message = "地图保存失败：未找到 map.pcd 和 ground.pcd，请查看 start_mapping_debug.log"
        elif len(map_pcd_candidates) == 0:
            message = "地图保存不完整：缺少 map.pcd，请查看 start_mapping_debug.log"
        else:
            message = "地图保存不完整：缺少 ground.pcd，请查看 start_mapping_debug.log"

        if forced:
            message += "（脚本被强制终止，文件可能不完整）"

        for file_info in pcd_files:
            if file_info["valid"]:
                mapping_logger.info("有效 PCD 已保存：{} ({} 字节)", file_info["path"], file_info["size_bytes"])

        # 恢复后端 ROS2 节点
        self._resume_runtime_interferers(session.runtime_pause_state)
        self._resume_nav_bridge()

        mapping_logger.info(
            "建图停止完成：scene_name={}，saved={}，pcd_files={}",
            scene_name,
            saved,
            len(pcd_files),
        )

        result = {
            "success": True,
            "enabled": False,
            "running": False,
            "saving": False,
            "saved": saved,
            "scene_name": scene_name,
            "map_dir": map_dir,
            "pid": pid,
            "map_pcd_candidates": map_pcd_candidates,
            "ground_pcd_candidates": ground_pcd_candidates,
            "pcd_files": pcd_files,
            "origin_waypoint": origin_waypoint,
            "origin_waypoint_error": origin_waypoint_error,
            "message": message,
        }
        with self._lock:
            self._last_result = dict(result)
            if self._session is session:
                self._session = None
        return result


_mapping_service = MappingService()


def get_mapping_service() -> MappingService:
    return _mapping_service
