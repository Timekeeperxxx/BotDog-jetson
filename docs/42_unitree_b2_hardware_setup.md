# 宇树 B2 硬件接入与操控指南

## 一、整体架构

### 推荐部署方式（后端在机身 Jetson 上）

```
B2 机身（Jetson）
  └── 后端（Python + unitree_sdk2_python）← SDK 本地调用，最稳定
      ↑ WiFi 或网线
你的电脑
  └── 浏览器前端 → 连 http://192.168.123.161:8000
```

### 临时/开发部署（后端在电脑上）

```
摄像头 192.168.144.25 ──┐
                         ├── 交换机 ── 你的电脑（单网口双IP）
B2     192.168.123.161 ──┘
```

---

## 二、网络配置

### 问题背景
- 摄像头：`192.168.144.25`（不同网段）
- B2：`192.168.123.161`
- 电脑只有一个网口

### 解决：交换机 + 网卡双 IP

**硬件：** 购买一个千兆网络交换机（约 30-80 元）

**Windows 配置两个 IP（高级设置）：**

控制面板 → 网络连接 → 以太网 → IPv4 → 高级 → 添加：

| IP 地址 | 子网掩码 | 用途 |
|---------|---------|------|
| `192.168.123.100` | `255.255.255.0` | 与 B2 通信 |
| `192.168.144.100` | `255.255.255.0` | 与摄像头通信 |

或 PowerShell：
```powershell
New-NetIPAddress -InterfaceAlias "以太网" -IPAddress 192.168.144.100 -PrefixLength 24
```

验证：
```powershell
ping 192.168.123.161   # B2
ping 192.168.144.25    # 摄像头
```

### 摄像头 RTSP 地址（SIYI 系列）
```
rtsp://192.168.144.25:8554/main.264
```
用 VLC → 打开网络串流 验证。

---

## 三、SDK 安装

```bash
pip install cyclonedds==0.10.2

git clone https://github.com/unitreerobotics/unitree_sdk2_python.git
cd unitree_sdk2_python && pip install -e .
```

> **Windows 注意：** CycloneDDS 在 Windows 兼容性较弱，建议在 WSL2 或 B2 机身 Jetson 上运行后端。

验证 SDK：
```bash
python example/high_level/read_highstate.py Ethernet
```
能看到连续输出机器人状态数据则链路正常。

---

## 四、后端配置（`.env`）

```ini
# 控制器 ─ 宇树 B2
CONTROL_ADAPTER_TYPE=unitree_b2
UNITREE_NETWORK_IFACE=Ethernet     # Windows 网卡名；机身上改为 eth0 或 lo
UNITREE_B2_VX=0.3                  # 前进速度 m/s
UNITREE_B2_VYAW=0.5                # 转向速度 rad/s

# 摄像头
AI_ENABLED=true
AI_RTSP_URL=rtsp://192.168.144.25:8554/main.264

# 允许外部访问（若后端在机身上）
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8000
```

---

## 五、将后端部署到 B2 机身（可选，推荐）

### 1. SSH 登录
```bash
ssh unitree@192.168.123.161
```

### 2. 传代码
```bash
# 在电脑上（PowerShell）
scp -r C:\Code\Project\BOTDOG\BotDog\backend unitree@192.168.123.161:~/botdog/backend
scp C:\Code\Project\BOTDOG\BotDog\run_backend.py unitree@192.168.123.161:~/botdog/
```
或在机身上直接 `git clone`。

### 3. 安装依赖
```bash
cd ~/botdog
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
# 安装 SDK（ARM 版本）
git clone https://github.com/unitreerobotics/unitree_sdk2_python.git
cd unitree_sdk2_python && pip install -e . && cd ..
```

### 4. 配置 & 启动
```bash
cp backend/.env.example backend/.env
# 编辑 .env：UNITREE_NETWORK_IFACE 改为机身内部网卡名（ip link show 查看）
nano backend/.env
python run_backend.py
```

### 5. 前端指向机身 IP
```ini
# frontend/.env
VITE_API_BASE_URL=http://192.168.123.161:8000
VITE_WS_BASE_URL=ws://192.168.123.161:8000
```

### 6. 开机自启（可选）
```bash
sudo nano /etc/systemd/system/botdog.service
```
```ini
[Unit]
Description=BotDog Backend
After=network.target
[Service]
User=unitree
WorkingDirectory=/home/unitree/botdog
ExecStart=/home/unitree/botdog/.venv/bin/python run_backend.py
Restart=always
[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl enable botdog && sudo systemctl start botdog
```

---

## 六、控制方式

| 方式 | 说明 |
|------|------|
| 前端 ControlPad | 浏览器打开，方向控制盘手动遥控 |
| 自动跟踪 | AutoTrackPanel 启用 → 人进画面 → B2 自动跟随 |
| API 调试 | `POST /api/v1/control/command` `{"cmd":"forward"}` |

### 控制权优先级
```
E-STOP  >  遥控器（FT24）  >  Web 手动  >  自动跟踪
```

---

## 七、命令映射

| 项目命令 | SDK 调用 | 说明 |
|---------|---------|------|
| `forward` | `Move(0.3, 0, 0)` | 前进 |
| `backward` | `Move(-0.3, 0, 0)` | 后退 |
| `left` | `Move(0, 0, 0.5)` | 左转 |
| `right` | `Move(0, 0, -0.5)` | 右转 |
| `stop` | `StopMove()` | 停止 |
| `stand` | `RecoveryStand()` | 站立 |
| `sit` | `StandDown()` | 趴下 |

---

## 八、常见问题

| 问题 | 原因 | 解决 |
|------|------|------|
| `[UnitreeB2] 初始化失败` | SDK 未安装 / 网卡名错误 | 检查安装 + 网卡名 |
| ping 不通 B2 | IP 未在同网段 | 设 192.168.123.100 |
| B2 不动，命令有日志 | 机器人处于趴下/锁定状态 | 先遥控器让它站起来 |
| Windows DDS 初始化失败 | CycloneDDS Win 兼容性 | 用 WSL2 或机身 Jetson |
