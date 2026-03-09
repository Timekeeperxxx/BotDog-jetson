# ✅ Pipeline 语法错误已修复

## 🐛 问题原因
在 `video_track_native.py` 第 101 行，`video/x-raw` 的 caps 字符串**缺少了 `f` 前缀**：

```python
# ❌ 错误（缺少 f 前缀）
'! video/x-raw,format=I420,width={self.width},height={self.height},framerate={self.framerate}/1 '
```

导致 GStreamer 收到的字符串是：
```
video/x-raw,format=I420,width={self.width},height={self.height},framerate={self.framerate}/1
```

而不是：
```
video/x-raw,format=I420,width=1920,height=1080,framerate=30/1
```

## ✅ 修复后的代码

```python
# ✅ 正确（添加了 f 前缀）
f'! video/x-raw,format=I420,width={self.width},height={self.height},framerate={self.framerate}/1 '
```

## 📋 完整的 Pipeline（修复后）

```
gst-launch-1.0 -q -e
udpsrc port=5000
caps="application/x-rtp,media=video,encoding-name=H264,payload=96"
! rtpjitterbuffer latency=100 do-retransmission=true
! rtph264depay
! h264parse
! d3d11h264dec
! videoconvert
! video/x-raw,format=I420,width=1920,height=1080,framerate=30/1
! fdsink fd=1 sync=false
```

## 🎯 验证清单

### GStreamer 应该能正常启动：
- ✅ 变量正确解析（width=1920, height=1080, framerate=30）
- ✅ caps 字符串格式正确
- ✅ 不再有 "could not parse caps" 错误

### 后端终端应该看到：
```
启动 H.264 硬件解码...
[OK] GStreamer 进程已启动 (PID: xxxx)
[读取线程] 开始疯狂读取 stdout...
[GPU Decode] Received Frame #1 from RTX 3060
[GPU Decode] Received Frame #2 from RTX 3060
...
```

### 不应该再看到：
- ❌ `could not parse caps "video/x-raw,format=I420,width={self.width}...`
- ❌ `returncode=1`
- ❌ WebRTC 连接 1006 错误

---

**现在可以测试了！🚀**
