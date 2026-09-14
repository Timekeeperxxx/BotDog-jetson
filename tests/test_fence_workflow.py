from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from backend import fence_detection_service
from backend.config import settings
from backend.services_nav_tasks import NavTaskError, _validate_task_step_payload
from backend.services_nav_task_runtime import _materialize_step
from backend.services_ros_nav import RosNavBridge


@pytest.mark.asyncio
async def test_fence_workflow_validation_and_runtime(monkeypatch):
    service = SimpleNamespace(
        enable=AsyncMock(return_value={"state": "finding"}),
        disable=AsyncMock(return_value={"state": "disabled"}),
    )
    monkeypatch.setattr(fence_detection_service, "get_fence_detection_service", lambda: service)
    monkeypatch.setattr(settings, "AI_ENABLED", True)
    monkeypatch.setattr(settings, "POSE_ENABLED", True)
    bridge = SimpleNamespace(_submit_broadcast=Mock(), _submit_alert=Mock())
    for enabled in (True, False):
        step = {"type": "fence_detection_control", "enabled": enabled}
        _validate_task_step_payload(step)
        assert _materialize_step("scene", step) == step
        await RosNavBridge._apply_fence_detection_workflow_control(bridge, step)
    service.enable.assert_awaited_once()
    service.disable.assert_awaited_once_with(center_gimbal=True)
    assert bridge._submit_broadcast.call_count == 2
    bridge._submit_alert.assert_not_called()
    for value in ("false", 1, None):
        with pytest.raises(NavTaskError):
            _validate_task_step_payload({"type": "fence_detection_control", "enabled": value})
    monkeypatch.setattr(settings, "POSE_ENABLED", False)
    await RosNavBridge._apply_fence_detection_workflow_control(
        bridge, {"type": "fence_detection_control", "enabled": True},
    )
    assert service.enable.await_count == 1
    bridge._submit_alert.assert_called_once()
