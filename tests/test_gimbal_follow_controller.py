from __future__ import annotations

import pytest

from backend.gimbal_follow_controller import (
    calculate_gimbal_guidance,
    effective_horizontal_fov_deg,
)


def test_centered_target_bearing_equals_camera_yaw() -> None:
    guidance = calculate_gimbal_guidance(
        bbox=(220, 80, 420, 460),
        image_width=640,
        camera_yaw_deg=28.0,
        zoom_ratio=1.0,
        horizontal_fov_deg=60.0,
        servo_gain=0.75,
        pixel_deadband_px=20,
    )

    assert guidance.pixel_bearing_deg == pytest.approx(0.0)
    assert guidance.body_heading_error_deg == pytest.approx(28.0)
    assert guidance.should_adjust_gimbal is False


def test_target_on_right_moves_gimbal_and_body_bearing_right() -> None:
    guidance = calculate_gimbal_guidance(
        bbox=(360, 80, 560, 460),
        image_width=640,
        camera_yaw_deg=10.0,
        zoom_ratio=1.0,
        horizontal_fov_deg=60.0,
        servo_gain=0.75,
        pixel_deadband_px=20,
    )

    assert guidance.pixel_error_x > 0
    assert guidance.pixel_bearing_deg > 0
    assert guidance.body_heading_error_deg > 10.0
    assert guidance.target_gimbal_yaw_deg > 10.0
    assert guidance.should_adjust_gimbal is True


def test_zoom_reduces_angle_represented_by_same_pixel_error() -> None:
    one_x = calculate_gimbal_guidance(
        bbox=(360, 80, 560, 460),
        image_width=640,
        camera_yaw_deg=0.0,
        zoom_ratio=1.0,
        horizontal_fov_deg=60.0,
        servo_gain=1.0,
        pixel_deadband_px=0,
    )
    four_x = calculate_gimbal_guidance(
        bbox=(360, 80, 560, 460),
        image_width=640,
        camera_yaw_deg=0.0,
        zoom_ratio=4.0,
        horizontal_fov_deg=60.0,
        servo_gain=1.0,
        pixel_deadband_px=0,
    )

    assert effective_horizontal_fov_deg(60.0, 4.0) < 60.0
    assert abs(four_x.pixel_bearing_deg) < abs(one_x.pixel_bearing_deg)


def test_gimbal_target_is_limited_before_mechanical_stop() -> None:
    guidance = calculate_gimbal_guidance(
        bbox=(540, 80, 640, 460),
        image_width=640,
        camera_yaw_deg=159.0,
        zoom_ratio=1.0,
        horizontal_fov_deg=60.0,
        servo_gain=1.0,
        pixel_deadband_px=0,
    )

    assert guidance.target_gimbal_yaw_deg == 160.0
