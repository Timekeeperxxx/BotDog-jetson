# 启动文档（Windows 本机 RTSP → WHEP → 主界面）

本文档用于在 Windows 本机启动低延迟管线：
- 摄像头 RTSP(H.265) 拉流
- FFmpeg 转码为 H.264
- MediaMTX 发布 WHEP
- 前端主界面播放

## 前置要求
- Python 3.10+
- Node.js 18+
- 网络端口可用：8000、8554、8889、5174

## 安装依赖（仅首次）

### MediaMTX
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup-mediamtx.ps1
```

### FFmpeg
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup-ffmpeg.ps1
```

## 配置前端 WHEP 地址

`frontend/.env` 中设置：
```
VITE_WHEP_URL=http://192.168.144.30:8889/cam/whep
```

如果前端不是运行在同一台机器，请把 IP 改成运行 MediaMTX 的那台机器的地址。

## 启动顺序

### 1) 启动后端（主界面遥测/控制所需）
```cmd
.\scripts\start_backend.bat
```

### 2) 启动 MediaMTX
```cmd
.\scripts\mediamtx .\config\mediamtx.yml
```

启动日志应包含：
```
[RTSP] listener opened on :8554
[WebRTC] listener opened on :8889
```

### 3) 启动 FFmpeg 拉流转码推流
```cmd
.\scripts\ffmpeg-supervisor.cmd
```

可选环境变量（降低负载/提高稳定性）：
```cmd
set TARGET_FPS=15
set TARGET_WIDTH=1280
set TARGET_HEIGHT=-2
set FFMPEG_RETRY_DELAY_S=1
```

### 4) 启动前端
```cmd
cd frontend
npm install
npm run dev
```

打开主界面：
```
http://localhost:5174
```

## 快速验证 WHEP
如果需要单独验证 WHEP，可访问：
```
http://127.0.0.1:8889/cam/whep
```

或在本机启动测试页：
```cmd
cd web
python -m http.server 8090
```
打开：
```
http://127.0.0.1:8090/index.html
```

## 常见问题

### WHEP 404
- 先确认 MediaMTX 日志中有：
  `path cam stream is available and online`
- 说明 FFmpeg 推流正常后，再刷新页面

### FFmpeg 断流（End of file / Broken pipe）
- 表示相机 RTSP 源断开
- 可尝试降低 TARGET_FPS / TARGET_WIDTH

### 端口占用
- 关闭旧的 MediaMTX / FFmpeg 进程后再启动

## 停止
- 直接关闭各个命令行窗口
- 或在任务管理器结束 `mediamtx.exe`、`ffmpeg.exe`
