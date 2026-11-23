from __future__ import annotations

import fcntl
import glob
import json
import os
import select
import termios
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


UNIT_CODES = {
    0x0: "ppm",
    0x2: "%LEL",
    0x4: "%VOL",
    0x6: "mg/m3",
    0x8: "ppb",
    0xA: "°C",
}
DECIMAL_CODES = {0x0: 0, 0x4: 1, 0x8: 2, 0xC: 3}
STATUS_CODES = {
    0x00: "预热",
    0x01: "正常",
    0x02: "数据错误",
    0x03: "传感器故障",
    0x04: "预警",
    0x05: "低报",
    0x06: "高报",
    0x07: "访问故障",
    0x08: "超量程",
    0x09: "需要标定",
    0x0A: "超时",
    0x0B: "STEL报警",
    0x0C: "TWA报警",
    0x0F: "通信故障",
}

# The connected GT-01 reports these three channels on one Modbus-RTU bus.
CHANNELS = {
    "o2": {"address": 2, "expected_type": 67, "name": "O₂"},
    "co2": {"address": 3, "expected_type": 6, "name": "CO₂"},
    "ph3": {"address": 4, "expected_type": 69, "name": "PH₃"},
}
DUST_CHANNEL = {"address": 1, "expected_type": 11, "name": "DUST"}
POLL_INTERVAL_SECONDS = 2.0
# A missed Modbus response does not invalidate the last physical measurement.
# Treat readings as current for the site's accepted three-minute grace window.
FRESH_MAX_AGE_SECONDS = 3 * 60.0
DEFAULT_CACHE_PATH = Path(__file__).resolve().parents[1] / ".runtime" / "gas-readings.json"


class GasSensorError(RuntimeError):
    pass


@dataclass(frozen=True)
class GasReading:
    address: int
    value: float
    unit: str
    decimals: int
    low_alarm: float
    high_alarm: float
    full_scale: float
    status_code: int
    status: str
    ad_value: int
    temperature: float
    humidity: float
    gas_type_code: int
    type_matches: bool
    raw_registers: list[int]

    def to_dict(self) -> dict:
        return asdict(self)


def dust_payload(reading: GasReading) -> dict:
    """Normalize the address-1 firmware payload to the UI's mg/m³ unit.

    This device uses the generic gas firmware metadata (ppm/type 0x0B) for its
    dust channel, while the values and 75/150 thresholds are reported in µg/m³.
    """
    return {
        "address": reading.address,
        "value": reading.value / 1000,
        "value_ug_m3": reading.value,
        "unit": "mg/m3",
        "decimals": 3,
        "low_alarm": reading.low_alarm / 1000,
        "high_alarm": reading.high_alarm / 1000,
        "full_scale": reading.full_scale / 1000,
        "status_code": reading.status_code,
        "status": reading.status,
        "ad_value": reading.ad_value,
        "firmware_unit": reading.unit,
        "firmware_type_code": reading.gas_type_code,
        "raw_registers": reading.raw_registers,
    }


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def build_read_query(address: int) -> bytes:
    body = bytes((address, 0x03, 0x00, 0x00, 0x00, 0x0A))
    return body + crc16_modbus(body).to_bytes(2, "little")


def parse_modbus_response(
    frame: bytes,
    *,
    expected_address: int,
    expected_type: int,
) -> GasReading:
    if len(frame) < 5:
        raise GasSensorError("返回帧过短")
    if frame[0] != expected_address:
        raise GasSensorError(
            f"地址不匹配：期望 {expected_address}，收到 {frame[0]}"
        )
    if frame[1] & 0x80:
        raise GasSensorError(f"Modbus异常响应：0x{frame[2]:02X}")
    if frame[1] != 0x03:
        raise GasSensorError(f"功能码不匹配：0x{frame[1]:02X}")

    byte_count = frame[2]
    expected_length = 3 + byte_count + 2
    if byte_count != 20 or len(frame) != expected_length:
        raise GasSensorError(
            f"数据长度不匹配：期望25字节，收到{len(frame)}字节"
        )
    received_crc = int.from_bytes(frame[-2:], "little")
    calculated_crc = crc16_modbus(frame[:-2])
    if received_crc != calculated_crc:
        raise GasSensorError(
            f"CRC错误：收到0x{received_crc:04X}，计算0x{calculated_crc:04X}"
        )

    registers = [
        int.from_bytes(frame[index:index + 2], "big")
        for index in range(3, 3 + byte_count, 2)
    ]
    format_register = registers[0]
    unit_code = (format_register >> 12) & 0x0F
    decimal_code = (format_register >> 8) & 0x0F
    if unit_code not in UNIT_CODES:
        raise GasSensorError(f"未知单位代码：0x{unit_code:X}")
    if decimal_code not in DECIMAL_CODES:
        raise GasSensorError(f"未知小数位代码：0x{decimal_code:X}")

    decimals = DECIMAL_CODES[decimal_code]
    divisor = 10**decimals
    gas_type_code = (registers[8] >> 8) & 0xFF
    status_code = registers[5] & 0xFF
    return GasReading(
        address=expected_address,
        value=registers[1] / divisor,
        unit=UNIT_CODES[unit_code],
        decimals=decimals,
        low_alarm=registers[2] / divisor,
        high_alarm=registers[3] / divisor,
        full_scale=registers[4] / divisor,
        status_code=status_code,
        status=STATUS_CODES.get(status_code, "未知状态"),
        ad_value=registers[6],
        temperature=(registers[7] - 500) / 10,
        humidity=registers[9] / 10,
        gas_type_code=gas_type_code,
        type_matches=gas_type_code == expected_type,
        raw_registers=registers,
    )


class GasSensorReader:
    def __init__(
        self,
        port: str | None = None,
        *,
        cache_path: str | Path | None = None,
    ) -> None:
        self.configured_port = port or os.getenv("CAMERA_MODEL_LAB_GAS_PORT")
        self.cache_path = Path(
            cache_path
            or os.getenv("CAMERA_MODEL_LAB_GAS_CACHE_PATH")
            or DEFAULT_CACHE_PATH
        )
        self._lock = threading.Lock()
        self._condition = threading.Condition()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._cache: dict[str, dict] = {}
        self._cache_updated_at: dict[str, float] = {}
        self._cache_updated_epoch: dict[str, float] = {}
        self._background_errors: dict[str, str] = {}
        self._active_port: str | None = None
        self._last_persist_at = 0.0
        self._load_cache()

    def start(self) -> None:
        with self._condition:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="gas-sensor-reader",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        with self._condition:
            self._condition.notify_all()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=3)
        self._persist_cache(force=True)

    def _load_cache(self) -> None:
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return

        records = data.get("channels")
        if records is None:
            read_at = data.get("read_at")
            try:
                read_epoch = datetime.fromisoformat(read_at).timestamp()
            except (TypeError, ValueError):
                read_epoch = time.time()
            records = {
                **{
                    key: {
                        "payload": payload,
                        "sampled_at": read_epoch - float(payload.get("age_seconds", 0)),
                    }
                    for key, payload in (data.get("gases") or {}).items()
                },
                **(
                    {
                        "dust": {
                            "payload": data["dust"],
                            "sampled_at": read_epoch
                            - float(data["dust"].get("age_seconds", 0)),
                        }
                    }
                    if data.get("dust")
                    else {}
                ),
            }

        monotonic_now = time.monotonic()
        epoch_now = time.time()
        for channel_id, record in records.items():
            if channel_id not in {"dust", *CHANNELS} or not isinstance(record, dict):
                continue
            payload = record.get("payload")
            sampled_at = record.get("sampled_at")
            if not isinstance(payload, dict) or not isinstance(sampled_at, (int, float)):
                continue
            value = dict(payload)
            value.pop("cached", None)
            value.pop("age_seconds", None)
            value.pop("sampled_at", None)
            age = max(0.0, epoch_now - float(sampled_at))
            self._cache[channel_id] = value
            self._cache_updated_at[channel_id] = monotonic_now - age
            self._cache_updated_epoch[channel_id] = float(sampled_at)

    def _persist_cache(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_persist_at < 10.0:
            return
        with self._condition:
            channels = {
                channel_id: {
                    "payload": payload,
                    "sampled_at": self._cache_updated_epoch[channel_id],
                }
                for channel_id, payload in self._cache.items()
                if channel_id in self._cache_updated_epoch
            }
        if not channels:
            return
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.cache_path.with_name(f"{self.cache_path.name}.tmp")
            temporary.write_text(
                json.dumps({"version": 1, "channels": channels}, ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(temporary, self.cache_path)
            self._last_persist_at = now
        except OSError:
            return

    def _remember(self, channel_id: str, payload: dict) -> None:
        with self._condition:
            self._cache[channel_id] = payload
            self._cache_updated_at[channel_id] = time.monotonic()
            self._cache_updated_epoch[channel_id] = time.time()
            self._background_errors.pop(channel_id, None)
            self._background_errors.pop("port", None)
            self._condition.notify_all()
        self._persist_cache()

    def snapshot(self, wait_timeout: float = 2.0) -> dict:
        self.start()
        with self._condition:
            self._condition.wait_for(
                lambda: bool(self._cache) or self._stop_event.is_set(),
                timeout=wait_timeout,
            )
            now = time.monotonic()
            values: dict[str, dict] = {}
            fresh_channels: list[str] = []
            cached_channels: list[str] = []
            for channel_id in ("dust", *CHANNELS):
                payload = self._cache.get(channel_id)
                updated_at = self._cache_updated_at.get(channel_id)
                if payload is None or updated_at is None:
                    continue
                age = now - updated_at
                value = dict(payload)
                is_cached = age > FRESH_MAX_AGE_SECONDS
                sampled_epoch = self._cache_updated_epoch.get(channel_id, time.time() - age)
                value.update(
                    {
                        "cached": is_cached,
                        "age_seconds": round(age, 1),
                        "sampled_at": datetime.fromtimestamp(sampled_epoch)
                        .astimezone()
                        .isoformat(timespec="seconds"),
                    }
                )
                values[channel_id] = value
                (cached_channels if is_cached else fresh_channels).append(channel_id)

            dust = values.pop("dust", None)
            readings = {key: values[key] for key in CHANNELS if key in values}
            if not readings and dust is None:
                detail = "；".join(self._background_errors.values())
                raise GasSensorError(detail or "正在等待传感器首次回包")
            return {
                "status": (
                    "ok"
                    if len(fresh_channels) == len(CHANNELS) + 1
                    else "partial"
                ),
                "port": self._active_port or self.configured_port or "/dev/ttyUSB0",
                "read_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "gases": readings,
                "dust": dust,
                "fresh_channels": sorted(fresh_channels),
                "cached_channels": sorted(cached_channels),
                "errors": dict(self._background_errors),
            }

    def _resolve_port(self) -> str:
        if self.configured_port:
            if os.path.exists(self.configured_port):
                return self.configured_port
            raise GasSensorError(f"串口不存在：{self.configured_port}")

        candidates = sorted(
            glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")
        )
        if not candidates:
            raise GasSensorError("未发现USB串口设备")
        return candidates[0]

    @staticmethod
    def _open_port(port: str) -> int:
        fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            # Prevent another unprivileged reader from consuming Modbus replies.
            # Root can bypass TIOCEXCL, so deployment must also keep the legacy
            # radiation reader's device alias separate from this gas sensor.
            fcntl.ioctl(fd, termios.TIOCEXCL)
        except OSError:
            os.close(fd)
            raise
        return fd

    @staticmethod
    def _configure(fd: int) -> None:
        attrs = termios.tcgetattr(fd)
        attrs[0] = 0
        attrs[1] = 0
        attrs[2] = termios.CLOCAL | termios.CREAD | termios.CS8
        attrs[3] = 0
        attrs[4] = termios.B9600
        attrs[5] = termios.B9600
        attrs[6][termios.VMIN] = 0
        attrs[6][termios.VTIME] = 1
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        termios.tcflush(fd, termios.TCIOFLUSH)

    @staticmethod
    def _receive(fd: int, timeout: float = 0.9) -> bytes:
        response = bytearray()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            remaining = max(0.0, deadline - time.monotonic())
            readable, _, _ = select.select([fd], [], [], min(0.08, remaining))
            if not readable:
                continue
            try:
                chunk = os.read(fd, 256)
            except (BlockingIOError, InterruptedError):
                # A non-blocking serial fd can become temporarily unreadable
                # between select() and read(). Keep waiting until the deadline.
                continue
            if chunk:
                response.extend(chunk)
            if len(response) >= 3:
                expected_length = 3 + response[2] + 2
                if len(response) >= expected_length:
                    return bytes(response[:expected_length])
        return bytes(response)

    def _query_channel(
        self,
        fd: int,
        channel: dict,
        *,
        attempts: int = 3,
        receive_timeout: float = 0.9,
    ) -> GasReading:
        address = channel["address"]
        query = build_read_query(address)
        last_error = "无响应"
        for attempt in range(attempts):
            # Other serial probers can change a tty's shared termios settings
            # after this process opens it. Reassert the GT-01 Modbus settings
            # before every request so the reader cannot remain at 115200 baud.
            self._configure(fd)
            termios.tcflush(fd, termios.TCIFLUSH)
            os.write(fd, query)
            # Wait until the CH340 has physically transmitted the complete RTU
            # request before switching to receive. This is important for
            # auto-direction USB-RS485 adapters.
            termios.tcdrain(fd)
            frame = self._receive(fd, timeout=receive_timeout)
            if frame:
                try:
                    return parse_modbus_response(
                        frame,
                        expected_address=address,
                        expected_type=channel["expected_type"],
                    )
                except GasSensorError as exc:
                    last_error = str(exc)
            if attempt < attempts - 1:
                time.sleep(0.5)
        raise GasSensorError(f"地址{address}读取失败：{last_error}")

    def _run(self) -> None:
        channels = [("dust", DUST_CHANNEL), *CHANNELS.items()]
        while not self._stop_event.is_set():
            fd: int | None = None
            try:
                port = self._resolve_port()
                fd = self._open_port(port)
                self._configure(fd)
                with self._condition:
                    self._active_port = port
                    self._condition.notify_all()

                while not self._stop_event.is_set():
                    cycle_started_at = time.monotonic()
                    received_sample = False
                    for channel_id, channel in channels:
                        if self._stop_event.is_set():
                            break
                        try:
                            reading = self._query_channel(
                                fd,
                                channel,
                                attempts=2,
                                receive_timeout=0.9,
                            )
                            if not reading.type_matches:
                                raise GasSensorError(
                                    f"地址{reading.address}类型代码不匹配："
                                    f"期望{channel['expected_type']}，收到{reading.gas_type_code}"
                                )
                            payload = (
                                dust_payload(reading)
                                if channel_id == "dust"
                                else reading.to_dict()
                            )
                            self._remember(channel_id, payload)
                            received_sample = True
                        except GasSensorError as exc:
                            with self._condition:
                                self._background_errors[channel_id] = str(exc)
                        if self._stop_event.wait(0.08):
                            break
                    if not received_sample and not self._stop_event.is_set():
                        raise GasSensorError("四路传感器均无有效回包，正在重新连接串口")
                    self._stop_event.wait(
                        max(0.0, POLL_INTERVAL_SECONDS - (time.monotonic() - cycle_started_at))
                    )
            except (GasSensorError, OSError, termios.error) as exc:
                with self._condition:
                    self._background_errors["port"] = str(exc)
                    self._condition.notify_all()
            finally:
                if fd is not None:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                with self._condition:
                    self._active_port = None
            self._stop_event.wait(1.0)

    def read_all(self) -> dict:
        with self._lock:
            port = self._resolve_port()
            try:
                fd = self._open_port(port)
            except PermissionError as exc:
                raise GasSensorError(
                    f"无权限访问{port}，运行用户需要加入dialout组"
                ) from exc
            except OSError as exc:
                raise GasSensorError(f"无法打开{port}：{exc.strerror}") from exc

            readings: dict[str, dict] = {}
            dust: dict | None = None
            errors: dict[str, str] = {}
            try:
                self._configure(fd)
                channels = [("dust", DUST_CHANNEL), *CHANNELS.items()]
                for index, (channel_id, channel) in enumerate(channels):
                    if index:
                        time.sleep(0.5)
                    try:
                        reading = self._query_channel(fd, channel)
                        if not reading.type_matches:
                            raise GasSensorError(
                                f"地址{reading.address}类型代码不匹配："
                                f"期望{channel['expected_type']}，收到{reading.gas_type_code}"
                            )
                        payload = (
                            dust_payload(reading)
                            if channel_id == "dust"
                            else reading.to_dict()
                        )
                        payload.update({"cached": False, "age_seconds": 0.0})
                        self._cache[channel_id] = payload
                        self._cache_updated_at[channel_id] = time.monotonic()
                        if channel_id == "dust":
                            dust = payload
                        else:
                            readings[channel_id] = payload
                    except GasSensorError as exc:
                        errors[channel_id] = str(exc)
            except OSError as exc:
                raise GasSensorError(f"串口通信失败：{exc.strerror or exc}") from exc
            finally:
                os.close(fd)

            fresh_channels = set(readings)
            if dust is not None:
                fresh_channels.add("dust")
            cached_channels: list[str] = []
            now = time.monotonic()
            for channel_id in ("dust", *CHANNELS):
                if channel_id in fresh_channels or channel_id not in self._cache:
                    continue
                age = now - self._cache_updated_at[channel_id]
                cached = dict(self._cache[channel_id])
                cached.update({"cached": True, "age_seconds": round(age, 1)})
                cached_channels.append(channel_id)
                if channel_id == "dust":
                    dust = cached
                else:
                    readings[channel_id] = cached

            if not readings and dust is None:
                detail = "；".join(errors.values()) or "没有收到传感器数据"
                raise GasSensorError(detail)

            return {
                "status": "ok" if len(fresh_channels) == len(CHANNELS) + 1 else "partial",
                "port": port,
                "read_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "gases": readings,
                "dust": dust,
                "fresh_channels": sorted(fresh_channels),
                "cached_channels": sorted(cached_channels),
                "errors": errors,
            }
