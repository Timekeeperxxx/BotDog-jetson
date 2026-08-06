from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.z2mini_gimbal import (
    GcuProtocolError,
    Z2MiniGimbal,
    build_packet,
    crc16,
    parse_status,
)


def _status_packet() -> bytes:
    packet = bytearray(72)
    packet[0:2] = b"\x8A\x5E"
    packet[2:4] = (72).to_bytes(2, "little")
    packet[4] = 0x02
    packet[5] = 0x12
    packet[6:8] = ((1 << 9) | (1 << 10)).to_bytes(2, "little")
    packet[12:14] = (25).to_bytes(2, "little", signed=True)
    packet[14:16] = (-1250).to_bytes(2, "little", signed=True)
    packet[16:18] = (3400).to_bytes(2, "little", signed=True)
    packet[18:20] = (10).to_bytes(2, "little", signed=True)
    packet[20:22] = (-200).to_bytes(2, "little", signed=True)
    packet[22:24] = (35990).to_bytes(2, "little")
    packet[24:26] = (5).to_bytes(2, "little", signed=True)
    packet[26:28] = (-6).to_bytes(2, "little", signed=True)
    packet[28:30] = (7).to_bytes(2, "little", signed=True)
    packet[37] = 0x01
    packet[38] = 1
    packet[39] = 67
    packet[40] = 52
    packet[41:43] = (1 << 14).to_bytes(2, "little")
    packet[59:61] = (35).to_bytes(2, "little")
    packet[64:66] = (
        (1 << 13) | (1 << 14) | (1 << 4) | 2
    ).to_bytes(2, "little")
    packet[-2:] = crc16(packet[:-2]).to_bytes(2, "big")
    return bytes(packet)


def test_builds_protocol_null_packet_from_official_example() -> None:
    packet = build_packet()

    assert len(packet) == 72
    assert packet[:5] == b"\xA8\xE5\x48\x00\x02"
    assert packet[30] == 0x01
    assert packet[69] == 0x00
    assert packet[-2:] == bytes.fromhex("fd 13")
    assert crc16(packet[:-2]) == int.from_bytes(packet[-2:], "big")


def test_builds_angle_control_values_and_validity_bit() -> None:
    packet = build_packet(
        b"\x10",
        control_values=(0.0, -45.0, 60.0),
    )

    assert int.from_bytes(packet[7:9], "little", signed=True) == -4500
    assert int.from_bytes(packet[9:11], "little", signed=True) == 6000
    assert packet[11] & (1 << 2)


def test_parses_angles_camera_settings_and_identity() -> None:
    status = parse_status(_status_packet())

    assert status.connected is True
    assert status.mode == "head_follow"
    assert status.relative_roll_deg == -12.5
    assert status.relative_pitch_deg == -0.25
    assert status.relative_yaw_deg == 34.0
    assert status.absolute_yaw_deg == 359.9
    assert status.zoom_ratio == 3.5
    assert status.picture_mode == "thermal"
    assert status.picture_mode_code == 2
    assert status.osd_enabled is True
    assert status.night_vision_enabled is True
    assert status.lighting_enabled is True
    assert status.digital_zoom_enabled is True
    assert status.camera_recording is True
    assert status.pod_code == 52
    assert status.error_code == 1 << 14


def test_normalizes_signed_firmware_absolute_yaw() -> None:
    packet = bytearray(_status_packet())
    packet[22:24] = (-713).to_bytes(2, "little", signed=True)

    assert parse_status(bytes(packet)).absolute_yaw_deg == 352.87


def test_rejects_short_status_packet() -> None:
    with pytest.raises(GcuProtocolError):
        parse_status(b"\x00" * 20)


@pytest.mark.asyncio
async def test_position_limits_are_checked_before_network_access() -> None:
    gimbal = Z2MiniGimbal(host="127.0.0.1")

    with pytest.raises(ValueError, match="俯仰角"):
        await gimbal.set_position(pitch_deg=-91.0, yaw_deg=0.0)

    with pytest.raises(ValueError, match="偏航角"):
        await gimbal.set_position(pitch_deg=0.0, yaw_deg=171.0)


@pytest.mark.asyncio
async def test_jog_speed_limit_is_checked_before_network_access() -> None:
    gimbal = Z2MiniGimbal(host="127.0.0.1")

    with pytest.raises(ValueError, match="20"):
        await gimbal.jog(pitch_velocity_dps=21.0, yaw_velocity_dps=0.0)


@pytest.mark.asyncio
async def test_yaw_jog_sends_zero_roll_and_pitch_velocity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gimbal = Z2MiniGimbal(host="127.0.0.1")
    captured: list[tuple[int, tuple[float, float, float] | None]] = []
    expected = parse_status(_status_packet())

    def command_and_status(
        command: int,
        parameters: bytes = b"",
        *,
        control_values: tuple[float, float, float] | None = None,
    ):
        del parameters
        captured.append((command, control_values))
        return expected

    monkeypatch.setattr(gimbal, "_command_and_status_sync", command_and_status)

    status = await gimbal.jog(pitch_velocity_dps=0.0, yaw_velocity_dps=8.0)

    assert status is expected
    assert captured == [(0x12, (0.0, 0.0, 8.0))]

    await gimbal.jog(pitch_velocity_dps=0.0, yaw_velocity_dps=0.0)
    assert captured[-1] == (0x12, (0.0, 0.0, 0.0))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "expected_code"),
    [
        ("visible", 4),
        ("thermal", 2),
        ("visible_thermal_pip", 1),
        ("thermal_visible_pip", 3),
    ],
)
async def test_picture_mode_uses_verified_z2mini_mode_codes(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    expected_code: int,
) -> None:
    gimbal = Z2MiniGimbal(host="127.0.0.1")
    commands: list[tuple[int, bytes]] = []

    monkeypatch.setattr(
        gimbal,
        "_execute_command_sync",
        lambda command, parameters=b"": commands.append((command, parameters)),
    )
    monkeypatch.setattr(
        gimbal,
        "_read_status_sync",
        lambda: SimpleNamespace(picture_mode_code=expected_code),
    )

    status = await gimbal.set_picture_mode(mode)  # type: ignore[arg-type]

    assert status.picture_mode_code == expected_code
    assert commands == [(0x74, bytes((expected_code,)))]
