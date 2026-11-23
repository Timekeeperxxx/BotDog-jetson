from __future__ import annotations

import errno
import fcntl
import os
import pty
import termios
from pathlib import Path

import pytest

from server.gas_sensor import (
    GasSensorError,
    GasSensorReader,
    build_read_query,
    dust_payload,
    parse_modbus_response,
)


RESPONSES = {
    "dust": bytes.fromhex(
        "01 03 14 00 00 00 03 00 4B 00 96 03 E8 00 01 00 03 00 01 0B 00 03 5A 68 2F"
    ),
    "o2": bytes.fromhex(
        "02 03 14 44 00 00 D1 00 C3 00 EB 01 2C 00 01 07 85 01 02 43 00 01 02 FF 32"
    ),
    "co2": bytes.fromhex(
        "03 03 14 00 00 02 9E 07 D0 13 88 27 10 00 01 00 00 01 02 06 00 01 02 26 30"
    ),
    "ph3": bytes.fromhex(
        "04 03 14 04 08 00 00 00 18 00 C8 03 E8 00 01 00 00 03 2F 45 00 02 4F BD F4"
    ),
}


def test_queries_match_sensor_manual() -> None:
    assert build_read_query(1).hex(" ").upper() == "01 03 00 00 00 0A C5 CD"
    assert build_read_query(2).hex(" ").upper() == "02 03 00 00 00 0A C5 FE"
    assert build_read_query(3).hex(" ").upper() == "03 03 00 00 00 0A C4 2F"
    assert build_read_query(4).hex(" ").upper() == "04 03 00 00 00 0A C5 98"


def test_open_port_prevents_a_second_reader() -> None:
    master, slave = pty.openpty()
    fd = None
    try:
        port = os.ttyname(slave)
        fd = GasSensorReader._open_port(port)
        with pytest.raises(OSError) as error:
            os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        assert error.value.errno == errno.EBUSY
    finally:
        if fd is not None:
            fcntl.ioctl(fd, termios.TIOCNXCL)
            os.close(fd)
        os.close(slave)
        os.close(master)


def test_open_port_closes_descriptor_when_exclusive_claim_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed = []
    monkeypatch.setattr(os, "open", lambda *_args: 17)
    monkeypatch.setattr(os, "close", closed.append)

    def fail_claim(_fd, _request):
        raise OSError(errno.ENOTTY, "exclusive claim failed")

    monkeypatch.setattr(fcntl, "ioctl", fail_claim)
    with pytest.raises(OSError, match="exclusive claim failed"):
        GasSensorReader._open_port("/dev/ttyUSB-test")
    assert closed == [17]


def test_receive_retries_when_nonblocking_read_temporarily_has_no_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fd = 17
    frame = RESPONSES["dust"]
    reads: list[bytes | BlockingIOError] = [
        BlockingIOError(11, "Resource temporarily unavailable"),
        frame,
    ]

    monkeypatch.setattr(
        "server.gas_sensor.select.select",
        lambda *_args, **_kwargs: ([fd], [], []),
    )

    def fake_read(_fd: int, _size: int) -> bytes:
        result = reads.pop(0)
        if isinstance(result, BlockingIOError):
            raise result
        return result

    monkeypatch.setattr(os, "read", fake_read)
    assert GasSensorReader._receive(fd, timeout=0.1) == frame


def test_read_all_uses_recent_real_reading_when_next_poll_temporarily_misses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = GasSensorReader("/dev/ttyUSB-test")
    calls: list[int] = []

    monkeypatch.setattr("server.gas_sensor.os.path.exists", lambda _path: True)
    monkeypatch.setattr(reader, "_open_port", lambda _port: 17)
    monkeypatch.setattr("server.gas_sensor.os.close", lambda _fd: None)
    monkeypatch.setattr("server.gas_sensor.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(reader, "_configure", lambda _fd: None)

    fail_all = False

    def fake_query(_fd: int, channel: dict, *, attempts: int = 3):
        address = channel["address"]
        calls.append(address)
        assert attempts == 3
        if fail_all:
            raise GasSensorError(f"地址{address}读取失败：无响应")
        response_name = {1: "dust", 2: "o2", 3: "co2", 4: "ph3"}[address]
        return parse_modbus_response(
            RESPONSES[response_name],
            expected_address=address,
            expected_type=channel["expected_type"],
        )

    monkeypatch.setattr(reader, "_query_channel", fake_query)
    fresh = reader.read_all()
    assert fresh["status"] == "ok"
    assert fresh["fresh_channels"] == ["co2", "dust", "o2", "ph3"]
    assert fresh["cached_channels"] == []

    fail_all = True
    cached = reader.read_all()
    assert cached["status"] == "partial"
    assert cached["fresh_channels"] == []
    assert cached["cached_channels"] == ["co2", "dust", "o2", "ph3"]
    assert all(reading["cached"] for reading in cached["gases"].values())
    assert cached["dust"]["cached"] is True
    assert set(cached["errors"]) == {"dust", "o2", "co2", "ph3"}


@pytest.mark.parametrize(
    ("failed_addresses", "error_type", "expected_descriptors"),
    [
        ({1, 2, 3, 4}, GasSensorError, [17, 18]),
        ({1}, OSError, [17, 18]),
        ({1}, termios.error, [17, 18]),
        ({1}, GasSensorError, [17]),
    ],
    ids=["no-replies", "device-error", "termios-error", "one-channel-missing"],
)
def test_background_reader_recovers_from_bus_faults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failed_addresses: set[int],
    error_type: type[Exception],
    expected_descriptors: list[int],
) -> None:
    port = "/dev/ttyUSB-test"
    reader = GasSensorReader(port, cache_path=tmp_path / "readings.json")
    opened: list[int] = []
    closed: list[int] = []
    queried: set[int] = set()

    def open_port(path: str) -> int:
        assert path == port
        assert opened == closed
        assert len(opened) < len(expected_descriptors)
        if opened:
            assert "port" in reader._background_errors
        fd = expected_descriptors[len(opened)]
        opened.append(fd)
        return fd

    def query(fd: int, channel: dict, **_kwargs):
        address = channel["address"]
        first_request = fd == 17 and address not in queried
        queried.add(address)
        if first_request and address in failed_addresses:
            raise error_type("串口测试故障")
        if address == 4 and not first_request:
            reader._stop_event.set()
        name = {1: "dust", 2: "o2", 3: "co2", 4: "ph3"}[address]
        return parse_modbus_response(
            RESPONSES[name],
            expected_address=address,
            expected_type=channel["expected_type"],
        )

    monkeypatch.setattr(reader, "_resolve_port", lambda: port)
    monkeypatch.setattr(reader, "_open_port", open_port)
    monkeypatch.setattr(reader, "_configure", lambda _fd: None)
    monkeypatch.setattr(reader, "_query_channel", query)
    monkeypatch.setattr(reader._stop_event, "wait", lambda _seconds: reader._stop_event.is_set())
    monkeypatch.setattr("server.gas_sensor.os.close", closed.append)

    reader._run()

    assert opened == closed == expected_descriptors
    assert set(reader._cache) == set(RESPONSES)
    assert reader._background_errors == {}


def test_last_good_reading_is_persisted_across_process_restart(tmp_path: Path) -> None:
    cache_path = tmp_path / "gas-readings.json"
    reading = parse_modbus_response(
        RESPONSES["o2"], expected_address=2, expected_type=67
    ).to_dict()

    reader = GasSensorReader("/dev/ttyUSB-test", cache_path=cache_path)
    reader._remember("o2", reading)
    reader._persist_cache(force=True)

    restored = GasSensorReader("/dev/ttyUSB-test", cache_path=cache_path)
    assert restored._cache["o2"]["value"] == 20.9
    assert restored._cache["o2"]["status_code"] == 1
    assert restored._cache_updated_epoch["o2"] > 0


@pytest.mark.parametrize(
    ("channel", "address", "gas_type", "value", "unit", "decimals"),
    [
        ("o2", 2, 67, 20.9, "%VOL", 1),
        ("co2", 3, 6, 670.0, "ppm", 0),
        ("ph3", 4, 69, 0.0, "ppm", 1),
    ],
)
def test_parse_actual_sensor_frames(
    channel: str,
    address: int,
    gas_type: int,
    value: float,
    unit: str,
    decimals: int,
) -> None:
    reading = parse_modbus_response(
        RESPONSES[channel],
        expected_address=address,
        expected_type=gas_type,
    )
    assert reading.value == value
    assert reading.unit == unit
    assert reading.decimals == decimals
    assert reading.status == "正常"
    assert reading.gas_type_code == gas_type
    assert reading.type_matches is True


def test_parse_rejects_bad_crc() -> None:
    damaged = RESPONSES["ph3"][:-1] + b"\x00"
    with pytest.raises(GasSensorError, match="CRC错误"):
        parse_modbus_response(damaged, expected_address=4, expected_type=69)


def test_address_one_is_normalized_as_dust() -> None:
    reading = parse_modbus_response(
        RESPONSES["dust"], expected_address=1, expected_type=11
    )
    dust = dust_payload(reading)
    assert dust["value_ug_m3"] == 3.0
    assert dust["value"] == 0.003
    assert dust["unit"] == "mg/m3"
    assert dust["low_alarm"] == 0.075
    assert dust["high_alarm"] == 0.15
    assert dust["full_scale"] == 1.0
    assert dust["firmware_unit"] == "ppm"
    assert dust["firmware_type_code"] == 11
