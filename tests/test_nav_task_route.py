from copy import deepcopy
from types import SimpleNamespace
import json

import pytest

from backend import services_nav_state as state
from backend.services_ros_nav import RosNavBridge


@pytest.fixture(autouse=True)
def isolated_task_route(monkeypatch):
    state.clear_global_path()
    monkeypatch.setattr(state, "_task_route_run_id", None)
    yield
    state.clear_global_path()


def route(status="ready", run_id="run-1"):
    return {"task_id": "task-1", "run_id": run_id, "frame_id": "map", "status": status,
            "current_index": 0, "segments": [{"points": [{"x": 0, "y": 1, "z": 0}, {"x": 2, "y": 1, "z": 0}],
            "waypoint": {"name": "A", "x": 2, "y": 1, "z": 0, "yaw": 0}}]}


def test_route_updates_preserve_full_path_and_clear_rejects_late_scene_data():
    state.begin_task_route()
    planning = {**route("planning"), "segments": []}
    assert state.update_task_route(planning) is not None
    assert state.update_task_route(route()) is not None
    original = state.get_nav_state()["task_route"]
    state.update_global_path({"points": [], "frame_id": "map"})
    assert state.get_nav_state()["task_route"] == original
    state.update_task_route(route("completed"))
    assert state.get_nav_state()["task_route"]["segments"] == original["segments"]
    state.clear_global_path()
    assert state.get_nav_state()["task_route"] is None
    assert state.update_task_route(route("running")) is None
    state.update_global_path({"points": [{"x": 10, "y": 0, "z": 0}], "frame_id": "map"})
    state.begin_task_route()
    assert state.get_nav_state()["global_path"] is None
    assert state.update_task_route(route("ready")) is None
    state.update_task_route({**route("planning", "run-2"), "segments": []})
    assert state.update_task_route(route("running")) is None
    assert state.update_task_route(route("ready", "run-2")) is not None
    state.clear_global_path()


def test_route_boundary_rejects_invalid_coordinates_and_broadcasts_empty_clear():
    state.begin_task_route()
    bridge = RosNavBridge.__new__(RosNavBridge)
    events = []
    bridge._submit_broadcast = lambda event, payload: events.append((event, payload))
    bridge._handle_task_route_message(SimpleNamespace(data=json.dumps({**route("planning"), "segments": []})))
    bridge._handle_task_route_message(SimpleNamespace(data=json.dumps(route())))
    assert events[-1][0] == "nav.task_route"
    original = deepcopy(state.get_nav_state()["task_route"])
    for bad in (float("nan"), float("inf"), "1", True):
        invalid = route()
        invalid["segments"][0]["points"][0]["x"] = bad
        bridge._handle_task_route_message(SimpleNamespace(data=json.dumps(invalid)))
        assert state.get_nav_state()["task_route"] == original
    bridge._handle_task_route_message(SimpleNamespace(data=json.dumps({**route("failed"), "segments": []})))
    assert state.get_nav_state()["task_route"]["segments"] == []
    assert events[-1][1]["segments"] == []
    state.clear_global_path()


@pytest.mark.asyncio
async def test_selecting_current_scene_restores_route_but_new_scene_clears(monkeypatch):
    from backend.api.routes import nav_pcd_routes
    import backend.services_nav_localization as localization
    import backend.services_nav_task_runtime as runtime
    import backend.services_pcd_maps as maps

    calls = []
    monkeypatch.setattr(localization, "load_current_scene", lambda strict=False: {"scene_id": "same"})
    monkeypatch.setattr(localization, "save_current_scene", lambda scene_id: {"scene_id": scene_id})
    monkeypatch.setattr(maps, "resolve_scene_path", lambda scene_id: scene_id)
    monkeypatch.setattr(maps, "find_scene_pcd_files", lambda path: {"wall": "map.pcd", "ground": "ground.pcd"})
    monkeypatch.setattr(runtime, "clear_nav_task_runtime", lambda: calls.append("clear-runtime"))
    monkeypatch.setattr(nav_pcd_routes, "cancel_pending_auto_track_resume", lambda reason: None)
    async def audit(*args, **kwargs):
        pass
    monkeypatch.setattr(nav_pcd_routes, "safe_write_audit_log", audit)
    state.begin_task_route()
    state.update_task_route({**route("planning", "scene-run"), "segments": []})
    state.update_task_route(route("ready", "scene-run"))
    user = SimpleNamespace(username="test", role="admin")
    await nav_pcd_routes.nav_select_pcd_scene("same", user=user, db=None)
    assert state.get_nav_state()["task_route"] is not None
    assert calls == []
    await nav_pcd_routes.nav_select_pcd_scene("different", user=user, db=None)
    assert state.get_nav_state()["task_route"] is None
    assert calls == ["clear-runtime"]


@pytest.mark.asyncio
async def test_select_first_scene_without_saved_state(monkeypatch):
    from backend.api.routes import nav_pcd_routes
    import backend.services_nav_localization as localization
    import backend.services_nav_task_runtime as runtime
    import backend.services_pcd_maps as maps

    def missing(strict=False):
        raise FileNotFoundError("no current scene yet")
    monkeypatch.setattr(localization, "load_current_scene", missing)
    monkeypatch.setattr(localization, "save_current_scene", lambda scene_id: {"scene_id": scene_id})
    monkeypatch.setattr(maps, "resolve_scene_path", lambda scene_id: scene_id)
    monkeypatch.setattr(maps, "find_scene_pcd_files", lambda path: {"wall": "map.pcd", "ground": "ground.pcd"})
    monkeypatch.setattr(runtime, "clear_nav_task_runtime", lambda: None)
    monkeypatch.setattr(nav_pcd_routes, "cancel_pending_auto_track_resume", lambda reason: None)
    async def audit(*args, **kwargs):
        pass
    monkeypatch.setattr(nav_pcd_routes, "safe_write_audit_log", audit)
    result = await nav_pcd_routes.nav_select_pcd_scene("first", user=SimpleNamespace(username="test", role="admin"), db=None)
    assert result["scene_id"] == "first"
