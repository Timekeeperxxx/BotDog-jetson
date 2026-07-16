from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
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
RADAR_MIN_NORMAL_HZ = 2.0
RADAR_MIN_WARNING_HZ = 0.5
LIVOX_DRIVER_COMMAND = ["ros2", "launch", "livox_ros_driver2", "msg_MID360_launch.py"]
LIVOX_DRIVER_TOPIC_WAIT_TIMEOUT_S = 18.0
LIVOX_DRIVER_TOPIC_POLL_INTERVAL_S = 0.5
LIVOX_DRIVER_STOP_TIMEOUT_S = 8.0
RADAR_HEALTH_LOG_NAME = "radar_health.log"


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


def _list_topics() -> tuple[CommandResult, dict[str, str]]:
    result = _run_ros2(["topic", "list", "-t"])
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
    attempts = [
        ("sensor_data", ["topic", "hz", topic, "--window", "5", "--qos-profile", "sensor_data"]),
        ("best_effort", ["topic", "hz", topic, "--window", "5", "--qos-reliability", "best_effort"]),
        ("default", ["topic", "hz", topic, "--window", "5"]),
    ]

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
        # sensor_data 是 Livox 这类传感器 topic 的正确 QoS。若它已经订阅超时，
        # 继续用默认 QoS 通常只会拉长接口等待时间。
        if result.timed_out:
            break

    if last_result is None:
        last_result = CommandResult(returncode=1, stdout="", stderr="未执行频率检查")
    return last_result, None, last_label, time.monotonic() - total_started_at


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
