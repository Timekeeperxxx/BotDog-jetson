# Windows GStreamer 硬件加速视频处理 - 安装配置指南

## 目标
在 Windows 上使用 GPU 硬件解码 H.265 视频流，实现 CPU 占用 <30%，无灰屏流畅播放。

---

## 一、GStreamer 安装

### 1. 下载 GStreamer for Windows (MSVC)

**推荐版本:** GStreamer 1.24.0 或更新版本

**下载地址:** https://gstreamer.freedesktop.org/download/

**需要安装的组件:**

#### 必装组件:
1. **gstreamer-1.0-msvc-x86_64.msi** (核心运行时)
   - 版本: 1.24.0 或更新
   - 架构: x86_64 (64位)

2. **gstreamer-1.0-devel-msvc-x86_64.msi** (开发包，如需编译 Python 绑定)
   - 版本: 与核心运行时一致
   - 架构: x86_64

### 2. 安装步骤

1. **运行安装程序:**
   ```
   右键 gstreamer-1.0-msvc-x86_64.msi -> 以管理员身份运行
   ```

2. **安装路径设置:**
   - 默认路径: `C:\gstreamer\1.0\msvc_x86_64`
   - **重要:** 不要修改路径，或记住自定义路径

3. **环境变量设置:**
   安装完成后，需要添加以下环境变量：

   ```
   GSTREAMER_1_0_ROOT_MSVC_X86_64=C:\gstreamer\1.0\msvc_x86_64
   ```

4. **添加到 PATH:**
   在系统环境变量 PATH 中添加:
   ```
   %GSTREAMER_1_0_ROOT_MSVC_X86_64%\bin
   ```

### 3. 验证安装

打开新的命令提示符（**必须重启终端以生效**）：

```cmd
gst-inspect-1.0 --version
```

预期输出:
```
GStreamer 1.24.0
```

验证关键插件:
```cmd
gst-inspect-1.0 d3d11h265dec
gst-inspect-1.0 x264enc
gst-inspect-1.0 udpsrc
```

如果都显示插件信息，说明安装成功。

---

## 二、Python 依赖安装

### 1. 更新 requirements.txt

在现有 `requirements.txt` 基础上添加以下依赖:

```txt
# OpenCV with GStreamer support (pip binary)
opencv-python>=4.8.0

# NumPy (OpenCV 依赖)
numpy>=1.24.0

# PyAV (VideoFrame 支持)
av>=11.0.0

# aiortc (WebRTC)
aiortc>=1.6.0
```

### 2. 安装命令

```bash
# 创建虚拟环境（推荐）
python -m venv venv
venv\Scripts\activate

# 升级 pip
python -m pip install --upgrade pip

# 安装依赖
pip install -r requirements.txt
```

### 3. 验证 OpenCV GStreamer 支持

创建测试脚本 `test_opencv_gst.py`:

```python
import cv2
import os

# 检查 GStreamer 支持
print(f"OpenCV 版本: {cv2.__version__}")
print(f"GStreamer 支持: {cv2.getBuildInformation().find('GStreamer') != -1}")

# 测试管道
pipeline = "videotestsrc ! videoconvert ! appsink"
cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)

if cap.isOpened():
    print("✅ GStreamer 管道测试成功")
    ret, frame = cap.read()
    if ret:
        print(f"✅ 成功读取测试帧，尺寸: {frame.shape}")
    cap.release()
else:
    print("❌ GStreamer 管道测试失败")
```

运行:
```bash
python test_opencv_gst.py
```

---

## 三、测试 GPU 硬件解码

### 1. 测试 H.265 硬件解码管道

创建测试脚本 `test_h265_decode.py`:

```python
import cv2
import time
import subprocess
import sys

# 测试管道字符串
pipeline = (
    "videotestsrc pattern=ball ! "
    "video/x-raw,width=1920,height=1080,framerate=30/1 ! "
    "x265enc ! "
    "h265parse ! "
    "d3d11h265dec ! "
    "videoconvert ! "
    "appsink"
)

print("=" * 80)
print("测试 H.265 硬件解码管道")
print("=" * 80)
print(f"管道: {pipeline}")
print("=" * 80)

try:
    cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)

    if not cap.isOpened():
        print("❌ 无法打开管道")
        sys.exit(1)

    print("✅ 管道打开成功")

    # 测试读取 100 帧
    frame_count = 0
    start_time = time.time()

    for i in range(100):
        ret, frame = cap.read()
        if not ret:
            print(f"❌ 读取第 {i} 帧失败")
            break
        frame_count += 1
        if i % 10 == 0:
            print(f"已读取 {i} 帧...")

    end_time = time.time()
    elapsed = end_time - start_time
    fps = frame_count / elapsed

    print(f"\n{'=' * 80}")
    print(f"✅ 测试完成!")
    print(f"{'=' * 80}")
    print(f"读取帧数: {frame_count}")
    print(f"耗时: {elapsed:.2f} 秒")
    print(f"平均 FPS: {fps:.2f}")
    print(f"{'=' * 80}")

    cap.release()

except Exception as e:
    print(f"❌ 测试失败: {e}")
    sys.exit(1)
```

运行测试:
```bash
python test_h265_decode.py
```

预期输出:
```
✅ 管道打开成功
已读取 0 帧...
已读取 10 帧...
...
✅ 测试完成!
读取帧数: 100
耗时: 3.3X 秒
平均 FPS: 30.XX
```

---

## 四、完整系统测试

### 1. 测试 UDP 接收 + H.265 解码

创建完整测试 `test_full_pipeline.py`:

```python
import cv2
import asyncio
import subprocess
import time

async def test_udp_stream():
    """
    测试 UDP H.265 流的硬件解码
    """
    pipeline = (
        "udpsrc port=5000 "
        'caps="application/x-rtp,media=video,encoding-name=H265,payload=96" '
        "! rtpjitterbuffer latency=100 do-retransmission=true "
        "! rtph265depay "
        "! h265parse "
        "! d3d11h265dec "
        "! videoconvert "
        "! video/x-raw,format=I420 "
        "! x264enc tune=zerolatency speed-preset=ultrafast "
        "! rtph264pay "
        "! appsink sync=false"
    )

    print("=" * 80)
    print("测试 UDP H.265 流接收")
    print("=" * 80)
    print(f"监听端口: 5000")
    print(f"解码器: d3d11h265dec")
    print("=" * 80)

    # 启动 GStreamer 管道
    cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)

    if not cap.isOpened():
        print("❌ 无法打开 UDP 管道")
        print("请确保相机正在推流到 127.0.0.1:5000")
        return False

    print("✅ UDP 管道打开成功，等待数据...")

    # 读取 100 帧进行测试
    frame_count = 0
    start_time = time.time()

    try:
        for i in range(100):
            ret, frame = cap.read()
            if not ret:
                print(f"⚠️  未收到第 {i} 帧，可能等待流...")
                await asyncio.sleep(0.1)
                continue

            frame_count += 1
            if i % 10 == 0:
                print(f"✅ 已接收 {i} 帧，尺寸: {frame.shape}")

    except KeyboardInterrupt:
        print("\n⚠️  测试被用户中断")

    finally:
        cap.release()

    end_time = time.time()
    elapsed = end_time - start_time

    if frame_count > 0:
        fps = frame_count / elapsed
        print(f"\n{'=' * 80}")
        print(f"✅ 测试完成!")
        print(f"{'=' * 80}")
        print(f"接收帧数: {frame_count}")
        print(f"耗时: {elapsed:.2f} 秒")
        print(f"平均 FPS: {fps:.2f}")
        print(f"{'=' * 80}")
        return True
    else:
        print("\n❌ 未接收到任何帧，请检查:")
        print("1. 相机是否正在推流")
        print("2. RTSP 地址是否正确: rtsp://192.168.144.25:8554/main.264")
        print("3. 网络连接是否正常")
        return False

if __name__ == "__main__":
    asyncio.run(test_udp_stream())
```

### 2. 运行测试

首先确保相机正在推流，然后运行:

```bash
python test_full_pipeline.py
```

---

## 五、集成到现有系统

### 1. 使用新的硬件加速视频轨道

在你的 `main.py` 或 WebRTC 相关代码中，替换:

```python
# 旧版本
from backend.video_track import GStreamerVideoSourceFactory

# 新版本（硬件加速）
from backend.video_track_hw import GStreamerVideoSourceFactory
```

### 2. 启动测试

```bash
python backend/main.py
```

观察日志输出，应该看到:
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

## 六、性能监控

### 1. 监控 CPU/GPU 占用

使用 Windows 任务管理器或性能监视器:

```powershell
# 启动性能监视器
perfmon
```

添加计数器:
- Processor % Processor Time (CPU)
- GPU Engine -> * -> Utilization Percentage

### 2. 目标指标

- **CPU 占用:** <30% (单核心)
- **GPU 占用:** 10-20% (视频解码)
- **帧率:** 稳定 30fps
- **延迟:** <100ms
- **灰屏:** 0次

---

## 七、故障排查

### 问题 1: OpenCV 不支持 GStreamer

**症状:** `test_opencv_gst.py` 报错 "GStreamer support: False"

**解决方案:**

1. **检查 GStreamer 环境变量:**
   ```cmd
   echo %GSTREAMER_1_0_ROOT_MSVC_X86_64%
   ```

2. **确保 PATH 包含 GStreamer bin:**
   ```cmd
   echo %PATH% | findstr gstreamer
   ```

3. **重新安装 OpenCV:**
   ```bash
   pip uninstall opencv-python
   pip install opencv-python
   ```

### 问题 2: 缺少 d3d11h265dec 插件

**症状:** `gst-inspect-1.0 d3d11h265dec` 报错

**解决方案:**

1. **确认安装了 gst-plugins-bad:**
   ```cmd
   gst-inspect-1.0 | findstr d3d11
   ```

2. **重新安装 GStreamer，确保选择完整安装:**
   - 运行安装程序
   - 选择 "Complete" 安装类型

3. **验证显卡驱动:**
   - NVIDIA: 更新到最新驱动
   - AMD: 更新到最新驱动
   - Intel: 更新到最新驱动

### 问题 3: 端口被占用

**症状:** 管道启动失败，提示端口被占用

**解决方案:**

```cmd
# 查找占用端口的进程
netstat -ano | findstr :5000

# 终止进程（替换 PID）
taskkill /PID <PID> /F
```

### 问题 4: 灰屏/花屏

**症状:** 能接收流但画面异常

**解决方案:**

1. **增加抖动缓冲:**
   ```python
   # 修改 pipeline_str
   "! rtpjitterbuffer latency=200 do-retransmission=true "
   ```

2. **检查网络质量:**
   ```cmd
   ping 192.168.144.25
   ```

3. **验证编码格式:**
   - 确认相机输出是 H.265 (不是 H.264)
   - 使用 VLC 播放 RTSP 流验证

---

## 八、环境变量完整配置

创建批处理文件 `setup_env.bat`:

```batch
@echo off
echo 设置 GStreamer 环境变量...

REM GStreamer Root
setx GSTREAMER_1_0_ROOT_MSVC_X86_64 "C:\gstreamer\1.0\msvc_x86_64" /M

REM 添加到 PATH
setx PATH "%PATH%;C:\gstreamer\1.0\msvc_x86_64\bin" /M

REM Python 虚拟环境（可选）
setx VIRTUAL_ENV "D:\ACode\Project\BOTDOG\BotDog\venv" /M

echo 环境变量设置完成!
echo 请重启命令提示符以生效
pause
```

右键 -> 以管理员身份运行

---

## 九、快速启动脚本

创建 `start_video.bat`:

```batch
@echo off
echo 启动视频处理系统...

REM 激活虚拟环境
call venv\Scripts\activate.bat

REM 启动系统
python backend/main.py

pause
```

双击运行即可启动系统。

---

## 十、总结

### 安装清单:
- [x] GStreamer 1.24.0 (MSVC x86_64)
- [x] 环境变量配置完成
- [x] OpenCV with GStreamer 支持
- [x] Python 依赖安装完成
- [x] GPU 驱动更新到最新

### 测试清单:
- [x] gst-inspect-1.0 d3d11h265dec 成功
- [x] test_opencv_gst.py 通过
- [x] test_h265_decode.py 通过
- [x] test_full_pipeline.py 通过

### 性能目标:
- [x] CPU 占用 <30%
- [x] GPU 硬件解码正常
- [x] 1080P @ 30fps 流畅
- [x] 无灰屏无花屏

完成以上步骤后，你的系统就能在 Windows 上使用 GPU 硬件加速解码 H.265 视频流了！
