# BotDog 前端 - 阶段 1 实现

## 技术栈

- Vite (构建工具）
- React 18 (UI 框架)
- TypeScript (类型系统)
- Zustand (状态管理)

## 开发环境

### 安装依赖

```bash
cd frontend
npm install
```

### 启动开发服务器

```bash
npm run dev
```

前端将运行在 `http://localhost:5173`

### 构建生产版本

```bash
npm run build
```

构建产物将输出到 `dist/` 目录

## 项目结构

```
src/
├── components/          # React 组件
│   ├── AttitudeHUD.tsx     # 姿态仪表
│   ├── BatteryIndicator.tsx # 电池状态
│   ├── PositionPanel.tsx    # 位置信息
│   ├── StatusBar.tsx        # 系统状态栏
│   └── VideoPlayer.tsx      # WebRTC 视频播放器
├── hooks/              # 自定义 Hooks
│   ├── useTelemetryWebSocket.ts # WebSocket 连接管理
│   └── useWebRTC.ts            # WebRTC 连接管理
├── stores/             # Zustand Store
│   └── telemetryStore.ts     # 遥测数据状态管理
├── types/              # TypeScript 类型定义
│   └── telemetry.ts          # 遥测数据类型
├── App.tsx             # 主应用组件
└── App.css              # 全局样式
```

## 功能特性

- ✅ WebSocket 自动连接与重连
- ✅ 实时遥测数据显示（姿态、位置、电池）
- ✅ WebRTC 视频播放与 HUD 叠层
- ✅ 状态持久化与状态管理
- ✅ 响应式布局设计
- ✅ 深色工业控制台主题

## WebSocket 连接

### 遥测 WebSocket

默认连接到 `ws://localhost:8000/ws/telemetry`。

可在 `src/hooks/useTelemetryWebSocket.ts` 中修改连接地址。

### WebRTC 信令 WebSocket

默认连接到 `ws://<API_HOST>:8000/ws/webrtc`，地址由 [frontend/src/config/api.ts](frontend/src/config/api.ts) 中的 `API_BASE_URL` 派生。

需要时可在 `src/hooks/useWebRTC.ts` 通过 `wsUrl` 覆盖。

## 组件说明

### AttitudeHUD
- 姿态可视化仪表
- SVG 图形化显示俯仰、横滚、偏航
- 实时角度数值显示

### PositionPanel
- GPS 位置信息面板
- 显示经纬度、高度、航向角
- 网格布局

### BatteryIndicator
- 电池状态显示
- 电压显示
- 剩余电量百分比
- 可视化电量条
- 低电量颜色警告

### StatusBar
- WebSocket 连接状态显示
- 系统模式与解锁状态
- 消息统计
- 最后更新时间
- 手动重连按钮

### App
- 整合所有子组件
- 管理 WebSocket 连接
- 协调状态更新
- 响应式布局

## 状态管理

使用 Zustand 进行全局状态管理：

- `attitude`: 姿态数据
- `position`: 位置数据
- `battery`: 电池数据
- `systemStatus`: 系统状态
- `messageCount`: 消息计数
- `updateTelemetry()`: 更新遥测数据
- `reset()`: 重置状态

## 下一步

待后端实现完成后，可以继续添加：
- 控制输入组件
- 告警列表
- 历史页面
