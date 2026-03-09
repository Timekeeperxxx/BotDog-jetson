# BotDog Windows 部署指南

## 🎯 项目概述

BotDog 是一个完整的四足机器狗远程控制系统，支持实时控制、遥测监控、AI 告警和 WebRTC 视频流。

## 📋 系统要求

### Windows 开发环境
- Windows 10/11 64位
- Python 3.10+
- Node.js 18+
- Git

### 可选硬件
- 游戏手柄（Xbox/PlayStation）
- 网络摄像头

## 🚀 快速开始

### 1. 安装 Python 依赖

```bash
# 进入后端目录
cd backend

# 创建虚拟环境
python -m venv .venv

# 激活虚拟环境
.venv\Scripts\activate

# 安装依赖
pip install -r ../requirements.txt
```

### 2. 安装前端依赖

```bash
# 进入前端目录
cd frontend

# 安装依赖
npm install
```

### 3. 配置环境变量

**后端配置** (`backend/.env`)：
```env
# 数据库配置
DATABASE_URL=sqlite:///./data/botdog.db

# 视频设备
VIDEO_DEVICE=0

# MAVLink 配置
MAVLINK_SERIAL_PORT=COM3
MAVLINK_BAUDRATE=57600

# WebSocket 配置
WS_MAX_CLIENTS_PER_IP=10
```

**前端配置** (`frontend/.env`)：
```env
# API 地址
VITE_API_BASE_URL=http://localhost:8000
```

### 4. 初始化数据库

```bash
# 从项目根目录
python init_config.py
```

### 5. 启动服务

**启动后端**（终端 1）：
```bash
# 激活虚拟环境
.venv\Scripts\activate

# 启动后端
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

**启动前端**（终端 2）：
```bash
cd frontend
npm run dev
```

### 6. 访问应用

打开浏览器访问：`http://localhost:5173`

## 📹 视频流配置

### 方案 1：使用网络摄像头（RTSP）

**推流命令**：
```bash
python edge/gstreamer_streamer.py \
  --source rtsp \
  --device "rtsp://YOUR_CAMERA_IP:8554/main.264" \
  --host YOUR_PC_IP \
  --port 5000 \
  --bitrate 2000000 \
  --width 1280 \
  --height 720
```

### 方案 2：使用 USB 摄像头

**推流命令**：
```bash
python edge/gstreamer_streamer.py \
  --source v4l2 \
  --device 0 \
  --host 127.0.0.1 \
  --port 5000 \
  --bitrate 2000000 \
  --width 1280 \
  --height 720
```

### 方案 3：使用测试源

**推流命令**：
```bash
python edge/gstreamer_streamer.py \
  --source videotestsrc \
  --host 127.0.0.1 \
  --port 5000
```

## 🔧 Windows 特定配置

### GStreamer 安装（用于视频处理）

1. 下载 GStreamer for Windows
2. 安装到 `C:\gstreamer\1.0\msvc_x86_64`
3. 添加环境变量：
   ```
   GSTREAMER_1_0_ROOT_MSVC_X86_64=C:\gstreamer\1.0\msvc_x86_64
   ```
4. 将 `%GSTREAMER_1_0_ROOT_MSVC_X86_64%\bin` 添加到 PATH

### 防火墙配置

允许以下端口通过 Windows 防火墙：
- 8000（后端 API 和 WebSocket）
- 5173（前端开发服务器）
- 5000（视频流 UDP）

## 🎮 控制方式

### 游戏手柄

1. 连接游戏手柄到 Windows
2. 打开浏览器访问应用
3. 按下手柄任意按钮激活
4. 点击"启用控制"按钮

### 键盘控制

- W/S: 前进/后退
- A/D: 左右平移
- Q/E: 升降
- ←/→: 转向

## 📊 性能优化

### 当前配置（交付模式）

**后端解码**：
- 编码格式：H.264（avdec_h264 硬解加速）
- 输出分辨率：1280x720 @ 20fps
- 抖动缓冲：200ms + 重传

**推流端建议**：
- 码率：2Mbps
- 分辨率：1280x720
- 帧率：20fps

## 🧪 测试

```bash
# 运行验收测试
python acceptance_test.py

# 运行单元测试
pytest tests/
```

## 📁 项目结构

```
BotDog_Windows/
├── backend/          # FastAPI 后端
│   ├── main.py      # 主应用入口
│   ├── video_track.py  # WebRTC 视频流
│   └── .env         # 环境配置
├── frontend/         # React 前端
│   ├── src/
│   │   ├── components/  # React 组件
│   │   └── hooks/       # React Hooks
│   └── package.json
├── edge/            # 边缘端推流脚本
├── docs/            # 项目文档
├── scripts/         # 部署脚本
└── requirements.txt # Python 依赖
```

## 🐛 故障排查

### 问题 1：后端无法启动

```bash
# 检查端口占用
netstat -ano | findstr :8000

# 更改端口
uvicorn backend.main:app --host 0.0.0.0 --port 8001
```

### 问题 2：前端连接失败

检查 `frontend/.env` 中的 API 地址是否正确。

### 问题 3：视频流无法播放

1. 确认 GStreamer 已正确安装
2. 检查防火墙设置
3. 确认推流端正在运行

### 问题 4：游戏手柄无响应

1. 确认手柄已连接（Windows 设置）
2. 在浏览器中按下手柄按钮
3. 检查浏览器兼容性（推荐 Chrome）

## 📞 技术支持

- GitHub: https://github.com/Timekeeperxxx/BotDog
- 文档: docs/ 目录

## 📄 许可证

MIT License

---

**最后更新**: 2026-03-09
**版本**: v5.0 Windows 交付版
