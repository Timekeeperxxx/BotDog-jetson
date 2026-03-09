#!/usr/bin/env python3
"""
网络环境预检工具

职责：
- 检测多网卡环境
- 验证目标网段可达性
- 检测路由冲突
- 提供修复建议
"""

import socket
import subprocess
import platform
from typing import List, Tuple, Optional
import ipaddress


class NetworkInterface:
    """网络接口信息"""

    def __init__(self, name: str, ip: str, metric: int = 0):
        self.name = name
        self.ip = ip
        self.metric = metric

    def __repr__(self):
        return f"NetworkInterface(name={self.name}, ip={self.ip}, metric={self.metric})"


def get_local_interfaces() -> List[NetworkInterface]:
    """
    获取本机所有网络接口

    Returns:
        网络接口列表
    """
    interfaces = []

    try:
        if platform.system() == "Windows":
            # Windows: 使用 ipconfig
            result = subprocess.run(
                ["ipconfig"],
                capture_output=True,
                text=True,
                encoding="gbk",
                timeout=10
            )

            # 解析 ipconfig 输出
            lines = result.stdout.split("\n")
            current_adapter = None

            for line in lines:
                line = line.strip()
                if line.startswith("以太网适配器") or line.startswith("Wireless") or line.startswith("WLAN") or line.startswith("Wi-Fi"):
                    current_adapter = line.split(":")[0].strip()
                elif "IPv4 地址" in line or "IPv4 Address" in line:
                    if current_adapter:
                        # 提取 IP 地址
                        ip_part = line.split(":")[-1].strip()
                        # 移除 "(首选)" 等标记
                        ip = ip_part.split("(")[0].strip()
                        try:
                            # 验证 IP 格式
                            ipaddress.ip_address(ip)
                            interfaces.append(NetworkInterface(current_adapter, ip))
                        except ValueError:
                            pass
        else:
            # Linux: 使用 ip addr
            result = subprocess.run(
                ["ip", "addr", "show"],
                capture_output=True,
                text=True,
                timeout=10
            )

            # 解析 ip 输出
            lines = result.stdout.split("\n")
            current_interface = None

            for line in lines:
                line = line.strip()
                if line.startswith("inet "):
                    if current_interface:
                        ip = line.split()[1].split("/")[0]
                        interfaces.append(NetworkInterface(current_interface, ip))
                elif line and not line.startswith(" ") and ":" in line:
                    current_interface = line.split(":")[1].strip()

    except Exception as e:
        print(f"[警告] 无法获取网络接口: {e}")

    return interfaces


def get_route_to_target(target_ip: str) -> Optional[Tuple[str, str]]:
    """
    获取到目标 IP 的路由

    Args:
        target_ip: 目标 IP 地址

    Returns:
        (网关, 接口) 或 None
    """
    try:
        if platform.system() == "Windows":
            # Windows: 使用 route print
            result = subprocess.run(
                ["route", "print", "-4"],
                capture_output=True,
                text=True,
                encoding="gbk",
                timeout=10
            )

            lines = result.stdout.split("\n")
            active_routes = False

            for line in lines:
                line = line.strip()
                if "活动路由" in line or "Active Routes" in line:
                    active_routes = True
                    continue

                if not active_routes or not line or line.startswith("="):
                    continue

                # 解析路由表
                parts = line.split()
                if len(parts) >= 5:
                    try:
                        # 检查是否匹配目标网段
                        network = parts[0]
                        mask = parts[1]
                        gateway = parts[2]
                        interface = parts[3]

                        # 简单匹配（生产环境应该用子网掩码计算）
                        if network == "0.0.0.0" or target_ip.startswith(network.rsplit(".", 1)[0]):
                            return (gateway, interface)
                    except (ValueError, IndexError):
                        continue
        else:
            # Linux: 使用 ip route get
            result = subprocess.run(
                ["ip", "route", "get", target_ip],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                # 解析: 192.168.144.25 dev eth0 src 192.168.144.30
                parts = result.stdout.split()
                for i, part in enumerate(parts):
                    if part == "dev" and i + 1 < len(parts):
                        interface = parts[i + 1]
                        return ("", interface)

    except Exception as e:
        print(f"[警告] 无法获取路由信息: {e}")

    return None


def check_target_reachable(target_ip: str, port: int, timeout: float = 2.0) -> bool:
    """
    检查目标 IP:端口 是否可达

    Args:
        target_ip: 目标 IP
        port: 目标端口
        timeout: 超时时间（秒）

    Returns:
        是否可达
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((target_ip, port))
        sock.close()
        return result == 0
    except Exception:
        return False


def check_network_environment(target_ip: str, target_port: int) -> Tuple[bool, List[str]]:
    """
    检查网络环境

    Args:
        target_ip: 目标 IP（相机）
        target_port: 目标端口（RTSP）

    Returns:
        (是否健康, 警告列表)
    """
    warnings = []
    is_healthy = True

    print("\n" + "=" * 80)
    print("网络环境预检")
    print("=" * 80)

    # 1. 获取本机接口
    interfaces = get_local_interfaces()
    print(f"\n[1] 检测到 {len(interfaces)} 个网络接口:")
    for iface in interfaces:
        print(f"    - {iface.name}: {iface.ip}")

    # 2. 检测多网卡环境
    if len(interfaces) > 1:
        # 检查是否有 WiFi 和以太网同时存在
        has_wifi = any("wlan" in iface.name.lower() or "wi-fi" in iface.name.lower() for iface in interfaces)
        has_ethernet = any("以太网" in iface.name or "ethernet" in iface.name.lower() for iface in interfaces)

        if has_wifi and has_ethernet:
            warnings.append(
                "检测到 WiFi 和以太网同时启用，可能导致路由冲突。\n"
                "建议：关闭 WiFi 或调整网卡优先级（见下方说明）"
            )
            is_healthy = False

    # 3. 检查路由
    print(f"\n[2] 检查到 {target_ip} 的路由:")
    route = get_route_to_target(target_ip)
    if route:
        gateway, interface = route
        if gateway:
            print(f"    网关: {gateway}")
        if interface:
            print(f"    接口: {interface}")

            # 检查是否使用了错误的接口（WiFi）
            if interface and ("wlan" in interface.lower() or "wi-fi" in interface.lower()):
                warnings.append(
                    f"警告：流量正在通过无线接口 ({interface}) 路由到相机！\n"
                    f"相机 IP {target_ip} 应该通过以太网访问。\n"
                    f"请关闭 WiFi 或运行网卡优先级配置脚本。"
                )
                is_healthy = False
    else:
        print("    无法确定路由（可能使用了默认路由）")

    # 4. 检查目标可达性
    print(f"\n[3] 检查目标 {target_ip}:{target_port} 可达性:")
    # 先 Ping 测试
    try:
        ping_result = subprocess.run(
            ["ping", "-n", "2", target_ip],
            capture_output=True,
            text=True,
            timeout=5
        )
        if ping_result.returncode == 0:
            print(f"    Ping: 成功")
        else:
            warnings.append(f"Ping {target_ip} 失败，请检查网络连接")
            is_healthy = False
    except Exception as e:
        warnings.append(f"Ping 测试失败: {e}")
        is_healthy = False

    # TCP 端口测试
    if check_target_reachable(target_ip, target_port, timeout=2.0):
        print(f"    端口 {target_port}: 可达")
    else:
        warnings.append(
            f"端口 {target_port} (RTSP) 不可达。\n"
            f"可能原因：\n"
            f"  1. 相机未开机或 RTSP 服务未启动\n"
            f"  2. 防火墙阻止了连接\n"
            f"  3. 路由配置错误（使用了错误的网卡）"
        )
        is_healthy = False

    # 5. 输出结果
    print("\n" + "=" * 80)
    if is_healthy:
        print("[OK] 网络环境健康")
    else:
        print("[警告] 发现网络问题")
        print("\n问题列表:")
        for i, warning in enumerate(warnings, 1):
            print(f"\n{i}. {warning}")

    print("=" * 80 + "\n")

    return is_healthy, warnings


def print_fix_instructions():
    """打印修复指导"""
    print("\n" + "=" * 80)
    print("网络问题修复指导")
    print("=" * 80)

    print("\n方案 1: 关闭 WiFi（推荐，最简单）")
    print("-" * 40)
    print("1. 打开 Windows 设置")
    print("2. 进入 网络和 Internet → Wi-Fi")
    print("3. 点击关闭 Wi-Fi")

    print("\n方案 2: 调整网卡优先级（永久方案）")
    print("-" * 40)
    print("运行 PowerShell 脚本:")
    print("  .\\fix_network_priority.ps1")
    print("\n该脚本会:")
    print("  - 以太网卡跃点数设为 1（最高优先级）")
    print("  - WiFi 网卡跃点数设为 9999（最低优先级）")
    print("  - 确保所有机器人流量走以太网")

    print("\n方案 3: 手动配置（高级用户）")
    print("-" * 40)
    print("1. 打开 控制面板 → 网络和共享中心")
    print("2. 更改适配器设置")
    print("3. 右键 以太网 → 属性")
    print("4. Internet 协议版本 4 (TCP/IPv4) → 高级")
    print("5. 取消勾选 '自动跃点'")
    print("6. 设置跃点数为 1")

    print("\n" + "=" * 80 + "\n")


if __name__ == "__main__":
    import sys

    # 默认检查相机地址
    target_ip = "192.168.144.25"
    target_port = 8554

    if len(sys.argv) > 1:
        target_ip = sys.argv[1]
    if len(sys.argv) > 2:
        target_port = int(sys.argv[2])

    is_healthy, warnings = check_network_environment(target_ip, target_port)

    if not is_healthy:
        print_fix_instructions()
        sys.exit(1)
    else:
        print("[OK] 网络环境检查通过")
        sys.exit(0)
