# PyGObject 安装指南 - Windows

## 问题

PyGObject 需要 C++ 编译器才能从源码安装，但你的系统没有安装。

## 解决方案：使用预编译的 wheel

### 选项 1: 使用 Christoph Gohlke 的预编译 wheel（推荐）

1. **访问 PyGObject wheel 下载页面**
   https://www.lfd.uci.edu/~gohlke/pythonlibs/#pygobject

2. **下载对应 Python 3.10 的版本**
   - 文件名类似: `PyGObject-3.42.2-cp310-cp310-win_amd64.whl`
   - `cp310` = Python 3.10
   - `win_amd64` = Windows 64-bit

3. **安装 wheel**
   ```cmd
   cd D:\ACode\Project\BOTDOG\BotDog
   venv\Scripts\activate
   pip install PyGObject-3.42.2-cp310-cp310-win_amd64.whl
   ```

### 选项 2: 使用 conda（如果你有 conda）

```cmd
conda install pygobject
```

### 选项 3: 使用 MSYS2（更复杂）

1. 安装 MSYS2: https://www.msys2.org/
2. 在 MSYS2 中安装 PyGObject
3. 配置环境变量

---

## 快速测试

安装后运行测试：

```cmd
venv\Scripts\activate
python test_gst_bindings.py
```

预期输出：
```
✓ Step 1: imported gi
✓ Step 2: required GStreamer 1.0
✓ Step 3: imported Gst
✓ Step 4: initialized GStreamer

✅ SUCCESS! GStreamer version: 1.28.1

Testing pipeline creation...
✓ Created pipeline: videotestsrc ! fakesink
✅ All tests passed!
```

---

## 当前状况

### ✅ 已确认工作
- GStreamer 1.28.1 CLI 完全正常
- H.265 硬件解码 FPS 37.67 (优秀!)
- Python 3.10 环境已配置
- 所有 WebRTC 依赖已安装

### ⚠️ 只差一步
- PyGObject 安装即可完成全部配置

---

## 临时方案

如果不想安装 PyGObject，可以先测试 UDP 接收：

```cmd
gst-launch-1.0 -v udpsrc port=5000 caps="application/x-rtp,media=video,encoding-name=H265,payload=96" ! rtpjitterbuffer latency=100 do-retransmission=true ! rtph265depay ! h265parse ! d3d11h265dec ! videoconvert ! fakesink
```

这可以验证：
1. 相机是否正在推流
2. UDP 接收是否正常
3. H.265 硬件解码是否工作

---

**你想继续安装 PyGObject 吗？还是先测试 UDP 接收？**
