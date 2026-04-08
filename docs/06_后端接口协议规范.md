# 智能巡检系统 - 后端协议与数据结构设计说明书 (Backend Protocol & Data Schema Design)

## 1. 总体说明

### 1.1 后端职责范围

本巡检系统后端（基于 FastAPI）定位于“天地链路”的中间件总线，其核心职责包括：

* ​**MAVLink 网关 (MAVLink Gateway)**​：负责底层串口/UDP比特流的解析、校验、协议封装与解包。
* ​**WebSocket Hub (实时信令中心)**​：维持高并发的全双工长连接，分发高频遥测数据及系统告警。
* ​**日志/抓拍服务 (Storage Service)**​：基于 SQLAlchemy (ORM) 管理 SQLite 数据库，处理时序轨迹降采样落盘与多媒体证据链持久化。
* ​**流媒体协同 (Media Orchestration)**​：MediaMTX + FFmpeg 管理视频流，后端不再承担信令。

### 1.2 通讯拓扑

系统采用异步解耦的星型拓扑结构：

```
[边缘机载端 (ArduPilot/PX4)] 
       <--(MAVLink over UDP/Serial)--> [ FastAPI 异步事件循环 (Event Loop) ] 
                                           |-- (内部 AsyncQueue) --> [ 数据落盘 Worker -> SQLite ]
                                           |-- (内部 AsyncQueue) --> [ WebSocket 广播组 -> 前端 UI ]
                                           |-- (REST API) ---------> [ 历史查询/指令下发 -> 前端 UI ]
```

### 1.3 端口与协议一览表

| 服务/模块                | 地址/端口             | 通讯协议         | 核心用途                                |
| -------------------------- | ----------------------- | ------------------ | ----------------------------------------- |
| **REST API 服务**  | `0.0.0.0:8000`    | HTTP/1.1         | 历史日志获取、系统配置下发、登录鉴权    |
| **WebSocket 服务** | `0.0.0.0:8000/ws` | WebSocket (WSS)  | 提供 `/ws/telemetry`、`/ws/event` 等长连接入口 |
| **飞控数据链路**   | `127.0.0.1:14550` | UDP / Serial     | 接收边缘侧 MAVLink 2.0 二进制码流       |
| **MediaMTX WHEP**   | `0.0.0.0:8889`    | HTTP/WHEP       | MediaMTX 向前端提供 WHEP 播放          |

## 2. HTTP API 设计

所有 API 默认基础路径为 `/api/v1`，数据交换格式为 `application/json`。

### 2.1 会话与系统状态

#### 获取系统健康状态

* ​**URL、方法**​: `GET /api/v1/system/health`
* ​**权限要求**​: 无需 JWT (公开探针)
* ​**功能说明**​: 供负载均衡或前端检测后端存活状态及硬件负载。
* ​**请求参数**​: 无
* ​**响应体结构**​:
  * `status` (String): `healthy`, `degraded`, `offline`
  * `mavlink_connected` (Boolean): 底层数据链路是否连通
  * `uptime` (Float): 服务运行秒数
* ​**示例响应**​:
  ```
  { "status": "healthy", "mavlink_connected": true, "uptime": 3600.5 }
  ```

#### 启动/停止巡检任务

* ​**URL、方法**​: `POST /api/v1/session/start` | `POST /api/v1/session/stop`
* ​**权限要求**​: Bearer JWT (需操作员权限)
* ​**请求参数 (Start)**​: `task_name` (String, 必填, 任务名称)
* ​**响应体结构**​: `task_id` (Integer), `start_time` (String)

### 2.2 巡检任务与日志

#### 分页查询运行日志

* ​**URL、方法**​: `GET /api/v1/logs`
* ​**权限要求**​: Bearer JWT
* ​**请求参数**​:
  * `page` (Integer, 非必填, 默认1)
  * `size` (Integer, 非必填, 默认50)
  * `level` (String, 非必填, 过滤日志级别 INFO/WARN/ERROR)
* ​**响应体结构**​:
  * `total` (Integer): 总条数
  * `items` (Array): 日志对象数组 `[{"log_id": 1, "level": "ERROR", "message": "...", "timestamp": "..."}]`

### 2.3 抓拍与告警

#### 获取异常证据链列表

* ​**URL、方法**​: `GET /api/v1/evidence`
* ​**权限要求**​: Bearer JWT
* ​**功能说明**​: 获取 AI 引擎触发的抓拍记录及对应的物理坐标。
* ​**请求参数**​: `task_id` (Integer, 非必填, 查特定任务)
* ​**响应体结构**​: `evidence_id`, `event_type`, `gps_lat`, `gps_lon`, `image_url`, `timestamp`
* ​**可能错误码**​: `40401` (任务ID不存在)

### 2.4 配置与控制

#### 更新系统全局配置

* ​**URL、方法**​: `POST /api/v1/config`
* ​**权限要求**​: Bearer JWT (需管理员 Admin 权限)
* ​**请求参数表**​:
  * `thermal_threshold` (Float, 必填, 触发异常的温度极值，默认 60.0)
  * `heartbeat_timeout` (Float, 必填, 心跳超时判定阈值，默认 3.0)
* ​**响应体结构**​: `status` (String, "success"), `updated_keys` (Array)

## 3. WebSocket 协议设计

### 3.1 通道规划

本系统采用单通道复用拓扑，通过挂载不同路径实现关注点分离：

* `/ws/telemetry`：单向广播，用于下发飞行姿态、经纬度、电池等高频遥测。
* `/ws/event`：单向广播，推送 AI 抓拍告警、链路断开等系统级重大事件。

### 3.2 消息通用格式

所有 WS 消息强制使用统一的 JSON Envelope 包装：

```
{
  "timestamp": 1714560000.123,
  "msg_type": "TELEMETRY_UPDATE", 
  "seq": 1024,                      // 自增序列号，用于检测乱序/丢包
  "source": "BACKEND_HUB",          // 消息来源标识
  "payload": {}                     // 强类型业务数据载荷
}
```

### 3.3 消息类型定义

#### [1] TELEMETRY\_UPDATE (高频遥测)

* ​**更新频率**​: \~15Hz (经过后端滑动窗口降采样防抖)
* ​**Payload 结构**​:
  ```
  "payload": {
    "attitude": { "pitch": 0.12, "roll": -0.05, "yaw": 184.5 },
    "position": { "lat": 39.9087, "lon": 116.3975, "alt": 1.2, "hdg": 184 },
    "battery":  { "voltage": 84.2, "remaining_pct": 82 }
  }
  ```

#### [2] ALERT\_RAISED (异常告警事件)

* ​**更新频率**​: 事件触发时即时推送
* ​**Payload 结构**​:
  ```
  "payload": {
    "event_code": "E_THERMAL_HIGH",
    "severity": "CRITICAL",
    "message": "检测到目标温度过高 (65.2°C)",
    "evidence_id": 402,
    "image_url": "/api/v1/static/snapshots/20260302/task_1/img_402.jpg"
  }
  ```

## 4. MAVLink 映射与内部数据结构

### 4.1 支持的 MAVLink 消息列表

* `#0 HEARTBEAT`: 映射本地模型 `SystemHealthDTO`。
* `#33 GLOBAL_POSITION_INT`: 映射本地模型 `PositionDTO`。
* `#74 VFR_HUD` / `#30 ATTITUDE`: 映射本地模型 `AttitudeDTO`。
* `#251 NAMED_VALUE_FLOAT`: 用于扩展承接红外温度，映射本地模型 `ThermalExtDTO`。

### 4.2 MAVLink → 内部模型 → WebSocket 的映射表

| MAVLink Msg (ID)                | 原始字段名                          | 转换规则 / 单位                        | WebSocket 目标字段                  |
| --------------------------------- | ------------------------------------- | ---------------------------------------- | ------------------------------------- |
| `ATTITUDE (#30)`            | `pitch`,`roll`,`yaw`    | 弧度 (rad) 转角度 (deg)，保留 2 位小数 | `payload.attitude.pitch`等      |
| `GLOBAL_POSITION_INT (#33)` | `lat`,`lon`                 | 原始 int32 除以`1E7`               | `payload.position.lat`等        |
| `SYS_STATUS (#1)`           | `battery_remaining`             | 无转换 (0-100%)                        | `payload.battery.remaining_pct` |
| `NAMED_VALUE_FLOAT (#251)`  | `value`(需`name`=="T\_MAX") | 直接提取浮点数 (°C)                   | 触发`ALERT_RAISED`阈值判断      |

## 5. 数据库与持久化结构

### 5.1 SQLite 表结构概述

基于 V4 版数据库设计，采用 SQLAlchemy (Async Engine) 构建。

* ​**`inspection_tasks`**​: `task_id` (PK), `task_name`, `status` (执行中/已完成), `started_at`, `ended_at`。
* ​**`telemetry_snapshots`**​: 高频数据降采样，用于满足“遥测数据 100% 结构化留存”的目标。典型字段：
  * `task_id` (FK), `timestamp` (索引)
  * `gps_lat`, `gps_lon`, `gps_alt`, `hdg`
  * `att_pitch`, `att_roll`, `att_yaw`
  * `battery_voltage`, `battery_remaining_pct`
* ​**`anomaly_evidence`**​: 存储告警元数据与证据链索引。字段: `evidence_id` (PK), `task_id` (FK), `event_type`, `confidence`, `file_path`, `gps_lat`, `gps_lon`, `created_at`。
* ​**`operation_logs`**​: 行为审计与系统事件。字段: `log_id` (PK), `level` (INFO/WARN/ERROR), `module` (BACKEND/UI/MEDIA), `message`, `created_at`。

### 5.2 文件存储规范

* ​**抓拍图片持久化路径**​: 绝对隔离于数据库之外，存储规则为：`/data/snapshots/{YYYY-MM-DD}/{task_id}/evd_{evidence_id}_T{timestamp}.jpg`
* ​**日志文件滚动策略**​: 使用 `Loguru` 框架写入物理文件。策略：`rotation="500 MB"`, `retention="10 days"`, `compression="zip"`，确保不会撑爆边缘设备的有限磁盘空间。

## 6. 错误码与状态枚举

### 6.1 API 错误码体系

遵循标准的 `HTTP Status` + 业务 `Code` 结构。

| HTTP Status | 业务 Code   | 消息 (Message)                | 场景说明                                 |
| ------------- | ------------- | ------------------------------- | ------------------------------------------ |
| `400`   | `40001` | `Invalid Control Payload` | 前端下发的摇杆矢量越界（非 -1000\~1000） |
| `401`   | `40101` | `Unauthorized Access`     | JWT Token 缺失、伪造或已过期             |
| `403`   | `40301` | `Action Locked`           | 在低电量或失联状态下强行下发移动指令     |
| `503`   | `50301` | `Edge Device Offline`     | MAVLink 心跳超时，无法连通底层飞控       |

### 6.2 系统状态枚举 (System States)

* `DISCONNECTED`: 完全无 MAVLink 信号传入。前端 UI 呈灰色离线态。
* `STANDBY`: 链路正常，电机未解锁（Disarmed）。前端 UI 开放参数配置。
* `IN_MISSION`: 巡检任务执行中。UI 渲染姿态与视频。
* `E_STOP_TRIGGERED`: 紧急制动生效中。禁止除解锁外的一切控制指令。

## 7. 安全与限流策略

### 7.1 鉴权方式

* ​**REST API**​: HTTP Header 携带 `Authorization: Bearer <JWT_TOKEN>`。
* ​**WebSocket**​: 建连阶段在 Query 参数中携带 `ws://.../?token=<JWT_TOKEN>`，握手阶段进行拦截与校验，失败则直接返回 `1008 Policy Violation` 掐断连接。

### 7.2 控制链路说明

* Web 控制已下线，控制链路由 FT24 硬件直连。
* 后端不再接收控制 WebSocket 指令。

### 7.3 资源保护机制

* ​**路径穿越防御**​: 获取抓拍图片 `/api/v1/static/{filepath}` 接口采用严格正则匹配，防止请求 `../../etc/passwd` 导致服务器文件泄露。
* ​**WS 恶意攻击防御**​: 单 IP 最大允许维持 5 个 WebSocket 长连接。若单一客户端不断发起恶意重连风暴，将触发 60 秒的 IP 黑名单封禁机制。

