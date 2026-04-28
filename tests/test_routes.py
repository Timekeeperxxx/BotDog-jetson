"""
路由回归检查。

只调用 create_app() 读取注册的路由表，不启动 lifespan，
不连接数据库、ROS、AI、B2 适配器。
"""

import pytest
from fastapi.routing import APIRoute, APIWebSocketRoute

from backend.main import create_app


@pytest.fixture(scope="module")
def route_index() -> dict[tuple[str, str], APIRoute]:
    """构建 (METHOD, path) → APIRoute 索引，仅用于断言路由注册情况。"""
    app = create_app()
    index: dict[tuple[str, str], APIRoute] = {}
    for route in app.routes:
        if isinstance(route, APIRoute):
            for method in route.methods or []:
                index[(method.upper(), route.path)] = route
    return index


@pytest.fixture(scope="module")
def websocket_paths() -> set[str]:
    """收集已注册 WebSocket 路径。"""
    app = create_app()
    paths: set[str] = set()
    for route in app.routes:
        if isinstance(route, APIWebSocketRoute):
            paths.add(route.path)
    return paths


# ── 必须注册的 nav 路由（method, path）───────────────────────────────────────
NAV_ROUTES = [
    # 地图列表
    ("GET",    "/api/v1/nav/pcd-maps"),
    # 导航状态
    ("GET",    "/api/v1/nav/state"),
    # 页面打开通知
    ("POST",   "/api/v1/nav/page-open"),
    # 地图元数据
    ("GET",    "/api/v1/nav/pcd-maps/{map_id}/metadata"),
    # 地图预览点云
    ("GET",    "/api/v1/nav/pcd-maps/{map_id}/preview"),
    # 导航点列表（GET）和新建（POST）— 同 path 不同 method
    ("GET",    "/api/v1/nav/pcd-maps/{map_id}/waypoints"),
    ("POST",   "/api/v1/nav/pcd-maps/{map_id}/waypoints"),
    # 导航到指定点（两条路径注册同一 handler）
    ("POST",   "/api/v1/nav/pcd-maps/{map_id}/waypoints/{waypoint_id}"),
    ("POST",   "/api/v1/nav/pcd-maps/{map_id}/waypoints/{waypoint_id}/go-to"),
    # 删除导航点
    ("DELETE", "/api/v1/nav/pcd-maps/{map_id}/waypoints/{waypoint_id}"),
    # 导航急停
    ("POST",   "/api/v1/nav/e-stop"),
]

SESSION_ROUTES = [
    ("POST", "/api/v1/session/start"),
    ("POST", "/api/v1/session/stop"),
]

LOGS_ROUTES = [
    ("GET", "/api/v1/logs"),
]

EVIDENCE_ROUTES = [
    ("GET", "/api/v1/evidence"),
    ("DELETE", "/api/v1/evidence/{evidence_id}"),
    ("POST", "/api/v1/evidence/bulk-delete"),
]

SYSTEM_ROUTES = [
    ("GET", "/api/v1/system/health"),
]

CONTROL_DEBUG_ROUTES = [
    ("GET", "/api/v1/control/debug"),
]

CONFIG_ROUTES = [
    ("GET", "/api/v1/config"),
    ("POST", "/api/v1/config"),
    ("GET", "/api/v1/config/history"),
]

VIDEO_SOURCE_ROUTES = [
    ("GET", "/api/v1/video-sources"),
    ("GET", "/api/v1/video-sources/active"),
    ("POST", "/api/v1/video-sources"),
    ("PUT", "/api/v1/video-sources/{source_id}"),
    ("DELETE", "/api/v1/video-sources/{source_id}"),
]

NETWORK_INTERFACE_ROUTES = [
    ("GET", "/api/v1/network-interfaces"),
    ("POST", "/api/v1/network-interfaces"),
    ("PUT", "/api/v1/network-interfaces/{iface_id}"),
    ("DELETE", "/api/v1/network-interfaces/{iface_id}"),
]

AUDIO_ROUTES = [
    ("POST", "/api/v1/audio/play"),
    ("POST", "/api/v1/audio/stop"),
    ("GET", "/api/v1/audio/status"),
]

GUARD_MISSION_ROUTES = [
    ("POST", "/api/v1/guard-mission/enable"),
    ("POST", "/api/v1/guard-mission/disable"),
    ("POST", "/api/v1/guard-mission/abort"),
    ("GET", "/api/v1/guard-mission/status"),
]

CONTROL_ROUTES = [
    ("POST", "/api/v1/control/command"),
    ("POST", "/api/v1/control/stop"),
    ("POST", "/api/v1/control/e-stop"),
    ("POST", "/api/v1/control/e-stop/reset"),
]

FOCUS_ZONE_ROUTES = [
    ("GET", "/api/v1/focus-zones"),
    ("POST", "/api/v1/focus-zones"),
    ("PUT", "/api/v1/focus-zones/{zone_id}"),
    ("DELETE", "/api/v1/focus-zones/{zone_id}"),
]

AUTO_TRACK_ROUTES = [
    ("GET", "/api/v1/auto-track/debug"),
    ("POST", "/api/v1/auto-track/enable"),
    ("POST", "/api/v1/auto-track/disable"),
    ("POST", "/api/v1/auto-track/pause"),
    ("POST", "/api/v1/auto-track/resume"),
    ("POST", "/api/v1/auto-track/manual-override"),
    ("POST", "/api/v1/auto-track/release-override"),
    ("GET", "/api/v1/auto-track/arbiter"),
    ("POST", "/api/v1/auto-track/mark-known/{track_id}"),
    ("POST", "/api/v1/auto-track/unmark-known/{track_id}"),
    ("GET", "/api/v1/auto-track/known-list"),
]

TEST_ALERT_ROUTES = [
    ("POST", "/api/v1/test/alert"),
]

WEBSOCKET_ROUTES = [
    "/ws/telemetry",
    "/ws/event",
]


@pytest.mark.parametrize("method,path", NAV_ROUTES)
def test_nav_route_registered(route_index: dict, method: str, path: str) -> None:
    """每条 nav 路由必须以正确的 HTTP method 注册，拆分后不能丢失。"""
    assert (method, path) in route_index, (
        f"{method} {path} 未注册 ── 路由可能在拆分中丢失"
    )


@pytest.mark.parametrize("method,path", SESSION_ROUTES)
def test_session_route_registered(route_index: dict, method: str, path: str) -> None:
    """session 路由拆分后必须保持 method 与 path 不变。"""
    assert (method, path) in route_index, (
        f"{method} {path} 未注册 ── session 路由可能在拆分中丢失"
    )


@pytest.mark.parametrize("method,path", LOGS_ROUTES)
def test_logs_route_registered(route_index: dict, method: str, path: str) -> None:
    """logs 路由拆分后必须保持 method 与 path 不变。"""
    assert (method, path) in route_index, (
        f"{method} {path} 未注册 ── logs 路由可能在拆分中丢失"
    )


@pytest.mark.parametrize("method,path", EVIDENCE_ROUTES)
def test_evidence_route_registered(route_index: dict, method: str, path: str) -> None:
    """evidence 路由拆分后必须保持 method 与 path 不变。"""
    assert (method, path) in route_index, (
        f"{method} {path} 未注册 ── evidence 路由可能在拆分中丢失"
    )


@pytest.mark.parametrize("method,path", SYSTEM_ROUTES)
def test_system_route_registered(route_index: dict, method: str, path: str) -> None:
    """system 诊断路由拆分后必须保持 method 与 path 不变。"""
    assert (method, path) in route_index, (
        f"{method} {path} 未注册 ── system 路由可能在拆分中丢失"
    )


@pytest.mark.parametrize("method,path", CONTROL_DEBUG_ROUTES)
def test_control_debug_route_registered(route_index: dict, method: str, path: str) -> None:
    """control debug 路由拆分后必须保持 method 与 path 不变。"""
    assert (method, path) in route_index, (
        f"{method} {path} 未注册 ── control debug 路由可能在拆分中丢失"
    )


@pytest.mark.parametrize("method,path", CONFIG_ROUTES)
def test_config_route_registered(route_index: dict, method: str, path: str) -> None:
    """config 路由拆分后必须保持 method 与 path 不变。"""
    assert (method, path) in route_index, (
        f"{method} {path} 未注册 ── config 路由可能在拆分中丢失"
    )


@pytest.mark.parametrize("method,path", VIDEO_SOURCE_ROUTES)
def test_video_source_route_registered(route_index: dict, method: str, path: str) -> None:
    """video_sources 路由拆分后必须保持 method 与 path 不变。"""
    assert (method, path) in route_index, (
        f"{method} {path} 未注册 ── video_sources 路由可能在拆分中丢失"
    )


@pytest.mark.parametrize("method,path", NETWORK_INTERFACE_ROUTES)
def test_network_interface_route_registered(route_index: dict, method: str, path: str) -> None:
    """network_interfaces 路由拆分后必须保持 method 与 path 不变。"""
    assert (method, path) in route_index, (
        f"{method} {path} 未注册 ── network_interfaces 路由可能在拆分中丢失"
    )


@pytest.mark.parametrize("method,path", AUDIO_ROUTES)
def test_audio_route_registered(route_index: dict, method: str, path: str) -> None:
    """audio 路由拆分后必须保持 method 与 path 不变。"""
    assert (method, path) in route_index, (
        f"{method} {path} 未注册 ── audio 路由可能在拆分中丢失"
    )


@pytest.mark.parametrize("method,path", GUARD_MISSION_ROUTES)
def test_guard_mission_route_registered(route_index: dict, method: str, path: str) -> None:
    """guard_mission 路由拆分后必须保持 method 与 path 不变。"""
    assert (method, path) in route_index, (
        f"{method} {path} 未注册 ── guard_mission 路由可能在拆分中丢失"
    )


@pytest.mark.parametrize("method,path", CONTROL_ROUTES)
def test_control_route_registered(route_index: dict, method: str, path: str) -> None:
    """control 路由拆分后必须保持 method 与 path 不变。"""
    assert (method, path) in route_index, (
        f"{method} {path} 未注册 ── control 路由可能在拆分中丢失"
    )


@pytest.mark.parametrize("method,path", FOCUS_ZONE_ROUTES)
def test_focus_zone_route_registered(route_index: dict, method: str, path: str) -> None:
    """focus_zones 路由拆分后必须保持 method 与 path 不变。"""
    assert (method, path) in route_index, (
        f"{method} {path} 未注册 ── focus_zones 路由可能在拆分中丢失"
    )


@pytest.mark.parametrize("method,path", AUTO_TRACK_ROUTES)
def test_auto_track_route_registered(route_index: dict, method: str, path: str) -> None:
    """auto_track 路由拆分后必须保持 method 与 path 不变。"""
    assert (method, path) in route_index, (
        f"{method} {path} 未注册 ── auto_track 路由可能在拆分中丢失"
    )


@pytest.mark.parametrize("method,path", TEST_ALERT_ROUTES)
def test_test_alert_route_registered(route_index: dict, method: str, path: str) -> None:
    """test alert 路由拆分后必须保持 method 与 path 不变。"""
    assert (method, path) in route_index, (
        f"{method} {path} 未注册 ── test alert 路由可能在拆分中丢失"
    )


@pytest.mark.parametrize("path", WEBSOCKET_ROUTES)
def test_websocket_route_registered(websocket_paths: set[str], path: str) -> None:
    """WebSocket 路由拆分后必须保持 path 不变。"""
    assert path in websocket_paths, (
        f"{path} 未注册 ── WebSocket 路由可能在拆分中丢失"
    )
