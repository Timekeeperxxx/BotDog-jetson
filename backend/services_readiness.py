"""Operational readiness uses live authoritative state, never startup snapshots."""
from __future__ import annotations

from .config import settings
from .control_service import get_control_service
from .schemas import utc_now_iso
from .services_nav_state import get_nav_freshness
from .state_machine import SystemState
from .state_machine_state import get_state_machine


def collect_readiness(ai_worker) -> dict:
    state_machine = get_state_machine()
    service = get_control_service()
    connected = state_machine is not None and state_machine.is_connected
    adapter_ready = service is not None and service.get_adapter_status()["ready"]
    latched = state_machine is not None and state_machine.state == SystemState.E_STOP_TRIGGERED
    control_ready = connected and adapter_ready and not latched
    if latched:
        control_message, control_status = "急停已锁定，禁止运动", "blocked"
    elif not connected:
        control_message, control_status = "未收到有效机器人遥测，等待设备接入", "waiting"
    elif not adapter_ready:
        control_message, control_status = "机器人控制适配器不可用", "failed"
    else:
        control_message, control_status = "控制适配器与机器人遥测均在线", "ready"
    components = {
        "control": {"ready": control_ready, "required": True, "status": control_status,
                    "message": control_message,
                    "heartbeat_age_s": state_machine.heartbeat_age_s if state_machine is not None else None},
    }
    if not settings.AI_ENABLED:
        components["video_ai"] = {"ready": False, "required": False, "status": "disabled", "message": "AI 视频分析已关闭"}
    elif ai_worker is None:
        components["video_ai"] = {"ready": False, "required": True, "status": "waiting", "message": "AI Worker 尚未就绪"}
    else:
        components["video_ai"] = ai_worker.get_runtime_status()
    if settings.ROS_NAV_ENABLED:
        components["navigation"] = get_nav_freshness()
    else:
        components["navigation"] = {"ready": False, "required": False, "status": "disabled", "message": "ROS 导航已关闭"}
    required = [item for item in components.values() if item["required"]]
    ready = all(item["ready"] for item in required)
    degraded = any(item["status"] in {"failed", "blocked", "degraded"} for item in required)
    return {"ready": ready, "status": "ready" if ready else ("degraded" if degraded else "standby"),
            "checked_at": utc_now_iso(), "components": components,
            "reasons": [item["message"] for item in required if not item["ready"]]}
