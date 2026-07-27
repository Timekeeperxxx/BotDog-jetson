from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .logging_config import get_logger
from .services_radar_health import (
    _list_topics,
    _select_radar_topic,
    _start_livox_driver,
    _stop_livox_driver,
    _wait_for_radar_topic,
)


recording_logger = get_logger("雷达录包")

NAVIGATION_ROOT = Path("/home/jetson/Projects/Navigation")
RECORD_SCRIPT = NAVIGATION_ROOT / "adapters/legacy_scripts/record_mapping_sensors.sh"
ROSBAG_ROOT = Path("/home/jetson/Projects/Bags")
LOG_ROOT = Path("/home/jetson/Projects/BotDog/logs")
ROSBAG_STOP_TIMEOUT_SECONDS = 30


class RosbagRecordingError(RuntimeError):
    pass


@dataclass(slots=True)
class RosbagSession:
    process: subprocess.Popen[Any]
    output_dir: Path
    log_path: Path
    started_at: float
    lidar_mode: str
    mapping_active_at_start: bool
    owned_lidar_process: subprocess.Popen[Any] | None = None


class RosbagRecordingService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._session: RosbagSession | None = None
        self._last_result: dict[str, Any] | None = None

    @staticmethod
    def _result(
        *,
        running: bool,
        message: str,
        session: RosbagSession | None = None,
        saved: bool | None = None,
    ) -> dict[str, Any]:
        return {
            "success": True,
            "enabled": running,
            "running": running,
            "pid": session.process.pid if session and running else None,
            "output_dir": str(session.output_dir) if session else None,
            "log_path": str(session.log_path) if session else None,
            "started_at": session.started_at if session else None,
            "lidar_mode": session.lidar_mode if session else None,
            "mapping_active_at_start": session.mapping_active_at_start if session else False,
            "saved": saved,
            "message": message,
        }

    @staticmethod
    def _existing_lidar_topic() -> tuple[str | None, str | None]:
        result, topics = _list_topics()
        if result.returncode != 0:
            return None, None
        return _select_radar_topic(topics)

    @staticmethod
    def _next_output_dir() -> Path:
        ROSBAG_ROOT.mkdir(parents=True, exist_ok=True)
        base = datetime.now().strftime("rosbag_%Y%m%d_%H%M%S")
        candidate = ROSBAG_ROOT / base
        suffix = 1
        while candidate.exists():
            candidate = ROSBAG_ROOT / f"{base}_{suffix}"
            suffix += 1
        return candidate

    @staticmethod
    def _stop_process_group(process: subprocess.Popen[Any]) -> None:
        if process.poll() is not None:
            return
        try:
            pgid = os.getpgid(process.pid)
        except ProcessLookupError:
            return

        for sig, timeout in (
            (signal.SIGINT, ROSBAG_STOP_TIMEOUT_SECONDS),
            (signal.SIGTERM, 5),
            (signal.SIGKILL, None),
        ):
            try:
                os.killpg(pgid, sig)
            except ProcessLookupError:
                return
            if timeout is None:
                return
            try:
                process.wait(timeout=timeout)
                return
            except subprocess.TimeoutExpired:
                continue

    def _release_owned_lidar(self, session: RosbagSession) -> None:
        if session.owned_lidar_process is None:
            return
        try:
            _stop_livox_driver(session.owned_lidar_process)
        finally:
            session.owned_lidar_process = None

    def _refresh_unlocked(self) -> None:
        session = self._session
        if session is None or session.process.poll() is None:
            return
        self._release_owned_lidar(session)
        saved = (session.output_dir / "metadata.yaml").is_file()
        self._last_result = self._result(
            running=False,
            session=session,
            saved=saved,
            message=(
                f"录包进程已结束，数据已保存：{session.output_dir}"
                if saved
                else f"录包进程异常退出，请查看日志：{session.log_path}"
            ),
        )
        self._session = None

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            self._refresh_unlocked()
            if self._session is not None:
                return self._result(
                    running=True,
                    session=self._session,
                    message=(
                        "正在录包，复用建图雷达驱动"
                        if self._session.lidar_mode == "mapping"
                        else "正在录包，复用现有雷达驱动"
                        if self._session.lidar_mode == "existing"
                        else "正在录包，使用录包服务启动的雷达驱动"
                    ),
                )
            if self._last_result is not None:
                return dict(self._last_result)
            return self._result(running=False, message="当前未录包")

    def start(self, *, mapping_active: bool) -> dict[str, Any]:
        with self._lock:
            self._refresh_unlocked()
            if self._session is not None:
                return self.get_status()
            if not RECORD_SCRIPT.is_file():
                raise RosbagRecordingError(f"录包脚本不存在：{RECORD_SCRIPT}")

            owned_lidar_process: subprocess.Popen[Any] | None = None
            topic, _ = self._existing_lidar_topic()
            if mapping_active:
                if topic is None:
                    _, topic, _ = _wait_for_radar_topic(5.0)
                if topic is None:
                    raise RosbagRecordingError("建图状态下未发现 /livox/lidar，录包未启动")
                lidar_mode = "mapping"
            elif topic is not None:
                lidar_mode = "existing"
            else:
                owned_lidar_process, start_error = _start_livox_driver()
                if owned_lidar_process is None:
                    raise RosbagRecordingError(start_error or "启动 Livox 雷达驱动失败")
                _, topic, _ = _wait_for_radar_topic(18.0)
                if topic is None:
                    _stop_livox_driver(owned_lidar_process)
                    raise RosbagRecordingError("启动雷达驱动后仍未发现 /livox/lidar，录包未启动")
                lidar_mode = "owned"

            output_dir = self._next_output_dir()
            LOG_ROOT.mkdir(parents=True, exist_ok=True)
            log_path = LOG_ROOT / f"rosbag_recording_{output_dir.name}.log"
            env = os.environ.copy()
            env.update(
                {
                    "NAV_ENV_FILE": "/dev/null",
                    "ROBOT_NAV_WS": str(NAVIGATION_ROOT),
                    "ROBOT_NAV_LOG_ROOT": str(LOG_ROOT),
                    "ROBOT_NAV_RUNTIME_ROOT": "/home/jetson/Projects/Navigation/runtime",
                }
            )

            try:
                log_file = log_path.open("a", encoding="utf-8")
                process = subprocess.Popen(
                    ["bash", str(RECORD_SCRIPT), str(output_dir)],
                    cwd=str(NAVIGATION_ROOT),
                    env=env,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    text=True,
                )
                log_file.close()
            except Exception as exc:
                if owned_lidar_process is not None:
                    _stop_livox_driver(owned_lidar_process)
                raise RosbagRecordingError(f"启动录包进程失败：{exc}") from exc

            time.sleep(1.0)
            if process.poll() is not None:
                if owned_lidar_process is not None:
                    _stop_livox_driver(owned_lidar_process)
                raise RosbagRecordingError(f"录包进程启动后立即退出，请查看日志：{log_path}")

            session = RosbagSession(
                process=process,
                output_dir=output_dir,
                log_path=log_path,
                started_at=time.time(),
                lidar_mode=lidar_mode,
                mapping_active_at_start=mapping_active,
                owned_lidar_process=owned_lidar_process,
            )
            self._session = session
            self._last_result = None
            recording_logger.info(
                "录包已启动：pid={} output_dir={} lidar_mode={} mapping_active={}",
                process.pid,
                output_dir,
                lidar_mode,
                mapping_active,
            )
            return self._result(
                running=True,
                session=session,
                message=(
                    f"录包已启动，复用建图雷达驱动：{output_dir}"
                    if lidar_mode == "mapping"
                    else f"录包已启动：{output_dir}"
                ),
            )

    def stop(self, *, reason: str = "user") -> dict[str, Any]:
        with self._lock:
            self._refresh_unlocked()
            session = self._session
            if session is None:
                return self.get_status()

            # rosbag2 必须先收到 SIGINT 并写完 metadata.yaml，之后才能停止
            # 由录包服务拥有的雷达驱动。建图拥有的驱动不会在这里停止。
            self._stop_process_group(session.process)
            self._release_owned_lidar(session)
            saved = (session.output_dir / "metadata.yaml").is_file()
            message = (
                f"录包已停止并保存：{session.output_dir}"
                if saved
                else f"录包已停止，但未发现 metadata.yaml，请查看日志：{session.log_path}"
            )
            recording_logger.info(
                "录包已停止：reason={} output_dir={} saved={} lidar_mode={}",
                reason,
                session.output_dir,
                saved,
                session.lidar_mode,
            )
            result = self._result(running=False, session=session, saved=saved, message=message)
            self._session = None
            self._last_result = result
            return dict(result)

    def stop_before_mapping_transition(self, *, reason: str) -> dict[str, Any] | None:
        with self._lock:
            self._refresh_unlocked()
            if self._session is None:
                return None
        return self.stop(reason=reason)


_service = RosbagRecordingService()


def get_rosbag_recording_service() -> RosbagRecordingService:
    return _service
