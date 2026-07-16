from __future__ import annotations

from types import SimpleNamespace

from backend.logging_config import (
    _access_file_filter,
    _backend_file_filter,
    _debug_file_filter,
    _ffmpeg_file_filter,
    _patch_record,
)


def _record(*, level: int = 20, access: bool = False, ffmpeg: bool = False):
    return {
        "level": SimpleNamespace(no=level),
        "extra": {
            "access_log": access,
            "raw_ffmpeg": ffmpeg,
        },
    }


def test_patch_record_supplies_stable_context_defaults() -> None:
    record = {"name": "backend.alert_service", "extra": {}}

    _patch_record(record)

    assert record["extra"] == {
        "domain": "alert_service",
        "access_log": False,
        "raw_ffmpeg": False,
        "request_id": "-",
    }


def test_runtime_sinks_are_mutually_exclusive() -> None:
    application_info = _record(level=20)
    application_debug = _record(level=10)
    access = _record(level=20, access=True)
    ffmpeg = _record(level=10, ffmpeg=True)

    assert _backend_file_filter(application_info) is True
    assert _debug_file_filter(application_info) is False
    assert _access_file_filter(application_info) is False
    assert _ffmpeg_file_filter(application_info) is False

    assert _backend_file_filter(application_debug) is True
    assert _debug_file_filter(application_debug) is True

    assert _backend_file_filter(access) is False
    assert _debug_file_filter(access) is False
    assert _access_file_filter(access) is True

    assert _backend_file_filter(ffmpeg) is False
    assert _debug_file_filter(ffmpeg) is False
    assert _ffmpeg_file_filter(ffmpeg) is True
