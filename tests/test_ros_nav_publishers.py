from __future__ import annotations

import sys
import threading
from types import ModuleType, SimpleNamespace

import pytest

from backend.ros_nav_publishers import (
    euler_to_quaternion,
    publish_goal_xyz_yaw,
    wait_for_initial_pose_subscribers,
)
from backend.services_nav_state import (
    get_nav_state,
    set_navigation_idle,
    update_execution_path,
    update_global_path,
)
from backend.services_ros_nav import RosNavBridge


def test_euler_to_quaternion_identity():
    quaternion = euler_to_quaternion(0.0, 0.0, 0.0)

    assert quaternion["w"] == pytest.approx(1.0)
    assert quaternion["x"] == pytest.approx(0.0)
    assert quaternion["y"] == pytest.approx(0.0)
    assert quaternion["z"] == pytest.approx(0.0)


def test_wait_for_initial_pose_subscribers_reports_ready():
    result = wait_for_initial_pose_subscribers(
        topic="/initialpose",
        timeout_s=0.1,
        subscription_counts=lambda: {
            "graph_count": 1,
            "matched_count": 0,
            "subscriber_count": 1,
        },
        backend_publisher_count=lambda: 1,
    )

    assert result["ready"] is True
    assert result["topic"] == "/initialpose"
    assert result["subscriber_count"] == 1
    assert result["backend_publisher_count"] == 1


def test_task_start_rejects_missing_task_navigator(monkeypatch):
    class PublisherWithoutSubscribers:
        def get_subscription_count(self) -> int:
            return 0

    bridge = RosNavBridge.__new__(RosNavBridge)
    bridge._node = object()
    bridge._nav_task_start_publisher = PublisherWithoutSubscribers()
    bridge._publisher_lock = threading.RLock()

    timestamps = iter([0.0, 3.0])
    monkeypatch.setattr("backend.services_ros_nav.time.monotonic", lambda: next(timestamps))

    with pytest.raises(RuntimeError, match="nav_task_start 没有订阅者"):
        bridge.publish_navigation_task_start(True)


def _install_fake_goal_messages(monkeypatch):
    class PointStamped:
        def __init__(self) -> None:
            self.header = SimpleNamespace(stamp=None, frame_id="")
            self.point = SimpleNamespace(x=0.0, y=0.0, z=0.0)

    class Float64:
        def __init__(self) -> None:
            self.data = 0.0

    geometry_msgs = ModuleType("geometry_msgs")
    geometry_msgs_msg = ModuleType("geometry_msgs.msg")
    geometry_msgs_msg.PointStamped = PointStamped
    geometry_msgs.msg = geometry_msgs_msg
    std_msgs = ModuleType("std_msgs")
    std_msgs_msg = ModuleType("std_msgs.msg")
    std_msgs_msg.Float64 = Float64
    std_msgs.msg = std_msgs_msg
    monkeypatch.setitem(sys.modules, "geometry_msgs", geometry_msgs)
    monkeypatch.setitem(sys.modules, "geometry_msgs.msg", geometry_msgs_msg)
    monkeypatch.setitem(sys.modules, "std_msgs", std_msgs)
    monkeypatch.setitem(sys.modules, "std_msgs.msg", std_msgs_msg)


def test_goal_publisher_sends_one_explicit_same_floor_goal(monkeypatch):
    _install_fake_goal_messages(monkeypatch)
    xyz_messages = []
    yaw_messages = []

    class Publisher:
        def __init__(self, messages):
            self.messages = messages

        def publish(self, msg) -> None:
            self.messages.append(msg)

    node = SimpleNamespace(
        get_clock=lambda: SimpleNamespace(
            now=lambda: SimpleNamespace(to_msg=lambda: "stamp")
        )
    )
    result = publish_goal_xyz_yaw(
        node=node,
        xyz_publisher=Publisher(xyz_messages),
        yaw_publisher=Publisher(yaw_messages),
        lock=threading.RLock(),
        waypoint={
            "id": "wp-lower",
            "x": 44.296,
            "y": -0.167,
            "z": -11.282,
            "yaw": 0.75,
            "frame_id": "map",
        },
        frame_id="map",
        xyz_topic="/clicked_point",
        yaw_topic="goal_yaw",
        publish_count=1,
        publish_interval_s=0.0,
        planner_goal_z=lambda value: value,
        planner_goal_z_offset_m=0.0,
    )

    assert len(xyz_messages) == 1
    assert len(yaw_messages) == 1
    assert xyz_messages[0].point.z == pytest.approx(-11.282)
    assert result["z"] == pytest.approx(-11.282)
    assert result["ground_z"] == pytest.approx(-11.282)


def test_goal_publisher_rejects_missing_z_instead_of_defaulting_zero(monkeypatch):
    _install_fake_goal_messages(monkeypatch)

    with pytest.raises(ValueError, match="z=0"):
        publish_goal_xyz_yaw(
            node=SimpleNamespace(),
            xyz_publisher=object(),
            yaw_publisher=object(),
            lock=threading.RLock(),
            waypoint={"x": 1.0, "y": 2.0, "yaw": 0.0},
            frame_id="map",
            xyz_topic="/clicked_point",
            yaw_topic="goal_yaw",
            publish_count=1,
            publish_interval_s=0.0,
            planner_goal_z=lambda value: value,
            planner_goal_z_offset_m=0.0,
        )


def test_goal_bridge_waits_for_both_subscribers_before_single_publish(monkeypatch):
    _install_fake_goal_messages(monkeypatch)
    xyz_messages = []
    yaw_messages = []

    class Publisher:
        def __init__(self, messages, subscription_counts):
            self.messages = messages
            self.subscription_counts = iter(subscription_counts)
            self.last_subscription_count = 0

        def get_subscription_count(self) -> int:
            self.last_subscription_count = next(
                self.subscription_counts,
                self.last_subscription_count,
            )
            return self.last_subscription_count

        def publish(self, msg) -> None:
            assert self.last_subscription_count > 0
            self.messages.append(msg)

    bridge = RosNavBridge.__new__(RosNavBridge)
    bridge._node = SimpleNamespace(
        get_clock=lambda: SimpleNamespace(
            now=lambda: SimpleNamespace(to_msg=lambda: "stamp")
        )
    )
    bridge._goal_xyz_publisher = Publisher(xyz_messages, [0, 1])
    bridge._goal_yaw_publisher = Publisher(yaw_messages, [0, 1])
    bridge._publisher_lock = threading.RLock()
    monkeypatch.setattr("backend.services_ros_nav.time.sleep", lambda _value: None)

    result = bridge._publish_goal_xyz_yaw_inner(
        {
            "id": "wp-1",
            "x": 1.0,
            "y": 2.0,
            "z": -0.5,
            "yaw": 0.25,
            "frame_id": "map",
        }
    )

    assert len(xyz_messages) == 1
    assert len(yaw_messages) == 1
    assert result["publish_count"] == 1


def test_goal_bridge_fails_without_both_subscribers_and_does_not_publish(
    monkeypatch,
):
    _install_fake_goal_messages(monkeypatch)
    xyz_messages = []
    yaw_messages = []

    class Publisher:
        def __init__(self, messages, subscription_count):
            self.messages = messages
            self.subscription_count = subscription_count

        def get_subscription_count(self) -> int:
            return self.subscription_count

        def publish(self, msg) -> None:
            self.messages.append(msg)

    bridge = RosNavBridge.__new__(RosNavBridge)
    bridge._node = SimpleNamespace()
    bridge._goal_xyz_publisher = Publisher(xyz_messages, 1)
    bridge._goal_yaw_publisher = Publisher(yaw_messages, 0)
    bridge._publisher_lock = threading.RLock()
    timestamps = iter([0.0, 3.0])
    monkeypatch.setattr(
        "backend.services_ros_nav.time.monotonic",
        lambda: next(timestamps),
    )

    with pytest.raises(
        RuntimeError,
        match=r"goal_yaw 订阅者=0",
    ):
        bridge._publish_goal_xyz_yaw_inner(
            {
                "id": "wp-1",
                "x": 1.0,
                "y": 2.0,
                "z": -0.5,
                "yaw": 0.25,
                "frame_id": "map",
            }
        )

    assert xyz_messages == []
    assert yaw_messages == []


def test_goal_bridge_rejects_publishers_recreated_while_waiting():
    old_messages = []
    new_messages = []

    class Publisher:
        def __init__(self, messages):
            self.messages = messages

        def publish(self, msg) -> None:
            self.messages.append(msg)

    bridge = RosNavBridge.__new__(RosNavBridge)
    old_node = object()
    old_xyz_publisher = Publisher(old_messages)
    old_yaw_publisher = Publisher(old_messages)
    bridge._node = old_node
    bridge._goal_xyz_publisher = old_xyz_publisher
    bridge._goal_yaw_publisher = old_yaw_publisher
    bridge._publisher_lock = threading.RLock()

    def recreate_publishers(**_kwargs) -> None:
        bridge._node = object()
        bridge._goal_xyz_publisher = Publisher(new_messages)
        bridge._goal_yaw_publisher = Publisher(new_messages)

    bridge._wait_for_goal_subscribers = recreate_publishers

    with pytest.raises(RuntimeError, match="发布器已重建"):
        bridge._publish_goal_xyz_yaw_inner(
            {
                "id": "wp-1",
                "x": 1.0,
                "y": 2.0,
                "z": -0.5,
                "yaw": 0.25,
            }
        )

    assert old_messages == []
    assert new_messages == []


def test_new_goal_replaces_frontend_paths_and_enters_planning(monkeypatch):
    set_navigation_idle()
    update_global_path(
        {
            "frame_id": "map",
            "points": [{"x": 1.0, "y": 1.0, "z": -0.4}],
            "timestamp": 1.0,
        }
    )
    update_execution_path(
        {
            "frame_id": "map",
            "points": [{"x": 1.0, "y": 1.0, "z": -0.4}],
            "timestamp": 1.0,
        }
    )
    broadcasts = []
    bridge = RosNavBridge.__new__(RosNavBridge)
    bridge._goal_submission_lock = threading.RLock()
    bridge._publish_goal_xyz_yaw_inner = lambda waypoint: {
        "success": True,
        "xyz_topic": "/clicked_point",
        "yaw_topic": "goal_yaw",
        "x": float(waypoint["x"]),
        "y": float(waypoint["y"]),
        "z": float(waypoint["z"]),
        "frame_id": "map",
    }
    bridge._submit_broadcast = lambda event_type, payload: broadcasts.append(
        (event_type, payload)
    )

    first = {"id": "wp-1", "name": "上层", "x": 1.0, "y": 2.0, "z": -0.4}
    second = {"id": "wp-2", "name": "下层", "x": 1.0, "y": 2.0, "z": -11.3}
    bridge.publish_goal_xyz_yaw(first)
    bridge.publish_goal_xyz_yaw(second)

    state = get_nav_state()
    assert state["global_path"] is None
    assert state["execution_path"] is None
    assert state["navigation_status"]["status"] == "planning"
    assert state["navigation_status"]["target_waypoint_id"] == "wp-2"
    assert "-11.300" in state["navigation_status"]["message"]
    assert bridge._last_goal_waypoint == second
    assert bridge._navigation_control_expected is True
    assert [event for event, _ in broadcasts].count("nav.global_path") == 2
    assert [event for event, _ in broadcasts].count("nav.navigation_status") == 2


def test_concurrent_web_goals_publish_and_replace_state_in_submission_order():
    bridge = RosNavBridge.__new__(RosNavBridge)
    bridge._goal_submission_lock = threading.RLock()
    bridge._latest_planning_generation = None
    bridge._latest_planning_status = None
    bridge._planning_status_seen = False
    bridge._planning_status_accept_generation_reset = False
    bridge._planning_status_awaiting_new_generation = False
    bridge._planning_generation_floor = None

    first_publish_entered = threading.Event()
    release_first_publish = threading.Event()
    second_publish_entered = threading.Event()
    publish_order = []
    replacement_order = []
    errors = []

    def publish_inner(waypoint):
        publish_order.append(waypoint["id"])
        if waypoint["id"] == "first":
            first_publish_entered.set()
            if not release_first_publish.wait(2.0):
                raise TimeoutError("test did not release first goal")
        else:
            second_publish_entered.set()
        return {
            "success": True,
            "x": waypoint["x"],
            "y": waypoint["y"],
            "z": waypoint["z"],
            "frame_id": "map",
        }

    bridge._publish_goal_xyz_yaw_inner = publish_inner
    bridge._replace_paths_and_status_for_new_goal = (
        lambda waypoint, _result: replacement_order.append(waypoint["id"])
    )

    first = {"id": "first", "x": 1.0, "y": 2.0, "z": -0.5}
    second = {"id": "second", "x": 3.0, "y": 4.0, "z": -0.5}

    def submit(waypoint) -> None:
        try:
            bridge.publish_goal_xyz_yaw(waypoint)
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    first_thread = threading.Thread(target=submit, args=(first,), daemon=True)
    second_thread = threading.Thread(target=submit, args=(second,), daemon=True)
    first_thread.start()
    assert first_publish_entered.wait(1.0)
    second_thread.start()
    try:
        assert not second_publish_entered.wait(0.05)
    finally:
        release_first_publish.set()
    first_thread.join(1.0)
    second_thread.join(1.0)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert errors == []
    assert publish_order == ["first", "second"]
    assert replacement_order == ["first", "second"]
    assert bridge._last_goal_waypoint == second
