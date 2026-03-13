# 智能巡检系统开发与运行环境说明 (Dev Setup)

## 1. 总体目标

本说明用于指导开发人员在一台全新的开发机上，完成“从零到可跑通最小闭环”的环境搭建，包括：

* 后端 FastAPI 服务
* 前端控制终端
* 基础 MAVLink/遥测模拟

## 2. 环境依赖矩阵

### 2.1 操作系统

* 开发机推荐：Windows 11 / WSL2 Ubuntu 22.04 / 原生 Ubuntu 22.04
* 边缘端：Ubuntu 22.04 LTS (Jetson Orin Nano)，启用 NVIDIA 驱动与硬编编码器

### 2.2 后端依赖

* Python `3.10+`（推荐 `3.12.x`）
* 包管理：`pip` 或 `uv`（推荐）
* 主要三方库（不列版本号，具体见后续 `requirements.txt`）：
  * `fastapi`, `uvicorn[standard]`
  * `pydantic`
  * `SQLAlchemy` (async)
  * `loguru`
  * `pymavlink`, `pyserial`
  * `redis`（如启用实时缓存）

### 2.3 前端依赖

* Node.js `>= 20`
* 包管理：`pnpm` 或 `yarn`（推荐）/ `npm`
* 技术栈：
  * `React 18` + `Vite` + `TypeScript`
  * 状态管理：`zustand`
  * WebSocket 封装：`socket.io-client` 或原生 WebSocket 包装层

### 2.4 媒体与工具链

* GStreamer `>= 1.22`，带常用插件：
  * `v4l2src`, `videoconvert`, `x264enc` / `nvv4l2h264enc`
  * `rtph264pay`, `webrtcbin`
* FFmpeg（用于调试流媒体）
* `gst-inspect-1.0` / `gst-launch-1.0` 命令可用

### 2.5 WebRTC 直出（WSL2 可选）

* webrtcbin 运行在 WSL2（Windows 后端仅信令中转）
* 后端 `.env` 设置：`VIDEO_BACKEND_MODE=webrtcbin`
* WSL2 需安装：`python3-gi`、`gstreamer1.0-plugins-*`
* runner 入口：`backend/webrtc_gst_runner.py`

## 3. 后端本地启动步骤

假设仓库根目录为 `BotDog/`。

### 3.1 创建虚拟环境

```bash
cd BotDog
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell 使用: .venv\Scripts\Activate.ps1
```

### 3.2 安装依赖

```bash
pip install -r requirements.txt
```

> 如使用 `uv`，可替换为：
> ```bash
> uv pip install -r requirements.txt
> ```

### 3.3 环境变量与配置

新建 `.env` 文件（不纳入版本控制），示例：

```bash
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8000
MAVLINK_ENDPOINT=udp:127.0.0.1:14550
DATABASE_URL=sqlite+aiosqlite:///./data/botdog.db
JWT_SECRET=请在本地自定义
CORS_ALLOW_ORIGINS=["http://localhost:5173"]
CORS_ALLOW_CREDENTIALS=false
SIMULATION_WORKER_ENABLED=true
```

### 3.4 启动后端服务

```bash
uvicorn backend.main:app --reload
```

## 4. 前端本地启动步骤

### 4.1 安装依赖

```bash
cd BotDog/frontend
pnpm install  # 或 yarn / npm install
```

### 4.2 开发服务器

```bash
pnpm dev  # 默认 http://localhost:5173
```

前端需在 `.env.local` 中配置后端地址，例如：

```bash
VITE_API_BASE=http://localhost:8000/api/v1
VITE_WS_BASE=ws://localhost:8000/ws
```

## 5. 本地 MAVLink/遥测模拟

在尚未接入真实机器狗与飞控的情况下，可通过简单的“模拟器脚本”或现有工具生成 MAVLink 流：

* 推荐方案 1：使用 `pymavlink` 官方示例的 SITL/模拟器，将 `udpout` 指向 `127.0.0.1:14550`。
* 推荐方案 2：编写一个简化的 Python 脚本，定时发送 `HEARTBEAT`、`GLOBAL_POSITION_INT` 等消息到本地 UDP 端口。

后端在检测到 `HEARTBEAT` 后，`/api/v1/system/health` 中的 `mavlink_connected` 应从 `false` 变为 `true`。

## 6. 最小可验证闭环 (MVP Smoke Test)

在完成上述步骤后，第一次启动系统时可按以下顺序简单验证：

1. 启动后端 FastAPI (`uvicorn backend.main:app --reload`)。
2. 启动前端 Vite 开发服务器。
3. 启动 MAVLink 模拟器，观察后端日志中是否有心跳解析记录。
4. 在浏览器打开前端界面，确认：
   * WebSocket 已连接（状态条显示“在线”）。
   * Telemetry 面板出现模拟的姿态/经纬度/电量数据。

若上述闭环跑通，即可进入后续功能开发与联调阶段。

