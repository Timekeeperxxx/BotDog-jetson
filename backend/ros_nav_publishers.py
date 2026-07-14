from __future__ import annotations

import math
import time
from typing import Any, Callable


def publish_bool_message(
    *,
    node: Any,
    publisher: Any,
    lock: Any,
    topic: str,
    value: bool,
    not_ready_message: str,
) -> dict[str, Any]:
    if node is None or publisher is None:
        raise RuntimeError(not_ready_message)

    from std_msgs.msg import Bool

    msg = Bool()
    msg.data = bool(value)
    with lock:
        publisher.publish(msg)

    return {
        "success": True,
        "topic": topic,
        "data": bool(value),
    }


def publish_zero_cmd_vel(
    *,
    node: Any,
    publisher: Any,
    lock: Any,
    publish_count: int = 10,
    interval_s: float = 0.03,
) -> dict[str, Any]:
    if node is None or publisher is None:
        raise RuntimeError("ROS2 cmd_vel 发布器未就绪")

    from geometry_msgs.msg import Twist

    count = max(1, int(publish_count))
    interval = max(0.0, float(interval_s))
    msg = Twist()
    with lock:
        for _ in range(count):
            publisher.publish(msg)
            if interval > 0:
                time.sleep(interval)

    return {
        "success": True,
        "topic": "/cmd_vel",
        "publish_count": count,
        "linear": {"x": 0.0, "y": 0.0, "z": 0.0},
        "angular": {"x": 0.0, "y": 0.0, "z": 0.0},
    }


def publish_goal_xyz_yaw(
    *,
    node: Any,
    xyz_publisher: Any,
    yaw_publisher: Any,
    lock: Any,
    waypoint: dict[str, Any],
    frame_id: str,
    xyz_topic: str,
    yaw_topic: str,
    publish_count: int,
    publish_interval_s: float,
    planner_goal_z: Callable[[float], float],
    planner_goal_z_offset_m: float,
) -> dict[str, Any]:
    if node is None:
        raise RuntimeError("ROS2 导航节点未就绪")
    if xyz_publisher is None:
        raise RuntimeError("ROS2 clicked_point 发布器未就绪")
    if yaw_publisher is None:
        raise RuntimeError("ROS2 goal_yaw 发布器未就绪")

    from geometry_msgs.msg import PointStamped
    from std_msgs.msg import Float64

    yaw = float(waypoint.get("yaw", 0.0))

    yaw_msg = Float64()
    yaw_msg.data = yaw

    point_msg = PointStamped()
    point_msg.header.stamp = node.get_clock().now().to_msg()
    point_msg.header.frame_id = str(waypoint.get("frame_id") or frame_id)
    point_msg.point.x = float(waypoint["x"])
    point_msg.point.y = float(waypoint["y"])
    original_z = float(waypoint.get("z", 0.0))
    point_msg.point.z = planner_goal_z(original_z)

    actual_publish_count = 0
    for index in range(publish_count):
        point_msg.header.stamp = node.get_clock().now().to_msg()
        with lock:
            yaw_publisher.publish(yaw_msg)
            xyz_publisher.publish(point_msg)
        actual_publish_count += 1
        if index < publish_count - 1:
            time.sleep(publish_interval_s)

    return {
        "success": True,
        "xyz_topic": xyz_topic,
        "yaw_topic": yaw_topic,
        "publish_count": actual_publish_count,
        "waypoint_id": waypoint.get("id"),
        "x": point_msg.point.x,
        "y": point_msg.point.y,
        "z": point_msg.point.z,
        "ground_z": original_z,
        "planner_goal_z": point_msg.point.z,
        "planner_goal_z_offset_m": float(planner_goal_z_offset_m),
        "yaw": yaw,
        "frame_id": point_msg.header.frame_id,
    }


def euler_to_quaternion(roll: float, pitch: float, yaw: float) -> dict[str, float]:
    cr = math.cos(float(roll) / 2.0)
    sr = math.sin(float(roll) / 2.0)
    cp = math.cos(float(pitch) / 2.0)
    sp = math.sin(float(pitch) / 2.0)
    cy = math.cos(float(yaw) / 2.0)
    sy = math.sin(float(yaw) / 2.0)
    return {
        "w": cr * cp * cy + sr * sp * sy,
        "x": sr * cp * cy - cr * sp * sy,
        "y": cr * sp * cy + sr * cp * sy,
        "z": cr * cp * sy - sr * sp * cy,
    }


def publish_initial_pose_messages(
    *,
    node: Any,
    publisher: Any,
    lock: Any,
    pose_msg_cls: Any,
    x: float,
    y: float,
    z: float,
    roll: float,
    pitch: float,
    yaw: float,
    frame_id: str,
    publish_count: int,
    publish_interval_s: float,
) -> int:
    quaternion = euler_to_quaternion(roll, pitch, yaw)
    actual_publish_count = 0

    for index in range(publish_count):
        msg = pose_msg_cls()
        msg.header.stamp = node.get_clock().now().to_msg()
        msg.header.frame_id = frame_id

        msg.pose.pose.position.x = float(x)
        msg.pose.pose.position.y = float(y)
        msg.pose.pose.position.z = float(z)
        msg.pose.pose.orientation.w = quaternion["w"]
        msg.pose.pose.orientation.x = quaternion["x"]
        msg.pose.pose.orientation.y = quaternion["y"]
        msg.pose.pose.orientation.z = quaternion["z"]

        with lock:
            publisher.publish(msg)
        actual_publish_count += 1

        if index < publish_count - 1:
            time.sleep(publish_interval_s)

    return actual_publish_count


def initial_pose_subscription_counts(node: Any, publisher: Any, topic: str) -> dict[str, int]:
    if node is None or publisher is None:
        raise RuntimeError("ROS2 initial_pose 发布器未就绪")

    graph_count = 0
    matched_count = 0

    count_subscribers = getattr(node, "count_subscribers", None)
    if callable(count_subscribers):
        graph_count = int(count_subscribers(topic))

    get_count = getattr(publisher, "get_subscription_count", None)
    if callable(get_count):
        matched_count = int(get_count())

    if not callable(count_subscribers) and not callable(get_count):
        raise RuntimeError("ROS2 initial_pose 发布器不支持订阅者计数")

    return {
        "graph_count": graph_count,
        "matched_count": matched_count,
        "subscriber_count": max(graph_count, matched_count),
    }


def backend_initial_pose_publisher_count(node: Any, publisher: Any, topic: str) -> int:
    if node is None or publisher is None:
        return 0

    count_publishers = getattr(node, "count_publishers", None)
    if callable(count_publishers):
        return int(count_publishers(topic))
    return 1


def wait_for_initial_pose_subscribers(
    *,
    topic: str,
    timeout_s: float,
    subscription_counts: Callable[[], dict[str, int]],
    backend_publisher_count: Callable[[], int],
) -> dict[str, Any]:
    deadline = time.time() + max(0.1, float(timeout_s))
    last_counts = {
        "graph_count": 0,
        "matched_count": 0,
        "subscriber_count": 0,
        "backend_publisher_count": 0,
    }

    while time.time() < deadline:
        counts = subscription_counts()
        publisher_count = backend_publisher_count()
        last_counts = {
            **counts,
            "backend_publisher_count": publisher_count,
        }
        if last_counts["subscriber_count"] > 0 and publisher_count > 0:
            return {
                "ready": True,
                "topic": topic,
                **last_counts,
                "message": (
                    f"{topic} 已发现订阅者 "
                    f"{last_counts['subscriber_count']} 个"
                    f"（graph={last_counts['graph_count']} matched={last_counts['matched_count']} "
                    f"publisher={publisher_count}）"
                ),
            }
        time.sleep(0.2)

    if last_counts["backend_publisher_count"] <= 0:
        message = (
            f"后端 {topic} publisher 未进入 ROS graph"
            f"（publisher={last_counts['backend_publisher_count']} "
            f"graph={last_counts['graph_count']} matched={last_counts['matched_count']}），"
            "请检查后端 ROS 导航桥是否已恢复"
        )
    else:
        message = (
            f"{topic} 暂无订阅者"
            f"（graph={last_counts['graph_count']} matched={last_counts['matched_count']} "
            f"publisher={last_counts['backend_publisher_count']}），"
            "Super-LIO 还未准备接收 initialpose 或后端 ROS graph 与导航进程不一致"
        )

    return {
        "ready": False,
        "topic": topic,
        **last_counts,
        "message": message,
    }
