# BotDog 机器狗控制系统

![Version](https://img.shields.io/badge/version-5.0-blue)
![Python](https://img.shields.io/badge/python-3.12+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## 项目简介

BotDog 是一个完整的**四足机器狗远程控制系统**，提供实时控制、遥测监控、AI 告警和可视化界面。

### 核心功能

- ✅ **遥测监控** - 实时姿态、位置、温度、电池
- ✅ **AI 告警** - 温度异常自动检测和告警
- ✅ **配置管理** - 可视化配置界面，13 个配置项
- ✅ **视频流** - RTSP(H.265) → FFmpeg(H.264) → MediaMTX(WHEP)
- ✅ **事件系统** - 实时事件推送和历史记录

### 技术栈

**后端**:
- Python 3.12+
- FastAPI（Web 框架）
- SQLAlchemy（ORM）
- WebSocket（实时通信）
- MAVLink（机器人通信协议）

**视频流链路**:
- FFmpeg（H.265 → H.264 转码）
- MediaMTX（RTSP → WHEP 网关）
- WHEP（浏览器 WebRTC 播放）

**前端**:
- React 18
- TypeScript
- Vite（构建工具）
- WebSocket（实时数据）

---

## 快速开始

### 1. 环境要求

```bash
# Python 3.12+
python --version

# Node.js 18+
node --version
npm --version
```

### 2. 安装依赖

```bash
# 后端：创建并激活 Python 虚拟环境
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate

pip install -r requirements.txt

# 前端
cd frontend
npm install
```

### 3. 配置环境变量

```bash
# 后端配置（复制模板，按需修改）
copy backend\.env.example backend\.env   # Windows
cp backend/.env.example backend/.env       # Linux/Mac

# 前端配置（复制模板，按需修改）
copy frontend\.env.example frontend\.env  # Windows
cp frontend/.env.example frontend/.env     # Linux/Mac
```

> **提示**：
> - 默认配置即为**纯模拟模式**，无需任何硬件即可运行
> - AI 功能默认关闭（`AI_ENABLED=false`），开启需额外下载模型文件（见下文）

### 4. 初始化数据库

```bash
# 在项目根目录执行（激活虚拟环境后）
python scripts/init_db.py
```

### 5. 启动服务

```bash
# 后端（终端 1，在项目根目录）
# Windows
.\scripts\start_backend.bat
# Linux/Mac
bash scripts/start_backend.sh

# 前端（终端 2）
cd frontend
npm run dev
```

### 6. 访问界面

打开浏览器访问: `http://localhost:5174`

---

## 视频流与技术栈转换

### 视频流架构

```
┌─────────────┐   RTSP(H.265)   ┌─────────────┐   RTSP publish  ┌─────────────┐
│  相机 RTSP   │ ──────────────> │   FFmpeg     │ ──────────────> │  MediaMTX   │
│ (H.265)      │   554/8554     │  转码 H.264  │                 │  WHEP 输出  │
└─────────────┘                  └─────────────┘                 └─────┬──────┘
                                                                       │
                                                                       ▼
                                                               ┌─────────────┐
                                                               │  浏览器播放  │
                                                               │  (WHEP)     │
                                                               └─────────────┘
```

### 本机低延迟播放（推荐）

**步骤**：
1. 一键启动：`scripts/run-pipeline.cmd`
2. 前端访问：`http://127.0.0.1:5174` 或 `http://YOUR_IP:5174`

**默认配置**：
- 相机 RTSP：`CAMERA_RTSP_URL=rtsp://192.168.144.25:8554/main.264`
- MediaMTX RTSP：`rtsp://127.0.0.1:8554/cam`
- WHEP：`http://127.0.0.1:8889/cam/whep`

### 重连机制说明

- FFmpeg 断流会自动重启（脚本内置看门狗）。
- 前端 WHEP 连接断开后会自动重连。

### WHEP 测试页

- `web/index.html` 用于快速验证 WHEP 播放（需要 MediaMTX 运行中）
- 可在输入框中修改 WHEP URL

---

## 控制方式

支持两种控制方式：
- **Web 控制面板**：通过界面上的虚拟摇杆或键盘控制，无需硬件
- **FT24 遥控器**：通过 SBUS 协议硬件直连控制机器狗（需要硬件）

---

## 配置管理

### 配置界面

点击顶部状态栏的 **"⚙️ 配置"** 按钮打开配置界面。

### 配置类别

**后端配置** (4 项):
- `thermal_threshold` - 高温告警阈值
- `heartbeat_timeout` - 心跳超时
- `ws_max_clients_per_ip` - WebSocket 连接限制
- `video_watchdog_timeout_s` - 视频看门狗超时

**前端配置** (4 项):
- `ui_alert_ack_timeout_s` - 告警确认超时
- `telemetry_display_hz` - 遥测显示刷新率
- `ui_lang` - 界面语言
- `ui_theme` - UI 主题

**存储配置** (3 项):
- `snapshot_retention_days` - 快照保留天数
- `max_snapshot_disk_usage_gb` - 快照最大占用
- `telemetry_retention_days` - 遥测数据保留天数

---

## 系统架构

```
┌───────────────────────────────────────────────────────┐
│                       浏览器界面                        │
│  ┌────────────────────────────────────────────────┐   │
│  │  HeaderBar  │  VideoSection  │  SnapshotList │   │
│  └────────────────────────────────────────────────┘   │
└───────────────────────────────────────────────────────┘
                           │
                  WebSocket + WHEP
                           │
┌───────────────────────────────────────────────────────┐
│                    FastAPI 后端                      │
│  ┌───────────────┐  ┌───────────────┐  ┌─────────┐ │
│  │  WebSocket   │  │ AlertService  │  │MAVLink  │ │
│  │   Handler     │  │ConfigService  │  │ Gateway │ │
│  └───────────────┘  └───────────────┘  └─────────┘ │
│  ┌───────────────────────────────────────────────┐   │
│  │                Database (SQLite)             │   │
│  └───────────────────────────────────────────────┘   │
└───────────────────────────────────────────────────────┘
                           │
                   MAVLink / Serial
                           │
┌───────────────────────────────────────────────────────┐
│              机器狗硬件（摄像头、MAVLink 设备）      │
└───────────────────────────────────────────────────────┘
```

```
┌─────────────┐   RTSP(H.265)   ┌─────────────┐   RTSP publish  ┌─────────────┐
│  相机 RTSP   │ ──────────────> │   FFmpeg     │ ──────────────> │  MediaMTX   │
│ (H.265)      │                 │  转码 H.264  │                 │  WHEP 输出  │
└─────────────┘                  └─────────────┘                 └─────┬──────┘
                                                                      │
                                                                      ▼
                                                              ┌─────────────┐
                                                              │  浏览器播放  │
                                                              │  (WHEP)     │
                                                              └─────────────┘
```

---

## 测试

```bash
# 运行单元测试
pytest tests/

# 带覆盖率报告
pytest tests/ --cov=backend --cov-report=term-missing
```

### 测试覆盖

- ✅ 系统健康检查
- ✅ 遥测 WebSocket 连接
- ✅ 事件 WebSocket 连接
- ✅ 配置管理 API
- ✅ 告警系统功能

---

## 文档

详细文档请查看 [docs/](docs/) 目录：

### 核心文档
- [需求与用例](docs/01_requirements_use_cases.md)
- [实施计划](docs/13_implementation_plan.md)
- [开发环境搭建](docs/10_dev_setup.md)

### 技术规范
- [前端视图契约](docs/05_frontend_view_contract.md)
- [后端协议规范](docs/06_backend_protocol_schema.md)
- [MAVLink 规范](docs/07_mavlink_spec.md)

### 最新功能
- [配置管理界面](docs/23_config_panel_implementation.md)

### 部署指南
- [Git 推送指南](docs/25_git_push_guide.md)

---

## 🔧 开发命令

> **提示**: 所有后端命令都需要先激活虚拟环境：
> ```bash
> source .venv/bin/activate  # Linux/Mac
> .venv\Scripts\activate     # Windows
> ```

### 后端

```bash
# 推荐启动方式
# Windows
.\scripts\start_backend.bat
# Linux/Mac
bash scripts/start_backend.sh

# 开发模式（热重载）
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

# 生产模式
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 4

# 初始化数据库
python scripts/init_db.py

# 运行单元测试
pytest tests/
```

### 前端

```bash
# 开发模式（端口 5174）
cd frontend
npm run dev

# 生产构建
npm run build

# 预览生产构建
npm run preview
```

### 数据库

```bash
# 初始化数据库表（首次运行必须执行）
python scripts/init_db.py

# 清理数据库（谨慎使用）
del data\botdog.db    # Windows
rm -f data/botdog.db  # Linux/Mac
```

### AI 模型（可选）

```bash
# 如需开启 AI 功能，下载 YOLOv8n 模型（~6MB）并放入 models/ 目录
mkdir -p models
# 下载地址：https://github.com/ultralytics/assets/releases/download/v8.2.0/yolov8n.pt
# 然后在 backend/.env 中设置：AI_ENABLED=true
```

---

## 📁 项目结构

```
BotDog/
├── backend/              # FastAPI 后端
│   ├── main.py          # 主应用入口
│   ├── database.py      # 数据库连接
│   ├── models*.py       # SQLAlchemy 模型
│   ├── services_*.py    # 业务服务层
│   └── ws_*.py          # WebSocket 处理器
│
├── frontend/            # React 前端
│   ├── src/
│   │   ├── components/   # React 组件
│   │   ├── hooks/        # React Hooks
│   │   ├── types/        # TypeScript 类型
│   │   └── utils/        # 工具函数
│   └── package.json
│
├── models/              # YOLO 模型文件 (.pt)
├── config/              # 媒体配置（mediamtx.yml 等）
├── scripts/             # 启动脚本与工具
│   └── logs/            # 历史追踪日志归档
├── docs/                # 项目文档
├── tests/               # 后端测试
├── data/                # 数据库 & 抓拍文件
└── requirements.txt     # Python 依赖
```

---

## 🚢 部署

### 纯模拟模式（无需任何硬件）

适合快速体验和前端开发：

```bash
# backend/.env 中确保以下配置
MAVLINK_SOURCE=simulation
SIMULATION_WORKER_ENABLED=true
AI_ENABLED=false
```

### 连接真实机器狗

1. **机器狗端需要**:
   - MAVLink 设备（串口或 UDP 连接）
   - 摄像头设备（RTSP 输出）
   - Python 3.12+ 环境

2. **操作端需要**:
   - 现代浏览器（Chrome/Firefox/Edge）
   - 与机器狗在同一网段
   - 游戏手柄（可选）

3. **配置修改**:
   ```bash
   # backend/.env
   MAVLINK_SOURCE=mavlink
   MAVLINK_ENDPOINT=serial:COM3:57600  # Windows 串口示例
   # MAVLINK_ENDPOINT=serial:/dev/ttyUSB0:57600  # Linux 串口示例
   ```

详细部署步骤请参考: [docs/31_startup_guide.md](docs/31_startup_guide.md)

---

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

### 开发流程

1. Fork 本仓库
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

### 提交规范

- 遵循 [Conventional Commits](https://www.conventionalcommits.org/) 规范
- 添加测试覆盖新功能
- 更新相关文档

---

## 📄 许可证

MIT License

---

## 作者

- **开发者**: Claude Code + Human collaborator
- **项目**: BotDog 机器狗控制系统
- **版本**: v5.0

---

## 致谢

感谢所有开源项目的贡献者：
- FastAPI
- React
- MediaMTX
- FFmpeg
- MAVLink

---

**状态**: ✅ 生产就绪
**最后更新**: 2026-03-20
**仓库**: https://github.com/Timekeeperxxx/BotDog
