# 前端环境变量配置迁移

## 变更概述

将前端所有硬编码的后端地址（`localhost:8000`）替换为环境变量配置，支持指向 `192.168.144.40:8000`。

## 新增文件

### 1. `frontend/.env`
生产环境配置，默认指向 `192.168.144.40:8000`

```env
VITE_API_BASE_URL=http://192.168.144.40:8000
```

### 2. `frontend/.env.local`
本地开发配置，指向 `localhost:8000`

```env
VITE_API_BASE_URL=http://localhost:8000
```

### 3. `frontend/src/config/api.ts`
统一 API 和 WebSocket 地址配置工具

```typescript
getApiBaseUrl()      // 获取后端 API 基础 URL
getWsUrl(path)      // 将 HTTP URL 转换为 WebSocket URL
getApiUrl(path)     // 获取完整的 API URL
```

### 4. `scripts/start_frontend.sh`
前端启动脚本

## 修改的文件

### Hooks (8 个文件)

1. **frontend/src/hooks/useBotDogWebSocket.ts**
   - 导入 `getWsUrl`
   - 使用 `getWsUrl('/ws/telemetry')`

2. **frontend/src/hooks/useControlWebSocket.ts**
   - 导入 `getWsUrl`
   - 使用 `getWsUrl('/ws/control')`

3. **frontend/src/hooks/useEventWebSocket.ts**
   - 导入 `getWsUrl`
   - 使用 `getWsUrl('/ws/event')`

4. **frontend/src/hooks/useTelemetryWebSocket.ts**
   - 导入 `getWsUrl`
   - 使用 `getWsUrl('/ws/telemetry')`

5. **frontend/src/hooks/useWebRTC.ts**
   - 导入 `getWsUrl`
   - 使用 `getWsUrl('/ws/webrtc')`

6. **frontend/src/hooks/useWebRTCVideo.ts**
   - 导入 `getWsUrl`
   - 使用 `getWsUrl('/ws/webrtc')`

7. **frontend/src/hooks/useConfig.ts**
   - 导入 `getApiUrl`
   - 使用 `getApiUrl('')`

### 组件和页面 (3 个文件)

8. **frontend/src/components/EmergencyStopButton.tsx**
   - 导入 `getApiUrl`
   - 使用 `getApiUrl("/api/v1/control/e-stop")`

9. **frontend/src/pages/EvidenceHistory.tsx**
   - 导入 `getApiUrl`
   - 使用 `getApiUrl("/api/v1/evidence")`

10. **frontend/src/pages/EventWebSocketTest.tsx**
    - 导入 `getWsUrl`
    - 使用 `getWsUrl('/ws/event')`

## 使用方法

### 开发环境（指向本地后端）

```bash
cd frontend
cp .env.local .env
npm run dev
```

### 生产环境（指向 192.168.144.40）

```bash
cd frontend
npm run dev  # 使用 .env 中的默认配置
```

或者使用启动脚本：

```bash
bash scripts/start_frontend.sh
```

## 环境变量切换

### 切换到不同后端地址

编辑 `frontend/.env`：

```env
# 指向 192.168.144.40
VITE_API_BASE_URL=http://192.168.144.40:8000

# 或指向 localhost
VITE_API_BASE_URL=http://localhost:8000
```

然后重启前端服务器。

## 验证

启动前端后，在浏览器控制台检查网络请求：

```javascript
// 应该看到请求指向 192.168.144.40:8000
// WebSocket 连接指向 ws://192.168.144.40:8000/ws/...
```

## 注意事项

1. **环境变量优先级**：
   - `.env.local` > `.env` > 默认值
   - 生产部署时仅保留 `.env`

2. **前端必须重启**：
   - 修改 `.env` 后必须重启 `npm run dev`
   - 环境变量在构建时读取

3. **WebSocket 自动转换**：
   - `http://` → `ws://`
   - `https://` → `wss://`
