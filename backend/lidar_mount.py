"""雷达安装标定参数的运行时传递。"""

from __future__ import annotations

import os
from math import isfinite
from typing import Mapping

from .config import settings


_SETTING_TO_ENV = {
    "NAV_LIDAR_MOUNT_X_M": "NAV_LIDAR_MOUNT_X_M",
    "NAV_LIDAR_MOUNT_Y_M": "NAV_LIDAR_MOUNT_Y_M",
    "NAV_LIDAR_MOUNT_Z_M": "NAV_LIDAR_MOUNT_Z_M",
    "NAV_LIDAR_MOUNT_ROLL_DEG": "NAV_LIDAR_MOUNT_ROLL_DEG",
    "NAV_LIDAR_MOUNT_PITCH_DEG": "NAV_LIDAR_MOUNT_PITCH_DEG",
    "NAV_LIDAR_MOUNT_YAW_DEG": "NAV_LIDAR_MOUNT_YAW_DEG",
}


def lidar_mount_values() -> dict[str, float]:
    """读取并校验当前安装标定；异常值不得传入 ROS。"""
    values = {
        setting_name: float(getattr(settings, setting_name))
        for setting_name in _SETTING_TO_ENV
    }
    invalid = [name for name, value in values.items() if not isfinite(value)]
    if invalid:
        raise ValueError(f"雷达安装标定包含非有限数值: {', '.join(invalid)}")

    for axis in ("NAV_LIDAR_MOUNT_X_M", "NAV_LIDAR_MOUNT_Y_M"):
        if not -5.0 <= values[axis] <= 5.0:
            raise ValueError(f"{axis} 必须在 [-5, 5] m 内")
    if not 0.0 <= values["NAV_LIDAR_MOUNT_Z_M"] <= 5.0:
        raise ValueError("NAV_LIDAR_MOUNT_Z_M 必须在 [0, 5] m 内")
    for axis in (
        "NAV_LIDAR_MOUNT_ROLL_DEG",
        "NAV_LIDAR_MOUNT_PITCH_DEG",
        "NAV_LIDAR_MOUNT_YAW_DEG",
    ):
        if not -180.0 <= values[axis] <= 180.0:
            raise ValueError(f"{axis} 必须在 [-180, 180] deg 内")
    return values


def lidar_mount_environment(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """生成启动 ROS 子进程用的环境，保留调用方已有环境变量。"""
    env = dict(os.environ if base is None else base)
    values = lidar_mount_values()
    for setting_name, env_name in _SETTING_TO_ENV.items():
        # ROS2 launch 会从命令行文本推断参数类型。0.0 若被格式化成 "0"，
        # 会被推断为 integer，随后无法写入 C++ 中声明为 double 的参数。
        # 对所有标定值保留明确的浮点表示，避免零值再次触发类型崩溃。
        text = format(values[setting_name], ".12g")
        if "." not in text and "e" not in text.lower():
            text += ".0"
        env[env_name] = text
    return env


def lidar_mount_log_values() -> dict[str, float]:
    """返回适合结构化日志输出的短键标定值。"""
    values = lidar_mount_values()
    return {
        "x_m": values["NAV_LIDAR_MOUNT_X_M"],
        "y_m": values["NAV_LIDAR_MOUNT_Y_M"],
        "z_m": values["NAV_LIDAR_MOUNT_Z_M"],
        "roll_deg": values["NAV_LIDAR_MOUNT_ROLL_DEG"],
        "pitch_deg": values["NAV_LIDAR_MOUNT_PITCH_DEG"],
        "yaw_deg": values["NAV_LIDAR_MOUNT_YAW_DEG"],
    }
