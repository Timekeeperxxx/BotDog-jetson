from __future__ import annotations

import pytest

from backend.ws_event_broadcaster import EventBroadcaster


class _FakeWebSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.messages: list[dict[str, object]] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, message: dict[str, object]) -> None:
        self.messages.append(message)


@pytest.mark.asyncio
async def test_connect_replays_current_navigation_snapshot() -> None:
    state = {
        "robot_pose": {"x": 1.0, "y": 2.0},
        "global_path": {"frame_id": "map", "points": [{"x": 1.0}]},
        "execution_path": {"frame_id": "map", "points": [{"x": 2.0}]},
        "localization_status": {"status": "ok"},
        "navigation_status": {"status": "navigating"},
    }
    broadcaster = EventBroadcaster(nav_state_provider=lambda: state)
    websocket = _FakeWebSocket()

    await broadcaster.connect(websocket)  # type: ignore[arg-type]

    assert websocket.accepted is True
    assert websocket.messages[0]["msg_type"] == "welcome"
    snapshot_messages = websocket.messages[1:]
    assert [message["type"] for message in snapshot_messages] == [
        "nav.robot_pose",
        "nav.global_path",
        "nav.execution_path",
        "nav.localization_status",
        "nav.navigation_status",
    ]
    assert all(message["snapshot"] is True for message in snapshot_messages)
    assert snapshot_messages[2]["data"] == state["execution_path"]
    assert broadcaster.connection_count == 1


@pytest.mark.asyncio
async def test_connect_replays_null_paths_to_clear_stale_frontend_state() -> None:
    broadcaster = EventBroadcaster(
        nav_state_provider=lambda: {
            "robot_pose": None,
            "global_path": None,
            "execution_path": None,
            "localization_status": {"status": "initializing"},
            "navigation_status": {"status": "idle"},
        }
    )
    websocket = _FakeWebSocket()

    await broadcaster.connect(websocket)  # type: ignore[arg-type]

    events = {message["type"]: message for message in websocket.messages[1:]}
    assert events["nav.robot_pose"]["data"] is None
    assert events["nav.global_path"]["data"] is None
    assert events["nav.execution_path"]["data"] is None
