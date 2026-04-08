# BotDog 机器狗控制系统

![Version](https://img.shields.io/badge/version-6.0-blue)
![Python](https://img.shields.io/badge/python-3.12+-blue)
![Platform](https://img.shields.io/badge/platform-OrangePi%205%20Ultra-orange)
![License](https://img.shields.io/badge/license-MIT-green)

---

## 项目简介

BotDog 是一个完整的**四足机器狗远程控制系统**，运行在 OrangePi 5 Ultra 上，通过 HM30 无线图传与地面端浏览器实现实时的视频监控、AI 目标识别、自动跟踪和键盘/触控遥控。

### 核心功能

- ✅ **实时遥控** — Web 控制面板，支持键盘（WASD/QE/Shift/Ctrl）和触控操作
- ✅ **AI 目标识别** — YOLOv8 推理，自动检测、跟踪人员目标并抓拍证据
- ✅ **自动跟踪** — AutoTrackService 状态机，目标进入画面即自动跟随
- ✅ **低延迟视频图传** — HM30 无线图传 + WHEP WebRTC 浏览器播放
- ✅ **遥测监控** — 实时姿态、温度、电量 WebSocket 推送
- ✅ **配置管理** — 可视化配置界面，无需重启即可热更新参数
- ✅ **告警与证据** — 异常自动告警、快照落盘、历史查询

---

## 系统架构

```
[ IP 摄像头 192.168.144.25 H.265 RTSP ]
        │
        ├── FFmpeg(软解转码) → MediaMTX(:8889 WHEP) → 浏览器视频
        └── AIWorker(YOLOv8 推理) → AutoTrackService → 控制指令
                                                          │
[ OrangePi 5 Ultra ]                              UnitreeB2Adapter
        │ 网线 192.168.123.222                            │
[ Unitree B2 机器狗 ]  ←─────────────────────────────────┘
        │
  HM30 天空端 → ~ → HM30 地面端 → 交换机 → 笔记本浏览器
                                   http://192.168.144.104:8000
```

### 技术栈

**后端**：Python 3.12 / FastAPI / SQLAlchemy / WebSocket / Unitree SDK2

**AI**：YOLOv8n (Ultralytics) / OpenCV / RTSP 拉流推理

**视频链路**：FFmpeg（H.265→H.264 转码）/ MediaMTX / WebRTC WHEP

**前端**：React 18 / TypeScript / Vite

---

## 快速开始

### 1. 环境要求（OrangePi 5 Ultra）

```bash
python3 --version   # 3.12+
node --version      # 18+
ffmpeg -version     # 任意版本
```

### 2. 安装依赖

```bash
cd ~/Code/Project/BOTDOG/BotDog

# 后端
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Unitree SDK（真机必须）
pip install cyclonedds==0.10.2
git clone https://github.com/unitreerobotics/unitree_sdk2_python.git
cd unitree_sdk2_python && pip install -e . && cd ..

# 前端构建
cd frontend && npm install && npm run build && cd ..

# MediaMTX（ARM64）
cd scripts && wget -qO- https://github.com/bluenviron/mediamtx/releases/download/v1.9.3/mediamtx_v1.9.3_linux_arm64.tar.gz | tar -xzf - mediamtx && chmod +x mediamtx && cd ..
```

### 3. 配置

```bash
cp backend/.env.example backend/.env
# 修改关键参数：
#   CONTROL_ADAPTER_TYPE=unitree_b2
#   UNITREE_NETWORK_IFACE=enP3p49s0
#   AI_ENABLED=true
```

### 4. 启动

```bash
# 初始化数据库（首次）
python scripts/init_db.py

# 启动视频流水线
bash scripts/run-pipeline.sh

# 启动后端
bash scripts/start_backend.sh

# 浏览器访问
# http://<OrangePi_IP>:8000
```

---

## 控制方式

### 键盘快捷键

| 按键 | 功能 | 按键 | 功能 |
|------|------|------|------|
| `W` | 前进 | `S` | 后退 |
| `A` | 左平移 | `D` | 右平移 |
| `Q` | 左转 | `E` | 右转 |
| `Shift` | 起立 | `Ctrl` | 下蹲 |

> 键盘在任意页面内生效（输入框聚焦时自动屏蔽）

### 控制优先级

```
E-STOP  >  遥控器（FT24）  >  Web 手动  >  AutoTrack 自动跟踪
```

---

## 视频流架构

```
IP 摄像头 (H.265 RTSP)
    ↓  FFmpeg：-fflags nobuffer -bf 0 -preset ultrafast -r 15
MediaMTX RTSP (:8554/cam)
    ↓  WebRTC WHEP
浏览器 <video>
```

> **延迟说明**：当前软解转码延迟约 200-400ms（H.265 源头限制）。
> 换用 H.264 摄像头后可通过 MediaMTX 直通无转码，延迟降至 <50ms。

---

## 项目结构

```
BotDog/
├── backend/              # FastAPI 后端
│   ├── main.py           # 应用入口
│   ├── robot_adapter.py  # UnitreeB2Adapter
│   ├── auto_track_service.py  # 自动跟踪状态机
│   ├── control_arbiter.py     # 控制权仲裁
│   ├── workers_ai.py          # YOLOv8 推理 Worker
│   └── config.py         # 全量配置项
│
├── frontend/             # React 前端
│   └── src/
│       ├── components/   # ControlPad（键盘+触控）、VideoPlayer 等
│       ├── hooks/        # useRobotControl、useWebSocket 等
│       └── config/       # api.ts（动态 API 地址）
│
├── scripts/
│   ├── run-pipeline.sh   # 视频流水线（FFmpeg + MediaMTX）
│   ├── start_backend.sh  # 后端启动脚本
│   └── install-services.sh  # systemd 服务安装
│
├── config/
│   └── mediamtx.yml      # MediaMTX 配置
│
├── docs/                 # 项目文档（见 docs/01_项目索引.md）
├── models/               # YOLOv8 模型文件
└── data/                 # SQLite 数据库 & 快照
```

---

## 文档

详细文档见 [docs/01_项目索引.md](docs/01_项目索引.md)

| 文件 | 说明 |
|------|------|
| [docs/03_实施计划与架构.md](docs/03_实施计划与架构.md) | 系统架构与功能完成清单 |
| [docs/04_开发环境搭建.md](docs/04_开发环境搭建.md) | OrangePi 环境搭建详细步骤 |
| [docs/12_宇树B2硬件接入指南.md](docs/12_宇树B2硬件接入指南.md) | B2 SDK、HM30、网络配置 |

---

## 开机自启

```bash
sudo bash scripts/install-services.sh

# 查看服务状态
sudo systemctl status botdog-backend
sudo systemctl status botdog-pipeline

# 查看日志
journalctl -u botdog-backend -f
```

---

## 许可证

MIT License

---

**状态**：✅ 生产就绪  
**最后更新**：2026-04-08  
**平台**：OrangePi 5 Ultra / Unitree B2  
**仓库**：https://github.com/Timekeeperxxx/BotDog
