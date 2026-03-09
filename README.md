# BotDog 机器狗控制系统

![Version](https://img.shields.io/badge/version-5.0-blue)
![Python](https://img.shields.io/badge/python-3.10+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## 🎯 项目简介

BotDog 是一个完整的**四足机器狗远程控制系统**，提供实时控制、遥测监控、AI 告警和可视化界面。

### 核心功能

- ✅ **实时控制** - 键盘 + 游戏手柄（Xbox/PlayStation）
- ✅ **遥测监控** - 实时姿态、位置、温度、电池
- ✅ **AI 告警** - 温度异常自动检测和告警
- ✅ **配置管理** - 可视化配置界面，13 个配置项
- ✅ **视频流** - WebRTC 实时视频传输
- ✅ **事件系统** - 实时事件推送和历史记录

### 技术栈

**后端**:
- Python 3.10+
- FastAPI（Web 框架）
- SQLAlchemy（ORM）
- WebSocket（实时通信）
- WebRTC（视频流）
- MAVLink（机器人通信协议）

**前端**:
- React 18
- TypeScript
- Vite（构建工具）
- WebSocket（实时数据）
- WebRTC（视频流）

---

## 🚀 快速开始

### 1. 环境要求

```bash
# Python 3.10+
python --version

# Node.js 18+
node --version
npm --version
```

### 2. 安装依赖

```bash
# 创建并激活 Python 虚拟环境（首次运行）
python3 -m venv .venv
source .venv/bin/activate  # Linux/Mac
# 或者在 Windows 上使用: .venv\Scripts\activate

# 后端依赖
pip install -r requirements.txt

# 前端依赖
cd frontend
npm install
```

### 3. 启动服务

```bash
# 激活虚拟环境（如果尚未激活）
source .venv/bin/activate  # Linux/Mac

# 后端（终端 1）- 从项目根目录启动
uvicorn backend.main:app --host 0.0.0.0 --port 8000

# 或者进入 backend 目录启动
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000

# 前端（终端 2）- 新开一个终端
cd frontend
npm run dev
```

> **⚠️ 重要**：
> - 后端必须使用 `--host 0.0.0.0` 监听所有网卡，否则外部设备无法连接
> - 生产环境可以去掉 `--reload` 参数，提高性能
> - 如果端口被占用，可以使用 `--port 8001` 等其他端口

### 4. 访问界面

打开浏览器访问: `http://localhost:5173` 或 `http://YOUR_IP:5173`

---

## 📹 视频流获取指南

### 视频流架构

```
┌─────────────┐    H.265 RTP    ┌─────────────┐    WebRTC    ┌─────────────┐
│  边缘端摄像头 │ ──────────────> │  后端中继    │ ────────────> │  浏览器播放  │
│ (GStreamer) │   UDP:5000      │ (video_track) │   信令:8000   │  (WebRTC)   │
└─────────────┘                  └─────────────┘               └─────────────┘
```

### 获取视频流的方法

#### 方法 1：浏览器实时观看（推荐）

**步骤**：
1. 启动后端（监听 `0.0.0.0:8000`）
2. **启动边缘端推流**（在边缘设备上运行）：
   ```bash
   python3 edge/gstreamer_streamer.py \
     --source rtsp \
     --device "rtsp://YOUR_CAMERA_IP:8554/main.264" \
     --host 192.168.144.40 \  # 后端服务器 IP
     --port 5000 \
     --bitrate 2000000 \      # 2Mbps 码率（根据网络调整）
     --width 1280 \           # 输出分辨率
     --height 720
   ```
3. 启动前端：`cd frontend && npm run dev`
4. 打开浏览器访问 `http://YOUR_IP:5173`
5. 视频会自动通过 WebRTC 播放

**特点**：
- ✅ 实时性最好（延迟 < 500ms）
- ✅ 自动编解码优化
- ✅ 支持所有现代浏览器
- ✅ 可调节码率和分辨率适应网络

#### 方法 2：GStreamer 命令直接接收

**查看实时视频**：
```bash
gst-launch-1.0 udpsrc port=5000 ! \
  application/x-rtp,media=video,encoding-name=H265 ! \
  rtph265depay ! h265parse ! \
  avdec_h265 ! \
  videoconvert ! \
  autovideosink
```

**保存视频流到文件**：
```bash
gst-launch-1.0 udpsrc port=5000 ! \
  application/x-rtp,media=video,encoding-name=H265 ! \
  rtph265depay ! h265parse ! \
  mp4mux ! \
  filesink location=video.mp4
```

#### 方法 3：Python 后端处理视频帧

在后端 `video_track.py` 的 `_on_new_sample` 方法中添加自定义逻辑：

```python
def _on_new_sample(self, sink):
    # 现有的帧处理逻辑...
    frame = self._create_video_frame(info)

    # 添加你的自定义处理
    self._process_frame(frame)  # AI 推理、目标检测等

    # 将帧放入队列
    self.frame_queue.put(frame)
    return Gst.FlowReturn.OK

def _process_frame(self, frame):
    # 你的自定义处理逻辑
    # 例如：目标检测、姿态估计、保存图片等
    pass
```

### 视频流配置

#### 边缘端推流配置（edge/gstreamer_streamer.py）

**基本推流命令**：
```bash
python3 edge/gstreamer_streamer.py \
  --source rtsp \
  --device "rtsp://192.168.144.25:8554/main.264" \
  --host 192.168.144.40 \
  --port 5000 \
  --bitrate 2000000 \
  --width 1280 \
  --height 720
```

**参数说明**：
- `--source`: 输入源类型（`rtsp`、`v4l2`、`file`）
- `--device`: 输入设备地址（RTSP URL、设备路径、文件路径）
- `--host`: 后端服务器 IP 地址
- `--port`: 后端 UDP 接收端口（默认 5000）
- `--bitrate`: 视频码率（bps），推荐值：
  - 2Mbps (2000000) - 720p 流畅
  - 4Mbps (4000000) - 1080p 流畅
  - 1Mbps (1000000) - 低带宽环境
- `--width/--height`: 输出分辨率

**网络质量调优建议**：

| 网络环境 | 码率 | 分辨率 | 命令示例 |
|---------|------|--------|---------|
| 千兆局域网 | 4Mbps | 1920x1080 | `--bitrate 4000000 --width 1920 --height 1080` |
| 百兆局域网 | 2Mbps | 1280x720 | `--bitrate 2000000 --width 1280 --height 720` |
| 弱网环境 | 1Mbps | 640x480 | `--bitrate 1000000 --width 640 --height 480` |

#### 后端解码配置（backend/video_track.py）

**当前默认配置**：
- **输入**: H.265 RTP, UDP port 5000
- **输出分辨率**: 800x600（多线程解码）
- **帧率**: 15 FPS（videorate 稳定）
- **抖动缓冲**: 200ms（抗丢包）
- **接收缓冲**: 5MB（防关键帧丢包）
- **解码格式**: I420（YUV420P）
- **线程架构**: 3 个独立队列（网络接收、解码、后处理）

**修改分辨率**：
```python
# 在 backend/video_track.py 中修改
track = GStreamerVideoTrack(
    udp_port=5000,
    width=1280,   # 修改为 1920 可获得 1080p
    height=720,   # 修改为 1080 可获得 1080p
    framerate=15, # 帧率（建议 15-30）
)
```

### 故障排查

**问题 1：画面卡在第一帧**
- ✅ 已优化：多线程管道（3 个独立队列）
- ✅ 配置 `config-interval=1` 强制发送 SPS/PPS
- ✅ 5MB 接收缓冲 + 200ms 抖动缓冲

**问题 2：CPU 占用过高**
- ✅ 使用 800x600 分辨率平衡画质与性能
- ✅ 15fps 稳定帧率（videorate）
- ✅ 多线程并行处理（6 核协同）

**问题 3：灰屏/残影**
- ✅ 多线程管道防止 UDP 丢包
- ✅ 5MB 接收缓冲确保关键帧完整
- ✅ `config-interval=1` 频繁发送配置头
- ✅ 降低边缘端码率（`--bitrate 2000000`）

**问题 4：延迟过高**
- ✅ 检查网络质量（ping 测试）
- ✅ 降低边缘端码率（1-2Mbps）
- ✅ 降低分辨率（640x480）
- ✅ 使用千兆网络

**检查视频流状态**：
```bash
# 查看后端日志
tail -f /tmp/backend_multithread.log

# 检查 GStreamer 管道状态
ps aux | grep python | grep video_track

# 测试 UDP 端口（应该能看到 RTP 数据包）
nc -lu 5000

# 检查网络带宽
iftop -i eth0  # 监控网络流量
```

---

## 🎮 控制方式

### 游戏手柄控制（推荐）

**支持的控制器**:
- Xbox 360 / Xbox One / Xbox Series X/S
- PlayStation 4 / PlayStation 5
- 任何标准映射的 USB 游戏手柄

**控制映射**:
- 左摇杆 Y: 前进/后退
- 左摇杆 X: 左右平移
- 右摇杆 Y: 上下控制
- LB/RB: 左右转向

**使用步骤**:
1. 连接游戏手柄到电脑
2. 打开浏览器，访问前端页面
3. **按下手柄上的任意按钮**（激活 Gamepad API）
4. 点击"启用控制"按钮
5. 开始使用摇杆控制机器狗

### 键盘控制（备用）

- W/S: 前进/后退
- A/D: 左右平移
- Q/E: 升降
- ←/→: 转向

---

## ⚙️ 配置管理

### 配置界面

点击顶部状态栏的 **"⚙️ 配置"** 按钮打开配置界面。

### 配置类别

**后端配置** (5 项):
- `thermal_threshold` - 高温告警阈值
- `heartbeat_timeout` - 心跳超时
- `control_rate_limit_hz` - 控制速率限制
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

## 📊 系统架构

```
┌───────────────────────────────────────────────────────┐
│                       浏览器界面                        │
│  ┌────────────────────────────────────────────────┐   │
│  │  HeaderBar  │  VideoSection  │  ControlPanel │   │
│  └────────────────────────────────────────────────┘   │
│  ┌────────┐                                        │
│  │SnapshotList (告警快照)                       │
│  └────────┘                                        │
└───────────────────────────────────────────────────────┘
                            │
                    WebSocket / WebRTC
                            │
┌───────────────────────────────────────────────────────┐
│                    FastAPI 后端                      │
│  ┌───────────────┐  ┌───────────────┐  ┌─────────┐ │
│  │  WebSocket   │  │  WebRTC信令   │  │MAVLink  │ │
│  │   Handler     │  │   Server      │  │ Gateway │ │
│  └───────────────┘  └───────────────┘  └─────────┘ │
│  ┌───────────────┐  ┌───────────────┐                │
│  │ AlertService  │  │ConfigService  │  Database  │ │
│  └───────────────┘  └───────────────┘  (SQLite)  │
└───────────────────────────────────────────────────────┘
                            │
                    MAVLink / Serial
                            │
┌───────────────────────────────────────────────────────┐
│              机器狗硬件（摄像头、MAVLink 设备）      │
└───────────────────────────────────────────────────────┘
```

---

## 🧪 验收测试

```bash
# 运行所有验收测试（UC-01 到 UC-05）
python acceptance_test.py
```

### 测试覆盖

- ✅ UC-01: 系统健康检查
- ✅ UC-02: 遥测 WebSocket 连接
- ✅ UC-03: 事件 WebSocket 连接
- ✅ UC-04: 配置管理 API
- ✅ UC-05: 告警系统功能

**当前通过率**: 100% (5/5) 🎉

---

## 📚 文档

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
- [游戏手柄控制](docs/22_gamepad_implementation_complete.md)
- [配置管理界面](docs/23_config_panel_implementation.md)

### 部署指南
- [部署测试指南](docs/24_deployment_testing_guide.md) ⭐ **正式部署必读**
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
# 开发模式（热重载）
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

# 生产模式
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 4

# 初始化配置数据库
python init_config.py

# 运行单元测试
pytest tests/
```

### 前端

```bash
# 开发模式
cd frontend
npm run dev

# 生产构建
npm run build

# 预览生产构建
npm run preview
```

### 数据库

```bash
# 初始化数据库表
python init_config.py

# 清理数据库（谨慎使用）
rm -f data/botdog.db
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
├── docs/                # 项目文档
├── tests/               # 后端测试
├── data/                # 数据库文件
├── acceptance_test.py   # 验收测试
└── requirements.txt     # Python 依赖
```

---

## 🚢 部署

### 前置条件

1. **机器狗端需要**:
   - MAVLink 设备（串口或 UDP 连接）
   - 摄像头设备（/dev/video0）
   - Python 3.10+ 环境
   - GStreamer 库

2. **操作端需要**:
   - 现代浏览器（Chrome/Firefox/Edge）
   - 网络连接到机器狗
   - 游戏手柄（可选）

详细部署步骤请参考: [docs/24_deployment_testing_guide.md](docs/24_deployment_testing_guide.md)

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

## 👥 作者

- **开发者**: Claude Code + Human collaborator
- **项目**: BotDog 机器狗控制系统
- **版本**: v5.0

---

## 🎉 致谢

感谢所有开源项目的贡献者：
- FastAPI
- React
- WebRTC
- MAVLink
- GStreamer
- aiortc

---

**状态**: ✅ 生产就绪
**最后更新**: 2026-03-06
**仓库**: https://github.com/Timekeeperxxx/BotDog
