#!/usr/bin/env python3
"""
BotDog 视频流系统一键启动脚本

功能：
1. 网络环境检查
2. 自动提示网络问题修复方案
3. 启动后端服务
4. 提供测试推流选项

使用方法：
    python start_botdog.py
"""

import subprocess
import sys
import time
import os


def run_command(cmd, description):
    """运行命令并显示输出"""
    print(f"\n{'='*80}")
    print(f"{description}")
    print(f"{'='*80}")
    print(f"命令: {' '.join(cmd)}\n")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore'
        )

        if result.stdout:
            print(result.stdout)

        return result.returncode == 0
    except Exception as e:
        print(f"错误: {e}")
        return False


def check_python_version():
    """检查 Python 版本"""
    print("=" * 80)
    print("Python 版本检查")
    print("=" * 80)
    print(f"当前版本: {sys.version}")
    print(f"Python 路径: {sys.executable}")

    if sys.version_info < (3, 10):
        print("\n[警告] 推荐使用 Python 3.10 或更高版本")
        return False

    print("[OK] Python 版本符合要求\n")
    return True


def check_gstreamer():
    """检查 GStreamer 安装"""
    print("=" * 80)
    print("GStreamer 检查")
    print("=" * 80)

    try:
        result = subprocess.run(
            ["gst-launch-1.0", "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode == 0:
            print(result.stdout.strip())
            print("[OK] GStreamer 已安装\n")
            return True
        else:
            print("[错误] GStreamer 未正确安装")
            return False
    except FileNotFoundError:
        print("[错误] 未找到 gst-launch-1.0，请安装 GStreamer")
        print("下载地址: https://gstreamer.freedesktop.org/download/")
        return False
    except Exception as e:
        print(f"[错误] 检查 GStreamer 失败: {e}")
        return False


def check_network():
    """检查网络环境"""
    print("\n" + "=" * 80)
    print("网络环境检查")
    print("=" * 80)

    try:
        from backend.network_check import check_network_environment, print_fix_instructions
        from backend.config import settings

        camera_ip = settings.CAMERA_RTSP_URL.split("//")[1].split("/")[0].split(":")[0]
        is_healthy, warnings = check_network_environment(camera_ip, 8554)

        if not is_healthy:
            print("\n发现网络问题！请选择修复方案：")
            print("1. 关闭 WiFi (推荐)")
            print("2. 运行网卡优先级配置脚本")
            print("3. 跳过，继续启动")

            choice = input("\n请输入选项 (1/2/3): ").strip()

            if choice == "1":
                print("\n请手动关闭 WiFi：")
                print("1. 打开 Windows 设置")
                print("2. 网络和 Internet → Wi-Fi")
                print("3. 关闭 Wi-Fi\n")
                input("关闭后按 Enter 继续...")

            elif choice == "2":
                print("\n正在启动网卡优先级配置...")
                print("需要管理员权限！\n")
                input("按 Enter 启动 PowerShell 脚本...")

                subprocess.run(
                    ["powershell", "-ExecutionPolicy", "Bypass", "-File", "fix_network_priority.ps1"],
                    check=False
                )

                print("\n请重启计算机使配置生效")
                return False

            elif choice == "3":
                print("\n跳过网络修复，继续启动...")
                print("注意：视频流可能无法正常工作\n")

        return True

    except ImportError as e:
        print(f"[警告] 无法导入网络检查模块: {e}")
        print("跳过网络检查\n")
        return True


def start_backend():
    """启动后端服务"""
    print("\n" + "=" * 80)
    print("启动后端服务")
    print("=" * 80)

    try:
        # 使用 uvicorn 启动
        cmd = [sys.executable, "run_backend.py"]

        print(f"命令: {' '.join(cmd)}\n")
        print("后端服务正在启动...")
        print("按 Ctrl+C 停止服务\n")

        # 直接运行，不捕获输出（让用户看到实时日志）
        subprocess.run(cmd, check=False)

    except KeyboardInterrupt:
        print("\n\n后端服务已停止")
    except Exception as e:
        print(f"\n[错误] 启动后端失败: {e}")
        return False

    return True


def offer_test_stream():
    """提供测试推流选项"""
    print("\n" + "=" * 80)
    print("测试推流")
    print("=" * 80)

    print("\n相机 RTSP 连接可能失败，是否使用测试源？")
    print("测试源会发送一个移动球的图案，用于验证系统是否正常")

    choice = input("\n是否启动测试推流？ (y/n): ").strip().lower()

    if choice == 'y':
        print("\n启动测试推流（在新终端中运行）：")
        print("  python push_test_stream.py\n")

        input("按 Enter 打开新终端...")
        subprocess.Popen([
            "cmd", "/k",
            "python push_test_stream.py"
        ])

        print("\n测试推流已启动")
        print("现在可以在浏览器中查看视频流：")
        print("  http://localhost:5174\n")


def main():
    """主函数"""
    print("\n" + "=" * 80)
    print("BotDog 视频流系统 - 一键启动")
    print("=" * 80)
    print()

    # 检查 Python 版本
    if not check_python_version():
        print("\n请安装 Python 3.10 或更高版本")
        return 1

    # 检查 GStreamer
    if not check_gstreamer():
        print("\n请安装 GStreamer 1.28.1 或更高版本")
        return 1

    # 检查网络环境
    if not check_network():
        print("\n请先修复网络问题后再启动")
        return 1

    # 提供测试推流选项
    offer_test_stream()

    # 启动后端
    print("\n准备启动后端服务...")
    input("按 Enter 继续...\n")

    start_backend()

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n[错误] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
