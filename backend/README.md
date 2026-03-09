# BotDog 后端 - 阶段 1 实现

## 技术栈

- Python 3.10+（当前使用 3.10.12）
- FastAPI（Web 框架）
- SQLAlchemy 2.0（异步 ORM）
- aiosqlite（异步 SQLite 驱动）
- pymavlink（MAVLink 协议解析）
- loguru（日志系统）
- uvicorn（ASGI 服务器）
- websockets（WebSocket 支持）
- Pydantic（数据验证）

## 环境配置

### 创建虚拟环境

```bash
# 在项目根目录执行
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# Windows PowerShell: .venv\Scripts\Activate.ps1
```

### 安装依赖

```bash
pip install -r requirements.txt
```

### 环境变量配置

在项目根目录创建 `.env` 文件：

```bash
# 基础网络配置
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8000

# MAVLink / 数据库
MAVLINK_ENDPOINT=udp:127.0.0.1:14550
DATABASE_URL=sqlite+aiosqlite:///./data/botdog.db

# 安全配置
JWT_SECRET=请在本地自定义

# CORS 配置
CORS_ALLOW_ORIGINS=["http://localhost:5173"]
CORS_ALLOW_CREDENTIALS=false

# MAVLink 数据源选择
# - mavlink: 使用真实 MAVLink 端口
# - simulation: 使用模拟数据生成器（开发默认）
MAVLINK_SOURCE=simulation

# 系统参数
HEARTBEAT_TIMEOUT=3.0              # 心跳超时（秒）
TELEMETRY_SAMPLING_HZ=2.0          # 遥测落盘采样频率（Hz）
TELEMETRY_BROADCAST_HZ=15.0        # 遥测广播频率（Hz）

# 模拟数据 Worker（开发调试用）
SIMULATION_WORKER_ENABLED=true
```

## 启动服务

### 开发模式

```bash
# 确保已激活虚拟环境
source .venv/bin/activate

# 启动后端服务（带热重载）
uvicorn backend.main:app --reload

# 或指定端口
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

### 生产模式

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### 访问 API 文档

启动服务后，访问以下地址：

- Swagger UI: http://localhost:8000/api/docs
- OpenAPI JSON: http://localhost:8000/api/openapi.json

## 项目结构

```
backend/
├── __init__.py
├── main.py                 # FastAPI 应用入口
├── config.py               # 配置管理（Pydantic Settings）
├── database.py             # 数据库连接与会话管理
├── logging_config.py       # Loguru 日志配置
├── models.py               # SQLAlchemy ORM 模型
├── schemas.py              # Pydantic 数据传输对象（DTO）
├── mavlink_gateway.py      # MAVLink 网关（UDP 报文解析）
├── mavlink_dto.py          # MAVLink 数据传输对象
├── telemetry_queue.py      # 遥测队列管理器
├── state_machine.py        # 系统状态机
├── ws_broadcaster.py       # WebSocket 遥测广播器
├── workers_telemetry.py    # 遥测数据落盘 Worker
├── workers_simulation.py   # 模拟数据生成器
├── services_tasks.py       # 任务管理服务
├── services_logs.py        # 日志服务
├── services_telemetry.py   # 遥测数据服务
└── services_evidence.py    # 异常证据服务
```

## 核心模块说明

### main.py

**职责：**
- FastAPI 应用装配与生命周期管理
- 路由注册与中间件配置
- 全局组件初始化（状态机、MAVLink 网关、WebSocket 广播器等）

**关键组件：**
- `lifespan()`: 应用启动/关闭钩子
- `create_app()`: FastAPI 应用工厂函数
- `register_routes()`: 路由注册函数

### config.py

**职责：**
- 全局配置管理
- 环境变量加载（`.env` 文件）
- 类型安全的配置访问

**配置项：**
- `MAVLINK_SOURCE`: 数据源切换（`mavlink` 或 `simulation`）
- `HEARTBEAT_TIMEOUT`: MAVLink 心跳超时检测
- `TELEMETRY_SAMPLING_HZ`: 遥测数据采样频率
- `TELEMETRY_BROADCAST_HZ`: WebSocket 广播频率

### mavlink_gateway.py

**职责：**
- 监听 UDP 端口接收 MAVLink 报文
- 解析 `HEARTBEAT`、`ATTITUDE`、`GLOBAL_POSITION_INT`、`SYS_STATUS` 等报文
- 支持**模拟数据源**（通过 `MAVLINK_SOURCE` 配置切换）
- 推送遥测数据到队列管理器

**数据流：**
```
MAVLink UDP (14550) → MAVLinkGateway → TelemetryQueueManager
```

### ws_broadcaster.py

**职责：**
- 维护 WebSocket 客户端连接池
- 从遥测队列获取最新快照（15Hz）
- 广播 `TELEMETRY_UPDATE` 消息给所有客户端
- 管理消息序列号

**WebSocket 协议：**
```json
{
  "type": "TELEMETRY_UPDATE",
  "seq": 123,
  "timestamp": "2025-01-15T10:30:45.123Z",
  "payload": {
    "attitude": { "pitch": 0.0, "roll": 0.0, "yaw": 0.0 },
    "position": { "lat": 0.0, "lon": 0.0, "alt": 0.0, "hdg": 0.0 },
    "battery": { "voltage": 12.6, "remaining_pct": 100 },
    "system_status": { "armed": false, "mode": "STABILIZE" }
  }
}
```

### telemetry_queue.py

**职责：**
- 遥测数据队列管理（广播队列 + 落盘队列）
- 采样控制（降频落盘）
- 线程安全的数据访问

### state_machine.py

**职责：**
- 系统状态管理（`DISCONNECTED`, `CONNECTED`, `ARMED`, `MISSION_ACTIVE`, `E_STOP_TRIGGERED`）
- MAVLink 心跳超时检测
- 状态转换验证

### workers_telemetry.py

**职责：**
- 遥测数据持久化（写入 `telemetry_snapshots` 表）
- 降采样存储策略
- 任务关联（通过 `task_id`）

### models.py

**数据库模型：**

| 模型 | 表名 | 说明 |
|------|------|------|
| `InspectionTask` | `inspection_tasks` | 巡检任务 |
| `TelemetrySnapshot` | `telemetry_snapshots` | 遥测快照（降采样） |
| `AnomalyEvidence` | `anomaly_evidence` | 异常证据链 |
| `OperationLog` | `operation_logs` | 操作日志 |
| `ConfigEntry` | `config` | 配置项（热更新） |

## API 端点

### 系统健康检查

```
GET /api/v1/system/health
```

**响应示例：**
```json
{
  "status": "healthy",
  "mavlink_connected": true,
  "uptime": 3600.123
}
```

**状态说明：**
- `healthy`: MAVLink 已连接且系统正常
- `degraded`: MAVLink 断连或触发急停
- `offline`: 启动初期（< 10 秒）且未检测到连接

### 启动巡检任务

```
POST /api/v1/session/start
```

**请求体：**
```json
{
  "task_name": "巡检任务-001"
}
```

**响应示例：**
```json
{
  "task_id": 1,
  "task_name": "巡检任务-001",
  "status": "running",
  "started_at": "2025-01-15T10:30:45.123Z",
  "ended_at": null
}
```

### 停止巡检任务

```
POST /api/v1/session/stop
```

**请求体：**
```json
{
  "task_id": 1
}
```

### 查询日志

```
GET /api/v1/logs
```

**响应示例：**
```json
{
  "items": [
    {
      "log_id": 1,
      "level": "INFO",
      "module": "BACKEND",
      "message": "Session started: 巡检任务-001 (id=1)",
      "task_id": 1,
      "created_at": "2025-01-15T10:30:45.123Z"
    }
  ]
}
```

### 查询异常证据

```
GET /api/v1/evidence?task_id=1
```

**响应示例：**
```json
{
  "items": [
    {
      "evidence_id": 1,
      "task_id": 1,
      "event_type": "THERMAL_ANOMALY",
      "event_code": "T_MAX_EXCEEDED",
      "severity": "CRITICAL",
      "message": "检测到高温异常",
      "confidence": 0.95,
      "file_path": "/data/snapshots/2025-01-15/10-30-45.jpg",
      "image_url": "/api/v1/evidence/1/image",
      "gps_lat": 31.2304,
      "gps_lon": 121.4737,
      "created_at": "2025-01-15T10:30:45.123Z"
    }
  ]
}
```

### WebSocket 遥测流

```
WS /ws/telemetry
```

**消息类型：**

#### 1. TELEMETRY_UPDATE（服务端推送）

```json
{
  "type": "TELEMETRY_UPDATE",
  "seq": 123,
  "timestamp": "2025-01-15T10:30:45.123Z",
  "payload": { ... }
}
```

#### 2. SYSTEM_EVENT（服务端推送）

```json
{
  "type": "SYSTEM_EVENT",
  "event": "MAVLINK_CONNECTED",
  "timestamp": "2025-01-15T10:30:45.123Z"
}
```

#### 3. PING（客户端发送）

```json
{
  "type": "PING"
}
```

**服务端响应：**
```json
{
  "type": "PONG",
  "timestamp": "2025-01-15T10:30:45.123Z"
}
```

## 数据库

### 初始化

数据库表会在应用启动时自动创建（通过 `init_db()`）。

数据库文件位置：`./data/botdog.db`（可在 `.env` 中配置）

### 表结构

详见 `docs/14_database_schema.md` 或直接查看 `backend/models.py`。

## 测试

### 运行测试

```bash
# 运行所有测试
pytest

# 运行测试并生成覆盖率报告
pytest --cov=backend --cov-report=html
```

### 测试依赖

测试框架已包含在 `requirements.txt` 中：
- `pytest`
- `pytest-asyncio`
- `httpx`
- `pytest-cov`

## 开发调试

### 查看日志

应用使用 `loguru` 输出结构化日志：

```python
from backend.logging_config import logger

logger.info("消息")
logger.warning("警告")
logger.error("错误")
```

### 模拟数据源

开发时默认使用模拟数据源（`MAVLINK_SOURCE=simulation`），无需连接真实 MAVLink 设备。

模拟数据生成器位于 `workers_simulation.py`。

### 连接真实 MAVLink 设备

修改 `.env` 配置：

```bash
MAVLINK_SOURCE=mavlink
MAVLINK_ENDPOINT=udp:127.0.0.1:14550
```

确保 MAVLink 设备（如飞控、仿真器）已启动并监听指定端口。

## 下一步

阶段 2 计划实现：

- 控制通道 WebSocket `/ws/control`
- 急停机制 `POST /api/v1/control/e-stop`
- 控制输入速率限制
- MAVLink `MANUAL_CONTROL` 报文发送

详见 `docs/13_implementation_plan.md`。

## 常见问题

### Q: 数据库初始化失败？

检查 `DATABASE_URL` 配置是否正确，确保 `data/` 目录存在且有写入权限。

### Q: MAVLink 连接失败？

1. 确认 `MAVLINK_SOURCE` 配置（开发时用 `simulation`）
2. 确认 MAVLink 设备已启动并监听正确端口
3. 检查防火墙设置

### Q: WebSocket 客户端无法连接？

1. 确认后端服务已启动
2. 检查 CORS 配置（`CORS_ALLOW_ORIGINS`）
3. 确认前端 WebSocket 地址正确（`ws://localhost:8000/ws/telemetry`）

### Q: 遥测数据未显示？

1. 检查后端日志是否有 MAVLink 报文解析记录
2. 确认状态机状态（`/api/v1/system/health`）
3. 使用 WebSocket 客户端工具（如 `wscat`）测试连接

---

## 阶段 3：媒体管线与 WebRTC 流

### 新增依赖

```bash
# 系统依赖
sudo apt-get install -y \
    libgstreamer1.0-0 \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-tools \
    libgstreamer1.0-dev \
    python3-gi

# Python 依赖（已添加到 requirements.txt）
aiortc==1.6.0
```

### 新增模块

| 模块 | 说明 |
|------|------|
| `webrtc_signaling.py` | WebRTC 信令处理器（SDP/ICE 交换） |
| `video_track.py` | GStreamer 视频轨道（UDP RTP H.264 → aiortc MediaStreamTrack） |
| `video_watchdog.py` | 视频看门狗（超时检测与重连） |

### 新增配置项

在 `.env` 中添加：

```bash
# 视频配置
VIDEO_RESOLUTION=3840x2160
VIDEO_BITRATE=8000000
VIDEO_FRAMERATE=30
VIDEO_UDP_PORT=5000
VIDEO_WATCHDOG_TIMEOUT_S=5.0

# WebRTC 配置
WEBRTC_ICE_SERVERS=["stun:stun.l.google.com:19302"]
```

### 新增 API 端点

#### WebRTC 信令 WebSocket

```
WS /ws/webrtc
```

**信令流程：**

1. 客户端连接 → 服务端发送 `welcome` + `client_id`
2. 客户端发送 `offer`（SDP）
3. 服务端回复 `answer`（SDP）+ `ice_candidates`
4. 双方交换 `ice_candidate` 建立 P2P 连接

**消息格式：**

```json
{
  "msg_type": "offer|answer|ice_candidate|welcome|ice_candidates|error",
  "client_id": "uuid（仅 welcome）",
  "payload": {
    "sdp": "SDP 内容",
    "candidates": [/* ICE 候选数组 */],
    "candidate": "单个 ICE 候选",
    "sdpMid": "ICE 候选 SDP MID",
    "sdpMLineIndex": 0,
    "error": "错误信息"
  }
}
```

### 边缘端推流（部署在 Jetson）

脚本位置：`edge/gstreamer_streamer.py`

**测试模式（推荐）：**

```bash
python edge/gstreamer_streamer.py \
    --source videotestsrc \
    --width 1920 \
    --height 1080 \
    --framerate 30 \
    --host 127.0.0.1 \
    --port 5000
```

**摄像头模式：**

```bash
# USB 摄像头
python edge/gstreamer_streamer.py \
    --source v4l2src \
    --device /dev/video0 \
    --width 1920 \
    --height 1080

# Jetson MIPI CSI 摄像头
python edge/gstreamer_streamer.py \
    --source nvarguscamerasrc \
    --width 3840 \
    --height 2160
```

### 验证环境

运行环境验证脚本：

```bash
python backend/scripts/validate_environment.py
```

应看到所有关键依赖已安装（`gst-launch-1.0`、`aiortc`、GStreamer 插件）。

### 常见问题

**Q: WebRTC 连接失败？**

1. 检查 `/ws/webrtc` WebSocket 是否正常
2. 检查浏览器控制台错误
3. 确认 STUN 服务器可达

**Q: 没有视频流？**

1. 确认边缘端推流已启动
2. 检查 UDP 端口 5000 是否被占用
3. 确认 GStreamer 管道正常启动

**Q: 视频卡顿或延迟高？**

1. 降低分辨率和码率（例如 1280x720, 4Mbps）
2. 检查网络带宽
3. 检查系统负载

### 下一步

阶段 3 当前已完成：信令服务、视频轨道接入、前端 VideoPlayer 与 HUD 叠层、边缘端 GStreamer 推流脚本。

后续可完善：姿态仪可视化、航向指示器、自适应码率、网络波动恢复。
