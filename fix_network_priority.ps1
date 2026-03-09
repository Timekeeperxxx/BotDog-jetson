# 网卡优先级配置脚本
#
# 功能：将以太网卡跃点数设为 1，WiFi 网卡跃点数设为 9999
# 目的：确保机器人流量（192.168.144.x）始终走以太网
#
# 使用方法：
#   1. 以管理员身份运行 PowerShell
#   2. 执行: .\fix_network_priority.ps1
#   3. 重启计算机使配置生效
#
# 注意：此脚本需要管理员权限

#Requires -RunAsAdministrator

Write-Host "=" * 80
Write-Host "网卡优先级配置工具"
Write-Host "=" * 80
Write-Host ""

# 获取所有网络适配器
Write-Host "[1] 扫描网络适配器..."
Write-Host ""

$adapters = Get-NetAdapter | Where-Object { $_.Status -eq "Up" }

if ($adapters.Count -eq 0) {
    Write-Host "[错误] 未找到活动的网络适配器" -ForegroundColor Red
    exit 1
}

# 分类以太网和 WiFi 适配器
$ethernetAdapters = @()
$wifiAdapters = @()

foreach ($adapter in $adapters) {
    $name = $adapter.Name
    $description = $adapter.InterfaceDescription

    # 识别以太网适配器
    if ($name -match "以太网" -or $name -match "Ethernet" -or
        $description -match "Ethernet" -or $description -match "Realtek" -or
        $description -match "Intel" -or $description -match "Ethernet Controller") {
        $ethernetAdapters += $adapter
    }
    # 识别 WiFi 适配器
    elseif ($name -match "WLAN" -or $name -match "Wi-Fi" -or $name -match "Wireless" -or
            $description -match "Wi-Fi" -or $description -match "Wireless" -or
            $description -match "802.11") {
        $wifiAdapters += $adapter
    }
    # 其他适配器（默认视为以太网）
    else {
        $ethernetAdapters += $adapter
    }
}

Write-Host "发现 $($ethernetAdapters.Count) 个以太网适配器:"
foreach ($adapter in $ethernetAdapters) {
    $ip = (Get-NetIPAddress -InterfaceAlias $adapter.Name -AddressFamily IPv4 -ErrorAction SilentlyContinue).IPAddress
    Write-Host "  - $($adapter.Name) ($($adapter.InterfaceDescription))" -ForegroundColor Cyan
    if ($ip) {
        Write-Host "    IP: $ip" -ForegroundColor Gray
    }
}

Write-Host ""
Write-Host "发现 $($wifiAdapters.Count) 个 WiFi 适配器:"
foreach ($adapter in $wifiAdapters) {
    $ip = (Get-NetIPAddress -InterfaceAlias $adapter.Name -AddressFamily IPv4 -ErrorAction SilentlyContinue).IPAddress
    Write-Host "  - $($adapter.Name) ($($adapter.InterfaceDescription))" -ForegroundColor Yellow
    if ($ip) {
        Write-Host "    IP: $ip" -ForegroundColor Gray
    }
}

Write-Host ""
Write-Host "[2] 配置网卡优先级..."
Write-Host ""

# 配置以太网适配器（跃点数 = 1）
foreach ($adapter in $ethernetAdapters) {
    Write-Host "配置以太网适配器: $($adapter.Name)" -ForegroundColor Cyan

    try {
        # 设置接口跃点数
        Set-NetIPInterface -InterfaceAlias $adapter.Name -InterfaceMetric 1 -AddressFamily IPv4 -ErrorAction Stop

        # 禁用自动跃点
        $adapter | Set-NetIPInterface -AutomaticMetricEnabled $false -AddressFamily IPv4

        Write-Host "  ✓ 跃点数设为 1 (最高优先级)" -ForegroundColor Green
    }
    catch {
        Write-Host "  ✗ 配置失败: $_" -ForegroundColor Red
    }
}

# 配置 WiFi 适配器（跃点数 = 9999）
foreach ($adapter in $wifiAdapters) {
    Write-Host "配置 WiFi 适配器: $($adapter.Name)" -ForegroundColor Yellow

    try {
        # 设置接口跃点数
        Set-NetIPInterface -InterfaceAlias $adapter.Name -InterfaceMetric 9999 -AddressFamily IPv4 -ErrorAction Stop

        # 禁用自动跃点
        $adapter | Set-NetIPInterface -AutomaticMetricEnabled $false -AddressFamily IPv4

        Write-Host "  ✓ 跃点数设为 9999 (最低优先级)" -ForegroundColor Green
    }
    catch {
        Write-Host "  ✗ 配置失败: $_" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "[3] 验证配置..."
Write-Host ""

# 显示最终配置
$allAdapters = $ethernetAdapters + $wifiAdapters
$sortedAdapters = $allAdapters | Sort-Object { (Get-NetIPInterface -InterfaceAlias $_.Name -AddressFamily IPv4).InterfaceMetric }

Write-Host "网卡优先级（从高到低）:"
Write-Host ""

foreach ($adapter in $sortedAdapters) {
    $metric = (Get-NetIPInterface -InterfaceAlias $adapter.Name -AddressFamily IPv4).InterfaceMetric
    $ip = (Get-NetIPAddress -InterfaceAlias $adapter.Name -AddressFamily IPv4 -ErrorAction SilentlyContinue).IPAddress

    $color = if ($metric -le 10) { "Green" } elseif ($metric -ge 1000) { "Yellow" } else { "White" }

    Write-Host "  [$metric] $($adapter.Name)" -ForegroundColor $color
    if ($ip) {
        Write-Host "      IP: $ip" -ForegroundColor Gray
    }
}

Write-Host ""
Write-Host "=" * 80
Write-Host "配置完成！" -ForegroundColor Green
Write-Host ""
Write-Host "说明:"
Write-Host "  - 以太网适配器跃点数: 1 (最高优先级)"
Write-Host "  - WiFi 适配器跃点数: 9999 (最低优先级)"
Write-Host ""
Write-Host "效果:"
Write-Host "  - 所有访问 192.168.144.x (机器人) 的流量将走以太网"
Write-Host "  - WiFi 仅用于访问互联网（不影响机器人通信）"
Write-Host ""
Write-Host "下一步:"
Write-Host "  1. 运行测试: python backend/network_check.py"
Write-Host "  2. 重启计算机使配置完全生效"
Write-Host "  3. 启动视频流: python run_backend.py"
Write-Host ""
Write-Host "=" * 80
