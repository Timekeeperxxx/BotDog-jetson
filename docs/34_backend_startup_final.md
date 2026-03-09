# 🎯 BotDog 后端启动 - 最终指南

## ✅ **问题已解决！**

之前的导入错误已修复：
- ❌ 错误: `ImportError: attempted relative import with no known parent package`
- ✅ 原因: 在 `backend/` 目录下运行 `uvicorn main:app` 导致模块路径错误
- ✅ 解决: 从项目根目录运行 `uvicorn backend.main:app`

---

## 🚀 **正确启动方式**

### 方式 1：使用启动脚本（推荐）✅

```bash
cd /home/frank/Code/Project/BotDog
./scripts/start_backend.sh
```

### 方式 2：手动启动

```bash
cd /home/frank/Code/Project/BotDog
source .venv/bin/activate
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

**关键点**：
- ✅ 从项目根目录启动（不是 `backend/` 目录）
- ✅ 使用 `backend.main:app` 作为模块路径（不是 `main:app`）

---

## 📋 **预期启动日志**

```
🚀 启动 BotDog 后端（含 UDP 转发器）...
✅ Python 版本: Python 3.x.x
📡 检查网络配置...
✅ 硬件网卡 ens33 已配置 IP 192.168.144.40
⚙️  优化系统网络参数...
✅ UDP 缓冲区已优化至 128MB
✅ 启动后端服务器...
INFO:     Started server process [PID]
INFO:     Waiting for application startup.
INFO:     BotDog backend starting up (lifespan)...
INFO:     Database initialized.
INFO:     状态机已启动
INFO:     遥测队列管理器已启动
INFO:     MAVLink 网关已启动，数据源: simulation
INFO:     WebSocket 广播器已启动
INFO:     遥测落盘 Worker 已启动
INFO:     UDP 视频流转发器已启动: 192.168.144.40:5000 -> 127.0.0.1:19856  ← 🎯 关键！
INFO:     WebRTC 信令处理器已初始化
INFO:     事件广播器已初始化
INFO:     告警服务已初始化
INFO:     所有后台任务已启动，应用就绪
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

---

## ✅ **验证启动成功**

### 1. 检查 API 健康状态

```bash
curl http://localhost:8000/api/v1/system/health
```

**预期输出**：

```json
{
  "status": "healthy",
  "mavlink_connected": false,
  "uptime": 5.123
}
```

### 2. 检查 UDP 转发器状态

```bash
curl http://localhost:8000/api/v1/video/udp-relay/stats
```

**预期输出**：

```json
{
  "video_stream": {
    "packets_received": 0,
    "packets_sent": 0,
    "packets_dropped": 0,
    "packet_loss_rate": 0.0,
    "avg_latency_ms": 0.0,
    "bandwidth_mbps": 0.0,
    "uptime_seconds": 5.5
  }
}
```

### 3. 检查端口监听

```bash
sudo netstat -tuln | grep -E '5000|8000'
```

**预期输出**：

```
tcp        0      0 0.0.0.0:8000            0.0.0.0:*               LISTEN
udp        0      0 192.168.144.40:5000     0.0.0.0:*
```

---

## 🧪 **快速测试三步骤**

### 终端 1：启动后端

```bash
cd /home/frank/Code/Project/BotDog
./scripts/start_backend.sh
```

### 终端 2：启动测试推流

```bash
cd /home/frank/Code/Project/BotDog
source .venv/bin/activate

python3 edge/gstreamer_streamer.py \
  --source videotestsrc \
  --bind-address 192.168.144.40 \
  --host 192.168.144.40 \
  --port 5000
```

### 终端 3：监控统计

```bash
watch -n 2 'curl -s http://localhost:8000/api/v1/video/udp-relay/stats | jq'
```

---

## 🔧 **常见问题排查**

### 问题 1：ImportError

**症状**：
```
ImportError: attempted relative import with no known parent package
```

**原因**：从错误的目录启动

**解决方案**：
```bash
# ❌ 错误
cd backend
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000

# ✅ 正确
cd /home/frank/Code/Project/BotDog
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

### 问题 2：模块未找到

**症状**：
```
ModuleNotFoundError: No module named 'backend'
```

**原因**：Python 路径未包含项目根目录

**解决方案**：
```bash
# 确保从项目根目录启动
cd /home/frank/Code/Project/BotDog
pwd  # 应该显示 /home/frank/Code/Project/BotDog

# 使用正确的模块路径
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

### 问题 3：UDP 转发器未启动

**症状**：日志中没有 "UDP 视频流转发器已启动"

**原因**：可能启动失败（网卡未配置等）

**解决方案**：
```bash
# 1. 验证网卡配置
ip addr show ens33 | grep 192.168.144.40

# 2. 如果未配置，配置网卡
sudo ip addr add 192.168.144.40/24 dev ens33

# 3. 重新启动后端
./scripts/start_backend.sh
```

---

## 📊 **配置验证**

### 验证配置文件

```bash
python3 -c "
import sys
sys.path.insert(0, '.')
from backend.config import settings
print('✅ 配置验证')
print(f'UDP_RELAY_BIND_ADDRESS: {settings.UDP_RELAY_BIND_ADDRESS}')
print(f'HARDWARE_INTERFACE: {settings.HARDWARE_INTERFACE}')
print(f'UDP_RELAY_LISTEN_PORT: {settings.UDP_RELAY_LISTEN_PORT}')
"
```

**预期输出**：

```
✅ 配置验证
UDP_RELAY_BIND_ADDRESS: 192.168.144.40
HARDWARE_INTERFACE: ens33
UDP_RELAY_LISTEN_PORT: 5000
```

### 验证模块导入

```bash
python3 -c "
import sys
sys.path.insert(0, '.')
from backend.main import app
from backend.udp_relay import UDPRelayManager
from backend.webrtc_signaling import WebRTCSignalingHandler
print('✅ 所有模块导入成功')
"
```

---

## 🎯 **性能基准**

启动后验证性能指标：

| 指标 | 目标值 | 检查命令 |
|------|--------|----------|
| 后端健康 | healthy | `curl /api/v1/system/health` |
| UDP 转发器 | 运行中 | `curl /api/v1/video/udp-relay/stats` |
| 端口 8000 | LISTEN | `netstat -tuln \| grep 8000` |
| 端口 5000 | 绑定 ens33 | `netstat -tuln \| grep 5000` |

---

## 📚 **相关文档**

| 文档 | 用途 |
|------|------|
| **[docs/33_system_config.md](./33_system_config.md)** | ⭐ 你的系统配置 |
| [docs/29_udp_relay_deployment.md](./29_udp_relay_deployment.md) | 完整部署指南 |
| [docs/31_udp_relay_testing.md](./31_udp_relay_testing.md) | 测试验证指南 |

---

## ✅ **下一步**

1. ✅ 后端启动成功
2. 🧪 运行测试推流
3. 📊 验证 UDP 转发统计
4. 🎥 启动前端验证视频播放
5. 📹 接入真实 RTSP 源（SIYI HM30）

---

## 🚀 **立即开始**

```bash
cd /home/frank/Code/Project/BotDog
./scripts/start_backend.sh
```

**预期看到**：
```
INFO:     UDP 视频流转发器已启动: 192.168.144.40:5000 -> 127.0.0.1:19856
```

现在启动吧！🎉
