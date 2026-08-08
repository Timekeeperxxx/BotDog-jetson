"""先飞 Z2-Mini 云台 TCP 私有协议客户端。

只开放已经在 GCU Private Protocol V2.0.6 中确认的状态和控制字段。
方向点动和连续变焦均带后端自动停止保护，避免浏览器断连后设备持续动作。
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Literal

from .config import settings


PROTOCOL_VERSION = 0x02
CAMERA_ONE_MASK = 0x01
OSD_STATE_MASK = 1 << 13
DIGITAL_ZOOM_STATE_MASK = 1 << 14
CAMERA_RECORDING_STATE_MASK = 1 << 4
NIGHT_VISION_STATE_MASK = 1 << 9
LIGHTING_STATE_MASK = 1 << 10

PICTURE_MODE_NAMES = {
    # Z2-Mini 实机验证：协议只定义了模式编号，未给出各编号的语义名称。
    1: "visible_thermal_pip",
    2: "thermal",
    3: "thermal_visible_pip",
    4: "visible",
}

PICTURE_MODE_COMMANDS = {
    "visible_thermal_pip": 1,
    "thermal_visible_pip": 3,
    "visible": 4,
    "thermal": 2,
}

MODE_NAMES = {
    0x10: "angle",
    0x11: "head_lock",
    0x12: "head_follow",
    0x13: "orthoview",
    0x14: "euler",
    0x16: "gaze",
    0x17: "track",
    0x1C: "fpv",
}

MODE_COMMANDS = {
    "angle": 0x10,
    "head_lock": 0x11,
    "head_follow": 0x12,
    "fpv": 0x1C,
}

CRC_TABLE = (
    0x0000,
    0x1021,
    0x2042,
    0x3063,
    0x4084,
    0x50A5,
    0x60C6,
    0x70E7,
    0x8108,
    0x9129,
    0xA14A,
    0xB16B,
    0xC18C,
    0xD1AD,
    0xE1CE,
    0xF1EF,
)


class GcuProtocolError(RuntimeError):
    """GCU 返回了无效帧或命令执行失败。"""


def crc16(data: bytes) -> int:
    crc = 0
    for value in data:
        index = (crc >> 12) ^ (value >> 4)
        crc = ((crc << 4) & 0xFFFF) ^ CRC_TABLE[index]
        index = (crc >> 12) ^ (value & 0x0F)
        crc = ((crc << 4) & 0xFFFF) ^ CRC_TABLE[index]
    return crc


def _encode_s16(value: float) -> bytes:
    scaled = round(value * 100.0)
    if not -32768 <= scaled <= 32767:
        raise ValueError(f"控制值超出 S16 范围：{value}")
    return int(scaled).to_bytes(2, "little", signed=True)


def build_packet(
    command_data: bytes = b"\x00",
    *,
    control_values: tuple[float, float, float] | None = None,
    request_status: bool = True,
) -> bytes:
    """构造主机到 GCU 的完整数据包。"""
    if not command_data:
        raise ValueError("command_data 不能为空")
    packet_length = 69 + len(command_data) + 2
    frame = bytearray(69)
    frame[0:2] = b"\xA8\xE5"
    frame[2:4] = packet_length.to_bytes(2, "little")
    frame[4] = PROTOCOL_VERSION

    if control_values is not None:
        roll, pitch, yaw = control_values
        frame[5:7] = _encode_s16(roll)
        frame[7:9] = _encode_s16(pitch)
        frame[9:11] = _encode_s16(yaw)
        frame[11] |= 1 << 2

    if request_status:
        frame[30] = 0x01

    body = bytes(frame) + command_data
    return body + crc16(body).to_bytes(2, "big")


def receive_packet(connection: socket.socket) -> bytes:
    response = bytearray()
    while len(response) < 4:
        chunk = connection.recv(1024)
        if not chunk:
            raise GcuProtocolError("GCU 在返回帧头前关闭了连接")
        response.extend(chunk)

    packet_length = int.from_bytes(response[2:4], "little")
    if packet_length < 72 or packet_length > 4096:
        raise GcuProtocolError(f"GCU 返回了无效包长：{packet_length}")

    while len(response) < packet_length:
        chunk = connection.recv(packet_length - len(response))
        if not chunk:
            raise GcuProtocolError("GCU 在完整响应返回前关闭了连接")
        response.extend(chunk)

    packet = bytes(response[:packet_length])
    if packet[0:2] != b"\x8A\x5E":
        raise GcuProtocolError(f"GCU 响应帧头错误：{packet[0:2].hex(' ')}")
    expected_crc = int.from_bytes(packet[-2:], "big")
    actual_crc = crc16(packet[:-2])
    if actual_crc != expected_crc:
        raise GcuProtocolError(
            f"GCU 响应 CRC 错误：received={expected_crc:04x}, calculated={actual_crc:04x}"
        )
    return packet


def _s16(packet: bytes, offset: int) -> int:
    return int.from_bytes(packet[offset : offset + 2], "little", signed=True)


def _u16(packet: bytes, offset: int) -> int:
    return int.from_bytes(packet[offset : offset + 2], "little", signed=False)


def _absolute_yaw_deg(packet: bytes) -> float:
    raw = _u16(packet, 22)
    # 文档定义为 U16 [0, 36000)，但部分 Z2-Mini 固件在负角度区间
    # 实际返回 S16。兼容这两种表示并统一到 [0, 360)。
    hundredths = _s16(packet, 22) if raw > 36000 else raw
    return round((hundredths / 100.0) % 360.0, 2)


@dataclass(frozen=True)
class Z2MiniStatus:
    connected: bool
    timestamp: str
    mode: str
    mode_code: int
    relative_roll_deg: float
    relative_pitch_deg: float
    relative_yaw_deg: float
    absolute_roll_deg: float
    absolute_pitch_deg: float
    absolute_yaw_deg: float
    angular_velocity_roll_dps: float
    angular_velocity_pitch_dps: float
    angular_velocity_yaw_dps: float
    zoom_ratio: float | None
    picture_mode: str
    picture_mode_code: int
    osd_enabled: bool
    night_vision_enabled: bool
    lighting_enabled: bool
    digital_zoom_enabled: bool
    camera_recording: bool
    hardware_version: int | None
    firmware_version: int | None
    pod_code: int | None
    error_code: int | None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def parse_status(packet: bytes) -> Z2MiniStatus:
    if len(packet) < 72:
        raise GcuProtocolError(f"GCU 状态帧过短：{len(packet)}")

    pod_status = _u16(packet, 6)
    subframe_present = packet[37] == 0x01
    camera_status = _u16(packet, 64) if subframe_present else 0
    zoom_raw = _u16(packet, 59) if subframe_present else 0
    picture_mode_code = camera_status & 0x07
    mode_code = packet[5]
    timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )

    return Z2MiniStatus(
        connected=True,
        timestamp=timestamp,
        mode=MODE_NAMES.get(mode_code, "unknown"),
        mode_code=mode_code,
        # GCU 返回的是相机 X/Y/Z 轴编码器角。按协议附录的欧拉角变换：
        # roll=+AngleY, pitch=-AngleX, yaw=+AngleZ。
        relative_roll_deg=round(_s16(packet, 14) / 100.0, 2),
        relative_pitch_deg=round(-_s16(packet, 12) / 100.0, 2),
        relative_yaw_deg=round(_s16(packet, 16) / 100.0, 2),
        absolute_roll_deg=round(_s16(packet, 18) / 100.0, 2),
        absolute_pitch_deg=round(_s16(packet, 20) / 100.0, 2),
        absolute_yaw_deg=_absolute_yaw_deg(packet),
        angular_velocity_roll_dps=round(_s16(packet, 26) / 100.0, 2),
        angular_velocity_pitch_dps=round(-_s16(packet, 24) / 100.0, 2),
        angular_velocity_yaw_dps=round(_s16(packet, 28) / 100.0, 2),
        zoom_ratio=round(zoom_raw / 10.0, 1) if subframe_present and zoom_raw else None,
        picture_mode=PICTURE_MODE_NAMES.get(picture_mode_code, "unknown"),
        picture_mode_code=picture_mode_code,
        osd_enabled=bool(camera_status & OSD_STATE_MASK),
        night_vision_enabled=bool(pod_status & NIGHT_VISION_STATE_MASK),
        lighting_enabled=bool(pod_status & LIGHTING_STATE_MASK),
        digital_zoom_enabled=bool(camera_status & DIGITAL_ZOOM_STATE_MASK),
        camera_recording=bool(camera_status & CAMERA_RECORDING_STATE_MASK),
        hardware_version=packet[38] if subframe_present else None,
        firmware_version=packet[39] if subframe_present else None,
        pod_code=packet[40] if subframe_present else None,
        error_code=_u16(packet, 41) if subframe_present else None,
    )


class Z2MiniGimbal:
    """异步串行化访问单台 Z2-Mini。"""

    def __init__(
        self,
        *,
        host: str,
        port: int = 2332,
        timeout: float = 2.0,
        jog_seconds: float = 0.45,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = max(0.1, timeout)
        self.jog_seconds = max(0.1, min(jog_seconds, 2.0))
        self._lock = asyncio.Lock()
        self._jog_stop_task: asyncio.Task[None] | None = None
        self._zoom_stop_task: asyncio.Task[None] | None = None
        self._last_status: Z2MiniStatus | None = None
        self._last_status_monotonic = 0.0

    def _exchange(self, packet: bytes) -> bytes:
        with socket.create_connection(
            (self.host, self.port),
            timeout=self.timeout,
        ) as connection:
            connection.settimeout(self.timeout)
            connection.sendall(packet)
            return receive_packet(connection)

    def _read_status_sync(self) -> Z2MiniStatus:
        status = parse_status(self._exchange(build_packet()))
        # 供视频帧与雷达帧融合读取。只缓存已实际收到的 GCU 状态，不主动
        # 发起额外网络请求，也不会让 AI Worker 阻塞在云台 TCP 上。
        self._last_status = status
        self._last_status_monotonic = time.monotonic()
        return status

    def get_cached_status(self, *, max_age_seconds: float = 2.0) -> Z2MiniStatus | None:
        if self._last_status is None:
            return None
        if time.monotonic() - self._last_status_monotonic > max(0.0, max_age_seconds):
            return None
        return self._last_status

    def _execute_command_sync(
        self,
        command: int,
        parameters: bytes = b"",
        *,
        control_values: tuple[float, float, float] | None = None,
    ) -> None:
        # 同一命令码连续发送时 GCU 可能只执行一次，先发空命令作为分隔。
        self._exchange(build_packet())
        response = self._exchange(
            build_packet(
                bytes((command,)) + parameters,
                control_values=control_values,
            )
        )
        feedback = response[69:-2]
        if len(feedback) < 2 or feedback[0] != command or feedback[1] != 0:
            raise GcuProtocolError(
                f"GCU 命令 0x{command:02X} 执行失败，feedback={feedback.hex(' ') or '<empty>'}"
            )

    def _command_and_status_sync(
        self,
        command: int,
        parameters: bytes = b"",
        *,
        control_values: tuple[float, float, float] | None = None,
    ) -> Z2MiniStatus:
        self._execute_command_sync(
            command,
            parameters,
            control_values=control_values,
        )
        time.sleep(0.04)
        return self._read_status_sync()

    async def status(self) -> Z2MiniStatus:
        async with self._lock:
            return await asyncio.to_thread(self._read_status_sync)

    async def set_mode(
        self,
        mode: Literal["angle", "head_lock", "head_follow", "fpv"],
    ) -> Z2MiniStatus:
        command = MODE_COMMANDS[mode]
        self._cancel_jog_stop()
        async with self._lock:
            return await asyncio.to_thread(self._command_and_status_sync, command)

    async def center(self) -> Z2MiniStatus:
        self._cancel_jog_stop()

        def center_sync() -> Z2MiniStatus:
            self._execute_command_sync(MODE_COMMANDS["head_follow"])
            self._execute_command_sync(0x03)
            time.sleep(0.08)
            return self._read_status_sync()

        async with self._lock:
            return await asyncio.to_thread(center_sync)

    async def set_position(self, *, pitch_deg: float, yaw_deg: float) -> Z2MiniStatus:
        if not -90.0 <= pitch_deg <= 30.0:
            raise ValueError("俯仰角必须在 -90° 到 30° 之间")
        if not -170.0 <= yaw_deg <= 170.0:
            raise ValueError("偏航角必须在 -170° 到 170° 之间")
        self._cancel_jog_stop()
        async with self._lock:
            return await asyncio.to_thread(
                self._command_and_status_sync,
                MODE_COMMANDS["angle"],
                b"",
                control_values=(0.0, pitch_deg, yaw_deg),
            )

    async def jog(self, *, pitch_velocity_dps: float, yaw_velocity_dps: float) -> Z2MiniStatus:
        if abs(pitch_velocity_dps) > 20.0 or abs(yaw_velocity_dps) > 20.0:
            raise ValueError("云台点动速度不能超过 20°/s")
        self._cancel_jog_stop()
        async with self._lock:
            status = await asyncio.to_thread(
                self._command_and_status_sync,
                MODE_COMMANDS["head_follow"],
                b"",
                control_values=(0.0, pitch_velocity_dps, yaw_velocity_dps),
            )
        if pitch_velocity_dps or yaw_velocity_dps:
            self._jog_stop_task = asyncio.create_task(self._auto_stop_jog())
        return status

    async def zoom(self, action: Literal["in", "out", "stop"]) -> Z2MiniStatus:
        commands = {"in": 0x22, "out": 0x23, "stop": 0x24}
        self._cancel_zoom_stop()
        async with self._lock:
            status = await asyncio.to_thread(
                self._command_and_status_sync,
                commands[action],
                bytes((CAMERA_ONE_MASK,)),
            )
        if action != "stop":
            self._zoom_stop_task = asyncio.create_task(self._auto_stop_zoom())
        return status

    async def set_picture_mode(
        self,
        mode: Literal[
            "visible",
            "thermal",
            "visible_thermal_pip",
            "thermal_visible_pip",
        ],
    ) -> Z2MiniStatus:
        picture_mode_code = PICTURE_MODE_COMMANDS[mode]

        def set_picture_mode_sync() -> Z2MiniStatus:
            self._execute_command_sync(0x74, bytes((picture_mode_code,)))
            # 图像已经开始切换时，状态字约 300–400 ms 后才更新。
            # 等待反馈稳定，避免接口返回上一个模式导致前端高亮错误。
            deadline = time.monotonic() + 1.0
            status = self._read_status_sync()
            while (
                status.picture_mode_code != picture_mode_code
                and time.monotonic() < deadline
            ):
                time.sleep(0.1)
                status = self._read_status_sync()
            return status

        async with self._lock:
            return await asyncio.to_thread(set_picture_mode_sync)

    async def update_settings(
        self,
        *,
        osd_enabled: bool | None = None,
    ) -> Z2MiniStatus:
        def update_sync() -> Z2MiniStatus:
            if osd_enabled is not None:
                # Z2-Mini 实机固件与协议附录示例一致：1=显示，0=隐藏。
                self._execute_command_sync(0x73, bytes((int(osd_enabled),)))
            time.sleep(0.08)
            return self._read_status_sync()

        async with self._lock:
            return await asyncio.to_thread(update_sync)

    async def _auto_stop_jog(self) -> None:
        try:
            await asyncio.sleep(self.jog_seconds)
            async with self._lock:
                await asyncio.to_thread(
                    self._execute_command_sync,
                    MODE_COMMANDS["head_follow"],
                    b"",
                    control_values=(0.0, 0.0, 0.0),
                )
        except asyncio.CancelledError:
            raise
        except (OSError, GcuProtocolError):
            return
        finally:
            if self._jog_stop_task is asyncio.current_task():
                self._jog_stop_task = None

    async def _auto_stop_zoom(self) -> None:
        try:
            await asyncio.sleep(self.jog_seconds)
            async with self._lock:
                await asyncio.to_thread(
                    self._execute_command_sync,
                    0x24,
                    bytes((CAMERA_ONE_MASK,)),
                )
        except asyncio.CancelledError:
            raise
        except (OSError, GcuProtocolError):
            return
        finally:
            if self._zoom_stop_task is asyncio.current_task():
                self._zoom_stop_task = None

    def _cancel_jog_stop(self) -> None:
        task = self._jog_stop_task
        if task is not None and task is not asyncio.current_task():
            task.cancel()
        self._jog_stop_task = None

    def _cancel_zoom_stop(self) -> None:
        task = self._zoom_stop_task
        if task is not None and task is not asyncio.current_task():
            task.cancel()
        self._zoom_stop_task = None

    async def close(self) -> None:
        tasks = [self._jog_stop_task, self._zoom_stop_task]
        self._cancel_jog_stop()
        self._cancel_zoom_stop()
        for task in tasks:
            if task is not None:
                with contextlib.suppress(asyncio.CancelledError):
                    await task


_gimbal_service: Z2MiniGimbal | None = None


def get_z2mini_gimbal() -> Z2MiniGimbal:
    global _gimbal_service
    if _gimbal_service is None:
        _gimbal_service = Z2MiniGimbal(
            host=settings.Z2MINI_HOST,
            port=settings.Z2MINI_CONTROL_PORT,
            timeout=settings.Z2MINI_TIMEOUT_SECONDS,
            jog_seconds=settings.Z2MINI_JOG_SECONDS,
        )
    return _gimbal_service


def reset_z2mini_gimbal_for_tests() -> None:
    global _gimbal_service
    _gimbal_service = None
