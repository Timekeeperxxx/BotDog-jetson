from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from backend import workers_ai
from backend.fence_detection_service import FenceDetectionState
from backend.pose_detection import PoseEventEngine, PoseKeypoint, RawPose
from test_workers_ai_timeout import _FastDetector, _worker


def _upper_body_motion(index: int) -> RawPose:
    points = [PoseKeypoint(0.0, 0.0, 0.0) for _ in range(17)]
    points[5] = PoseKeypoint(140.0, 80.0, 0.95)
    points[6] = PoseKeypoint(180.0, 80.0, 0.95)
    points[9] = PoseKeypoint(130.0 + 18.0 * (index % 2), 100.0, 0.95)
    points[10] = PoseKeypoint(190.0, 100.0, 0.95)
    # 下半身全部不可见，框底在上半身；行为判断不需要脚下地图位置。
    return RawPose((110, 40, 220, 130), 0.95, tuple(points))


@pytest.mark.asyncio
@pytest.mark.parametrize("observation_state", [
    FenceDetectionState.FINDING,
    FenceDetectionState.GIMBAL_MOVING,
    FenceDetectionState.DETECTING,
    FenceDetectionState.TRACKING,
    FenceDetectionState.NOT_FOUND,
    FenceDetectionState.OUT_OF_RANGE,
    FenceDetectionState.LOCALIZATION_UNAVAILABLE,
    FenceDetectionState.CALIBRATION_UNAVAILABLE,
])
async def test_upper_body_action_alert_without_map_distance_or_observation_ready(
    tmp_path, monkeypatch, observation_state,
):
    worker = _worker(tmp_path, monkeypatch)
    worker._detector = _FastDetector()
    worker._pose_detector = object()
    worker._pose_event_engine = PoseEventEngine()
    monkeypatch.setattr(workers_ai.settings, "POSE_FRAME_SKIP", 1)
    monkeypatch.setattr(worker, "_is_weapon_due", lambda *args, **kwargs: False)
    monkeypatch.setattr(worker, "_broadcast_pose_overlay", AsyncMock())
    monkeypatch.setattr(worker, "_process_detection", AsyncMock())
    monkeypatch.setattr(worker, "_report_face_service_fault", AsyncMock())
    monkeypatch.setattr(worker, "_process_pose_events", AsyncMock())
    # 如果旧投影通道再次接入，此测试会失败，而不是让默认空结果掩盖问题。
    legacy_projection = Mock(side_effect=AssertionError("不得调用人员围栏投影"))
    fence = SimpleNamespace(
        enabled=True,
        tracking_override=observation_state is FenceDetectionState.TRACKING,
        state=observation_state,
        process_frame=legacy_projection,
        target_fence_id=None,
    )
    monkeypatch.setattr(
        "backend.fence_detection_service.get_fence_detection_service", lambda: fence,
    )
    for index in range(7):
        now = 100.0 + index * 0.2
        monkeypatch.setattr(worker, "_infer_pose", AsyncMock(
            return_value=([_upper_body_motion(index)], now, 0.1),
        ))
        await worker._detect_and_process_frame(b"frame", index + 1, frame_read_at=now)
    emitted = [
        event.event_type
        for call in worker._process_pose_events.call_args_list
        for event in call.args[0]
    ]
    assert emitted == ["POSE_DAMAGE_SUSPECTED"]
    legacy_projection.assert_not_called()


@pytest.mark.asyncio
async def test_behavior_switch_off_suppresses_actions_even_with_upper_body_motion(
    tmp_path, monkeypatch,
):
    worker = _worker(tmp_path, monkeypatch)
    worker._detector = _FastDetector()
    worker._pose_detector = object()
    worker._pose_event_engine = PoseEventEngine()
    monkeypatch.setattr(workers_ai.settings, "POSE_FRAME_SKIP", 1)
    monkeypatch.setattr(worker, "_is_weapon_due", lambda *args, **kwargs: False)
    for name in ("_broadcast_pose_overlay", "_process_detection", "_report_face_service_fault", "_process_pose_events"):
        monkeypatch.setattr(worker, name, AsyncMock())
    fence = SimpleNamespace(enabled=False, tracking_override=False)
    monkeypatch.setattr(
        "backend.fence_detection_service.get_fence_detection_service", lambda: fence,
    )
    for index in range(7):
        now = 100.0 + index * 0.2
        monkeypatch.setattr(worker, "_infer_pose", AsyncMock(
            return_value=([_upper_body_motion(index)], now, 0.1),
        ))
        await worker._detect_and_process_frame(b"frame", index + 1, frame_read_at=now)
    assert all(call.args[0] == [] for call in worker._process_pose_events.call_args_list)
    assert worker._pose_event_engine.active_actions == set()
