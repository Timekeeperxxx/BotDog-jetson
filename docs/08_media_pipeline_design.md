# 媒体管线与 WebRTC 设计说明 (Media Pipeline Design)

## 1. 设计目标

* 实现 4K H.264 低延迟推流，端到端时延 < 200ms。
* 保证在弱网/丢包场景下，媒体管线可自动恢复而不“卡死在最后一帧”。
* 使 GStreamer 管线设计在实现前就确定关键参数，减少试错。

## 2. 总体拓扑

### 2.1 边缘端 (Jetson / 机器狗)

* 视频源：`/dev/video0`（可替换为 CSI/RTSP 等）。
* 编码：硬件 H.264 编码器（优先 `nvv4l2h264enc`）。
* 输出：通过 `webrtcbin` 与地面 WebRTC 信令服务建立会话。

### 2.2 地面端 (GStreamer + WebRTC 信令)

* 接收来自边缘端的 WebRTC 媒体轨道。
* 将轨道通过 WebRTC 协议推送至浏览器 `<video>` 标签。
* 负责 ICE、SDP 协商和弱网反馈（PLI/FIR）。

## 3. 边缘端 GStreamer 管线草案

> 实际命令行/代码可在实现阶段根据具体硬件再做细化，此处强调结构与关键参数。

典型推流管线（伪代码形式）：

```bash
gst-launch-1.0 \
  v4l2src device=/dev/video0 ! \
  video/x-raw,framerate=30/1,width=3840,height=2160 ! \
  queue max-size-buffers=30 leaky=downstream ! \
  videoconvert ! \
  nvv4l2h264enc iframeinterval=30 bitrate=12000000 preset-level=1 insert-sps-pps=true ! \
  h264parse config-interval=-1 ! \
  rtph264pay pt=96 config-interval=1 ! \
  webrtcbin name=sendonly
```

关键点：

* 帧率 `30fps`，分辨率 4K，可根据实际场景降为 1080p 以换取更稳定延迟。
* `bitrate` 初始值 12Mbps，可配合网络测试后再微调。
* `iframeinterval=30`，保证约每 1 秒出一个关键帧，便于快速恢复画面。

## 4. 地面端 WebRTC 服务逻辑

### 4.1 信令通道

* 端口与协议：`wss://<host>:8443`（或共用 8000 端口，由反向代理分流）。
* 与后端 FastAPI 的关系：
  * 可作为单独的进程/容器运行，通过 HTTP/WS 与 FastAPI 交换状态和事件。
  * 或嵌入后端进程中，由 FastAPI 负责信令 HTTP API，其内部调用 GStreamer。

### 4.2 典型信令流程

1. 浏览器前端创建 WebRTC PeerConnection，向后端发起 “create-offer” 请求。
2. WebRTC 信令服务将 SDP offer 传递给 GStreamer `webrtcbin`。
3. `webrtcbin` 生成 SDP answer 并通过信令通道回传给前端。
4. ICE 候选在双方之间持续交换，直至连接建立。
5. 前端 `<video>` 标签挂载接收到的 MediaStream。

## 5. 弱网与错误恢复策略

### 5.1 Jitter Buffer 与丢包

* `webrtcbin` 自带抖动缓冲与丢包掩护，可通过参数适度增大：
  * `latency` 适度设置（如 100ms 级别），在延迟与平滑度之间取舍。

### 5.2 关键帧请求 (PLI/FIR)

* 当前端检测到“画面长期静止不动”或 RTCP 上报质量下降时：
  * 向远端发送 PLI/FIR，要求重新发送 I 帧。
* 可通过 WebSocket 将“画面异常”事件反馈给后端，供日志与告警使用。

### 5.3 管线看门狗 (Watchdog)

在后端/媒体服务中实现一个简易的看门狗逻辑：

* 维护“最近一次成功接收 RTP 包的时间戳”。
* 如超过 2 秒未收到数据：
  * 认为当前 GStreamer 管线已冻结，主动销毁并重新创建管线。
  * 通过 WebSocket 向前端广播 `VIDEO_STATUS` 消息（如 `reconnecting`）。

## 6. 关键参数建议表

| 参数名                     | 建议初始值          | 说明                                      |
| -------------------------- | ------------------- | ----------------------------------------- |
| 分辨率 (width x height)    | 3840 x 2160 或 1920 x 1080 | 视现场带宽调整                           |
| 帧率 (fps)                | 30                  | 若网络不稳可尝试降至 25                  |
| 编码码率 (bitrate)        | 8–12 Mbps           | 高动态场景建议略高                        |
| GOP / 关键帧间隔          | 30 帧               | ≈ 每秒 1 个关键帧                         |
| Jitter Buffer latency     | 100–150 ms          | 延迟 vs 抗抖动的平衡点                   |
| Watchdog 超时时间         | 2 秒                | 超过则重启管线                            |

## 7. 调试与排障建议

* 使用 `gst-launch-1.0` 在无应用代码的情况下单独拼接和验证管线。
* 借助 `webrtc-internals`（Chrome 内置）观察端到端码率、丢包、RTT 指标。
* 当端到端延迟超标时：
  * 先检查编码端是否缓存过多（编码缓冲、队列长度）。
  * 再检查网络 (RTT / 丢包) 与浏览器解码队列。

