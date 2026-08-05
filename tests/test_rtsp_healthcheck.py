from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _load_healthcheck_module() -> ModuleType:
    script = Path(__file__).resolve().parents[1] / "scripts" / "rtsp-healthcheck.py"
    spec = importlib.util.spec_from_file_location("rtsp_healthcheck", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def healthcheck() -> ModuleType:
    return _load_healthcheck_module()


def test_probe_accepts_video_stream(healthcheck: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "width": 2560, "height": 1440}
        ]
    }

    def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(healthcheck.subprocess, "run", fake_run)

    result = healthcheck.probe_rtsp_video("rtsp://camera/", timeout_seconds=8)

    assert result.ready is True
    assert result.detail == "video ready (h264, 2560x1440)"


def test_probe_rejects_port_without_video(healthcheck: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 0, stdout='{"streams": []}', stderr="")

    monkeypatch.setattr(healthcheck.subprocess, "run", fake_run)

    result = healthcheck.probe_rtsp_video("rtsp://camera/", timeout_seconds=8)

    assert result.ready is False
    assert result.detail == "RTSP source has no video stream"


def test_probe_reports_timeout(healthcheck: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd="ffprobe", timeout=8)

    monkeypatch.setattr(healthcheck.subprocess, "run", fake_run)

    result = healthcheck.probe_rtsp_video("rtsp://camera/", timeout_seconds=8)

    assert result.ready is False
    assert result.detail == "RTSP probe timed out after 8s"
