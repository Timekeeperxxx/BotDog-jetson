from __future__ import annotations

from backend.follow_decision_engine import FollowDecisionEngine


def test_area_threshold_sends_stop_before_turning() -> None:
    engine = FollowDecisionEngine(
        yaw_deadband_px=40,
        forward_area_ratio=0.30,
        command_interval_ms=0,
    )

    decision = engine.decide((0, 0, 640, 480), image_width=1280, image_height=720)
    assert decision.should_send is True
    assert decision.command == "stop"

    decision = engine.decide((0, 0, 640, 480), image_width=1280, image_height=720)
    assert decision.should_send is True
    assert decision.command == "left"


def test_area_threshold_keeps_stop_when_centered() -> None:
    engine = FollowDecisionEngine(
        yaw_deadband_px=40,
        forward_area_ratio=0.30,
        command_interval_ms=0,
    )

    decision = engine.decide((320, 0, 960, 480), image_width=1280, image_height=720)
    assert decision.should_send is True
    assert decision.command == "stop"

    decision = engine.decide((320, 0, 960, 480), image_width=1280, image_height=720)
    assert decision.should_send is True
    assert decision.command == "stop"


def test_small_target_turns_or_moves_forward() -> None:
    engine = FollowDecisionEngine(
        yaw_deadband_px=40,
        forward_area_ratio=0.30,
        command_interval_ms=0,
    )

    decision = engine.decide((100, 100, 300, 400), image_width=1280, image_height=720)
    assert decision.should_send is True
    assert decision.command == "left"

    decision = engine.decide((540, 100, 740, 400), image_width=1280, image_height=720)
    assert decision.should_send is True
    assert decision.command == "forward"


def test_target_backing_away_resumes_following_after_hysteresis() -> None:
    engine = FollowDecisionEngine(
        yaw_deadband_px=40,
        forward_area_ratio=0.30,
        command_interval_ms=0,
    )

    decision = engine.decide((320, 0, 960, 480), image_width=1280, image_height=720)
    assert decision.command == "stop"

    decision = engine.decide((400, 0, 880, 540), image_width=1280, image_height=720)
    assert decision.command == "stop"

    decision = engine.decide((440, 100, 840, 700), image_width=1280, image_height=720)
    assert decision.command == "stop"

    decision = engine.decide((540, 100, 740, 400), image_width=1280, image_height=720)
    assert decision.command == "forward"


def test_camera_heading_turns_before_forward_even_when_target_is_centered() -> None:
    engine = FollowDecisionEngine(
        yaw_deadband_px=40,
        forward_area_ratio=0.30,
        command_interval_ms=0,
    )

    decision = engine.decide(
        (540, 100, 740, 400),
        image_width=1280,
        image_height=720,
        heading_error_deg=25.0,
        heading_deadband_deg=5.0,
    )

    assert decision.command == "right"
    assert decision.heading_error_deg == 25.0
    assert "目标相对机身方位" in decision.reason


def test_camera_heading_allows_forward_only_inside_angular_deadband() -> None:
    engine = FollowDecisionEngine(
        yaw_deadband_px=40,
        forward_area_ratio=0.30,
        command_interval_ms=0,
    )

    decision = engine.decide(
        (540, 100, 740, 400),
        image_width=1280,
        image_height=720,
        heading_error_deg=-3.0,
        heading_deadband_deg=5.0,
    )

    assert decision.command == "forward"
    assert "机身已对准目标" in decision.reason
