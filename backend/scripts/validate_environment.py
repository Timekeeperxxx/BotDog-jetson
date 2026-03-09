#!/usr/bin/env python3
"""
环境验证脚本。

职责边界：
- 验证 GStreamer 安装
- 验证 Python 依赖
- 检查系统环境
- 报告缺失的依赖
"""

import sys
import subprocess
from pathlib import Path


def run_command(cmd: list[str]) -> tuple[bool, str, str]:
    """运行命令并返回结果。"""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", "Command timed out"
    except FileNotFoundError:
        return False, "", f"Command not found: {cmd[0]}"


def check_gstreamer() -> dict[str, bool]:
    """检查 GStreamer 安装。"""
    checks = {}

    # 检查 gst-launch-1.0
    success, stdout, _ = run_command(["gst-launch-1.0", "--version"])
    checks["gst-launch-1.0"] = success
    if success:
        version = stdout.strip()
        print(f"✓ gst-launch-1.0: {version}")
    else:
        print("✗ gst-launch-1.0: NOT FOUND")

    # 检查 GStreamer Python 绑定
    try:
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
        Gst.init(None)
        checks["gi.repository.Gst"] = True
        version = Gst.version_string()
        print(f"✓ GStreamer Python: {version}")
    except (ImportError, ValueError) as e:
        checks["gi.repository.Gst"] = False
        print(f"✗ GStreamer Python: {e}")

    # 检查关键插件
    plugins = [
        "v4l2src",      # Video4Linux2 源
        "videoconvert", # 视频转换
        "videoscale",   # 视频缩放
        "h264parse",    # H.264 解析
        "rtph264pay",   # RTP H.264 付费
        "udpsink",      # UDP 接收器
    ]

    for plugin in plugins:
        success, _, _ = run_command([
            "gst-inspect-1.0",
            plugin
        ])
        checks[f"plugin:{plugin}"] = success
        if success:
            print(f"✓ GStreamer plugin: {plugin}")
        else:
            print(f"✗ GStreamer plugin: {plugin} (MISSING)")

    return checks


def check_python_dependencies() -> dict[str, bool]:
    """检查 Python 依赖。"""
    checks = {}

    dependencies = [
        ("fastapi", "FastAPI"),
        ("uvicorn", "Uvicorn"),
        ("websockets", "WebSockets"),
        ("aiortc", "aiortc"),
        ("pydantic", "Pydantic"),
        ("pydantic_settings", "Pydantic Settings"),
    ]

    for module, name in dependencies:
        try:
            __import__(module)
            checks[module] = True
            print(f"✓ Python package: {name}")
        except ImportError:
            checks[module] = False
            print(f"✗ Python package: {name} (NOT INSTALLED)")

    return checks


def check_system_environment() -> dict[str, bool]:
    """检查系统环境。"""
    checks = {}

    # 检查 Python 版本
    version = sys.version_info
    checks["python_version"] = version >= (3, 10)
    if checks["python_version"]:
        print(f"✓ Python version: {version.major}.{version.minor}.{version.micro}")
    else:
        print(f"✗ Python version: {version.major}.{version.minor}.{version.micro} (需要 >= 3.10)")

    # 检查 /dev/video* 设备（摄像头）
    video_devices = list(Path("/dev").glob("video*"))
    checks["video_devices"] = len(video_devices) > 0
    if checks["video_devices"]:
        print(f"✓ Video devices: {[d.name for d in video_devices]}")
    else:
        print("⚠ Video devices: 未找到摄像头（可选，用于测试）")

    return checks


def main():
    """主函数。"""
    print("=" * 60)
    print("BotDog Phase 3 环境验证")
    print("=" * 60)

    all_checks = {}

    print("\n## 检查 GStreamer")
    print("-" * 60)
    all_checks.update(check_gstreamer())

    print("\n## 检查 Python 依赖")
    print("-" * 60)
    all_checks.update(check_python_dependencies())

    print("\n## 检查系统环境")
    print("-" * 60)
    all_checks.update(check_system_environment())

    # 汇总结果
    print("\n" + "=" * 60)
    print("验证结果汇总")
    print("=" * 60)

    critical_checks = [
        "gst-launch-1.0",
        "gi.repository.Gst",
        "plugin:v4l2src",
        "plugin:videoconvert",
        "plugin:videoscale",
        "plugin:h264parse",
        "plugin:rtph264pay",
        "plugin:udpsink",
        "fastapi",
        "uvicorn",
        "websockets",
        "aiortc",
        "pydantic",
        "pydantic_settings",
        "python_version",
    ]

    failed_critical = [
        check for check in critical_checks
        if not all_checks.get(check, False)
    ]

    if failed_critical:
        print(f"\n✗ 验证失败：{len(failed_critical)} 个关键依赖未安装")
        print("\n缺失的关键依赖：")
        for check in failed_critical:
            print(f"  - {check}")

        print("\n## 安装指南")
        print("\n### 系统依赖")
        print("sudo apt-get install -y \\")
        print("    libgstreamer1.0-0 \\")
        print("    gstreamer1.0-plugins-base \\")
        print("    gstreamer1.0-plugins-good \\")
        print("    gstreamer1.0-plugins-bad \\")
        print("    gstreamer1.0-tools \\")
        print("    libgstreamer1.0-dev \\")
        print("    python3-gi")

        print("\n### Python 依赖")
        print("pip install -r requirements.txt")

        return 1
    else:
        print("\n✓ 所有关键依赖已安装，环境验证通过！")
        return 0


if __name__ == "__main__":
    sys.exit(main())
