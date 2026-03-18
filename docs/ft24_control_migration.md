# FT24 控制链路重构方案

## 1. 目标与约束
- **目标**：将“手动控制链路”从 WebSocket 控制转为 FT24 (2.4G FHSS) 硬件直连，保证极低延迟与信号优先级。
- **约束**：
  - 软件端必须彻底禁用控制转发，避免覆盖 FT24 的物理信号。
  - **遥测链路保持不变**：MAVLink → 后端 → 前端。
  - 不引入“控制模式开关”，直接下线 Web 控制能力。

## 2. 链路对比
### 2.1 旧链路（Web 控制）
前端控制面板 → `/ws/control` → 后端控制处理 → MAVLink → 机器狗（已废弃）。

### 2.2 新链路（FT24 硬件直连）
FT24 手柄 (TX) → 接收机 (RX) → MCU

### 2.3 遥测链路（不变）
机器狗传感器 → 飞控 → FT24 数传 → 后端 `mavlink_gateway.py` → 前端

## 3. 代码改动范围（分阶段）
### Phase 1 — 控制链路彻底下线
- `/ws/control` 与控制面板已移除，控制链路固定为 FT24 硬件直连。
- 后端仅保留遥测与事件 WebSocket：`/ws/telemetry`、`/ws/event`。

### Phase 2 — 前端控制面板移除
- 主界面仅保留遥测、告警、视频播放与配置入口。
- 不再包含控制面板与控制 WebSocket 连接逻辑。

### Phase 3 — 测试用例（无 FT24 设备验证）
- **后端（pytest）**
  - `/ws/telemetry` 应可持续推送 `TELEMETRY_UPDATE`（`MAVLINK_SOURCE=simulation`）。
- **前端（Vitest + Testing Library）**
  - 仅保留核心 UI 渲染与 WHEP 播放相关测试（如需）。

## 4. 测试步骤（无设备环境）
### 4.1 后端
1. 启动后端（配置 `MAVLINK_SOURCE=simulation`）。
2. 自动化测试：`pytest tests/`
3. 手工验证：
- `/ws/control` 连接验证已移除（端点不存在）。
   - `/ws/telemetry` 可持续接收 `TELEMETRY_UPDATE`。

### 4.2 前端
1. 安装依赖：`npm install`
2. 运行测试：`npm test`
3. 启动前端：`npm run dev`
4. 页面中不再出现控制面板。
4. 页面中不再出现控制面板或 `/ws/control` 连接。

## 5. 风险与回退
- **风险**：若仍残留控制 WS 连接或控制转发逻辑，可能覆盖 FT24 信号。
- **回退**：仅在需要恢复 Web 控制时，手动恢复 `/ws/control` 路由与控制面板（需重新实现）。

## 6. 视频链路（MediaMTX + WHEP）
- 采用本机 MediaMTX + FFmpeg 方案，不依赖后端信令。
- FFmpeg 将相机 RTSP(H.265) 转码并推送到 MediaMTX `cam` 路径。
- 前端通过 `VITE_WHEP_URL` 直连播放。

关键环境变量：
- `CAMERA_RTSP_URL=rtsp://192.168.144.25:8554/main.264`
- `VITE_WHEP_URL=http://127.0.0.1:8889/cam/whep`

## 7. FT24 手柄连通性测试（有接收机，无机器狗）
### 7.1 连接方式
- **UART**：接收机串口输出（常见 115200 8N1）。
- **SBUS**：接收机 SBUS 输出（100000 8E2，部分需要反相）。

### 7.2 辅助脚本
脚本位置：[scripts/ft24_rx_test.py](../scripts/ft24_rx_test.py)

#### 运行示例
1) **自动检测模式（推荐）**
```
python scripts/ft24_rx_test.py --port COM4 --mode auto --duration 10
```
2) **明确 UART**
```
python scripts/ft24_rx_test.py --port COM4 --mode uart --baud 115200 --duration 10
```
3) **明确 SBUS**
```
python scripts/ft24_rx_test.py --port COM4 --mode sbus --duration 10
```

#### 判定标准
- **UART**：持续输出字节流，且在拨动摇杆/开关时，输出块内容发生变化。
- **SBUS**：持续输出帧，`ch1~ch8` 数值随摇杆变化而变化；`failsafe`/`lost` 为 `False`。

### 7.3 手工验证步骤
1. 连接接收机到 USB-UART（确认设备管理器中端口号）。
2. 运行脚本并观察输出。
3. 依次拨动摇杆与拨码开关，确认输出变化。

## 8. 验收标准
- 控制链路由 FT24 硬件直连，不再提供 Web 控制。
- `/ws/telemetry` 可用且数据持续更新。
- 前端无控制面板与控制 WS 连接。
- WHEP 视频流在主界面与 `web/index.html` 可播放。
- FT24 接收机连通性测试通过。
- 测试用例通过，文档与实现一致。
