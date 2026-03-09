# 🔧 UDP 转发器故障排除指南

## ✅ **问题已修复**

### 修复内容
- **NotImplementedError** - 已修复
- **原因**: Python 3.10 不支持 `loop.sock_recvfrom` 和 `loop.sock_sendto`
- **解决方案**: 使用 `run_in_executor` 包装同步 socket 操作

---

## 🚀 **重新启动后端**

修复后请重新启动：

```bash
cd /home/frank/Code/Project/BotDog
./scripts/start_backend.sh
```

---

## ✅ **预期结果**

### 启动日志应该显示：

```
INFO:     UDP 视频流转发器已启动: 192.168.144.40:5000 -> 127.0.0.1:19856
```

### 不应该再看到：

```
WARNING  | backend.udp_relay:_relay_loop:272 - UDP 转发错误: , 类型: NotImplementedError
```

---

## 🧪 **验证修复**

### 1. 检查 UDP 转发器状态

```bash
curl http://localhost:8000/api/v1/video/udp-relay/stats
```

**预期输出**（未收到数据时）：

```json
{
  "video_stream": {
    "packets_received": 0,
    "packets_sent": 0,
    "packets_dropped": 0,
    "packet_loss_rate": 0.0,
    "avg_latency_ms": 0.0,
    "bandwidth_mbps": 0.0,
    "uptime_seconds": 10.5
  }
}
```

### 2. 启动测试推流

在**另一个终端**运行：

```bash
cd /home/frank/Code/Project/BotDog
source .venv/bin/activate

python3 edge/gstreamer_streamer.py \
  --source videotestsrc \
  --bind-address 192.168.144.40 \
  --host 192.168.144.40 \
  --port 5000
```

### 3. 实时监控统计

```bash
watch -n 2 'curl -s http://localhost:8000/api/v1/video/udp-relay/stats | jq'
```

**预期输出**（收到数据后）：

```json
{
  "video_stream": {
    "packets_received": 15234,
    "packets_sent": 15234,
    "packets_dropped": 0,
    "packet_loss_rate": 0.0,
    "avg_latency_ms": 0.8,
    "bandwidth_mbps": 8.5,
    "uptime_seconds": 15.5
  }
}
```

---

## 📊 **性能指标**

启动测试推流后，应该看到：

| 指标 | 预期值 | 说明 |
|------|--------|------|
| `packets_received` | > 0 | 持续增长 |
| `packets_sent` | = `packets_received` | 无丢包 |
| `packet_loss_rate` | 0.0% | 完美转发 |
| `avg_latency_ms` | < 2.0 | 低延迟 |
| `bandwidth_mbps` | 8-12 | 1080p@30fps |

---

## 🔍 **如果仍有问题**

### 问题 1：UDP 转发错误仍然出现

**检查 Python 版本**：

```bash
python3 --version
```

应该显示 Python 3.9 或更高。

### 问题 2：端口已被占用

**检查端口占用**：

```bash
sudo netstat -tuln | grep 5000
```

如果被占用：

```bash
sudo lsof -i :5000
sudo kill -9 <PID>
```

### 问题 3：无法绑定到 192.168.144.40

**检查网卡配置**：

```bash
ip addr show ens33 | grep 192.168.144.40
```

如果未配置：

```bash
sudo ip addr add 192.168.144.40/24 dev ens33
```

---

## 🎯 **快速测试三步骤**

### 终端 1：启动后端

```bash
cd /home/frank/Code/Project/BotDog
./scripts/start_backend.sh
```

### 终端 2：启动测试推流

```bash
cd /home/frank/Code/Project/BotDog
source .venv/bin/activate

python3 edge/gstreamer_streamer.py --source videotestsrc --bind-address 192.168.144.40
```

### 终端 3：监控统计

```bash
watch -n 2 'curl -s http://localhost:8000/api/v1/video/udp-relay/stats | jq'
```

---

## ✅ **成功标志**

修复成功后，你应该看到：

- ✅ 后端启动无错误
- ✅ UDP 转发器日志显示已启动
- ✅ 测试推流成功启动
- ✅ `packets_sent` 持续增长
- ✅ `packet_loss_rate` 保持 0.0%
- ✅ `avg_latency_ms` < 2.0

---

## 📚 **相关文档**

- **[docs/34_backend_startup_final.md](./34_backend_startup_final.md)** - 最终启动指南
- **[docs/33_system_config.md](./33_system_config.md)** - 系统配置说明

---

**修复完成！重新启动后端开始测试吧！** 🚀
