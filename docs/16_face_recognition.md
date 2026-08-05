# 人脸身份显示

## 技术方案

当前实现使用 OpenCV DNN 的 YuNet（人脸检测）与 SFace（对齐、128 维特征）。它与现有 AIWorker 同进程运行，复用现有 RTSP 解码帧和轻量 IOU 轨迹，不新增 Docker、systemd 或视频拉流服务。

识别结果只写入 `TRACK_OVERLAY` / `POSE_OVERLAY` 的 `identity_id`、`display_name`、`face_status`、`face_score` 字段。它不会修改 `StrangerPolicy`、自动跟踪、驱离或机器人控制决策。

## 数据与权限

`face_identities` 保存显示姓名、备注和启用状态；`face_templates` 保存归一化 float32 特征、维度、模型版本和质量分。注册原图在请求内存中解码，提取特征后立即丢弃。人员库读写与模板上传/删除仅限 admin，运行状态允许 viewer 读取。

接口：

- `GET/POST /api/v1/face-identities`
- `GET/PATCH/DELETE /api/v1/face-identities/{id}`
- `POST /api/v1/face-identities/{id}/templates`
- `DELETE /api/v1/face-identities/{id}/templates/{template_id}`
- `GET /api/v1/face-recognition/status`

## 部署

安装依赖后执行 `scripts/download-face-models.sh`。默认模型目录是 `/home/jetson/Projects/Models`，脚本会核验 SHA256。模型来自 OpenCV 官方 model zoo：

- [YuNet `face_detection_yunet_2023mar.onnx`](https://github.com/opencv/opencv_zoo/blob/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx)
- [SFace `face_recognition_sface_2021dec.onnx`](https://github.com/opencv/opencv_zoo/blob/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx)

默认检测阈值为 0.80，余弦身份匹配阈值为 0.45，连续三次命中后显示确认姓名。每个人员最多五个模板；图片最大 8MB/1200 万像素，格式限 JPEG、PNG、WebP，且必须恰好包含一张最小边长 64px 的人脸。

后台注册会先应用手机照片的 EXIF 方向，将超大图片等比例缩放到最长边 1920px，并在没有检测结果时尝试四个方向及注册专用阈值 `FACE_ENROLL_DETECT_THRESHOLD`。该宽松阈值不会影响实时视频检测。

为保证没有巡检任务时也能在操作台持续看到识别结果，需要配置 `AI_ENABLED=true`、`AI_CONTINUOUS_DETECTION_ENABLED=true` 和 `FACE_RECOGNITION_ENABLED=true`。视觉页面首次打开时默认显示 AI 叠层；用户仍可通过画面底部的眼睛按钮关闭，选择会保存在浏览器本地。

可在项目根目录运行 `.venv/bin/python scripts/validate-face-recognition.py`，使用仓库内的两张合成人脸和真实 ONNX 模型验证已知人员命中、未知人员拒绝及模板删除后立即失效。

WebSocket 鉴权本次按产品决定暂缓，沿用现有 `/ws/event` 行为。
