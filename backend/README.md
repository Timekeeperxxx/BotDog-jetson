# BotDog 后端

BotDog 机器人控制系统的后端服务，运行于 **OrangePi 5 Ultra**，负责遥测采集、AI 识别、运动控制、任务管理与 WebSocket 广播。

## 技术栈

| 组件 | 版本/说明 |
|------|-----------|
| Python | 3.12+ |
| FastAPI | Web 框架 + API 路由 |
| uvicorn | ASGI 服务器 |
| SQLAlchemy 2.0 | 异步 ORM |
| aiosqlite | 异步 SQLite 驱动 |
| Pydantic Settings | 类型安全配置管理 |
| ultralytics (YOLOv8) | AI 目标检测 |
| loguru | 结构化日志 |

## 系统架构

```
OrangePi 5 Ultra
├── backend/          ← 本服务（FastAPI）
│   ├── 遥测广播 (WebSocket /ws/telemetry)
│   ├── 事件广播 (WebSocket /ws/events)
│   ├── AI 推理  (RTSP → YOLOv8 → ByteTrack)
│   ├── 运动控制 (Unitree B2 SDK / 模拟)
│   └── 任务管理 (SQLite)
│
├── MediaMTX          ← 视频服务器
│   ├── cam  (WHEP)   ← HM30 IP 摄像头
│   └── cam2 (WHEP)   ← USB 摄像头 (C920)
│
└── FFmpeg × 2        ← 视频采集推流（由 run-pipeline.sh 管理）
    ├── cam1: HM30 摄像头 RTSP → MediaMTX
    └── cam2: /dev/video1 V4L2 → MediaMTX
```

## 快速启动

### 1. 准备虚拟环境

```bash
# 在项目根目录执行
python -m venv .venv
source .venv/bin/activate        # Linux
# Windows: .venv\Scripts\Activate.ps1
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置环境变量

```bash
cp backend/.env.example backend/.env
# 根据实际硬件修改 .env 关键项（见下方说明）
```

### 4. 启动后端

```bash
# 开发模式（热重载）
uvicorn backend.main:app --reload

# 生产模式（OrangePi 上推荐）
python run_backend.py
```

### 5. 启动视频流水线

```bash
# 自动检测 HM30 摄像头和 USB 摄像头并启动 FFmpeg
bash scripts/run-pipeline.sh

# 停止
bash scripts/run-pipeline.sh stop
```

## 环境变量说明

完整模板见 `backend/.env.example`，以下列出关键项：

### 基础网络

```bash
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8000
```

### 遥测 & 数据库

```bash
DATABASE_URL=sqlite+aiosqlite:///./data/botdog.db
MAVLINK_SOURCE=simulation        # simulation | mavlink
MAVLINK_ENDPOINT=udp:127.0.0.1:14550
SIMULATION_WORKER_ENABLED=false  # 生产环境关闭
```

### AI 识别

```bash
AI_ENABLED=true
AI_RTSP_URL=rtsp://127.0.0.1:8554/cam   # MediaMTX cam 路径
AI_FRAME_WIDTH=1280
AI_FRAME_HEIGHT=720
AI_FPS=30
AI_MODEL_PATH=models/yolov8n.pt
AI_CONFIDENCE_THRESHOLD=0.33
AI_TARGET_CLASSES=["person"]
AI_DEVICE=auto                   # auto | cpu | cuda
```

### 运动控制

```bash
CONTROL_ADAPTER_TYPE=unitree_b2  # unitree_b2 | simulation
CONTROL_WATCHDOG_TIMEOUT_MS=1500 # 前端无命令超时自动 stop（ms）
CONTROL_CMD_RATE_LIMIT_MS=50
```

### 自动跟踪

```bash
AUTO_TRACK_ENABLED=false         # 启动时默认关闭，由前端控制
AUTO_TRACK_COMMAND_INTERVAL_MS=100
AUTO_TRACK_YAW_DEADBAND_PX=150   # 中心死区（像素），防抖
AUTO_TRACK_FORWARD_AREA_RATIO=0.35
AUTO_TRACK_YAW_PULSE_MS=150      # 脉冲转向时长（ms），0=禁用
```

### 宇树 B2 硬件

```bash
UNITREE_NETWORK_IFACE=enP3p49s0  # 连接 B2 的网卡（ip addr 确认）
UNITREE_B2_VX=0.3                # 前进/后退速度（m/s）
UNITREE_B2_VYAW=0.5              # 偏航转速（rad/s）
```

## 项目结构

```
backend/
├── main.py                     # FastAPI 应用入口，路由注册，生命周期
├── config.py                   # Pydantic Settings 配置管理
├── database.py                 # 数据库连接与会话
├── models.py                   # SQLAlchemy ORM 模型
├── schemas.py                  # Pydantic DTO（请求/响应结构）
├── logging_config.py           # Loguru 日志配置
│
├── mavlink_gateway.py          # MAVLink UDP 报文解析网关
├── mavlink_dto.py              # MAVLink 数据传输对象
├── telemetry_queue.py          # 遥测队列管理（广播 & 落盘）
├── state_machine.py            # 系统状态机
│
├── ws_broadcaster.py           # WebSocket 遥测广播器
├── ws_event_broadcaster.py     # WebSocket 事件广播器（AI/控制事件）
├── global_event_broadcaster.py # 全局事件总线（单例）
│
├── workers_ai.py               # AI Worker（YOLOv8 推理 + ByteTrack）
├── workers_telemetry.py        # 遥测落盘 Worker
├── workers_simulation.py       # 模拟遥测数据生成器
├── workers_unitree_telemetry.py# 宇树 B2 遥测采集 Worker
│
├── control_service.py          # 控制命令服务（仲裁 + 发送）
├── control_arbiter.py          # 控制权仲裁器（手动 vs 自动跟踪）
├── robot_adapter.py            # 机器人适配器（B2 SDK / 模拟）
│
├── auto_track_service.py       # 自动跟踪服务（状态机 + AI 决策）
├── follow_decision_engine.py   # 跟踪决策引擎（方向/速度计算）
├── target_manager.py           # 跟踪目标管理器
├── tracking_types.py           # 跟踪相关类型定义
│
├── alert_service.py            # 告警管理服务
├── zone_service.py             # 区域管理服务
├── stranger_policy.py          # 陌生人识别策略
│
├── services_config.py          # 配置管理 API 服务
├── services_video_sources.py   # 视频源 & 网口管理服务
├── services_tasks.py           # 任务管理服务
├── services_logs.py            # 操作日志服务
├── services_telemetry.py       # 遥测查询服务
├── services_evidence.py        # 证据管理服务
│
├── video_watchdog.py           # 视频流看门狗
└── temperature_monitor.py      # 系统温度监控

scripts/
├── run-pipeline.sh             # 视频流水线启动脚本（MediaMTX + FFmpeg）
└── mediamtx                    # MediaMTX 可执行文件

config/
└── mediamtx.yml                # MediaMTX 配置（RTSP + WHEP 路径）
```

## API 端点总览

### 系统

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/system/health` | 健康检查 |
| GET | `/api/v1/system/status` | 系统完整状态 |

### 任务管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/session/start` | 启动巡检任务 |
| POST | `/api/v1/session/stop` | 停止巡检任务 |

### 运动控制

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/control/command` | 发送运动命令 |
| POST | `/api/v1/control/stop` | 紧急停止 |

### AI 自动跟踪

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/auto-track/enable` | 启用自动跟踪 |
| POST | `/api/v1/auto-track/disable` | 禁用自动跟踪 |
| GET | `/api/v1/auto-track/status` | 获取跟踪状态 |

### 证据 & 日志

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/evidence` | 查询证据列表 |
| POST | `/api/v1/evidence/bulk-delete` | 批量删除证据 |
| GET | `/api/v1/logs` | 查询操作日志 |

### 视频源管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/video-sources` | 获取所有视频源 |
| GET | `/api/v1/video-sources/active` | 获取已启用视频源 |
| PUT | `/api/v1/video-sources/{id}` | 更新视频源配置 |

### 配置管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/config` | 获取所有配置项 |
| PUT | `/api/v1/config/{key}` | 更新配置项 |

### WebSocket

| 路径 | 说明 |
|------|------|
| `WS /ws/telemetry` | 遥测数据流（15Hz 推送） |
| `WS /ws/events` | 事件流（AI 检测、告警、跟踪状态） |

#### 遥测消息格式

```json
{
  "type": "TELEMETRY_UPDATE",
  "seq": 123,
  "timestamp": "2026-04-10T10:30:45.123Z",
  "payload": {
    "attitude": { "pitch": 0.0, "roll": 0.0, "yaw": 0.0 },
    "position": { "lat": 0.0, "lon": 0.0, "alt": 0.0, "groundspeed": 0.0 },
    "battery_pct": 85.0,
    "rssi_dbm": -65,
    "core_temp_c": 42.0
  }
}
```

#### 事件消息格式（AI 检测告警）

```json
{
  "type": "AI_DETECTION",
  "severity": "CRITICAL",
  "message": "检测到陌生人",
  "confidence": 0.92,
  "image_url": "/api/v1/evidence/42/image",
  "timestamp": "2026-04-10T10:30:45.123Z"
}
```

## 数据库模型

| 模型 | 表名 | 说明 |
|------|------|------|
| `InspectionTask` | `inspection_tasks` | 巡检任务 |
| `TelemetrySnapshot` | `telemetry_snapshots` | 遥测快照（降采样） |
| `AnomalyEvidence` | `anomaly_evidence` | AI 检测证据 |
| `OperationLog` | `operation_logs` | 操作日志 |
| `ConfigEntry` | `config` | 运行时配置 |
| `VideoSource` | `video_sources` | 视频源配置 |
| `NetworkInterface` | `network_interfaces` | 网口配置 |

数据库文件：`data/botdog.db`（应用启动时自动建表）

## 视频流接入

### 视频管线

```
HM30 IP 摄像头 (192.168.144.25:8554)
    → FFmpeg 拉流 → MediaMTX cam → WHEP → 浏览器主画面

USB 摄像头 C920 (/dev/video1)
    → FFmpeg V4L2 采集 → MediaMTX cam2 → WHEP → 浏览器 PiP
```

### 手动验证 cam2

```bash
# 查看 C920 支持的格式
v4l2-ctl --device=/dev/video1 --list-formats-ext

# 手动推流测试
ffmpeg -f v4l2 -input_format mjpeg -framerate 30 -video_size 1280x720 \
  -i /dev/video1 \
  -c:v libx264 -preset ultrafast -tune zerolatency -pix_fmt yuv420p \
  -b:v 1500k -f rtsp -rtsp_transport tcp rtsp://127.0.0.1:8554/cam2
```

### 验证 WHEP 流

```bash
# 查看 MediaMTX 路径状态
curl http://127.0.0.1:8889/v3/paths/list | python3 -m json.tool

# cam2 WHEP 地址
# http://<OrangePi_IP>:8889/cam2/whep
```

## 开发调试

### API 文档

```
http://localhost:8000/api/docs       # Swagger UI
http://localhost:8000/api/openapi.json
```

### 日志查看

```bash
# 后端日志（标准输出）
python run_backend.py 2>&1 | tee logs/backend.log

# MediaMTX 日志
tail -f logs/mediamtx.log

# FFmpeg cam1 日志
tail -f logs/ffmpeg.log

# FFmpeg cam2 日志
tail -f logs/ffmpeg_cam2.log
```

### 键盘控制调试脚本

```bash
# 直接用键盘控制 B2（绕过前端，调试用）
python backend/test_keyboard_to_dog.py
```

## 常见问题

**Q: 后端启动报 `unitree sdk` 相关错误？**

将 `CONTROL_ADAPTER_TYPE=simulation` 改为模拟模式，或确认宇树 SDK 已正确安装（参见 `arm46orangepi_bulid.md`）。

**Q: AI Worker 不推理？**

1. 检查 `AI_ENABLED=true`
2. 确认模型文件存在：`models/yolov8n.pt`
3. 确认 `AI_RTSP_URL` 指向有效的 MediaMTX 路径

**Q: cam2 画中画不显示？**

1. 确认 C920 已连接：`ls /dev/video1`
2. 确认 FFmpeg cam2 进程在运行：`tail -f logs/ffmpeg_cam2.log`
3. 检查 MediaMTX cam2 路径是否有流：`curl http://127.0.0.1:8889/v3/paths/list`

**Q: 自动跟踪机器人乱转？**

调整 `AUTO_TRACK_YAW_DEADBAND_PX`（增大死区）和 `AUTO_TRACK_YAW_PULSE_MS`（缩短脉冲），或检查 AI 检测帧率是否过低。

**Q: WebSocket 连接断开？**

1. 确认后端服务正常运行
2. 检查 `CORS_ALLOW_ORIGINS` 是否包含前端地址
3. OrangePi 防火墙确认 8000 端口开放
