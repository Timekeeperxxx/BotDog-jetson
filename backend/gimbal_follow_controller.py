"""云台视线与机器狗机身协同跟踪的纯计算部分。"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class GimbalGuidance:
    """一帧图像对应的云台修正量和目标相对机身方位。"""

    pixel_error_x: float
    pixel_bearing_deg: float
    body_heading_error_deg: float
    target_gimbal_yaw_deg: float
    should_adjust_gimbal: bool


def effective_horizontal_fov_deg(base_fov_deg: float, zoom_ratio: float) -> float:
    """按等效焦距计算变焦后的水平视场角。"""
    base_fov_deg = max(10.0, min(170.0, float(base_fov_deg)))
    zoom_ratio = max(1.0, float(zoom_ratio))
    half_fov_rad = math.radians(base_fov_deg) / 2.0
    return math.degrees(2.0 * math.atan(math.tan(half_fov_rad) / zoom_ratio))


def calculate_gimbal_guidance(
    *,
    bbox: tuple[int, int, int, int],
    image_width: int,
    camera_yaw_deg: float,
    zoom_ratio: float | None,
    horizontal_fov_deg: float,
    servo_gain: float,
    pixel_deadband_px: int,
    yaw_limit_deg: float = 160.0,
) -> GimbalGuidance:
    """将画面偏差换算成光轴角误差以及目标相对机身的方位。

    Z2-Mini 的相对 yaw 正值表示镜头朝机器狗右侧。图像目标位于右侧时，
    像素角误差同样为正，因此两者可直接相加得到目标相对机身方位。
    """
    if image_width <= 0:
        raise ValueError("image_width 必须大于 0")

    x1, _, x2, _ = bbox
    target_center_x = (x1 + x2) / 2.0
    image_center_x = image_width / 2.0
    pixel_error_x = target_center_x - image_center_x
    normalized_x = (2.0 * pixel_error_x) / image_width

    effective_fov = effective_horizontal_fov_deg(
        horizontal_fov_deg,
        zoom_ratio or 1.0,
    )
    pixel_bearing_deg = math.degrees(
        math.atan(normalized_x * math.tan(math.radians(effective_fov) / 2.0))
    )
    body_heading_error_deg = camera_yaw_deg + pixel_bearing_deg

    servo_gain = max(0.0, min(1.5, float(servo_gain)))
    yaw_limit_deg = max(1.0, min(170.0, float(yaw_limit_deg)))
    target_gimbal_yaw_deg = max(
        -yaw_limit_deg,
        min(yaw_limit_deg, camera_yaw_deg + pixel_bearing_deg * servo_gain),
    )

    return GimbalGuidance(
        pixel_error_x=round(pixel_error_x, 2),
        pixel_bearing_deg=round(pixel_bearing_deg, 3),
        body_heading_error_deg=round(body_heading_error_deg, 3),
        target_gimbal_yaw_deg=round(target_gimbal_yaw_deg, 3),
        should_adjust_gimbal=abs(pixel_error_x) > max(0, pixel_deadband_px),
    )
