# UDP 视频流透明转发部署指南

## 方案概述

**方案 B：后端透明转发**实现从边缘端到前端的 UDP 视频流低延迟传输，同时保留现有的 WebRTC 基础设施。

### 架构流程

```
┌──────────────────────────────────────────────────────────────────┐
│                      边缘端 (Jetson/摄像头)                        │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ GStreamer 推流器                                            │  │
│  │ - RTSP 源: rtsp://192.168.144.25:8554/stream               │  │
│  │ - 硬件编码: H.264                                           │  │
│  │ - UDP 推流: 192.168.144.40:5000 (绑定 ens38)              │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
                              │
                              │ UDP/RTP H.264 流
                              │ (通过 192.168.144.40 网卡)
                              ↓
┌──────────────────────────────────────────────────────────────────┐
│                      后端服务器 (BotDog)                           │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ UDP 转发器 (udp_relay.py)                                  │  │
│  │ - 监听: 192.168.144.40:5000                               │  │
│  │ - 转发: 127.0.0.1:19856 (本地 WebRTC)                    │  │
│  │ - 零拷贝转发，不重新编码                                   │  │
│  └────────────────────────────────────────────────────────────┘  │
│                              │                                   │
│                              ↓                                   │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ WebRTC 信令处理器 (webrtc_signaling.py)                    │  │
│  │ - GStreamer 接收: udpsrc port=19856                       │  │
│  │ - 解码: avdec_h264                                         │  │
│  │ - WebRTC 转发到前端                                        │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
                              │
                              │ WebRTC
                              ↓
┌──────────────────────────────────────────────────────────────────┐
│                      前端 (React/Vite)                            │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ VideoPlayer 组件 (VideoPlayer.tsx)                         │  │
│  │ - WebRTC 接收: useWebRTC Hook                              │  │
│  │ - 渲染: HTML5 <video> 元素                                 │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

### 关键优势

- **前端零修改**：保持现有 WebRTC 接口和组件
- **低延迟**：零拷贝转发，目标延迟 < 200ms
- **透明转发**：后端不重新编码，仅转发 UDP 数据包
- **性能监控**：内置丢包率、延迟、带宽统计
- **多网卡支持**：明确绑定硬件网卡，避免路由冲突

---

## 部署步骤

### 1. 后端配置

#### 1.1 确认网络配置

```bash
# 检查网卡状态
ip addr show

# 确认硬件网卡 ens38 已配置 IP
ip addr show ens38
# 预期输出: inet 192.168.144.40/24
```

#### 1.2 更新配置文件

编辑 [`backend/config.py`](../backend/config.py)：

```python
# UDP 视频流转发器配置
UDP_RELAY_LISTEN_PORT: int = 5000  # 与边缘端推流端口一致
UDP_RELAY_BIND_ADDRESS: str = "192.168.144.40"  # 硬件网卡 IP
UDP_RELAY_TARGET_ADDRESS: str = "127.0.0.1"  # 本地 WebRTC 端口
UDP_RELAY_BUFFER_SIZE: int = 65536  # UDP 缓冲区
UDP_RELAY_ENABLE_STATS: bool = True  # 启用统计
UDP_RELAY_STATS_INTERVAL: float = 5.0  # 统计日志间隔
```

#### 1.3 启动后端时自动启动 UDP 转发器

编辑后端主程序（如 [`main.py`](../backend/main.py) 或 [`app.py`](../backend/app.py)）：

```python
from fastapi import FastAPI
from backend.webrtc_signaling import WebRTCSignalingHandler

app = FastAPI()
webrtc_handler = WebRTCSignalingHandler()

@app.on_event("startup")
async def startup_event():
    """启动事件：初始化 UDP 转发器。"""
    await webrtc_handler.start_udp_relay()
    print("✅ UDP 视频流转发器已启动")

@app.on_event("shutdown")
async def shutdown_event():
    """关闭事件：清理 UDP 转发器。"""
    await webrtc_handler.stop_udp_relay()
    print("🛑 UDP 视频流转发器已停止")

# 添加统计端点（可选）
@app.get("/api/stats/udp-relay")
async def get_udp_relay_stats():
    """获取 UDP 转发器统计信息。"""
    return webrtc_handler.get_udp_relay_stats()
```

#### 1.4 验证后端配置

```bash
# 启动后端
cd /home/frank/Code/Project/BotDog/backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000

# 检查日志输出
# 预期: ✅ UDP 视频流转发器已启动
# 预期: UDP 转发器已初始化: 192.168.144.40:5000 -> 127.0.0.1:19856
# 预期: UDP 转发器已启动: 监听 192.168.144.40:5000 转发到 127.0.0.1:19856

# 检查端口监听
sudo netstat -tuln | grep 5000
# 预期: udp        0      0 192.168.144.40:5000     0.0.0.0:*
```

---

### 2. 边缘端配置

#### 2.1 准备 GStreamer 推流脚本

边缘端需要运行更新后的 [`edge/gstreamer_streamer.py`](../edge/gstreamer_streamer.py)。

#### 2.2 启动边缘端推流器

```bash
# 在边缘端设备（Jetson/摄像头）上运行

# 方式 1：使用 RTSP 源（SIYI HM30 图传）
python3 edge/gstreamer_streamer.py \
  --source rtsp \
  --device rtsp://192.168.144.25:554/stream \
  --width 1920 \
  --height 1080 \
  --framerate 30 \
  --bitrate 8000000 \
  --host 192.168.144.40 \
  --port 5000 \
  --bind-address 192.168.144.40

# 方式 2：使用测试源（开发调试）
python3 edge/gstreamer_streamer.py \
  --source videotestsrc \
  --width 1920 \
  --height 1080 \
  --framerate 30 \
  --bitrate 8000000 \
  --host 192.168.144.40 \
  --port 5000 \
  --bind-address 192.168.144.40

# 方式 3：使用 USB 摄像头
python3 edge/gstreamer_streamer.py \
  --source v4l2src \
  --device /dev/video0 \
  --width 1920 \
  --height 1080 \
  --framerate 30 \
  --bitrate 8000000 \
  --host 192.168.144.40 \
  --port 5000 \
  --bind-address 192.168.144.40
```

#### 2.3 验证边缘端推流

```bash
# 在后端服务器上抓包验证
sudo tcpdump -i ens38 -n 'udp port 5000' -vv

# 预期输出: 大量 UDP 数据包
# IP 192.168.144.25.554 > 192.168.144.40.5000: UDP, length 1234
```

---

### 3. 前端配置

**前端无需任何修改**，继续使用现有的 WebRTC 接口。

#### 3.1 验证前端连接

```bash
# 启动前端开发服务器
cd frontend
npm run dev

# 打开浏览器访问: http://localhost:5173
# 检查视频播放器是否正常显示
```

#### 3.2 前端组件说明

现有组件无需修改：
- **VideoPlayer**: [`frontend/src/components/VideoPlayer.tsx`](../frontend/src/components/VideoPlayer.tsx)
- **WebRTC Hook**: [`frontend/src/hooks/useWebRTC.ts`](../frontend/src/hooks/useWebRTC.ts)

---

## 网络验证与调试

### 1. 网络连通性测试

```bash
# 从后端服务器 ping 边缘端
ping -I ens38 192.168.144.25

# 从后端服务器 ping 宿主机
ping 192.168.144.30

# 使用 nc (netcat) 测试 UDP 端口
# 在后端服务器监听
nc -u -l 192.168.144.40 5000

# 从边缘端发送测试数据
echo "test" | nc -u 192.168.144.40 5000
```

### 2. GStreamer 管道调试

#### 2.1 后端 GStreamer 接收测试

```bash
# 在后端服务器上测试 GStreamer 接收管道
GST_DEBUG=3 gst-launch-1.0 -v \
  udpsrc port=19856 buffer-size=1048576 \
  ! application/x-rtp,media=video,encoding-name=H264,payload=96 \
  ! rtph264depay \
  ! h264parse \
  ! avdec_h264 \
  ! videoconvert \
  ! autovideosink

# 预期: 弹出窗口显示视频流
```

#### 2.2 边缘端 GStreamer 推流测试

```bash
# 在边缘端测试推流管道
GST_DEBUG=3 python3 edge/gstreamer_streamer.py \
  --source videotestsrc \
  --bind-address 192.168.144.40 \
  --host 192.168.144.40 \
  --port 5000

# 查看详细 GStreamer 日志
GST_DEBUG=4 gst-launch-1.0 -v \
  videotestsrc pattern=ball is-live=true \
  ! video/x-raw,width=1920,height=1080,framerate=30/1 \
  ! x264enc bitrate=8000 speed-preset=ultrafast tune=zerolatency \
  ! rtph264pay config-interval=1 pt=96 \
  ! udpsink host=192.168.144.40 port=5000 bind-address=192.168.144.40 \
     buffer-size=1048576 sync=false qos=true
```

### 3. UDP 转发器调试

```bash
# 查看 UDP 转发器统计日志
# 后端日志会每 5 秒输出一次统计信息
# 示例输出:
# UDP 转发统计: 接收 15234 包, 转发 15233 包, 丢失 1 包 (0.01%), 延迟 0.8ms, 带宽 12.5Mbps

# 通过 API 获取统计信息
curl http://localhost:8000/api/stats/udp-relay

# 预期 JSON 输出:
{
  "video_stream": {
    "packets_received": 15234,
    "packets_sent": 15233,
    "packets_dropped": 1,
    "packet_loss_rate": 0.01,
    "avg_latency_ms": 0.8,
    "bandwidth_mbps": 12.5,
    "uptime_seconds": 60.5
  }
}
```

### 4. WebRTC 连接调试

```bash
# 浏览器开发者工具 -> Console
# 查看以下日志:
# - WebRTC 信令 WebSocket 连接已建立
# - 客户端 ID: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
# - ICE 收集已完成
# - 对等连接状态: connected

# 浏览器开发者工具 -> Network -> WS
# 查看 WebSocket 消息:
# - msg_type: "welcome"
# - msg_type: "offer"
# - msg_type: "answer"
# - msg_type: "ice_candidates"
```

---

## 性能优化

### 1. 系统网络参数优化

```bash
# 增大 UDP 接收缓冲区
sudo sysctl -w net.core.rmem_max=134217728
sudo sysctl -w net.core.rmem_default=134217728
sudo sysctl -w net.core.wmem_max=134217728
sudo sysctl -w net.core.wmem_default=134217728

# 持久化配置
sudo tee -a /etc/sysctl.conf <<EOF
net.core.rmem_max = 134217728
net.core.rmem_default = 134217728
net.core.wmem_max = 134217728
net.core.wmem_default = 134217728
EOF

sudo sysctl -p
```

### 2. 网卡中断合并优化

```bash
# 降低网卡延迟（适用于 ens38 硬件网卡）
sudo ethtool -C ens38 rx-usecs 100 tx-usecs 100
sudo ethtool -C ens38 rx-frames 0 tx-frames 0

# 查看当前设置
sudo ethtool -c ens38
```

### 3. GStreamer 参数调优

#### 针对低延迟优化（< 100ms）

编辑 [`edge/gstreamer_streamer.py`](../edge/gstreamer_streamer.py)：

```python
# 在 _build_encoder() 中添加超低延迟参数
if encoder == "nvv4l2h264enc":
    return (
        f"! {encoder} "
        f"bitrate={self.bitrate // 1000} "
        f"control-rate=constant "  # 恒定码率
        f"preset-level=1 "  # 超低延迟预设（Jetson）
        f"insert-sps-pps=1 "  # 每个关键帧插入 SPS/PPS
        f"num-B-frames=0 "  # 禁用 B 帧（降低延迟）
        f"! 'video/x-h264,profile=high,level=(string)4.1'"
    )
elif encoder == "x264enc":
    return (
        f"! {encoder} "
        f"bitrate={self.bitrate // 1000} "
        f"speed-preset=ultrafast "  # 最快编码
        f"tune=zerolatency "  # 零延迟调优
        f"bframes=0 "  # 禁用 B 帧
        f"key-int-max=30 "  # 关键帧间隔（1秒 @ 30fps）
        f"! 'video/x-h264,profile=high'"
    )
```

#### 针对 HM30 图传特性优化

```python
# 在 udpsink 中添加性能参数
f"! udpsink host={self.host} port={self.port} bind-address={self.bind_address} "
f"buffer-size=1048576 "  # 1MB 发送缓冲区
f"sync=false "  # 禁用同步（低延迟）
f"qos=true "    # 启用服务质量监控
f"max-lateness=1000000 "  # 最大延迟 1 秒
f"ts-offset=0 "  # 时间戳偏移置零
```

---

## 常见问题排查

### 问题 1：后端无法接收 UDP 流

**症状**：
- 后端日志显示 "UDP 转发器已启动" 但没有收到数据包
- tcpdump 抓不到 UDP 包

**排查步骤**：
```bash
# 1. 检查网卡绑定
ip addr show ens38
# 确认 IP: 192.168.144.40

# 2. 检查防火墙
sudo iptables -L -n | grep 5000
# 如需放行:
sudo iptables -I INPUT -p udp --dport 5000 -j ACCEPT

# 3. 检查端口占用
sudo netstat -tuln | grep 5000
sudo lsof -i :5000

# 4. 验证边缘端网络
# 在边缘端运行:
ping -c 5 192.168.144.40
```

### 问题 2：视频播放卡顿或高延迟

**症状**：
- 前端视频卡顿
- 延迟 > 1 秒

**解决方案**：
```bash
# 1. 检查丢包率
curl http://localhost:8000/api/stats/udp-relay
# 如果丢包率 > 1%，检查网络质量

# 2. 降低码率
python3 edge/gstreamer_streamer.py --bitrate 4000000  # 4 Mbps

# 3. 降低分辨率
python3 edge/gstreamer_streamer.py --width 1280 --height 720

# 4. 检查 CPU 使用率
htop
# 如果 CPU 100%，考虑硬件加速编码
```

### 问题 3：WebRTC 连接失败

**症状**：
- 前端显示 "连接错误"
- 浏览器控制台显示 WebRTC 错误

**排查步骤**：
```bash
# 1. 检查 WebSocket 连接
# 浏览器开发者工具 -> Network -> WS
# 确认 WebSocket 已建立

# 2. 检查 GStreamer 接收管道
# 查看后端日志是否有 GStreamer 错误

# 3. 验证 GStreamer 接收
GST_DEBUG=3 gst-launch-1.0 \
  udpsrc port=19856 \
  ! application/x-rtp,media=video,encoding-name=H264,payload=96 \
  ! rtph264depay \
  ! h264parse \
  ! avdec_h264 \
  ! videoconvert \
  ! fakesink

# 4. 检查 WebRTC ICE 候选
# 浏览器控制台查看 ICE 连接状态
```

### 问题 4：UDP 转发器未启动

**症状**：
- 后端日志缺少 "UDP 转发器已启动"
- API `/api/stats/udp-relay` 返回 `{"status": "not_started"}`

**解决方案**：
```bash
# 1. 确认启动事件已注册
# 检查 main.py 或 app.py 是否包含:
# @app.on_event("startup")
# async def startup_event():
#     await webrtc_handler.start_udp_relay()

# 2. 手动启动（临时测试）
# 在 Python REPL 中:
import asyncio
from backend.webrtc_signaling import WebRTCSignalingHandler

handler = WebRTCSignalingHandler()
await handler.start_udp_relay()
```

---

## 性能基准

### 预期性能指标

| 指标 | 目标值 | 测试条件 |
|------|--------|----------|
| 端到端延迟 | < 200ms | 局域网，1080p@30fps |
| 丢包率 | < 0.1% | 有线网络，无干扰 |
| 吞吐量 | 8-12 Mbps | 1080p H.264 |
| CPU 使用率（后端） | < 10% | 转发模式（零拷贝） |
| 内存使用（后端） | < 100 MB | 单流转发 |

### 性能测试方法

```bash
# 1. 测量端到端延迟
# 在边缘端录制视频时间戳，在前端测量显示时间戳

# 2. 测试丢包率
curl http://localhost:8000/api/stats/udp-relay
# 观察 packet_loss_rate 字段

# 3. 测试带宽使用
# 使用 nload 或 iftop
sudo ntopng -i ens38

# 4. 压力测试
# 同时启动多个前端连接，观察性能变化
```

---

## 附录：完整启动脚本

### 后端启动脚本

创建 [`scripts/start_backend.sh`](../scripts/start_backend.sh)：

```bash
#!/bin/bash
set -e

echo "🚀 启动 BotDog 后端..."

# 激活虚拟环境
source /home/frank/Code/Project/BotDog/.venv/bin/activate

# 检查网络配置
echo "📡 检查网络配置..."
ip addr show ens38 | grep "inet 192.168.144.40" || {
    echo "❌ 错误: 硬件网卡 ens38 未配置 IP 192.168.144.40"
    exit 1
}

# 优化系统参数
echo "⚙️  优化系统参数..."
sudo sysctl -w net.core.rmem_max=134217728 >/dev/null 2>&1
sudo sysctl -w net.core.rmem_default=134217728 >/dev/null 2>&1
sudo sysctl -w net.core.wmem_max=134217728 >/dev/null 2>&1
sudo sysctl -w net.core.wmem_default=134217728 >/dev/null 2>&1

# 启动后端
echo "✅ 启动后端服务器..."
cd /home/frank/Code/Project/BotDog/backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 边缘端启动脚本

创建 [`scripts/start_edge_streamer.sh`](../scripts/start_edge_streamer.sh)：

```bash
#!/bin/bash
set -e

echo "📹 启动边缘端 GStreamer 推流器..."

# 配置参数
RTSP_URL="rtsp://192.168.144.25:554/stream"
WIDTH=1920
HEIGHT=1080
FRAMERATE=30
BITRATE=8000000
TARGET_HOST="192.168.144.40"
TARGET_PORT=5000
BIND_ADDRESS="192.168.144.40"

# 检查 GStreamer
if ! command -v gst-launch-1.0 &> /dev/null; then
    echo "❌ 错误: 未安装 GStreamer"
    exit 1
fi

# 启动推流器
echo "🔗 推流到: ${TARGET_HOST}:${TARGET_PORT} (绑定 ${BIND_ADDRESS})"
python3 edge/gstreamer_streamer.py \
  --source rtsp \
  --device "$RTSP_URL" \
  --width $WIDTH \
  --height $HEIGHT \
  --framerate $FRAMERATE \
  --bitrate $BITRATE \
  --host "$TARGET_HOST" \
  --port $TARGET_PORT \
  --bind-address "$BIND_ADDRESS"
```

---

## 总结

通过**方案 B：后端透明转发**，我们实现了：

✅ **零修改前端**：现有 WebRTC 组件无需任何改动
✅ **低延迟传输**：零拷贝转发，目标延迟 < 200ms
✅ **性能监控**：实时统计丢包率、延迟、带宽
✅ **多网卡支持**：明确绑定硬件网卡，避免路由冲突
✅ **易于部署**：自动化脚本和详细文档

现在可以开始部署和测试了！
