# BotDog 智能取证系统技术栈选型报告

## 1. 概述

本方案采用 **“旁路解耦、轻量加速”** 的设计哲学，旨在机器狗边缘端（如 Jetson 或 PC 边缘节点）实现高效的 AI 视觉巡检。通过 FFmpeg 管道技术规避笨重的图形库依赖，直接对接 Python AI 生态，实现发现即取证、告警即推送。

## 2. 核心技术栈选型

### 2.1 视频处理层 (Video Ingest)

* ​**核心引擎**​: **FFmpeg (Subprocess Mode)**
  * ​**用途**​: 从 MediaMTX 拉取 RTSP 流，解码为 Raw BGR24 原始字节流。
  * ​**选型理由**​: 绕过 OpenCV 的高功耗编解码瓶颈，利用管道（Pipe）实现零拷贝级的像素传输。
* ​**底层协议**​: **RTSP (UDP/TCP)**
  * ​**用途**​: 后端内部取流协议。

### 2.2 AI 推理层 (Intelligence)

* ​**视觉算法**​: **YOLOv8n / YOLOv10n (Nano 版)**
  * ​**用途**​: 实现对人员（Person）及特定废弃物（Bottle, Cup, Box）的实时识别。
  * ​**选型理由**​: 在边缘主板上拥有极高的 FPS 表现，且具备优秀的泛化能力。
* ​**加速框架**​: **TensorRT (针对 NVIDIA)** 或 **ONNX Runtime (通用)**
  * ​**用途**​: 模型推理加速。
* ​**计算库**​: **NumPy**
  * ​**用途**​: 承接 FFmpeg 管道流，通过 `frombuffer` 将字节瞬间转换为矩阵，供 AI 识别。

### 2.3 后端服务层 (Backend Service)

* ​**任务调度**​: **FastAPI (Lifespan)**
  * ​**用途**​: 管理 AI Worker 的生命周期，确保后台进程随系统启停。
* ​**异步 IO**​: **Asyncio + Subprocess**
  * ​**用途**​: 异步驱动多进程 AI 任务，不阻塞 MAVLink 遥测与 WebSocket 广播。
* ​**图像编码**​: **Pillow (PIL)**
  * ​**用途**​: 触发告警时，将内存中的 Raw 帧快速编码为轻量化的 `.jpg` 格式。

### 2.4 数据与通信层 (Data & Communication)

* ​**持久化**​: **SQLAlchemy (Async)**
  * ​**用途**​: 将 `Evidence`（证据记录）存入数据库，关联 GPS 与任务 ID。
* ​**实时推送**​: **WebSocket (EventBroadcaster)**
  * ​**用途**​: 向 `/ws/event` 所有的前端连接广播 `ALERT_RAISED` 事件。
* ​**存储**​: **Local File System**
  * ​**用途**​: 结构化存储高清抓拍原图，路径存入数据库。

### 2.5 前端展示层 (Frontend)

* ​**UI 框架**​: **React + TypeScript**
  * ​**用途**​: 在 `IndustrialConsole` 中集成实时告警卡片。
* ​**图标库**​: **Lucide React**
  * ​**用途**​: 提供直观的告警类型标识。

## 3. 关键配置参考 (FFmpeg Pipe)

在 Python 中启动解码管道的推荐配置：

```
ffmpeg -hwaccel auto -i rtsp://localhost:8554/cam \
  -f image2pipe -vcodec rawvideo -pix_fmt bgr24 -r 2 -
```

* `-r 2`: 强制降低 AI 采样率为每秒 2 帧，极大降低 CPU 负载。
* `-pix_fmt bgr24`: 直接输出符合模型输入的像素格式，无需二次转换。

## 4. 选型评估对比

| 方案                         | 性能 (边缘端)         | 开发难度                        | 维护性              | 推荐指数   |
| ------------------------------ | ----------------------- | --------------------------------- | --------------------- | ------------ |
| **OpenCV + GStreamer** | 高                    | 极高 (环境配置复杂)             | 一般                | ⭐⭐       |
| **FFmpeg Pipe + YOLO** | **极高 (轻量)** | **中 (原生 Python 异步)** | **高 (解耦)** | ⭐⭐⭐⭐⭐ |
| **云端推理**           | 极低 (受限带宽)       | 低                              | 高                  | ⭐         |

## 5. 结论

作为架构设计，本技术栈完全兼容 `BotDog` 目前的 Python 后端体系。它在保证 **150ms 以内** 操控延迟的同时，为系统增加了 **AI 自动干预** 的能力。这不仅是功能上的增加，更是从“被动查看”向“主动识别”的质变。
