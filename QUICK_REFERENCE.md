# 快速参考卡片 - Windows 硬件加速视频系统

## 📦 安装清单

### 1. GStreamer 安装
```
下载: https://gstreamer.freedesktop.org/download/
安装: gstreamer-1.0-msvc-x86_64.msi (推荐 1.24.0+)
```

### 2. 环境变量配置
```cmd
# 自动配置
setup_gstreamer_env.bat

# 或手动设置
GSTREAMER_1_0_ROOT_MSVC_X86_64=C:\gstreamer\1.0\msvc_x86_64
PATH+=C:\gstreamer\1.0\msvc_x86_64\bin
```

### 3. Python 依赖
```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

---

## 🔍 诊断步骤

### 快速诊断
```bash
python diagnose_environment.py
```

### 单项测试
```bash
# OpenCV GStreamer 支持
python test_opencv_gst.py

# H.265 硬件解码性能
python test_h265_decode.py

# 完整 UDP 管道 (需要相机推流)
python test_full_pipeline.py
```

---

## 🚀 启动系统

### 快速启动 (推荐)
```cmd
start_video_system.bat
```

### 手动启动
```bash
venv\Scripts\activate
python backend/main.py
```

---

## 🔧 GStreamer 管道

### 完整管道
```
udpsrc port=5000
! application/x-rtp,media=video,encoding-name=H265,payload=96
! rtpjitterbuffer latency=100 do-retransmission=true
! rtph265depay
! h265parse
! d3d11h265dec              ← D3D11 硬件解码
! videoconvert
! video/x-raw,format=I420
! x264enc tune=zerolatency speed-preset=ultrafast
! rtph264pay
! appsink sync=false
```

### 关键参数
| 参数 | 默认值 | 说明 |
|------|--------|------|
| port | 5000 | UDP 接收端口 |
| latency | 100 | 抖动缓冲 (ms) |
| width | 1920 | 视频宽度 |
| height | 1080 | 视频高度 |
| framerate | 30 | 目标帧率 |

---

## 📊 性能目标

| 指标 | 目标 | 说明 |
|------|------|------|
| CPU 占用 | <30% | 单核心使用率 |
| GPU 占用 | 10-20% | 视频解码占用 |
| 帧率 | 30fps | 稳定输出 |
| 延迟 | <100ms | 端到端延迟 |
| 灰屏 | 0次 | 抖动缓冲优化 |

---

## 🐛 常见问题

### ❌ OpenCV 不支持 GStreamer
```bash
# 1. 检查环境变量
echo %GSTREAMER_1_0_ROOT_MSVC_X86_64%

# 2. 重新安装 OpenCV
pip uninstall opencv-python
pip install opencv-python

# 3. 重启命令提示符
```

### ❌ 缺少 d3d11h265dec 插件
```cmd
# 检查插件
gst-inspect-1.0 d3d11h265dec

# 解决: 重新安装 GStreamer (Complete 安装)
```

### ❌ 端口被占用
```cmd
# 查找占用
netstat -ano | findstr :5000

# 终止进程
taskkill /PID <PID> /F
```

### ❌ 灰屏/花屏
```python
# 增加抖动缓冲
"! rtpjitterbuffer latency=200 "

# 检查网络
ping 192.168.144.25

# 验证编码格式 (必须是 H.265)
```

---

## 🎮 代码集成

### 导入硬件加速版本
```python
from backend.video_track_hw import GStreamerVideoSourceFactory
```

### 创建视频轨道
```python
track = GStreamerVideoSourceFactory.create_track(
    udp_port=5000,
    width=1920,   # 1080P
    height=1080,
    framerate=30
)

await track.start()
```

### 接收帧
```python
frame = await track.recv()
# frame: VideoFrame 对象
```

---

## 📁 文件说明

| 文件 | 用途 |
|------|------|
| `backend/video_track_hw.py` | 硬件加速视频轨道 (新) |
| `requirements.txt` | Python 依赖列表 |
| `setup_gstreamer_env.bat` | 环境配置脚本 |
| `start_video_system.bat` | 快速启动脚本 |
| `diagnose_environment.py` | 环境诊断工具 |
| `test_opencv_gst.py` | OpenCV 测试 |
| `test_h265_decode.py` | 硬件解码测试 |
| `test_full_pipeline.py` | 完整管道测试 |
| `WINDOWS_GSTREAMER_SETUP.md` | 详细安装指南 |
| `README_HW_ACCEL.md` | 完整文档 |

---

## 🔗 网络配置

### 相机信息
```
RTSP 地址: rtsp://192.168.144.25:8554/main.264
编码格式: H.265 (Main Profile)
推流目标: udp://127.0.0.1:5000
```

### 网络测试
```cmd
# 测试连接
ping 192.168.144.25

# 测试 RTSP 流
vlc rtsp://192.168.144.25:8554/main.264
```

---

## 📈 监控指标

### Windows 任务管理器
- **CPU**: <30% (单核心)
- **GPU**: 10-20% (视频解码)
- **内存**: <500MB

### 系统日志
```
🚀 启动 GStreamer 视频管道（Windows 硬件加速模式）:
输入: UDP port=5000, H.265 RTP
解码器: d3d11h265dec (D3D11 硬件解码)
抖动缓冲: latency=100ms + do-retransmission=true
输出: 1920x1080 @ 30fps I420
目标: GPU 硬解，CPU <30%，无灰屏
✅ GStreamer 管道启动成功
```

---

## 🎯 性能优化建议

### 根据网络调整抖动缓冲
```python
# 高质量网络
"! rtpjitterbuffer latency=50 "

# 普通网络 (默认)
"! rtpjitterbuffer latency=100 "

# 不稳定网络
"! rtpjitterbuffer latency=200 "
```

### 根据性能调整分辨率
```python
# 1080P @ 30fps (默认，推荐)
width=1920, height=1080, framerate=30

# 720P @ 30fps (低延迟)
width=1280, height=720, framerate=30

# 1080P @ 60fps (高帧率)
width=1920, height=1080, framerate=60
```

---

## ✅ 验收标准

完成以下检查确认系统就绪:

- [ ] GStreamer 安装成功 (gst-inspect-1.0 --version)
- [ ] 环境变量配置完成
- [ ] diagnose_environment.py 全部通过
- [ ] test_h265_decode.py FPS >= 24
- [ ] test_full_pipeline.py 接收到数据流
- [ ] CPU 占用 <30%
- [ ] GPU 占用 10-20%
- [ ] 无灰屏/花屏

---

## 📞 获取帮助

### 收集诊断信息
```bash
# 诊断输出
python diagnose_environment.py > diagnosis.txt

# 解码测试
python test_h265_decode.py > decode_test.txt

# 完整管道测试
python test_full_pipeline.py > pipeline_test.txt
```

### 需要提供的信息
- Windows 版本
- GPU 型号
- GStreamer 版本
- OpenCV 版本
- 上述诊断文件

---

**享受你的 GPU 加速视频处理系统! 🚀**
