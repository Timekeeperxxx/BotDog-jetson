from __future__ import annotations

import asyncio
import time
from typing import Any

from .logging_config import get_logger
from .tracking_types import ControlOwner

nav_track_logger = get_logger("导航跟踪联动")


class NavAutoTrackCoordinator:
    """Coordinates navigation pause/resume around automatic tracking."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._interrupted_task_id: str | None = None
        self._interrupted_target_name: str | None = None
        self._interrupted_target_waypoint_id: str | None = None
        self._interrupted_scene_id: str | None = None
        self._interrupted_scene_updated_at: str | None = None
        self._interrupted_at: float | None = None
        self._last_reason: str | None = None
        self._user_intervened = False
        self._resume_retry_task: asyncio.Task[None] | None = None
        self._resume_retry_reason: str | None = None

    def get_status(self) -> dict[str, Any]:
        return {
            "interrupted_task_id": self._interrupted_task_id,
            "interrupted_target_name": self._interrupted_target_name,
            "interrupted_target_waypoint_id": self._interrupted_target_waypoint_id,
            "interrupted_scene_id": self._interrupted_scene_id,
            "interrupted_scene_updated_at": self._interrupted_scene_updated_at,
            "interrupted_at": self._interrupted_at,
            "last_reason": self._last_reason,
            "user_intervened": self._user_intervened,
            "resume_retry_scheduled": self._resume_retry_task is not None and not self._resume_retry_task.done(),
            "resume_retry_reason": self._resume_retry_reason,
        }

    def is_navigation_context_active(self) -> bool:
        if self._interrupted_task_id:
            return True

        try:
            from .services_nav_state import get_nav_state

            nav_status = get_nav_state().get("navigation_status") or {}
        except Exception:
            return False

        status = str(nav_status.get("status") or "").strip().lower()
        task_id = str(nav_status.get("task_id") or "").strip()
        return bool(task_id and status in {"navigating", "paused"})

    async def pause_navigation_for_tracking(self, *, track_id: int) -> dict[str, Any]:
        async with self._lock:
            self._request_auto_track_control()
            if self._interrupted_task_id:
                return {"success": True, "already_paused": True, **self.get_status()}

            from .nav_bridge_state import get_ros_nav_bridge
            from .services_nav_state import clear_global_path, get_nav_state, update_navigation_status

            nav_status = get_nav_state().get("navigation_status") or {}
            status = str(nav_status.get("status") or "").strip().lower()
            task_id = str(nav_status.get("task_id") or "").strip()
            if not task_id or status != "navigating":
                return {
                    "success": False,
                    "skipped": True,
                    "reason": "navigation_not_running",
                    "navigation_status": nav_status,
                }

            bridge = get_ros_nav_bridge()
            if bridge is None:
                return {"success": False, "skipped": True, "reason": "ros_nav_bridge_unavailable"}

            nav_stop_result = bridge.publish_navigation_start(False)
            clear_global_path()
            scene_snapshot = self._current_scene_snapshot()

            self._interrupted_task_id = task_id
            self._interrupted_target_name = _optional_str(nav_status.get("target_name"))
            self._interrupted_target_waypoint_id = _optional_str(nav_status.get("target_waypoint_id"))
            self._interrupted_scene_id = scene_snapshot.get("scene_id")
            self._interrupted_scene_updated_at = scene_snapshot.get("updated_at")
            self._interrupted_at = time.time()
            self._last_reason = f"track_id={track_id}"
            self._user_intervened = False

            update_navigation_status(
                {
                    "status": "paused",
                    "target_waypoint_id": self._interrupted_target_waypoint_id,
                    "target_name": self._interrupted_target_name,
                    "task_id": self._interrupted_task_id,
                    "message": f"导航任务已暂停，正在自动跟踪陌生人 track_id={track_id}",
                    "source": "auto_track",
                    "ros_status": "auto_track_paused",
                }
            )
            nav_track_logger.info(
                "自动跟踪触发导航暂停：task_id={} track_id={} topic={}",
                self._interrupted_task_id,
                track_id,
                nav_stop_result.get("topic"),
            )
            return {
                "success": True,
                "already_paused": False,
                "nav_start": nav_stop_result,
                **self.get_status(),
            }

    async def resume_navigation_after_tracking(
        self,
        *,
        reason: str,
        apply_delay: bool = True,
    ) -> dict[str, Any]:
        async with self._lock:
            if not self._interrupted_task_id:
                self._release_auto_track_control()
                return {"success": True, "skipped": True, "reason": "no_interrupted_navigation"}

            from .config import settings

            resume_delay_s = max(0.0, float(settings.NAV_AUTO_TRACK_RESUME_TIMEOUT_S))
            if apply_delay and resume_delay_s > 0:
                task_id_for_log = self._interrupted_task_id
                nav_track_logger.info(
                    "自动跟踪结束，等待恢复确认窗口：task_id={} reason={} delay_s={}",
                    task_id_for_log,
                    reason,
                    resume_delay_s,
                )
                await asyncio.sleep(resume_delay_s)

            if not self._interrupted_task_id:
                self._release_auto_track_control()
                return {"success": True, "skipped": True, "reason": "interrupted_navigation_cleared"}
            if self._user_intervened:
                self._clear_interrupted_state(f"user_intervened:{reason}")
                self._release_auto_track_control()
                return {"success": True, "skipped": True, "reason": "user_intervened"}

            resume_blocker = self._resume_blocker()
            if resume_blocker is not None:
                if resume_blocker == "robot_pose_unavailable":
                    self._last_reason = resume_blocker
                    self._schedule_resume_retry_locked(reason=f"{reason}:{resume_blocker}")
                    self._release_auto_track_control()
                    nav_track_logger.warning(
                        "自动跟踪结束但暂时无法恢复导航，保留任务等待重试：task_id={} reason={}",
                        self._interrupted_task_id,
                        resume_blocker,
                    )
                    return {
                        "success": False,
                        "skipped": True,
                        "reason": resume_blocker,
                        "retry_scheduled": True,
                        **self.get_status(),
                    }
                self._clear_interrupted_state(resume_blocker)
                self._release_auto_track_control()
                return {"success": False, "skipped": True, "reason": resume_blocker}

            task_id = self._interrupted_task_id
            target_name = self._interrupted_target_name
            target_waypoint_id = self._interrupted_target_waypoint_id

            from .nav_bridge_state import get_ros_nav_bridge
            from .services_nav_state import update_navigation_status

            bridge = get_ros_nav_bridge()
            if bridge is None:
                nav_track_logger.warning("自动跟踪结束但 ROS 导航桥不可用，无法恢复导航：task_id={}", task_id)
                return {"success": False, "reason": "ros_nav_bridge_unavailable", **self.get_status()}

            self._request_navigation_control()
            nav_start_result = bridge.publish_navigation_start(True)
            update_navigation_status(
                {
                    "status": "navigating",
                    "target_waypoint_id": target_waypoint_id,
                    "target_name": target_name,
                    "task_id": task_id,
                    "message": f"自动跟踪结束（{reason}），已基于当前 TF 恢复导航任务",
                    "source": "auto_track",
                    "ros_status": "auto_track_resumed",
                }
            )

            self._clear_interrupted_state(reason)
            nav_track_logger.info(
                "自动跟踪结束，导航已恢复：task_id={} reason={} topic={}",
                task_id,
                reason,
                nav_start_result.get("topic"),
            )
            return {
                "success": True,
                "skipped": False,
                "task_id": task_id,
                "nav_start": nav_start_result,
            }

    def cancel_pending_resume(self, reason: str) -> None:
        if not self._interrupted_task_id:
            self._last_reason = reason
            return
        self._user_intervened = True
        nav_track_logger.info(
            "取消自动跟踪后的导航恢复：task_id={} reason={}",
            self._interrupted_task_id,
            reason,
        )
        self._clear_interrupted_state(reason)

    def request_navigation_control(self) -> None:
        self._request_navigation_control()

    def release_navigation_control(self) -> None:
        try:
            from .control_arbiter import get_control_arbiter

            arbiter = get_control_arbiter()
            if arbiter is not None:
                arbiter.release_control(ControlOwner.NAVIGATION)
        except Exception as exc:
            nav_track_logger.debug("释放导航控制权失败：{}", exc)

    def _resume_blocker(self) -> str | None:
        try:
            from .config import settings
            from .services_nav_state import get_robot_pose

            if settings.NAV_AUTO_TRACK_REQUIRE_FRESH_TF and get_robot_pose() is None:
                return "robot_pose_unavailable"
        except Exception:
            return "robot_pose_unavailable"

        current_scene = self._current_scene_snapshot()
        if self._interrupted_scene_id and current_scene.get("scene_id") != self._interrupted_scene_id:
            return "scene_changed"
        if (
            self._interrupted_scene_updated_at
            and current_scene.get("updated_at")
            and current_scene.get("updated_at") != self._interrupted_scene_updated_at
        ):
            return "scene_changed"
        return None

    def _schedule_resume_retry_locked(self, *, reason: str) -> None:
        try:
            current_task = asyncio.current_task()
        except RuntimeError:
            current_task = None
        if (
            self._resume_retry_task is not None
            and not self._resume_retry_task.done()
            and self._resume_retry_task is not current_task
        ):
            return

        from .config import settings

        delay_s = max(1.0, min(3.0, float(settings.NAV_AUTO_TRACK_RESUME_TIMEOUT_S)))
        self._resume_retry_reason = reason
        self._resume_retry_task = asyncio.create_task(
            self._resume_retry_after_delay(reason=reason, delay_s=delay_s)
        )

    async def _resume_retry_after_delay(self, *, reason: str, delay_s: float) -> None:
        await asyncio.sleep(delay_s)
        try:
            await self.resume_navigation_after_tracking(reason=reason, apply_delay=False)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            nav_track_logger.warning("自动跟踪后导航恢复重试失败：reason={} error={}", reason, exc)

    def _cancel_resume_retry_locked(self) -> None:
        task = self._resume_retry_task
        if task is not None and not task.done():
            try:
                current_task = asyncio.current_task()
            except RuntimeError:
                current_task = None
            if task is not current_task:
                task.cancel()
        self._resume_retry_task = None
        self._resume_retry_reason = None

    def _current_scene_snapshot(self) -> dict[str, str | None]:
        try:
            from .services_nav_localization import load_current_scene

            scene = load_current_scene(strict=False)
            return {
                "scene_id": _optional_str(scene.get("scene_id")),
                "updated_at": _optional_str(scene.get("updated_at")),
            }
        except Exception:
            return {"scene_id": None, "updated_at": None}

    def _request_auto_track_control(self) -> None:
        try:
            from .control_arbiter import get_control_arbiter

            arbiter = get_control_arbiter()
            if arbiter is not None:
                arbiter.request_control(ControlOwner.AUTO_TRACK)
        except Exception as exc:
            nav_track_logger.debug("申请自动跟踪控制权失败：{}", exc)

    def _release_auto_track_control(self) -> None:
        try:
            from .control_arbiter import get_control_arbiter

            arbiter = get_control_arbiter()
            if arbiter is not None:
                arbiter.release_control(ControlOwner.AUTO_TRACK)
        except Exception as exc:
            nav_track_logger.debug("释放自动跟踪控制权失败：{}", exc)

    def _request_navigation_control(self) -> None:
        try:
            from .control_arbiter import get_control_arbiter

            arbiter = get_control_arbiter()
            if arbiter is not None:
                arbiter.release_control(ControlOwner.AUTO_TRACK)
                arbiter.request_control(ControlOwner.NAVIGATION)
        except Exception as exc:
            nav_track_logger.debug("申请导航控制权失败：{}", exc)

    def _clear_interrupted_state(self, reason: str) -> None:
        self._cancel_resume_retry_locked()
        self._interrupted_task_id = None
        self._interrupted_target_name = None
        self._interrupted_target_waypoint_id = None
        self._interrupted_scene_id = None
        self._interrupted_scene_updated_at = None
        self._interrupted_at = None
        self._last_reason = reason
        self._user_intervened = False


def _optional_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


_nav_auto_track_coordinator: NavAutoTrackCoordinator | None = None


def get_nav_auto_track_coordinator() -> NavAutoTrackCoordinator | None:
    return _nav_auto_track_coordinator


def set_nav_auto_track_coordinator(coordinator: NavAutoTrackCoordinator) -> None:
    global _nav_auto_track_coordinator
    _nav_auto_track_coordinator = coordinator
