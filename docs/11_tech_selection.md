# 巡检系统全链路技术栈选型 v1.0

## 1. 前端 (Control Terminal)

* ​**核心**​: `React 18` + `Vite` + `TypeScript` (强类型约束，确保遥测数据解析一致性)。
* ​**状态**​: `Zustand` (高频遥测数据流轻量化管理，避免渲染瓶颈)。
* ​**渲染**​: `WebRTC` (低延迟视频) + `OffscreenCanvas` (HUD 独立线程渲染)。
* ​**通讯**​: 原生 `WebSocket`（与后端 `/ws/telemetry`、`/ws/control`、`/ws/event` 保持一致；前端自行封装重连/心跳即可）。

## 2. 后端 (Middleware)

* ​**环境**​: `Python 3.12` + `FastAPI` (全异步架构，适配高并发信令)。
* ​**模型**​: `Pydantic v2` (极速 JSON 校验)。
* ​**存储**​: `SQLite` (本地结构化日志) + `Redis` (实时遥测缓存，可选)。

## 3. 流媒体 (Media Pipeline)

* ​**框架**​: `GStreamer 1.22+` (工业级多路流处理引擎)。
* ​**插件**​: `v4l2src` (采集), `x264enc` (硬编), `webrtcbin` (推流)。
* ​**视觉**​: `ONNX Runtime` (轻量化端侧推断，实现实时人影检测)。

## 4. 协议与通讯 (Protocols)

* ​**控制**​: `MAVLink 2.0` (标准无人系统协议，支持 CRC 校验)。
* ​**视频**​: `RTP/RTCP over UDP` (牺牲可靠性换取极致实时性)。
* ​**接口**​: `PySerial` (底层串口通讯驱动)。

## 5. 机器狗本体 (Edge/Embedded)

* ​**固件**​: `ArduPilot / PX4` (成熟的底层运动控制算法栈)。
* ​**硬件**​: `Jetson Orin Nano` (算力支持 4K 硬编与实时 AI 分析)。
* ​**系统**​: `Ubuntu 22.04 LTS` + `RT-Patch` (内核级实时性优化)。

## 6. 工程化 (DevOps)

* ​**容器**​: `Docker` + `Docker Compose` (环境一致性隔离)。
* ​**日志**​: `Loguru` (结构化异步巡检日志录入)。

