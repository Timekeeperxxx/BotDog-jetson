# 图传设备接入指南

## 📡 设备说明

你现在拥有的设备：
- **天空端图传发射器**：安装在机器狗上
- **地面端图传接收器**：连接到操作电脑
- **摄像头**：连接到天空端

---

## 🎯 图传设备使用场景

### 场景 A：无机器狗，仅测试图传（当前情况）

由于你暂时没有机器狗，天空端图传发射器无法安装到机器狗上。但你可以：

#### 方案 1：直接使用摄像头（最简单）

跳过图传设备，直接将 USB 摄像头连接到电脑：

```bash
# 1. 检查摄像头设备
ls /dev/video0

# 2. 安装依赖
sudo apt-get install gstreamer1.0-tools gstreamer1.0-plugins-good
sudo apt-get install gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly
sudo apt-get install python3-gst-1.0

# 3. 测试摄像头
gst-launch-1.0 v4l2src device=/dev/video0 ! videoconvert ! autovideosink
```

#### 方案 2：使用图传设备（测试图传功能）

如果你想测试图传设备是否工作：

**硬件连接**：
```
天空端：
  摄像头 -> 天空端图传发射器

地面端：
  地面端图传接收器 -> USB 视频采集卡 -> 电脑 (/dev/video0)
```

**步骤**：
1. 天空端：将摄像头连接到天空端图传发射器的视频输入
2. 天空端：给天空端供电
3. 地面端：将地面端图传接收器连接到 USB 视频采集卡
4. 地面端：USB 采集卡插入电脑
5. 检查设备：
   ```bash
   ls /dev/video*
   # 应该看到 /dev/video0 或类似设备
   ```

6. 测试视频输入：
   ```bash
   # 使用 VLC 播放器测试
   vlc v4l2:///dev/video0

   # 或使用 GStreamer 测试
   gst-launch-1.0 v4l2src device=/dev/video0 ! videoconvert ! autovideosink
   ```

---

## 🔧 修改代码以支持真实摄像头

### 第一步：启用 GStreamer 视频源

编辑 `backend/webrtc_signaling.py`：

```python
# 将这一行：
from .simple_video_track import SimpleTestVideoSourceFactory

# 改为：
from .video_track import GStreamerVideoSourceFactory
```

### 第二步：修改视频源配置

#### 选项 A：使用 USB 摄像头（推荐）

创建新文件 `backend/usb_video_track.py`：

```python
#!/usr/bin/env python3
"""
USB 摄像头视频源。
"""

import asyncio
import fractions
import time
from typing import Optional

from av import VideoFrame
from aiortc import MediaStreamTrack
import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst


class USBVideoTrack(MediaStreamTrack):
    """USB 摄像头视频轨道。"""

    kind = "video"

    def __init__(
        self,
        device: str = "/dev/video0",
        width: int = 640,
        height: int = 480,
        framerate: int = 30,
    ):
        super().__init__()
        self.device = device
        self.width = width
        self.height = height
        self.framerate = framerate
        self._queue: asyncio.Queue[Optional[VideoFrame]] = asyncio.Queue(maxsize=30)
        self._started = False
        self._pipeline: Optional[Gst.Pipeline] = None
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        """启动 GStreamer 管道。"""
        if self._started:
            return

        Gst.init(None)

        # USB 摄像头管道
        pipeline_str = (
            f"v4l2src device={self.device} "
            f"! video/x-raw, width={self.width}, height={self.height}, framerate={self.framerate}/1 "
            "! videoconvert "
            "! videoscale "
            f"! video/x-raw, width={self.width}, height={self.height}, format=I420 "
            "! appsink name=sink emit-signals=true max-buffers=1 drop=true"
        )

        self._pipeline = Gst.parse_launch(pipeline_str)

        if not self._pipeline:
            raise RuntimeError("无法创建 GStreamer 管道")

        # 获取 appsink 元素
        sink = self._pipeline.get_by_name("sink")
        sink.connect("new-sample", self._on_new_sample)

        # 启动管道
        self._pipeline.set_state(Gst.State.PLAYING)
        self._started = True

        # 启动处理任务
        self._task = asyncio.create_task(self._run())

    async def stop(self):
        """停止 GStreamer 管道。"""
        if not self._started:
            return

        self._started = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        if self._pipeline:
            self._pipeline.set_state(Gst.State.NULL)

        await self._queue.put(None)

    async def _run(self):
        """处理帧队列的后台任务。"""
        while self._started:
            try:
                await asyncio.sleep(0)
            except asyncio.CancelledError:
                break

    def _on_new_sample(self, sink):
        """处理新样本。"""
        if not self._started:
            return Gst.FlowReturn.OK

        try:
            sample = sink.emit("pull-sample")
            if not sample:
                return Gst.FlowReturn.OK

            buffer = sample.get_buffer()
            if not buffer:
                return Gst.FlowReturn.OK

            # 转换为 VideoFrame
            success, info = buffer.map(Gst.MapFlags.READ)
            if not success:
                return Gst.FlowReturn.OK

            frame = VideoFrame.from_ndarray(
                np.frombuffer(info.data, dtype=np.uint8).reshape(
                    self.height + self.height // 2, self.width
                ),
                format="yuv420p",
            )

            buffer.unmap(info)

            # 添加到队列
            if self._queue.full():
                try:
                    self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass

            self._queue.put_nowait(frame)

            return Gst.FlowReturn.OK

        except Exception as e:
            print(f"处理视频帧错误: {e}")
            return Gst.FlowReturn.ERROR

    async def recv(self):
        """接收下一帧。"""
        frame = await self._queue.get()
        if frame is None:
            self.stop()
            raise MediaStreamError
        frame.pts = int(frame.time * self.framerate)
        frame.time_base = fractions.Fraction(1, self.framerate)
        return frame


class USBVideoSourceFactory:
    """USB 摄像头视频源工厂。"""

    def __init__(
        self,
        device: str = "/dev/video0",
        width: int = 640,
        height: int = 480,
        framerate: int = 30,
    ):
        self.device = device
        self.width = width
        self.height = height
        self.framerate = framerate

    def create(self):
        """创建视频轨道。"""
        return USBVideoTrack(
            device=self.device,
            width=self.width,
            height=self.height,
            framerate=self.framerate,
        )
```

然后修改 `backend/webrtc_signaling.py`：

```python
# 修改导入
from .usb_video_track import USBVideoSourceFactory
```

### 第三步：修改视频轨道创建逻辑

在 `backend/webrtc_signaling.py` 的 `WebRTCPeerConnection.initialize()` 方法中：

```python
# 原来的代码：
# video_track = SimpleTestVideoSourceFactory().create()

# 改为：
video_track = USBVideoSourceFactory(
    device="/dev/video0",  # 或者你实际的摄像头设备
    width=640,
    height=480,
    framerate=30,
).create()
```

---

## 🧪 测试视频流

### 1. 测试 GStreamer 管道

```bash
# 测试 USB 摄像头
gst-launch-1.0 v4l2src device=/dev/video0 ! videoconvert ! autovideosink

# 如果看到视频输出，说明摄像头工作正常
```

### 2. 启动后端

```bash
source .venv/bin/activate
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

### 3. 启动前端

```bash
cd frontend
npm run dev
```

### 4. 测试 WebRTC 视频流

1. 打开浏览器访问：`http://localhost:5173`
2. 观察视频流是否正常显示

---

## 🎛️ 图传设备参数配置

如果你的图传设备需要特殊配置，可能需要调整以下参数：

### UDP RTP 模式（如果图传输出网络流）

如果你的地面端图传接收器输出的是 UDP RTP 流：

```
图传接收器 -> UDP:5000 端口 -> 后端
```

使用原有的 `GStreamerVideoTrack`，配置：

```python
video_track = GStreamerVideoSourceFactory(
    udp_port=5000,  # 图传接收器输出的 UDP 端口
    width=1920,
    height=1080,
    framerate=30,
).create()
```

### 摄像头分辨率调整

根据你的摄像头分辨率调整参数：

```python
# 常见分辨率：
# 640x480 (VGA)
# 1280x720 (720p)
# 1920x1080 (1080p)
# 3840x2160 (4K)

USBVideoSourceFactory(
    device="/dev/video0",
    width=1280,  # 根据摄像头调整
    height=720,
    framerate=30,
)
```

---

## 🐛 故障排查

### 问题 1：摄像头设备不存在

```bash
# 检查摄像头设备
ls -la /dev/video*

# 如果没有 /dev/video0，检查：
# 1. 摄像头是否连接
# 2. USB 驱动是否安装
# 3. 其他应用是否占用（如 Cheese、VLC）

# 重新插拔摄像头
lsusb | grep -i camera
```

### 问题 2：GStreamer 管道启动失败

```bash
# 检查 GStreamer 安装
gst-inspect-1.0 v4l2src

# 如果提示插件缺失，安装：
sudo apt-get install gstreamer1.0-plugins-good
sudo apt-get install gstreamer1.0-plugins-bad
sudo apt-get install gstreamer1.0-plugins-ugly

# 测试管道
gst-launch-1.0 v4l2src device=/dev/video0 ! fakesink
```

### 问题 3：WebRTC 视频流无法连接

```bash
# 检查后端日志
grep "WebRTC" backend_*.log

# 检查 ICE 收集
grep "ICE" backend_*.log

# 如果是 Docker 环境，使用 host 网络
docker run --network=host ...
```

### 问题 4：图传无信号

```bash
# 检查天空端
# 1. 供电是否正常
# 2. 摄像头是否正确连接
# 3. 图传发射器指示灯

# 检查地面端
# 1. 接收器是否通电
# 2. 天线是否连接
# 3. USB 采集卡是否识别

# 使用 VLC 测试图传信号
vlc v4l2:///dev/video0
```

---

## 📊 验证检查清单

使用图传设备/摄像头验证：

- [ ] 摄像头设备被识别 (`/dev/video0`)
- [ ] GStreamer 插件已安装
- [ ] GStreamer 管道测试成功
- [ ] 后端代码已修改为使用真实视频源
- [ ] 前端"连接视频"按钮可点击
- [ ] WebRTC 连接成功
- [ ] 视频流正常显示

---

## 🎯 下一步

完成摄像头接入后，你就可以：

1. ✅ 验证完整的视频流功能
2. ✅ 测试 WebRTC 延迟
3. ✅ 调整视频质量和分辨率
4. ✅ 为将来接入机器狗做好准备

当有机器狗后，只需：
1. 将摄像头安装到机器狗上
2. 天空端图传安装到机器狗上
3. 接入 MAVLink 设备
4. 切换配置 `MAVLINK_SOURCE=mavlink`

即可完成完整集成！

---

**相关文档**：
- [无机器狗硬件验证指南](./26_hardware_verification_without_dog.md)
- [部署测试指南](./24_deployment_testing_guide.md)
