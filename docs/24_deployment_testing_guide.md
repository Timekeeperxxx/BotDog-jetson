# BotDog 项目 - 正式部署测试指南

## 📋 目录
1. [机器狗端需要提供的参数](#机器狗端需要提供的参数)
2. [操作端需要准备的环境](#操作端需要准备的环境)
3. [部署步骤](#部署步骤)
4. [测试流程](#测试流程)
5. [故障排查](#故障排查)

---

## 机器狗端需要提供的参数

### 必需参数

#### 1. MAVLink 连接参数

**串口连接**（推荐）:
```bash
MAVLINK_DEVICE=serial:/dev/ttyACM0  # 串口设备路径
MAVLINK_BAUDRATE=57600               # 波特率（57600 或 115200）
```

**UDP 网络连接**:
```bash
MAVLINK_DEVICE=udp
MAVLINK_CONNECTION=192.168.1.100:14550  # 机器狗 IP:端口
```

**示例**:
```bash
# 串口模式
export MAVLINK_SOURCE=mavlink
export MAVLINK_DEVICE=serial:/dev/ttyUSB0:57600

# UDP 模式
export MAVLINK_SOURCE=mavlink
export MAVLINK_DEVICE=udp
export MAVLINK_CONNECTION=192.168.1.100:14550
```

#### 2. 视频流参数

**GStreamer 视频流 URL**:
```bash
# 摄像头设备
VIDEO_SOURCE=/dev/video0

# GStreamer 管道
VIDEO_PIPELINE="videotestsrc ! video/x-raw,width=1280,height=720,framerate=30/1 ! \
             videoconvert ! x264enc ! rtph264pay name=pay0"

# RTP 输出地址
VIDEO_OUTPUT="udp://0.0.0.0:5000"
```

**摄像头设备信息**:
- 设备路径：`/dev/video0`, `/dev/video1` 等
- 分辨率：建议 1280x720 或 1920x1080
- 帧率：建议 30fps
- 编码格式：H.264 (推荐)

#### 3. 网络配置参数

**机器狗端 IP 地址**:
```bash
# 静态 IP 配置
MACHINE_DOG_IP="192.168.1.100"          # 机器狗 IP
MACHINE_DOG_NETMASK="255.255.255.0"      # 子网掩码
MACHINE_DOG_GATEWAY="192.168.1.1"         # 网关
```

**端口配置**:
```bash
# WebSocket 端口
WS_PORT=8000

# 视频流端口
VIDEO_PORT=5000
```

#### 4. 硬件信息

**摄像头设备**:
- 摄像头型号（如: Logitech C920, Raspberry Pi Camera）
- 支持的分辨率
- 驱动类型（V4L2, GStreamer）

**控制接口**:
- 是否支持 MAVLink 控制
- 控制频率限制（默认 20Hz）

### 可选参数

#### 1. STUN 服务器配置（用于 NAT 穿透）

```bash
# 公网 STUN 服务器
STUN_SERVER=stun.l.google.com:19302
STUN_SERVER_2=stun1.l.google.com:19302
```

#### 2. TURN 服务器配置（如果 STUN 不可用）

```bash
TURN_SERVER=turn.example.com:3478
TURN_USERNAME=username
TURN_PASSWORD=password
```

#### 3. 系统配置（可通过前端配置界面修改）

```bash
# 热度阈值
THERMAL_THRESHOLD=60.0

# 心跳超时
HEARTBEAT_TIMEOUT=3.0

# 控制速率限制
CONTROL_RATE_LIMIT_HZ=20
```

---

## 操作端需要准备的环境

### 1. 硬件要求

- **电脑**: 笔记本或台式机
- **网络**: 能连接到机器狗网络
  - 局域网（同一路由器）
  - 或通过 4G/5G 热点
- **控制器**: Xbox/PlayStation 游戏手柄（可选，可使用键盘）

### 2. 软件要求

#### 操作系统
- ✅ Windows 10/11
- ✅ macOS 10.15+
- ✅ Linux (Ubuntu 20.04+, Fedora 33+)

#### 浏览器
- ✅ Chrome 90+
- ✅ Firefox 88+
- ✅ Edge 90+
- ❌ Safari (不支持 WebRTC)

#### 开发工具（如果从源码运行）
```bash
# Node.js 18+ 和 npm
node --version  # 应该 >= v18.0.0
npm --version   # 应该 >= v9.0.0

# Python 3.10+
python --version  # 应该 >= 3.10
```

---

## 部署步骤

### 步骤 1: 准备机器狗端

#### 1.1 检查硬件连接

```bash
# 检查摄像头设备
ls -la /dev/video*

# 测试摄像头
ffplay /dev/video0

# 检查 MAVLink 设备
ls -la /dev/ttyACM*  # 或 /dev/ttyUSB*

# 查看 USB 设备
lsusb
```

#### 1.2 安装依赖

```bash
# 安装 GStreamer
sudo apt-get update
sudo apt-get install -y \
    gstreamer1.0-tools \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-plugins-ugly \
    gstreamer1.0-libav \
    libgstreamer1.0-dev \
    python3-dev

# 安装 Python 依赖
pip install -r requirements.txt
```

#### 1.3 配置环境变量

创建 `.env` 文件：

```bash
# MAVLink 配置
MAVLINK_SOURCE=mavlink
MAVLINK_DEVICE=serial:/dev/ttyACM0:57600

# 视频流配置
VIDEO_DEVICE=/dev/video0
VIDEO_WIDTH=1280
VIDEO_HEIGHT=720
VIDEO_FRAMERATE=30

# 网络配置
MACHINE_DOG_IP=192.168.1.100
WS_PORT=8000
VIDEO_PORT=5000
```

#### 1.4 启动机器狗端服务

```bash
# 方式 1: 直接运行（开发环境）
cd /path/to/BotDog/backend
python main.py

# 方式 2: 使用 Docker（生产环境）
docker build -t botdog-backend .
docker run -d \
  --network host \
  --device /dev/video0 \
  --device /dev/ttyACM0 \
  -e MAVLINK_DEVICE=serial:/dev/ttyACM0:57600 \
  -e VIDEO_DEVICE=/dev/video0 \
  --name botdog-backend \
  botdog-backend
```

### 步骤 2: 准备操作端

#### 2.1 获取后端服务器地址

确认机器狗端的 IP 地址和端口：

```bash
# 机器狗端 IP（示例）
MACHINE_DOG_IP="192.168.1.100"
BACKEND_URL="http://192.168.1.100:8000"
```

#### 2.2 修改前端配置

编辑 `frontend/src/hooks/useBotDogWebSocket.ts`:

```typescript
// 修改 WebSocket 连接地址
const WS_URL = `ws://${BACKEND_URL}/ws/telemetry`;
```

编辑 `frontend/src/hooks/useWebRTCVideo.ts`:

```typescript
// 修改 WebRTC 信令服务器地址
const SIGNALING_SERVER_URL = `http://${BACKEND_URL}/api/v1/webrtc/offer`;
```

#### 2.3 启动前端

```bash
# 方式 1: 开发模式
cd frontend
npm install
npm run dev

# 方式 2: 生产构建
npm run build
# 部署到 Nginx 或其他 Web 服务器
```

---

## 测试流程

### 测试 1: 网络连接测试

**目的**: 确保操作端能连接到机器狗端

```bash
# 1. Ping 测试
ping 192.168.1.100

# 2. 端口测试
curl http://192.168.1.100:8000/api/v1/system/health

# 预期输出:
# {
#   "status": "healthy",
#   "mavlink_connected": true,
#   "uptime": 123.45
# }
```

### 测试 2: MAVLink 连接测试

**目的**: 验证 MAVLink 通信正常

**检查项**:
- ✅ 后端日志显示 "MAVLink connected"
- ✅ 系统健康检查返回 `mavlink_connected: true`
- ✅ 接收到 HEARTBEAT 消息

**测试方法**:
```bash
# 查看后端日志
docker logs -f botdog-backend

# 或查看健康状态
curl http://192.168.1.100:8000/api/v1/system/health
```

### 测试 3: WebSocket 连接测试

**目的**: 验证 WebSocket 通信正常

**测试方法**:
1. 打开浏览器访问前端页面
2. 打开浏览器控制台（F12）
3. 查看是否有 WebSocket 连接成功的日志

**预期结果**:
```javascript
✅ 遥测 WebSocket 连接已建立
✅ 事件 WebSocket 连接已建立
✅ 控制 WebSocket 连接已建立
```

### 测试 4: 游戏手柄控制测试

**目的**: 验证游戏手柄控制功能

**测试步骤**:
1. 连接游戏手柄到操作端电脑
2. 打开浏览器控制台
3. **按下手柄上的任意按钮**（激活 Gamepad API）
4. 验证控制面板显示 "游戏手柄: 已连接 ✓"
5. 点击 "启用控制" 按钮
6. 移动摇杆测试控制响应

**预期结果**:
```javascript
🎮 游戏手柄已连接: Xbox Controller
游戏手柄: 已连接 ✓
✓ 控制已启用
```

### 测试 5: 配置管理测试

**目的**: 验证配置界面功能正常

**测试步骤**:
1. 点击顶部 "⚙️ 配置" 按钮
2. 切换不同类别（后端/前端/存储）
3. 修改配置项并保存
4. 查看变更历史

**测试用例**:
- [ ] 修改 `thermal_threshold` 为 65.0
- [ ] 修改 `telemetry_display_hz` 为 20
- [ ] 切换 `ui_theme` 为 light
- [ ] 查看配置变更历史

### 测试 6: 告警系统测试

**目的**: 验证告警功能正常

**测试步骤**:
1. 触发测试告警
2. 验证前端接收告警消息
3. 验证告警快照显示

**测试方法**:
```bash
# 触发测试告警
curl -X POST http://192.168.1.100:8000/api/v1/test/alert

# 预期结果:
# 前端左侧面板显示告警快照
# 控制台显示 "ALERT_RAISED" 消息
```

### 测试 7: WebRTC 视频流测试

**目的**: 验证视频流功能（解决 ICE 问题后）

**前置条件**:
- 确保不在 Docker 容器中运行后端
- 或使用 `--network=host` 模式

**测试步骤**:
1. 打开前端页面
2. 观察视频区域
3. 验证视频流正常显示

**预期结果**:
```
✅ WebRTC 连接建立
✅ ICE 候选收集成功（至少 1 个 host 候选）
✅ 视频流正常播放
```

**如果视频流不工作**:
- 检查浏览器控制台的 ICE 收集日志
- 确认后端不在 Docker 容器中
- 尝试使用 `--network=host` 运行 Docker

---

## 故障排查

### 问题 1: 无法连接到后端服务器

**症状**: 前端无法连接 WebSocket

**检查项**:
```bash
# 1. 检查后端是否运行
curl http://192.168.1.100:8000/api/v1/system/health

# 2. 检查防火墙
sudo ufw status
sudo ufw allow 8000

# 3. 检查端口监听
netstat -tuln | grep 8000
```

**解决方案**:
- 确保后端服务正在运行
- 开放防火墙端口 8000
- 确保网络连接正常

### 问题 2: MAVLink 连接失败

**症状**: 后端日志显示 MAVLink 未连接

**检查项**:
```bash
# 1. 检查串口设备
ls -la /dev/ttyACM*
ls -la /dev/ttyUSB*

# 2. 检查权限
sudo chmod 666 /dev/ttyACM0

# 3. 查看串口数据
sudo screen /dev/ttyACM0 57600
```

**解决方案**:
- 确认串口设备路径正确
- 添加用户到 dialout 组：`sudo usermod -aG dialout $USER`
- 重新登录以生效

### 问题 3: 游戏手柄无法识别

**症状**: 控制面板显示 "游戏手柄: 未连接"

**检查项**:
1. 打开浏览器控制台（F12）
2. 查看是否有 "🔍 检测到游戏手柄，但未激活" 的消息
3. **按下手柄上的任意按钮**

**解决方案**:
- Gamepad API 需要用户按下按钮才能激活
- 确保浏览器支持（Chrome/Firefox/Edge）
- 尝试不同的 USB 接口

### 问题 4: ICE 收集失败

**症状**: WebRTC 视频流无法建立，控制台显示 "ICE failed"

**原因**: Docker 容器网络限制

**解决方案**:

**方案 1: 退出 Docker**
```bash
# 直接在主机运行后端
cd backend
python main.py
```

**方案 2: 使用 host 网络**
```bash
docker run --network host ...
```

**方案 3: 配置虚拟网络接口**
```bash
# 添加虚拟网络接口
sudo ip link add veth0 type veth peer name veth1
sudo ip addr add 192.168.1.100/24 dev veth0
sudo ip link set veth0 up
```

### 问题 5: 视频流黑屏或卡顿

**症状**: 视频流连接成功但无画面

**检查项**:
```bash
# 1. 检查摄像头设备
ffmpeg -f v4l2 -list_formats all /dev/video0

# 2. 测试 GStreamer 管道
gst-launch-1.0 v4l2src device=/dev/video0 ! \
  video/x-raw,width=1280,height=720,framerate=30/1 ! \
  videoconvert ! ximagesink
```

**解决方案**:
- 确认摄像头设备可用
- 调整视频分辨率和帧率
- 检查 GStreamer 插件是否完整安装

---

## 部署检查清单

### 机器狗端

- [ ] 硬件连接（摄像头、MAVLink 设备）
- [ ] 网络配置（静态 IP 或 DHCP）
- [ ] GStreamer 安装
- [ ] Python 依赖安装
- [ ] 环境变量配置
- [ ] 后端服务启动
- [ ] 防火墙配置（端口 8000, 5000）

### 操作端

- [ ] 浏览器安装（Chrome/Firefox/Edge）
- [ ] 前端代码部署
- [ ] 后端 URL 配置
- [ ] WebSocket 连接测试
- [ ] 游戏手柄连接测试

### 集成测试

- [ ] 网络连通性测试
- [ ] MAVLink 连接测试
- [ ] WebSocket 连接测试
- [ ] 游戏手柄控制测试
- [ ] 配置管理测试
- [ ] 告警系统测试
- [ ] WebRTC 视频流测试（可选）

---

## 网络拓扑图

### 场景 1: 局域网部署（推荐）

```
┌─────────────────┐
│  操作端（浏览器）│
│   192.168.1.50  │
└────────┬────────┘
         │
         │ WiFi/以太网
         │
    ┌────┴────┐
    │ 路由器   │
    └────┬────┘
         │
         │
┌────────┴────────┐
│  机器狗端（后端）│
│   192.168.1.100  │
│  - 摄像头        │
│  - MAVLink      │
└─────────────────┘
```

### 场景 2: 4G/5G 远程部署

```
┌─────────────────┐
│  操作端（浏览器）│
│   公网 IP        │
└────────┬────────┘
         │
         │ 互联网
         │
    ┌────┴──────────────┐
    │  4G/5G 热点        │
    │  机器狗端（后端）  │
    │  - 私有 IP         │
    └───────────────────┘
```

**注意**: 远程部署需要配置 STUN/TURN 服务器以穿透 NAT

---

## 配置文件示例

### 机器狗端 `.env` 文件

```bash
# ==================== MAVLink 配置 ====================
MAVLINK_SOURCE=mavlink
MAVLINK_DEVICE=serial:/dev/ttyACM0:57600

# ==================== 视频流配置 ====================
VIDEO_DEVICE=/dev/video0
VIDEO_WIDTH=1280
VIDEO_HEIGHT=720
VIDEO_FRAMERATE=30
VIDEO_PORT=5000

# ==================== 网络配置 ====================
MACHINE_DOG_IP=192.168.1.100
WS_PORT=8000

# ==================== STUN 服务器配置 ====================
STUN_SERVER=stun.l.google.com:19302
STUN_SERVER_2=stun1.l.google.com:19302

# ==================== 系统配置 ====================
THERMAL_THRESHOLD=60.0
HEARTBEAT_TIMEOUT=3.0
CONTROL_RATE_LIMIT_HZ=20
```

### 操作端配置

编辑 `frontend/.env`:

```bash
# 后端服务器地址
VITE_BACKEND_URL=http://192.168.1.100:8000

# 或使用 Docker Compose
# VITE_BACKEND_URL=http://backend:8000
```

---

## 性能调优建议

### 1. 网络优化

**降低延迟**:
```bash
# 使用千兆网络
# 减少跳数（直连路由器）
# 使用 5GHz WiFi（而非 2.4GHz）
```

**增加带宽**:
```bash
# 降低视频帧率：15-30fps
# 降低视频分辨率：720p
# 使用 H.264 编码
```

### 2. 系统优化

**后端服务**:
```bash
# 使用 Docker 限制资源
docker run --cpus="2.0" --memory="2g" ...

# 或使用进程管理器
systemd
supervisord
```

**前端优化**:
```javascript
// 降低 WebSocket 重连频率
const RECONNECT_INTERVAL = 2000;  // 2秒

// 降低遥测刷新率
const TELEMETRY_HZ = 10;  // 10Hz
```

---

## 安全建议

### 1. 网络安全

```bash
# 使用 VPN（如果远程访问）
# 配置防火墙规则
# 限制端口访问
```

### 2. 认证（可选）

```bash
# 添加 API 密钥认证
# 添加 WebSocket 认证
# 添加用户权限管理
```

### 3. 加密（可选）

```bash
# 使用 WSS (WebSocket Secure)
# 使用 HTTPS
# 视频流加密
```

---

## 维护建议

### 1. 日志管理

```bash
# 定期清理日志
find logs/ -name "*.log" -mtime +7 -delete

# 或使用 logrotate
```

### 2. 监控

```bash
# 监控系统资源
htop

# 监控网络连接
netstat -tuln

# 监控进程状态
systemctl status botdog-backend
```

### 3. 备份

```bash
# 备份配置文件
cp .env .env.backup

# 备份数据库（如果使用）
pg_dump botdog_db > backup.sql
```

---

## 总结

### 最小化部署需求

**机器狗端必须提供**:
1. ✅ MAVLink 设备路径（串口或 UDP）
2. ✅ 摄像头设备路径
3. ✅ IP 地址（或配置 DHCP）
4. ✅ Python 环境 + GStreamer

**操作端必须准备**:
1. ✅ 现代浏览器（Chrome/Firefox/Edge）
2. ✅ 网络连接到机器狗
3. ✅ 前端部署（开发或生产）

### 验证测试

1. ✅ 网络连通性
2. ✅ 后端 API 响应
3. ✅ WebSocket 连接
4. ✅ 游戏手柄控制（或键盘）
5. ✅ 配置管理
6. ✅ 告警系统

### 可选功能

- ⏳ WebRTC 视频流（需要非 Docker 环境）

---

**文档版本**: 1.0
**创建日期**: 2026-03-06
**适用版本**: BotDog v5.0
**最后更新**: 2026-03-06
