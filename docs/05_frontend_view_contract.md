# 控制终端前端视图与数据契约 (Frontend View Contract)

## 1. 目的

将 `04_ui_prototype.html` 中的视觉原型，映射为前端实现可直接对照的数据契约与事件契约，明确每个可视区域依赖哪些后端接口/消息。

## 2. 主界面区域划分

参考 `04_ui_prototype.html`，主控制台界面主要划分为：

1. 顶部状态栏（Header Bar）
2. 左侧栏：地图占位 + 实时抓拍列表
3. 中央视频 + HUD 区域
4. 右侧栏：执行器/电机状态 + 系统日志
5. 底部状态条（Footer Bar）

## 3. 顶部状态栏

### 3.1 显示字段

* 链路延迟：`latency_ms`
* 信号强度：`rssi_dbm`
* 核心温度：`core_temp_c`
* 剩余电量：`battery.remaining_pct`
* 终端时间：本地时间（前端生成）

### 3.2 数据来源

* WebSocket `/ws/telemetry`，消息类型 `TELEMETRY_UPDATE`：
  * 延迟与信号强度可通过结合本地时间与后端广播时间戳估算，或由后端预先计算后下发。
* 终端时间由浏览器定时 `setInterval` 本地渲染。

## 4. 左侧栏

### 4.1 地图占位区域

当前版本（v1.0）仅显示坐标文本：

* 文本字段：`position.lat`, `position.lon`
* 数据来源：`TELEMETRY_UPDATE.payload.position`

未来扩展：

* 可在加载在线/离线地图 SDK 后，将坐标映射到实际地图点位。

### 4.2 实时抓拍列表

#### 字段

每一条抓拍卡片字段：

* `evidence_id`
* `created_at`
* `event_type`
* `confidence`
* `thumbnail_url`（可与原图 `image_url` 共用）

#### 数据来源

* 实时：WebSocket `/ws/event`，消息类型 `ALERT_RAISED`。
* 历史：HTTP `GET /api/v1/evidence`。

前端策略：

* 新的 `ALERT_RAISED` 推到列表顶部，列表长度限定（如最多 8 条），超出移除末尾。

## 5. 中央视频 + HUD 区域

### 5.1 视频容器

* 媒体流：从 WebRTC PeerConnection 的 `MediaStreamTrack` 挂载到 `<video>`。
* 分辨率/帧率：由媒体管线提供（参见 `08_media_pipeline_design.md`）。

### 5.2 HUD 元素

关键 HUD 元素与字段映射：

* 姿态仪中心圆与横线：`attitude.pitch`, `attitude.roll`
* 航向角显示：`attitude.yaw` / `position.hdg`
* 高度刻度：`position.alt`
* 速度刻度（如使用）：`groundspeed`（来自 `VFR_HUD`）

数据来源：

* WebSocket `/ws/telemetry`，`TELEMETRY_UPDATE.payload`。

刷新策略：

* 前端以不高于 15Hz 的频率刷新 HUD，避免 DOM 过度渲染。

### 5.3 全屏与 UI 隐藏逻辑

* 点击“全屏”按钮时：
  * 切换 `video-active-fullscreen` 样式类。
  * 将左右栏与顶部/底部状态栏加上 `ui-hidden` 类。
  * 仍保留 HUD 叠层显示（关键姿态信息始终可见）。

该逻辑已在 `04_ui_prototype.html` 中通过 JS 示例实现，React/Vue 实现时可按同样状态机复刻。

## 6. 右侧栏

### 6.1 执行器状态区

字段（每个电机/关节）：

* 名称：例如 `FL`、`FR` 等
* 温度：`motor_temp_c`
* 电流：`motor_current_a`
* 负载百分比（可选）：`motor_load_pct`

数据来源：

* 短期内可通过扩展 MAVLink 消息或自定义 Telemetry 字段在 `TELEMETRY_UPDATE` 中承载。
* 若底层暂不提供真实数据，可在前端以“占位假数据”形式渲染。

### 6.2 系统日志区

字段：

* `timestamp`
* `level`
* `module`
* `message`

数据来源：

* 实时：可选的 WebSocket 日志通道（未来扩展）。
* 历史：HTTP `GET /api/v1/logs`（分页），当前 UI 原型中模拟了循环日志。

前端可按需决定：

* 初始加载最近 N 条日志。
* 实时追加新日志到末尾，保持滚动到底部。

## 7. 底部状态条

字段：

* 当前系统运行状态：`DISCONNECTED` / `STANDBY` / `IN_MISSION` / `E_STOP_TRIGGERED`。
* 当前运行时长：`uptime`（来自 `/api/v1/system/health` 或 WebSocket）。
* 加密层信息：例如 `AES-XTS-256`（静态展示即可）。

数据来源：

* HTTP `GET /api/v1/system/health` 周期性轮询或由 WebSocket 状态事件更新。

## 8. 交互事件契约 (前端 -> 后端)

### 8.1 控制指令 (摇杆/键鼠)

* WebSocket 路径：`/ws/control`
* 消息：

```json
{
  "timestamp": 1714560000.123,
  "msg_type": "MANUAL_CONTROL",
  "payload": {
    "x": 0,
    "y": 200,
    "z": 0,
    "r": -150
  }
}
```

后端返回：

* 类型：`CONTROL_ACK`（见后端协议文档 3.3）。

### 8.2 急停按钮

* 可设计为：
  * HTTP：`POST /api/v1/control/e-stop`
  * 或 WebSocket 消息：`msg_type: "E_STOP_TRIGGER"`

结果：

* 后端切换系统状态为 `E_STOP_TRIGGERED`，触发一条 `ALERT_RAISED` 或专门的 `SYSTEM_EVENT`。
* UI 顶部/底部明显标示当前处于急停状态。

