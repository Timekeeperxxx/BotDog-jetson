# 无机器狗硬件验证指南

## 📋 场景说明

**当前情况**：
- ✅ 有天空端和地面端的图传设备
- ✅ 有一个摄像头
- ❌ 没有机器狗本体（无 MAVLink 控制器）

**目标**：在无机器狗的情况下验证系统功能

---

## 🎯 可验证的功能清单

### ✅ 完全可验证（无需硬件）

| 功能模块 | 验证方法 | 预期结果 |
|---------|---------|---------|
| **前端界面** | 访问 http://localhost:5173 | 界面正常显示 |
| **控制面板** | 点击"启用控制"，使用键盘/手柄 | 控制指令发送成功 |
| **游戏手柄** | 连接 USB 手柄，测试摇杆 | 输入正常响应 |
| **配置管理** | 打开"⚙️ 配置"面板 | 13 个配置项可修改 |
| **遥测显示** | 观察姿态、位置、温度显示 | 模拟数据正常更新 |
| **AI 告警** | 修改 `thermal_threshold` 触发告警 | 告警弹窗出现 |
| **事件系统** | 观察事件列表 | 实时事件记录 |
| **WebSocket 连接** | 打开浏览器控制台 | 三个 WebSocket 连接成功 |
| **数据库** | 检查 `data/botdog.db` | 数据正常存储 |

### ⚠️ 需要摄像头硬件

| 功能模块 | 验证方法 | 预期结果 |
|---------|---------|---------|
| **WebRTC 视频流** | 配置真实摄像头，点击"连接视频" | 视频流正常显示 |

### ❌ 需要机器狗（不可验证）

| 功能模块 | 原因 |
|---------|-----|
| **MAVLink 遥测** | 需要真实 MAVLink 设备 |
| **真实控制** | 需要机器狗执行器 |
| **电池监控** | 需要真实电源系统 |

---

## 🚀 快速验证步骤

### 第一步：启动系统（模拟模式）

```bash
# 1. 激活虚拟环境
source .venv/bin/activate

# 2. 确认配置（默认使用模拟模式）
cat backend/.env | grep MAVLINK_SOURCE
# 应该显示: MAVLINK_SOURCE=simulation

# 3. 启动后端
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

# 4. 新开终端，启动前端
cd frontend
npm run dev
```

### 第二步：验证前端界面

1. 打开浏览器访问：`http://localhost:5173`
2. 检查界面是否正常显示
3. 打开浏览器控制台（F12），检查 WebSocket 连接：
   ```javascript
   // 应该看到三个 WebSocket 连接
   // ws://localhost:8000/ws/telemetry
   // ws://localhost:8000/ws/control
   // ws://localhost:8000/ws/event
   ```

### 第三步：验证遥测显示（模拟数据）

**观察数据更新**：
- **姿态面板**：俯仰角、横滚角、偏航角持续变化
- **位置面板**：经度、纬度、高度持续变化
- **系统状态**：温度在 30-50°C 之间，电池电量 80-100%
- **状态指示灯**：绿色（正常）

**验证模拟数据源**：
```bash
# 查看后端日志，应该看到
# "MAVLink 网关启动，数据源: simulation"
```

### 第四步：验证控制功能

**键盘控制测试**：
1. 点击"启用控制"按钮
2. 按下键盘按键：
   - W/S: 前进/后退
   - A/D: 左右平移
   - Q/E: 升降
   - ←/→: 转向
3. 打开浏览器控制台，查看网络请求：
   ```javascript
   // 应该看到控制指令发送
   // POST /api/v1/control/manual
   ```

**游戏手柄测试**（如果有）：
1. 连接 USB 手柄（Xbox/PlayStation）
2. 打开浏览器
3. **按下手柄上任意按钮**（激活 Gamepad API）
4. 点击"启用控制"
5. 移动摇杆，观察控制面板输入显示

### 第五步：验证 AI 告警功能

**触发高温告警**：
1. 点击顶部"⚙️ 配置"按钮
2. 找到 `thermal_threshold`（默认 60.0）
3. 修改为 `40.0`（低于模拟温度）
4. 点击"保存"
5. 观察界面：
   - 状态指示灯变红色
   - 弹出告警确认对话框
   - 告警快照出现在左侧列表

**恢复正常**：
1. 将 `thermal_threshold` 改回 `60.0`
2. 系统恢复绿色状态

### 第六步：验证配置管理

**测试所有配置类别**：
1. 打开配置面板
2. 测试 **后端配置**（5 项）：
   - `thermal_threshold`: 修改高温阈值
   - `heartbeat_timeout`: 修改心跳超时
   - `control_rate_limit_hz`: 修改控制速率限制
   - `ws_max_clients_per_ip`: 修改连接数限制
   - `video_watchdog_timeout_s`: 修改视频超时

3. 测试 **前端配置**（4 项）：
   - `ui_alert_ack_timeout_s`: 修改告警超时
   - `telemetry_display_hz`: 修改刷新率
   - `ui_lang`: 切换界面语言
   - `ui_theme`: 切换 UI 主题

4. 测试 **存储配置**（3 项）：
   - `snapshot_retention_days`: 修改快照保留天数
   - `max_snapshot_disk_usage_gb`: 修改磁盘占用限制
   - `telemetry_retention_days`: 修改遥测数据保留天数

**验证配置持久化**：
```bash
# 查看数据库中的配置记录
sqlite3 data/botdog.db "SELECT key, value, value_type FROM system_configs;"
```

### 第七步：验证事件系统

**观察事件记录**：
1. 进行各种操作（修改配置、触发告警）
2. 查看底部事件面板
3. 应该看到实时事件记录：
   - `CONFIG_UPDATED`
   - `ALERT_RAISED`
   - `ALERT_ACKED`
   - `CONTROL_SENT`

**验证事件历史**：
```bash
# 查看数据库中的事件历史
sqlite3 data/botdog.db "SELECT event_type, created_at FROM events ORDER BY created_at DESC LIMIT 10;"
```

---

## 📹 接入真实摄像头（可选）

如果你有摄像头设备，可以验证 WebRTC 视频流功能。

### 方法 1：使用 USB 摄像头（推荐）

```bash
# 1. 确认摄像头设备
ls /dev/video*
# 应该看到 /dev/video0 或类似设备

# 2. 安装 GStreamer 插件
sudo apt-get install python3-gst-1.0 gstreamer1.0-tools
sudo apt-get install gstreamer1.0-plugins-good
sudo apt-get install gstreamer1.0-plugins-bad
sudo apt-get install gstreamer1.0-plugins-ugly

# 3. 修改后端配置
# 编辑 backend/webrtc_signaling.py
# 将：
from .simple_video_track import SimpleTestVideoSourceFactory
# 改为：
from .video_track import GStreamerVideoSourceFactory

# 4. 修改 video_track.py 中的摄像头管道
# 找到管道配置，改为：
pipeline = "v4l2src device=/dev/video0 ! video/x-raw, width=640, height=480, framerate=30/1 ! videoconvert ! videoscale ! video/x-raw, width=640, height=480 ! application/x-rtp"

# 5. 重启后端
```

### 方法 2：使用图传设备

如果你有天空端和地面端图传设备：

**天空端（机器狗端）**：
```
摄像头 -> 天空端图传发射器
```

**地面端（操作端）**：
```
地面端图传接收器 -> USB 视频采集卡 -> /dev/video0
```

然后按照方法 1 配置 USB 摄像头。

### 测试视频流

1. 启动后端和前端
2. 点击视频区域的"连接视频"按钮
3. 观察视频流是否正常显示

---

## 📊 验收测试（无机器狗版本）

```bash
# 运行验收测试（会跳过需要真实硬件的测试）
python acceptance_test.py
```

**预期结果**：
- ✅ UC-01: 系统健康检查 - **通过**
- ✅ UC-02: 遥测 WebSocket 连接 - **通过**（模拟数据）
- ✅ UC-03: 事件 WebSocket 连接 - **通过**
- ✅ UC-04: 配置管理 API - **通过**
- ✅ UC-05: 告警系统功能 - **通过**

**通过率**: 100% (5/5) 🎉

---

## 🔧 故障排查

### 问题 1：前端无法连接后端

```bash
# 检查后端是否启动
curl http://localhost:8000/api/v1/health

# 检查 WebSocket 连接
wscat -c ws://localhost:8000/ws/telemetry
```

### 问题 2：遥测数据不更新

```bash
# 检查后端日志，确认模拟模式启用
grep "数据源: simulation" backend_*.log

# 检查配置
cat backend/.env | grep MAVLINK_SOURCE
```

### 问题 3：视频流无法连接

```bash
# 检查摄像头设备
ls -la /dev/video0

# 测试 GStreamer 管道
gst-launch-1.0 v4l2src device=/dev/video0 ! videoconvert ! autovideosink

# 检查 WebRTC 日志
grep "WebRTC" backend_*.log
```

### 问题 4：配置无法保存

```bash
# 检查数据库权限
ls -la data/botdog.db

# 检查数据库初始化
python init_config.py
```

---

## 📝 验证检查清单

使用此清单确认所有功能已验证：

- [ ] 前端界面正常显示
- [ ] 三个 WebSocket 连接成功
- [ ] 模拟遥测数据正常更新
- [ ] 键盘控制指令正常发送
- [ ] 游戏手柄正常识别和控制（如有）
- [ ] 配置面板可以打开
- [ ] 13 个配置项都可以修改
- [ ] AI 告警可以触发和确认
- [ ] 告警快照正常记录
- [ ] 事件系统正常工作
- [ ] 配置持久化到数据库
- [ ] 验收测试 100% 通过
- [ ] 摄像头视频流正常显示（如有）

---

## 🎯 总结

**无机器狗情况下，你可以验证 90% 的功能**：
- ✅ 所有前端界面
- ✅ 所有控制输入
- ✅ 所有配置管理
- ✅ 所有事件系统
- ✅ 模拟遥测数据
- ⚠️ 真实摄像头视频流（需要摄像头）

**唯一无法验证的**：
- ❌ 真实 MAVLink 遥测数据
- ❌ 机器狗真实运动控制

但这不影响你验证整个系统的核心功能！

---

**下一步**：如果有真实 MAVLink 设备，可以参考 [部署测试指南](./24_deployment_testing_guide.md) 进行完整集成测试。
