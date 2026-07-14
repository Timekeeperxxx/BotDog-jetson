from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from pathlib import Path

from backend.api.routes import system as system_routes
from backend.api.routes.system import system_diagnostics, system_startup
from backend.app_bootstrap import (
    evaluate_security_config,
    is_default_admin_password,
    is_default_jwt_secret,
)
from backend.main import _write_startup_summary_snapshot


def test_system_startup_returns_summary_items() -> None:
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                startup_summary={
                    "数据库": ("ready", "数据库连接可用"),
                    "API 服务": ("ready", "地址=http://0.0.0.0:8000"),
                }
            )
        )
    )

    result = asyncio.run(system_startup(request))

    assert result.status == "全部模块正常"
    assert [item.name for item in result.items] == ["数据库", "API 服务"]
    assert result.items[0].status == "ready"
    assert result.items[0].detail == "数据库连接可用"


def test_write_startup_summary_snapshot(tmp_path: Path) -> None:
    generated_at, snapshot_file = _write_startup_summary_snapshot(
        {
            "数据库": ("ready", "数据库连接可用"),
            "API 服务": ("ready", "地址=http://0.0.0.0:8000"),
        },
        tmp_path,
    )

    snapshot_path = Path(snapshot_file)
    assert generated_at
    assert snapshot_path.is_file()

    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert payload["generated_at"] == generated_at
    assert [item["name"] for item in payload["items"]] == ["数据库", "API 服务"]


def test_bootstrap_detects_current_default_credentials() -> None:
    assert is_default_admin_password("admin123")
    assert is_default_admin_password("please_change_me")
    assert not is_default_admin_password("ValidPassword123!")

    assert is_default_jwt_secret("please_change_me_to_a_random_string")
    assert is_default_jwt_secret("please_change_me")
    assert not is_default_jwt_secret("custom-secret")


def test_security_config_summary_reports_defaults_as_degraded() -> None:
    status, detail = evaluate_security_config(
        auth_enabled=True,
        admin_password="admin123",
        jwt_secret="please_change_me_to_a_random_string",
        cors_allow_origins=["*"],
        cors_allow_credentials=False,
    )

    assert status == "degraded"
    assert "管理员密码仍为默认值" in detail
    assert "JWT_SECRET 仍为默认值" in detail
    assert "CORS 允许任意来源" in detail


def test_security_config_summary_accepts_hardened_config() -> None:
    status, detail = evaluate_security_config(
        auth_enabled=True,
        admin_password="ValidPassword123!",
        jwt_secret="custom-secret",
        cors_allow_origins=["http://192.168.144.104:8000"],
        cors_allow_credentials=False,
    )

    assert status == "ready"
    assert detail == "鉴权、默认凭据和 CORS 基础配置正常"


def test_system_diagnostics_returns_aggregate_checks(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / "BotDog"
    pipeline_script = project_root / "scripts" / "run-pipeline.sh"
    mediamtx_config = project_root / "config" / "mediamtx.yml"
    frontend_dist = project_root / "frontend" / "dist"
    pipeline_script.parent.mkdir(parents=True)
    mediamtx_config.parent.mkdir(parents=True)
    frontend_dist.mkdir(parents=True)
    pipeline_script.write_text("#!/bin/bash\n", encoding="utf-8")
    mediamtx_config.write_text("paths: {}\n", encoding="utf-8")

    monkeypatch.setattr(system_routes, "_PIPELINE_SCRIPT", pipeline_script)
    monkeypatch.setattr(system_routes, "_PROJECT_ROOT", project_root)

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                startup_summary={
                    "安全配置": ("ready", "鉴权、默认凭据和 CORS 基础配置正常"),
                    "数据库": ("ready", "数据库连接可用"),
                }
            )
        )
    )
    user = SimpleNamespace(username="admin")

    result = asyncio.run(system_diagnostics(request, user))

    assert result["requested_by"] == "admin"
    assert {check["name"] for check in result["checks"]} >= {
        "系统健康",
        "启动摘要",
        "运动安全",
        "视频 Pipeline 脚本",
        "MediaMTX 配置",
        "前端构建产物",
        "磁盘空间",
    }
    assert result["level"] in {"normal", "warning", "error"}
