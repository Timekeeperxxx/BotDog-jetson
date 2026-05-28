from __future__ import annotations

import os
import re
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .logging_config import get_logger
from .nav_bridge_state import get_ros_nav_bridge
from .services_nav_localization import stop_cmd_vel_script, stop_navigation_processes


mapping_logger = get_logger("建图服务")

MAPS_ROOT = Path("/home/jetson/Project/BOTDOG/MAPS")
START_MAPPING_SCRIPT = Path("/home/jetson/Project/BOTDOG/BotDog/scripts/start_mapping.sh")
SCENE_DIR_PATTERN = re.compile(r"^Scene(\d+)_")
# 必须长于 scripts/start_mapping.sh 里 trap cleanup 的最长等待时间，
# 否则后端会先把整个进程组 SIGKILL，super_lio 来不及写出最终 map.pcd。
MAPPING_STOP_WAIT_TIMEOUT_SECONDS = 95
MAPPING_STOP_FORCE_KILL_WAIT_SECONDS = 5


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


@dataclass(slots=True)
class MappingSession:
    scene_name: str
    map_dir: Path
    process: subprocess.Popen[Any]
    started_at: float

    def is_running(self) -> bool:
        return self.process.poll() is None


class MappingService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._session: MappingSession | None = None

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
        if self._session is not None and not self._session.is_running():
            mapping_logger.info(
                "建图进程已退出：scene_name={}，pid={}，退出码={}",
                self._session.scene_name,
                self._session.process.pid,
                self._session.process.returncode,
            )
            self._session = None

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            self._cleanup_finished_session_unlocked()
            if self._session is None:
                return {
                    "running": False,
                    "scene_name": None,
                    "map_dir": None,
                    "pid": None,
                    "started_at": None,
                }

            return {
                "running": True,
                "scene_name": self._session.scene_name,
                "map_dir": str(self._session.map_dir),
                "pid": self._session.process.pid,
                "started_at": self._session.started_at,
            }

    def start(self, scene_name: str) -> dict[str, Any]:
        normalized_scene_name = _normalize_scene_name(scene_name)

        with self._lock:
            self._cleanup_finished_session_unlocked()
            if self._session is not None:
                raise MappingError("建图已在进行中")

            if not START_MAPPING_SCRIPT.exists():
                raise MappingError(f"建图脚本不存在: {START_MAPPING_SCRIPT}")

            map_dir = resolve_map_dir(normalized_scene_name)
            map_dir.mkdir(parents=True, exist_ok=True)
            mapping_logger.info("开始建图前，准备停止导航相关后台进程")
            nav_stop_result = stop_navigation_processes()
            cmd_vel_stop_result = stop_cmd_vel_script()
            mapping_logger.info(
                "导航后台进程停止结果：nav_pids={} cmd_vel_pid={}",
                nav_stop_result.get("pids"),
                cmd_vel_stop_result.get("pid"),
            )

            # 给 LiDAR 硬件充分的复位时间。
            # stop_navigation_processes 会 SIGKILL Livox 驱动，
            # 硬件在下一次启动前需要几秒完成内部清理/校准。
            mapping_logger.info("等待 5s 让 LiDAR 硬件完成复位...")
            time.sleep(5)

            bridge = get_ros_nav_bridge()
            if bridge is not None:
                bridge.clear_accumulated_cloud()
                # 暂停后端 ROS2 节点，使其退出 DDS 网络。
                # CLI 建图时后端节点不存在；前端建图时若保持运行，
                # 其 DDS participant 可能干扰 SuperLIO 的 IMU 消息发现。
                mapping_logger.info("暂停后端 ROS2 导航节点以隔离建图 DDS 环境...")
                bridge.pause()
            command = ["bash", str(START_MAPPING_SCRIPT), str(map_dir)]
            mapping_logger.info(
                "开始建图：scene_name={}，map_dir={}，command={}",
                normalized_scene_name,
                map_dir,
                " ".join(command),
            )

            process = subprocess.Popen(
                command,
                start_new_session=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            self._attach_output_forwarders(process)
            self._session = MappingSession(
                scene_name=map_dir.name,
                map_dir=map_dir,
                process=process,
                started_at=time.time(),
            )

            mapping_logger.info(
                "建图脚本已启动：scene_name={}，pid={}，map_dir={}",
                map_dir.name,
                process.pid,
                map_dir,
            )

            return {
                "success": True,
                "enabled": True,
                "running": True,
                "scene_name": map_dir.name,
                "map_dir": str(map_dir),
                "pid": process.pid,
                "message": "建图脚本已启动",
            }

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self._cleanup_finished_session_unlocked()
            if self._session is None:
                return {
                    "success": True,
                    "enabled": False,
                    "running": False,
                    "scene_name": None,
                    "map_dir": None,
                    "pid": None,
                    "message": "当前没有正在运行的建图进程",
                }

            process = self._session.process
            pid = process.pid
            scene_name = self._session.scene_name
            map_dir = str(self._session.map_dir)

            mapping_logger.info(
                "停止建图：向脚本发送 SIGINT，触发 cleanup 按序停止进程...",
            )
            mapping_logger.info(
                "  脚本 PID={}，cleanup 顺序：terrain_analysis → super_lio → livox",
                pid,
            )

            try:
                # 只向 bash 脚本发送 SIGINT，让脚本自己的 trap cleanup 按序执行：
                #   1) terrain_analysis（等 15s 保存 ground.pcd）
                #   2) super_lio（等 60s 保存 map.pcd）
                #   3) livox
                # 之前用 os.killpg 会同时 SIGINT 整个进程组，绕过了脚本的清理顺序，
                # 导致 terrain_analysis 和 super_lio 同时被中断，ground.pcd 可能未完整落盘。
                os.kill(pid, signal.SIGINT)
            except ProcessLookupError:
                mapping_logger.warning("建图脚本已不存在：pid={}", pid)
            except Exception as exc:
                mapping_logger.warning("发送 SIGINT 到建图脚本失败：pid={}，原因={}", pid, exc)

            # 立即清除 session，避免阻塞 HTTP 响应；等待和文件校验在后台线程完成
            self._session = None
            map_dir_path = Path(map_dir)

            def _wait_and_verify() -> None:
                try:
                    process.wait(timeout=MAPPING_STOP_WAIT_TIMEOUT_SECONDS)
                except subprocess.TimeoutExpired:
                    mapping_logger.warning(
                        "建图脚本在 {} 秒内未退出，尝试 SIGTERM → bash（触发 trap）",
                        MAPPING_STOP_WAIT_TIMEOUT_SECONDS,
                    )
                    # 先尝试 SIGTERM 给 bash 脚本（也会触发 trap cleanup）
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
                for fname in ("map.pcd", "ground.pcd"):
                    fpath = map_dir_path / fname
                    if fpath.exists():
                        mapping_logger.info("文件已保存：{} ({} 字节)", fpath, fpath.stat().st_size)
                    else:
                        mapping_logger.warning("文件未生成：{}，请检查 terrain_analysis 日志", fpath)

                # 恢复后端 ROS2 节点，重新加入 DDS 网络
                try:
                    bridge = get_ros_nav_bridge()
                    if bridge is not None:
                        bridge.resume()
                        mapping_logger.info("后端 ROS2 导航节点已恢复")
                except Exception as exc:
                    mapping_logger.warning("恢复 ROS2 导航节点失败：{}", exc)

            threading.Thread(target=_wait_and_verify, daemon=True).start()

            return {
                "success": True,
                "enabled": False,
                "running": False,
                "scene_name": scene_name,
                "map_dir": map_dir,
                "pid": pid,
                "message": "建图进程已停止",
            }


_mapping_service = MappingService()


def get_mapping_service() -> MappingService:
    return _mapping_service
