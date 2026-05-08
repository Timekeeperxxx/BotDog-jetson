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


mapping_logger = get_logger("建图服务")

MAPS_ROOT = Path("/home/jetson/Project/BOTDOG/MAPS")
START_MAPPING_SCRIPT = Path("/home/jetson/Project/BOTDOG/BotDog/scripts/start_mapping.sh")
SCENE_DIR_PATTERN = re.compile(r"^Scene(\d+)_")


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
                "停止建图进程组：scene_name={}，pid={}，map_dir={}",
                scene_name,
                pid,
                map_dir,
            )

            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except ProcessLookupError:
                mapping_logger.warning("建图进程已不存在：pid={}", pid)
            except Exception as exc:
                mapping_logger.warning("发送建图进程终止信号失败：pid={}，原因={}", pid, exc)

            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                mapping_logger.warning("建图进程组未能及时退出，准备强制终止：pid={}", pid)
                try:
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=8)

            self._session = None
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
