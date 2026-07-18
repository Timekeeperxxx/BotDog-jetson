from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import time
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

from .config import settings
from .logging_config import get_logger, get_logs_dir
from .schemas import utc_now_iso

radar_logger = get_logger("雷达检测")

DEFAULT_RADAR_TOPIC_CANDIDATES = (
    "/livox/lidar",
)
DERIVED_CLOUD_TOPIC_CANDIDATES = ("/cloud_world", "/lio/cloud_world", "/mapcloud", "/mapground")
RADAR_TYPE_HINTS = (
    "sensor_msgs/msg/LaserScan",
    "sensor_msgs/msg/PointCloud2",
    "livox_ros_driver2/msg/CustomMsg",
)
ROS2_COMMAND_TIMEOUT_S = 5.0
RADAR_PREFLIGHT_COMMAND_TIMEOUT_S = 1.5
RADAR_PREFLIGHT_DATA_TIMEOUT_S = 2.0
RADAR_PREFLIGHT_SUCCESS_CACHE_S = 2.0
LIVOX_DEFAULT_IP = "192.168.123.179"
LIVOX_NETWORK_COMMAND_TIMEOUT_S = 1.0
RADAR_MIN_NORMAL_HZ = 2.0
RADAR_MIN_WARNING_HZ = 0.5
LIVOX_DRIVER_COMMAND = ["ros2", "launch", "livox_ros_driver2", "msg_MID360_launch.py"]
LIVOX_DRIVER_TOPIC_WAIT_TIMEOUT_S = 18.0
LIVOX_DRIVER_TOPIC_POLL_INTERVAL_S = 0.5
LIVOX_DRIVER_STOP_TIMEOUT_S = 8.0
RADAR_HEALTH_LOG_NAME = "radar_health.log"

_radar_preflight_cache_lock = Lock()
_radar_preflight_success_cache: tuple[float, dict[str, Any]] | None = None


@dataclass(slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


def _coerce_output(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    return str(value)


def _radar_log_path():
    logs_dir = get_logs_dir()
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir / RADAR_HEALTH_LOG_NAME


def _write_radar_log(message: str) -> None:
    try:
        path = _radar_log_path()
        with path.open("a", encoding="utf-8") as f:
            f.write(f"{utc_now_iso()} | {message}\n")
    except Exception:
        return


def _run_ros2(args: list[str], timeout: float = ROS2_COMMAND_TIMEOUT_S) -> CommandResult:
    try:
        completed = subprocess.run(
            ["ros2", *args],
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            returncode=124,
            stdout=_coerce_output(exc.stdout),
            stderr=_coerce_output(exc.stderr),
            timed_out=True,
        )
    except FileNotFoundError:
        return CommandResult(returncode=127, stdout="", stderr="ros2 command not found")

    return CommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )


def _run_system_command(args: list[str], timeout: float) -> CommandResult:
    try:
        completed = subprocess.run(
            args,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            returncode=124,
            stdout=_coerce_output(exc.stdout),
            stderr=_coerce_output(exc.stderr),
            timed_out=True,
        )
    except FileNotFoundError:
        return CommandResult(returncode=127, stdout="", stderr=f"command not found: {args[0]}")

    return CommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )


def _read_network_attribute(interface: str, attribute: str) -> str | None:
    try:
        return (Path("/sys/class/net") / interface / attribute).read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return None


def check_livox_network_preflight() -> dict[str, Any]:
    """快速确认到 Livox 的有线物理链路，不依赖已经运行的 ROS 驱动。"""
    target_ip = os.environ.get("LIVOX_LIDAR_IP", LIVOX_DEFAULT_IP).strip() or LIVOX_DEFAULT_IP
    checks: list[dict[str, Any]] = []
    ip_command = shutil.which("ip")
    if not ip_command:
        checks.append(_check_item("network_route", False, "failed", "未找到 ip 命令"))
        return _radar_response(
            checks=checks,
            ok=False,
            level="error",
            message="雷达连接检查失败：系统缺少 ip 命令",
        )

    route_result = _run_system_command(
        [ip_command, "-4", "route", "get", target_ip],
        timeout=LIVOX_NETWORK_COMMAND_TIMEOUT_S,
    )
    route_text = f"{route_result.stdout}\n{route_result.stderr}".strip()
    interface_match = re.search(r"(?:^|\s)dev\s+(\S+)", route_result.stdout)
    interface = interface_match.group(1) if interface_match else None
    route_ok = route_result.returncode == 0 and interface is not None
    checks.append(
        _check_item(
            "network_route",
            route_ok,
            "normal" if route_ok else "failed",
            f"雷达路由：{target_ip} -> {interface}" if route_ok else f"无法找到到雷达 {target_ip} 的网络路由",
            {"target_ip": target_ip, "interface": interface, "output": route_text[-500:]},
        )
    )
    if not route_ok or interface is None:
        return _radar_response(
            checks=checks,
            ok=False,
            level="error",
            message=f"雷达未连接：无法找到到 Livox {target_ip} 的网络路由，请检查网卡配置",
        )

    operstate = _read_network_attribute(interface, "operstate")
    carrier = _read_network_attribute(interface, "carrier")
    link_ok = carrier == "1" and operstate not in {"down", "dormant", "notpresent", "lowerlayerdown"}
    checks.append(
        _check_item(
            "physical_link",
            link_ok,
            "normal" if link_ok else "failed",
            (
                f"网卡 {interface} 物理链路正常"
                if link_ok
                else f"网卡 {interface} 未建立物理链路"
            ),
            {"interface": interface, "operstate": operstate, "carrier": carrier},
        )
    )
    if not link_ok:
        return _radar_response(
            checks=checks,
            ok=False,
            level="error",
            message=f"雷达未连接：网卡 {interface} 未建立物理链路，请检查 Livox MID360 供电和网线",
        )

    return _radar_response(
        checks=checks,
        ok=True,
        level="normal",
        message=f"雷达物理链路正常（{interface} -> {target_ip}）",
    )


def _list_topics(timeout: float = ROS2_COMMAND_TIMEOUT_S) -> tuple[CommandResult, dict[str, str]]:
    result = _run_ros2(["topic", "list", "-t"], timeout=timeout)
    if result.returncode != 0:
        return result, {}
    return result, _parse_topic_list(result.stdout)


def _parse_topic_list(output: str) -> dict[str, str]:
    topics: dict[str, str] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = re.match(r"^(\S+)(?:\s+\[(.+)\])?$", line)
        if not match:
            continue
        topics[match.group(1)] = match.group(2) or ""
    return topics


def _select_radar_topic(topics: dict[str, str]) -> tuple[str | None, str | None]:
    for topic in DEFAULT_RADAR_TOPIC_CANDIDATES:
        if topic in topics:
            return topic, topics[topic]

    return None, None


def _is_derived_or_map_topic(topic: str) -> bool:
    lowered = topic.lower()
    if topic in DERIVED_CLOUD_TOPIC_CANDIDATES or topic == getattr(settings, "ROS_NAV_MAPPING_CLOUD_TOPIC", None):
        return True
    return lowered.startswith("/map") or "mapcloud" in lowered or "mapground" in lowered or "cloud_world" in lowered


def _select_livox_node_topic(topics: dict[str, str]) -> tuple[str | None, str | None, str | None]:
    result = _run_ros2(["node", "info", "/livox_lidar_publisher"], timeout=4.0)
    if result.returncode != 0:
        return None, None, result.stderr or result.stdout

    in_publishers = False
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line == "Publishers:":
            in_publishers = True
            continue
        if in_publishers and line.endswith(":") and not line.startswith("/"):
            break
        if not in_publishers:
            continue

        match = re.match(r"^(\S+):\s*(\S+)$", line)
        if not match:
            continue
        topic = match.group(1)
        topic_type = match.group(2)
        if topic in {"/parameter_events", "/rosout"}:
            continue
        if _is_derived_or_map_topic(topic):
            continue
        if topic_type in RADAR_TYPE_HINTS or "livox" in topic.lower() or "lidar" in topic.lower():
            return topic, topics.get(topic) or topic_type, None

    return None, None, result.stdout


def _parse_topic_info(output: str) -> tuple[int | None, int | None]:
    publisher_count: int | None = None
    subscription_count: int | None = None
    publisher_match = re.search(r"Publisher count:\s*(\d+)", output)
    subscription_match = re.search(r"Subscription count:\s*(\d+)", output)
    if publisher_match:
        publisher_count = int(publisher_match.group(1))
    if subscription_match:
        subscription_count = int(subscription_match.group(1))
    return publisher_count, subscription_count


def _parse_topic_hz(output: str) -> float | None:
    matches = re.findall(r"average rate:\s*([0-9]+(?:\.[0-9]+)?)", output)
    if not matches:
        return None
    return float(matches[-1])


def _measure_topic_hz(topic: str) -> tuple[CommandResult, float | None, str, float]:
    # ROS2 Humble 的 `ros2 topic hz` 不支持 --qos-profile / --qos-reliability；
    # 传入这些参数会直接以 returncode=2 退出。Livox CustomMsg 使用默认订阅
    # 已能正常测得频率，因此只执行兼容 Humble 的命令。
    attempts = [("default", ["topic", "hz", topic, "--window", "5"])]

    last_result: CommandResult | None = None
    last_label = "default"
    total_started_at = time.monotonic()
    for label, args in attempts:
        started_at = time.monotonic()
        result = _run_ros2(args, timeout=7.0)
        frequency = _parse_topic_hz(f"{result.stdout}\n{result.stderr}")
        elapsed = time.monotonic() - started_at
        _write_radar_log(
            f"频率检查尝试：topic={topic} qos={label} elapsed_s={round(elapsed, 3)} "
            f"returncode={result.returncode} timed_out={result.timed_out} frequency_hz={frequency}"
        )
        if frequency is not None:
            return result, frequency, label, time.monotonic() - total_started_at

        last_result = result
        last_label = label
        # `ros2 topic hz` 是持续命令；超时只代表采样窗口结束，不代表没数据。
        if result.timed_out:
            break

    if last_result is None:
        last_result = CommandResult(returncode=1, stdout="", stderr="未执行频率检查")
    return last_result, None, last_label, time.monotonic() - total_started_at


def _measure_topic_hz_quick(topic: str) -> tuple[CommandResult, float | None]:
    """在很短的窗口内确认原始雷达 topic 确实有数据。

    使用 Humble 兼容参数，避免不支持的 QoS 选项导致已连接雷达被误判。
    `ros2 topic hz` 会持续运行，因此正常的超时返回中仍会带有已经测得的
    average rate。
    """
    result = _run_ros2(
        ["topic", "hz", topic, "--window", "2"],
        timeout=RADAR_PREFLIGHT_DATA_TIMEOUT_S,
    )
    return result, _parse_topic_hz(f"{result.stdout}\n{result.stderr}")


def _radar_response(
    *,
    checks: list[dict[str, Any]],
    ok: bool,
    level: str,
    message: str,
    topic: str | None = None,
    topic_type: str | None = None,
    publisher_count: int | None = None,
    subscription_count: int | None = None,
    frequency_hz: float | None = None,
) -> dict[str, Any]:
    return {
        "ok": ok,
        "level": level,
        "topic": topic,
        "topic_type": topic_type,
        "publisher_count": publisher_count,
        "subscription_count": subscription_count,
        "frequency_hz": frequency_hz,
        "checked_at": utc_now_iso(),
        "checks": checks,
        "message": message,
    }


def check_radar_preflight(*, allow_cached_success: bool = True) -> dict[str, Any]:
    """建图前的快速、无副作用雷达预检。

    与完整健康检查不同，本函数不会临时启动 Livox 驱动，也不会等待驱动上线。
    未连接时应快速返回，让调用方在修改导航/建图运行状态之前明确告警。
    """
    global _radar_preflight_success_cache

    if allow_cached_success:
        with _radar_preflight_cache_lock:
            cached = _radar_preflight_success_cache
            if cached is not None and time.monotonic() - cached[0] <= RADAR_PREFLIGHT_SUCCESS_CACHE_S:
                return deepcopy(cached[1])

    checks: list[dict[str, Any]] = []
    ros2_path = shutil.which("ros2")
    if not ros2_path:
        checks.append(_check_item("ros2", False, "failed", "未找到 ros2 命令"))
        return _radar_response(
            checks=checks,
            ok=False,
            level="error",
            message="雷达连接异常：ROS2 环境不可用",
        )

    checks.append(_check_item("ros2", True, "normal", f"ros2 可执行文件：{ros2_path}"))
    topic_list_result, topics = _list_topics(timeout=RADAR_PREFLIGHT_COMMAND_TIMEOUT_S)
    if topic_list_result.returncode != 0:
        reason = "读取 ROS2 topic 列表超时" if topic_list_result.timed_out else "读取 ROS2 topic 列表失败"
        checks.append(
            _check_item(
                "topic_list",
                False,
                "failed",
                reason,
                {"stderr": topic_list_result.stderr[-500:]},
            )
        )
        return _radar_response(
            checks=checks,
            ok=False,
            level="error",
            message=f"雷达连接异常：{reason}",
        )

    topic, topic_type = _select_radar_topic(topics)
    topic_ok = topic is not None
    checks.append(
        _check_item(
            "topic_exists",
            topic_ok,
            "normal" if topic_ok else "failed",
            f"发现雷达原始数据：{topic}" if topic else "未发现雷达原始数据 /livox/lidar",
            {"topic_count": len(topics), "topic_sample": _topic_sample(topics, limit=6)},
        )
    )
    if topic is None:
        return _radar_response(
            checks=checks,
            ok=False,
            level="error",
            message="雷达未连接：未发现原始数据 /livox/lidar，请检查雷达供电、网线和驱动",
        )

    info_result = _run_ros2(
        ["topic", "info", topic],
        timeout=RADAR_PREFLIGHT_COMMAND_TIMEOUT_S,
    )
    publisher_count: int | None = None
    subscription_count: int | None = None
    if info_result.returncode == 0:
        publisher_count, subscription_count = _parse_topic_info(info_result.stdout)
    publisher_ok = publisher_count is not None and publisher_count > 0
    checks.append(
        _check_item(
            "publisher",
            publisher_ok,
            "normal" if publisher_ok else "failed",
            f"发布者数量：{publisher_count}" if publisher_count is not None else "无法确认雷达发布者",
            {"subscription_count": subscription_count, "timed_out": info_result.timed_out},
        )
    )
    if not publisher_ok:
        return _radar_response(
            checks=checks,
            ok=False,
            level="error",
            topic=topic,
            topic_type=topic_type,
            publisher_count=publisher_count,
            subscription_count=subscription_count,
            message="雷达连接异常：/livox/lidar 没有有效发布者",
        )

    hz_result, frequency_hz = _measure_topic_hz_quick(topic)
    frequency_ok = frequency_hz is not None and frequency_hz >= RADAR_MIN_WARNING_HZ
    checks.append(
        _check_item(
            "frequency",
            frequency_ok,
            "normal" if frequency_ok else "failed",
            (
                f"已收到雷达数据：{frequency_hz:.2f} Hz"
                if frequency_hz is not None
                else f"{RADAR_PREFLIGHT_DATA_TIMEOUT_S:.0f} 秒内未收到雷达数据"
            ),
            {"timed_out": hz_result.timed_out},
        )
    )
    if not frequency_ok:
        message = (
            f"雷达数据异常：频率仅 {frequency_hz:.2f} Hz"
            if frequency_hz is not None
            else "雷达无有效数据：短时间内未收到 /livox/lidar 点云，请检查雷达连接"
        )
        return _radar_response(
            checks=checks,
            ok=False,
            level="error",
            topic=topic,
            topic_type=topic_type,
            publisher_count=publisher_count,
            subscription_count=subscription_count,
            frequency_hz=frequency_hz,
            message=message,
        )

    response = _radar_response(
        checks=checks,
        ok=True,
        level="normal" if frequency_hz >= RADAR_MIN_NORMAL_HZ else "warning",
        topic=topic,
        topic_type=topic_type,
        publisher_count=publisher_count,
        subscription_count=subscription_count,
        frequency_hz=frequency_hz,
        message=(
            "雷达连接正常"
            if frequency_hz >= RADAR_MIN_NORMAL_HZ
            else f"雷达已连接，但数据频率偏低：{frequency_hz:.2f} Hz"
        ),
    )
    with _radar_preflight_cache_lock:
        _radar_preflight_success_cache = (time.monotonic(), deepcopy(response))
    return response


def _has_livox_process() -> tuple[bool, list[str]]:
    try:
        completed = subprocess.run(
            ["ps", "-eo", "pid=,args="],
            text=True,
            capture_output=True,
            timeout=2,
            check=False,
        )
    except Exception:
        return False, []

    lines: list[str] = []
    for raw_line in (completed.stdout or "").splitlines():
        line = raw_line.strip()
        if "livox_ros_driver2_node" in line or "msg_MID360_launch.py" in line:
            lines.append(line)
    return bool(lines), lines[:5]


def _check_item(
    name: str,
    ok: bool,
    status: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "ok": ok,
        "status": status,
        "message": message,
        "details": details or {},
    }


def _topic_sample(topics: dict[str, str], limit: int = 12) -> list[str]:
    return [f"{name} [{topic_type}]" if topic_type else name for name, topic_type in list(topics.items())[:limit]]


def _visible_derived_cloud_topics(topics: dict[str, str]) -> list[str]:
    candidates = set(DERIVED_CLOUD_TOPIC_CANDIDATES)
    mapping_cloud_topic = getattr(settings, "ROS_NAV_MAPPING_CLOUD_TOPIC", None)
    if mapping_cloud_topic:
        candidates.add(mapping_cloud_topic)
    return [topic for topic in sorted(candidates) if topic in topics]


def _start_livox_driver() -> tuple[subprocess.Popen[Any] | None, str | None]:
    command_text = " ".join(LIVOX_DRIVER_COMMAND)
    _write_radar_log(f"准备临时启动 Livox 驱动：command={command_text}")
    try:
        process = subprocess.Popen(
            LIVOX_DRIVER_COMMAND,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        _write_radar_log("临时启动 Livox 驱动失败：未找到 ros2 命令")
        return None, "未找到 ros2 命令，无法启动 Livox 驱动"
    except Exception as exc:
        _write_radar_log(f"临时启动 Livox 驱动失败：{exc}")
        return None, f"启动 Livox 驱动失败：{exc}"

    time.sleep(1.0)
    return_code = process.poll()
    if return_code is not None:
        _write_radar_log(f"Livox 驱动启动后立即退出：pid={process.pid} returncode={return_code}")
        return None, f"Livox 驱动启动后立即退出：returncode={return_code}"

    radar_logger.info("已启动临时 Livox 雷达驱动：pid={} command={}", process.pid, " ".join(LIVOX_DRIVER_COMMAND))
    _write_radar_log(f"已启动临时 Livox 驱动：pid={process.pid} command={command_text}")
    return process, None


def _stop_livox_driver(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        _write_radar_log(f"临时 Livox 驱动已自行退出：pid={process.pid} returncode={process.returncode}")
        return

    try:
        pgid = os.getpgid(process.pid)
    except ProcessLookupError:
        _write_radar_log(f"临时 Livox 驱动进程不存在，跳过停止：pid={process.pid}")
        return

    for sig, timeout_s in (
        (signal.SIGINT, LIVOX_DRIVER_STOP_TIMEOUT_S),
        (signal.SIGTERM, 4.0),
        (signal.SIGKILL, None),
    ):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            _write_radar_log(f"临时 Livox 驱动进程组不存在，跳过停止：pid={process.pid} pgid={pgid}")
            return

        if timeout_s is None:
            radar_logger.warning("临时 Livox 雷达驱动已强制结束：pid={} pgid={}", process.pid, pgid)
            _write_radar_log(f"临时 Livox 驱动已强制结束：pid={process.pid} pgid={pgid}")
            return

        try:
            process.wait(timeout=timeout_s)
            radar_logger.info("临时 Livox 雷达驱动已停止：pid={} signal={}", process.pid, sig.name)
            _write_radar_log(f"临时 Livox 驱动已停止：pid={process.pid} signal={sig.name}")
            return
        except subprocess.TimeoutExpired:
            _write_radar_log(f"等待临时 Livox 驱动停止超时，继续升级信号：pid={process.pid} signal={sig.name}")
            continue
        except Exception as exc:
            radar_logger.warning("等待临时 Livox 雷达驱动停止失败：pid={} error={}", process.pid, exc)
            _write_radar_log(f"等待临时 Livox 驱动停止失败：pid={process.pid} error={exc}")
            return


def _wait_for_radar_topic(timeout_s: float) -> tuple[dict[str, str], str | None, str | None]:
    _write_radar_log(f"等待雷达原生 topic /livox/lidar：timeout_s={timeout_s}")
    deadline = time.monotonic() + timeout_s
    latest_topics: dict[str, str] = {}
    while time.monotonic() < deadline:
        result, topics = _list_topics()
        if result.returncode == 0:
            latest_topics = topics
            topic, topic_type = _select_radar_topic(topics)
            if topic:
                _write_radar_log(f"发现雷达原生 topic：topic={topic} type={topic_type} topic_count={len(topics)}")
                return topics, topic, topic_type
        time.sleep(LIVOX_DRIVER_TOPIC_POLL_INTERVAL_S)
    _write_radar_log(f"等待雷达原生 topic /livox/lidar 超时：timeout_s={timeout_s} topic_count={len(latest_topics)}")
    return latest_topics, None, None


def check_radar_health() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    topic: str | None = None
    topic_type: str | None = None
    publisher_count: int | None = None
    subscription_count: int | None = None
    frequency_hz: float | None = None
    temporary_driver: subprocess.Popen[Any] | None = None

    try:
        _write_radar_log("开始雷达健康检查")
        ros2_path = shutil.which("ros2")
        if not ros2_path:
            _write_radar_log("检测失败：未找到 ros2 命令")
            checks.append(_check_item("ros2", False, "failed", "未找到 ros2 命令"))
            return {
                "ok": False,
                "level": "error",
                "topic": None,
                "topic_type": None,
                "publisher_count": None,
                "subscription_count": None,
                "frequency_hz": None,
                "checked_at": utc_now_iso(),
                "checks": checks,
                "message": "ROS2 环境不可用，无法检测雷达",
            }

        checks.append(_check_item("ros2", True, "normal", f"ros2 可执行文件：{ros2_path}"))
        _write_radar_log(f"ROS2 命令可用：{ros2_path}")

        topic_list_result, topics = _list_topics()
        if topic_list_result.returncode != 0:
            _write_radar_log(
                "读取 ROS2 topic 列表失败："
                f"returncode={topic_list_result.returncode} stderr={topic_list_result.stderr.strip()[:500]}"
            )
            checks.append(
                _check_item(
                    "topic_list",
                    False,
                    "failed",
                    "读取 ROS2 topic 列表失败",
                    {"stderr": topic_list_result.stderr, "stdout": topic_list_result.stdout},
                )
            )
            return {
                "ok": False,
                "level": "error",
                "topic": None,
                "topic_type": None,
                "publisher_count": None,
                "subscription_count": None,
                "frequency_hz": None,
                "checked_at": utc_now_iso(),
                "checks": checks,
                "message": "无法读取 ROS2 topic 列表",
            }

        topic, topic_type = _select_radar_topic(topics)
        process_ok, process_lines = _has_livox_process()
        _write_radar_log(
            f"初始检查：topic={topic or '-'} type={topic_type or '-'} "
            f"topic_count={len(topics)} livox_process={process_ok} matches={process_lines}"
        )
        if topic is None:
            if process_ok:
                _write_radar_log(
                    f"已发现 Livox 驱动进程但 /livox/lidar 尚不存在，等待现有驱动发布：matches={process_lines}"
                )
                checks.append(
                    _check_item(
                        "driver_process",
                        True,
                        "normal",
                        "已发现 Livox 驱动进程，等待 /livox/lidar 发布",
                        {"matches": process_lines},
                    )
                )
                topics, topic, topic_type = _wait_for_radar_topic(LIVOX_DRIVER_TOPIC_WAIT_TIMEOUT_S)
                process_ok, process_lines = _has_livox_process()
            else:
                temporary_driver, start_error = _start_livox_driver()
                checks.append(
                    _check_item(
                        "temporary_driver",
                        temporary_driver is not None,
                        "normal" if temporary_driver is not None else "failed",
                        (
                            f"已临时启动 Livox 驱动：pid={temporary_driver.pid}"
                            if temporary_driver is not None
                            else start_error or "临时启动 Livox 驱动失败"
                        ),
                        {"command": LIVOX_DRIVER_COMMAND},
                    )
                )
                if temporary_driver is not None:
                    topics, topic, topic_type = _wait_for_radar_topic(LIVOX_DRIVER_TOPIC_WAIT_TIMEOUT_S)
                    process_ok, process_lines = _has_livox_process()
        else:
            _write_radar_log(f"已发现雷达原生 topic /livox/lidar，Livox 进程状态：{process_ok} matches={process_lines}")

        candidate_topics = list(DEFAULT_RADAR_TOPIC_CANDIDATES)
        derived_topics = _visible_derived_cloud_topics(topics)
        checks.append(
            _check_item(
                "topic_exists",
                topic is not None,
                "normal" if topic else "failed",
                f"发现雷达原生 topic：{topic}" if topic else "未发现雷达原生 topic /livox/lidar",
                {
                    "candidate_topics": candidate_topics,
                    "derived_cloud_topics_seen": derived_topics,
                    "matched_type": topic_type,
                    "topic_count": len(topics),
                    "topic_sample": _topic_sample(topics),
                },
            )
        )
        if topic is None:
            sample = _topic_sample(topics, limit=6)
            sample_text = f"，当前可见 topic 示例：{'；'.join(sample)}" if sample else ""
            _write_radar_log(f"检测失败：未发现雷达原生 topic /livox/lidar topic_count={len(topics)} sample={sample}")
            return {
                "ok": False,
                "level": "error",
                "topic": None,
                "topic_type": None,
                "publisher_count": None,
                "subscription_count": None,
                "frequency_hz": None,
                "checked_at": utc_now_iso(),
                "checks": checks,
                "message": (
                    f"雷达原生 topic /livox/lidar 不存在，当前 ROS graph 可见 topic 数={len(topics)}{sample_text}"
                    + (f"；检测到派生点云 topic：{', '.join(derived_topics)}，这不是原始雷达输入" if derived_topics else "")
                ),
            }

        checks.append(
            _check_item(
                "driver_process",
                process_ok,
                "normal" if process_ok else "warning",
                "发现 Livox 驱动进程" if process_ok else "未发现 Livox 驱动进程",
                {"matches": process_lines},
            )
        )

        info_result = _run_ros2(["topic", "info", topic])
        if info_result.returncode == 0:
            publisher_count, subscription_count = _parse_topic_info(info_result.stdout)
            publisher_ok = publisher_count is not None and publisher_count > 0
            _write_radar_log(
                f"发布者检查：topic={topic} publisher_count={publisher_count} "
                f"subscription_count={subscription_count}"
            )
            checks.append(
                _check_item(
                    "publisher",
                    publisher_ok,
                    "normal" if publisher_ok else "failed",
                    f"发布者数量：{publisher_count}" if publisher_count is not None else "无法解析发布者数量",
                    {"subscription_count": subscription_count, "raw": info_result.stdout},
                )
            )
        else:
            _write_radar_log(
                f"发布者检查失败：topic={topic} returncode={info_result.returncode} "
                f"stderr={info_result.stderr.strip()[:500]}"
            )
            checks.append(
                _check_item(
                    "publisher",
                    False,
                    "failed",
                    "读取 topic 发布者失败",
                    {"stderr": info_result.stderr, "stdout": info_result.stdout},
                )
            )

        hz_result, frequency_hz, hz_qos, hz_elapsed_s = _measure_topic_hz(topic)
        if frequency_hz is None:
            _write_radar_log(
                f"频率检查失败：topic={topic} qos={hz_qos} elapsed_s={round(hz_elapsed_s, 3)} "
                f"timed_out={hz_result.timed_out} stderr={hz_result.stderr.strip()[-500:]}"
            )
            checks.append(
                _check_item(
                    "frequency",
                    False,
                    "failed",
                    "未在检测窗口内收到雷达数据",
                    {
                        "elapsed_s": round(hz_elapsed_s, 3),
                        "qos": hz_qos,
                        "timed_out": hz_result.timed_out,
                        "stdout": hz_result.stdout[-1000:],
                        "stderr": hz_result.stderr[-1000:],
                    },
                )
            )
        else:
            if frequency_hz >= RADAR_MIN_NORMAL_HZ:
                status = "normal"
                ok = True
                message = f"雷达数据频率正常：{frequency_hz:.2f} Hz"
            elif frequency_hz >= RADAR_MIN_WARNING_HZ:
                status = "warning"
                ok = True
                message = f"雷达数据频率偏低：{frequency_hz:.2f} Hz"
            else:
                status = "failed"
                ok = False
                message = f"雷达数据频率过低：{frequency_hz:.2f} Hz"
            _write_radar_log(f"频率检查：topic={topic} qos={hz_qos} frequency_hz={frequency_hz:.3f} status={status}")
            checks.append(_check_item("frequency", ok, status, message, {"qos": hz_qos}))

        failed = [item for item in checks if item["status"] == "failed"]
        warnings = [item for item in checks if item["status"] == "warning"]
        level = "error" if failed else ("warning" if warnings else "normal")
        ok = level != "error"
        if failed:
            message = "雷达异常：" + "；".join(item["message"] for item in failed)
        elif warnings:
            message = "雷达可用但存在警告：" + "；".join(item["message"] for item in warnings)
        else:
            message = "雷达状态正常"

        _write_radar_log(
            f"雷达健康检查完成：ok={ok} level={level} topic={topic} "
            f"publisher_count={publisher_count} frequency_hz={frequency_hz} message={message}"
        )
        return {
            "ok": ok,
            "level": level,
            "topic": topic,
            "topic_type": topic_type,
            "publisher_count": publisher_count,
            "subscription_count": subscription_count,
            "frequency_hz": frequency_hz,
            "checked_at": utc_now_iso(),
            "checks": checks,
            "message": message,
        }
    finally:
        if temporary_driver is not None:
            _stop_livox_driver(temporary_driver)
