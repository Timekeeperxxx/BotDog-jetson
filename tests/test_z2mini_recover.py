from __future__ import annotations

import importlib.util
import socket
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _load_recovery_module() -> ModuleType:
    script = Path(__file__).resolve().parents[1] / "scripts" / "z2mini-recover.py"
    spec = importlib.util.spec_from_file_location("z2mini_recover", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def recovery() -> ModuleType:
    return _load_recovery_module()


class FakeSocket:
    def __init__(self, responses: list[bytes | BaseException]) -> None:
        self.responses = responses
        self.sent: list[bytes] = []

    def __enter__(self) -> FakeSocket:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def settimeout(self, _timeout: float) -> None:
        return None

    def sendall(self, payload: bytes) -> None:
        self.sent.append(payload)

    def recv(self, _size: int) -> bytes:
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def test_service_recovery_verifies_processes_and_rtsp(
    recovery: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeSocket(
        [
            b"\xff\xfd\x01AXERA login: ",
            b"root\r\n/root # ",
            b"__BOTDOG_RECOVERY_OK__\r\n/root # ",
        ]
    )
    monkeypatch.setattr(recovery.socket, "create_connection", lambda *_args, **_kwargs: connection)

    result = recovery.recover_z2mini("192.168.123.108", timeout_seconds=8)

    assert result.recovered is True
    assert result.detail == "camera image service and RTSP listener verified"
    assert b"root\r\n" in connection.sent
    assert recovery.RECOVERY_COMMAND in connection.sent
    assert b"camera_gcu.sh" in recovery.RECOVERY_COMMAND
    assert b">/dev/null" in recovery.RECOVERY_COMMAND
    assert b"pidof main" in recovery.RECOVERY_COMMAND
    assert b"pidof gb_control" in recovery.RECOVERY_COMMAND
    assert b":554" in recovery.RECOVERY_COMMAND
    assert recovery.RECOVERY_OK not in recovery.RECOVERY_COMMAND
    assert recovery.RECOVERY_FAILED not in recovery.RECOVERY_COMMAND


def test_reboot_recovery_sends_only_fixed_reboot_command(
    recovery: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeSocket(
        [
            b"AXERA login: ",
            b"/root # ",
            b"",
        ]
    )
    monkeypatch.setattr(recovery.socket, "create_connection", lambda *_args, **_kwargs: connection)

    result = recovery.recover_z2mini(
        "192.168.123.108",
        timeout_seconds=8,
        mode="reboot",
    )

    assert result.recovered is True
    assert result.detail == "camera reboot initiated and console disconnected"
    assert recovery.REBOOT_COMMAND in connection.sent
    assert b"sync; reboot" in recovery.REBOOT_COMMAND
    assert recovery.RECOVERY_COMMAND not in connection.sent


def test_reboot_requires_console_disconnect(
    recovery: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeSocket(
        [
            b"AXERA login: ",
            b"/root # ",
            socket.timeout("timed out"),
        ]
    )
    monkeypatch.setattr(recovery.socket, "create_connection", lambda *_args, **_kwargs: connection)

    result = recovery.recover_z2mini(
        "192.168.123.108",
        timeout_seconds=8,
        mode="reboot",
    )

    assert result.recovered is False
    assert "did not disconnect" in result.detail


def test_recovery_rejects_camera_without_factory_script(
    recovery: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeSocket(
        [
            b"AXERA login: ",
            b"/root # ",
            b"__BOTDOG_RECOVERY_UNSUPPORTED__\r\n/root # ",
        ]
    )
    monkeypatch.setattr(recovery.socket, "create_connection", lambda *_args, **_kwargs: connection)

    result = recovery.recover_z2mini("192.168.123.108", timeout_seconds=8)

    assert result.recovered is False
    assert result.detail == "camera does not expose the factory recovery script"


def test_recovery_reports_console_timeout(recovery: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    connection = FakeSocket([socket.timeout("timed out")])
    monkeypatch.setattr(recovery.socket, "create_connection", lambda *_args, **_kwargs: connection)

    result = recovery.recover_z2mini("192.168.123.108", timeout_seconds=8)

    assert result.recovered is False
    assert "response timed out" in result.detail


def test_recovery_rejects_unknown_mode(recovery: ModuleType) -> None:
    with pytest.raises(ValueError, match="unsupported recovery mode"):
        recovery.recover_z2mini("192.168.123.108", mode="power-cycle")


def test_pipeline_escalates_service_failure_to_camera_reboot() -> None:
    script = (
        Path(__file__).resolve().parents[1] / "scripts" / "run-pipeline.sh"
    ).read_text(encoding="utf-8")

    service_recovery = '--mode service 2>&1'
    video_verification = 'scripts/rtsp-healthcheck.py'
    reboot_recovery = '--mode reboot 2>&1'

    assert service_recovery in script
    assert video_verification in script
    assert reboot_recovery in script
    assert script.index(service_recovery) < script.index(reboot_recovery)
    assert 'CAM1_RECOVERY_REBOOT_ENABLED="${CAM1_RECOVERY_REBOOT_ENABLED:-1}"' in script
