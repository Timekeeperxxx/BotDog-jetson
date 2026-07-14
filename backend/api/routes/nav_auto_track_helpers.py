from __future__ import annotations

from typing import Any

from ...config import settings


def _get_nav_auto_track_coordinator():
    from ...nav_auto_track_coordinator import get_nav_auto_track_coordinator

    return get_nav_auto_track_coordinator()


def cancel_pending_auto_track_resume(reason: str) -> None:
    coordinator = _get_nav_auto_track_coordinator()
    if coordinator is not None:
        coordinator.cancel_pending_resume(reason)


def request_navigation_control() -> None:
    from ...control_arbiter import get_control_arbiter

    arbiter = get_control_arbiter()
    if arbiter is not None:
        # An explicit navigation request ends a previous web/remote override.
        arbiter.release_manual_override()

    coordinator = _get_nav_auto_track_coordinator()
    if coordinator is not None:
        coordinator.request_navigation_control()

    if arbiter is not None and not arbiter.can_navigation_send():
        owner = arbiter.owner.value
        raise RuntimeError(f"导航无法取得底盘控制权，当前 owner={owner}")


def release_navigation_control() -> None:
    coordinator = _get_nav_auto_track_coordinator()
    if coordinator is not None:
        coordinator.release_navigation_control()


def task_auto_track_requested(task: dict[str, Any]) -> bool:
    value = task.get("autoTrackEnabled")
    if value is not None:
        return bool(value)
    return bool(settings.NAV_AUTO_TRACK_DURING_NAV_ENABLED and settings.NAV_AUTO_TRACK_AUTO_ENABLE)


def ensure_auto_track_enabled_for_navigation(task: dict[str, Any]) -> dict[str, Any]:
    if not task_auto_track_requested(task):
        return {
            "requested": False,
            "enabled": False,
            "state": None,
            "message": "导航跟踪联动未开启",
        }

    from ...auto_track_service import get_auto_track_service
    from ...control_arbiter import get_control_arbiter
    from ...guard_mission_service import get_guard_mission_service

    arbiter = get_control_arbiter()
    if arbiter is not None:
        arbiter.release_manual_override()

    guard_mission = get_guard_mission_service()
    if guard_mission is not None and guard_mission.enabled:
        guard_mission.enabled = False

    auto_track = get_auto_track_service()
    if auto_track is None:
        return {
            "requested": True,
            "enabled": False,
            "state": None,
            "message": "自动跟踪服务未初始化",
        }

    if hasattr(auto_track, "enable_for_navigation"):
        auto_track.enable_for_navigation()
    else:
        auto_track.enable()
    if hasattr(auto_track, "resume"):
        auto_track.resume()

    status = auto_track.get_status()
    return {
        "requested": True,
        "enabled": bool(status.get("enabled")),
        "state": status.get("state"),
        "message": "导航跟踪联动已启用，AI 检测将随任务启动",
    }
