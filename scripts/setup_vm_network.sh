#!/bin/bash
# 虚拟机网络配置脚本 - 桥接模式
# 用于配置 192.168.144.0/24 网络

set -e

# 配置参数
INTERFACE="ens33"           # 网卡接口名
STATIC_IP="192.168.144.31"  # 虚拟机静态IP（避免与主机冲突）
NETMASK="255.255.255.0"     # 子网掩码
GATEWAY="192.168.144.1"     # 网关（根据实际情况调整）
DNS_SERVER="8.8.8.8"        # DNS服务器

# 检查是否以 root 权限运行
if [ "$EUID" -ne 0 ]; then
    echo "请使用 sudo 运行此脚本"
    exit 1
fi

echo "=========================================="
echo "虚拟机网络配置 - 桥接模式"
echo "=========================================="
echo "网卡接口: $INTERFACE"
echo "静态IP: $STATIC_IP"
echo "子网掩码: $NETMASK"
echo "网关: $GATEWAY"
echo "DNS: $DNS_SERVER"
echo "=========================================="

# 1. 备份原有配置
echo -e "\n[1/5] 备份原有网络配置..."
if [ -f /etc/netplan/01-network-manager-all.yaml ]; then
    cp /etc/netplan/01-network-manager-all.yaml /etc/netplan/01-network-manager-all.yaml.backup.$(date +%Y%m%d%H%M%S)
fi

# 2. 删除 DHCP 获取的 IP（如果有）
echo -e "\n[2/5] 清除原有 IP 配置..."
ip addr flush dev $INTERFACE

# 3. 配置静态 IP（临时配置，用于测试）
echo -e "\n[3/5] 配置静态 IP..."
ip addr add $STATIC_IP/24 dev $INTERFACE
ip link set $INTERFACE up

# 4. 配置路由
echo -e "\n[4/5] 配置默认网关..."
ip route add default via $GATEWAY dev $INTERFACE

# 5. 配置 DNS
echo -e "\n[5/5] 配置 DNS..."
echo "nameserver $DNS_SERVER" > /etc/resolv.conf

echo -e "\n=========================================="
echo "配置完成！"
echo "=========================================="

# 显示当前配置
echo -e "\n当前网络配置："
ip addr show $INTERFACE
echo -e "\n路由表："
ip route show
echo -e "\nDNS配置："
cat /etc/resolv.conf

echo -e "\n=========================================="
echo "测试网络连通性..."
echo "=========================================="

# 测试连通性
echo -e "\n[测试1] 检查网卡状态："
ip link show $INTERFACE | grep "state UP"

echo -e "\n[测试2] Ping 网关 ($GATEWAY)："
ping -c 2 $GATEWAY || echo "⚠️  无法 ping 通网关，请检查网关配置"

echo -e "\n[测试3] Ping 图传接收器 (192.168.144.12)："
ping -c 2 192.168.144.12 || echo "⚠️  无法 ping 通图传接收器，请检查网络连接"

echo -e "\n[测试4] Ping 外部网络 (8.8.8.8)："
ping -c 2 8.8.8.8 || echo "⚠️  无法访问外网，请检查网关和DNS配置"

echo -e "\n=========================================="
echo "配置验证完成！"
echo "=========================================="
echo -e "\n📝 提示："
echo "1. 如果上述测试都通过，说明网络配置成功"
echo "2. 如果 ping 不通网关，请检查 GATEWAY 参数是否正确"
echo "3. 如果 ping 不通图传接收器，请检查物理网线连接"
echo "4. 如果需要永久保存配置，请使用 Netplan 配置文件"
echo ""

# 询问是否永久保存配置
read -p "是否永久保存此配置？(y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "创建 Netplan 配置文件..."

    # 创建 Netplan 配置
    cat > /etc/netplan/01-network-manager-all.yaml <<EOF
network:
  version: 2
  renderer: networkd
  ethernets:
    $INTERFACE:
      dhcp4: no
      addresses:
        - $STATIC_IP/24
      routes:
        - to: default
          via: $GATEWAY
      nameservers:
        addresses:
          - $DNS_SERVER
EOF

    echo "应用 Netplan 配置..."
    netplan apply

    echo "✅ 配置已永久保存！重启后依然有效。"
else
    echo "⚠️  配置仅在当前会话有效，重启后将失效。"
    echo "如果需要永久配置，请重新运行此脚本并选择保存。"
fi

echo -e "\n配置脚本执行完成！"
