from __future__ import annotations

import math

import pytest

from backend.config import settings
from backend.lidar_mount import (
    base_pose_to_lidar_initial_position,
    lidar_mount_environment,
    lidar_mount_values,
)


def test_lidar_mount_environment_exports_all_calibration_values(monkeypatch) -> None:
    monkeypatch.setattr(settings, "NAV_LIDAR_MOUNT_X_M", 0.12)
    monkeypatch.setattr(settings, "NAV_LIDAR_MOUNT_Y_M", -0.03)
    monkeypatch.setattr(settings, "NAV_LIDAR_MOUNT_Z_M", 0.91)
    monkeypatch.setattr(settings, "NAV_LIDAR_MOUNT_ROLL_DEG", 1.5)
    monkeypatch.setattr(settings, "NAV_LIDAR_MOUNT_PITCH_DEG", 19.48)
    monkeypatch.setattr(settings, "NAV_LIDAR_MOUNT_YAW_DEG", -2.0)

    env = lidar_mount_environment({"PATH": "/test/bin"})

    assert env == {
        "PATH": "/test/bin",
        "NAV_LIDAR_MOUNT_X_M": "0.12",
        "NAV_LIDAR_MOUNT_Y_M": "-0.03",
        "NAV_LIDAR_MOUNT_Z_M": "0.91",
        "NAV_LIDAR_MOUNT_ROLL_DEG": "1.5",
        "NAV_LIDAR_MOUNT_PITCH_DEG": "19.48",
        "NAV_LIDAR_MOUNT_YAW_DEG": "-2.0",
    }


def test_base_pose_to_lidar_initial_position_adds_mount_height(monkeypatch) -> None:
    monkeypatch.setattr(settings, "NAV_LIDAR_MOUNT_X_M", 0.0)
    monkeypatch.setattr(settings, "NAV_LIDAR_MOUNT_Y_M", 0.0)
    monkeypatch.setattr(settings, "NAV_LIDAR_MOUNT_Z_M", 0.9)

    position = base_pose_to_lidar_initial_position(
        x=-4.25,
        y=0.69,
        z=0.076,
        yaw=2.08,
    )

    assert position == pytest.approx((-4.25, 0.69, 0.976))


def test_base_pose_to_lidar_initial_position_rotates_xy_offset(monkeypatch) -> None:
    monkeypatch.setattr(settings, "NAV_LIDAR_MOUNT_X_M", 0.2)
    monkeypatch.setattr(settings, "NAV_LIDAR_MOUNT_Y_M", 0.0)
    monkeypatch.setattr(settings, "NAV_LIDAR_MOUNT_Z_M", 0.9)

    position = base_pose_to_lidar_initial_position(
        x=1.0,
        y=2.0,
        z=0.1,
        yaw=math.pi / 2.0,
    )

    assert position == pytest.approx((1.0, 2.2, 1.0))


def test_lidar_mount_environment_preserves_float_type_for_zero(monkeypatch) -> None:
    for setting_name in (
        "NAV_LIDAR_MOUNT_X_M",
        "NAV_LIDAR_MOUNT_Y_M",
        "NAV_LIDAR_MOUNT_ROLL_DEG",
        "NAV_LIDAR_MOUNT_YAW_DEG",
    ):
        monkeypatch.setattr(settings, setting_name, 0.0)

    env = lidar_mount_environment({})

    assert env["NAV_LIDAR_MOUNT_X_M"] == "0.0"
    assert env["NAV_LIDAR_MOUNT_Y_M"] == "0.0"
    assert env["NAV_LIDAR_MOUNT_ROLL_DEG"] == "0.0"
    assert env["NAV_LIDAR_MOUNT_YAW_DEG"] == "0.0"


@pytest.mark.parametrize(
    ("setting_name", "invalid_value"),
    [
        ("NAV_LIDAR_MOUNT_X_M", math.nan),
        ("NAV_LIDAR_MOUNT_Z_M", -0.01),
        ("NAV_LIDAR_MOUNT_PITCH_DEG", 181.0),
    ],
)
def test_lidar_mount_values_rejects_unsafe_values(
    monkeypatch,
    setting_name: str,
    invalid_value: float,
) -> None:
    monkeypatch.setattr(settings, setting_name, invalid_value)

    with pytest.raises(ValueError):
        lidar_mount_values()
