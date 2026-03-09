# 配置项矩阵与参数约定 (Configuration Matrix)

## 1. 目的

集中管理系统中的关键配置项（阈值、频率、限流等），避免参数分散在多份文档和代码中难以维护。

字段说明：

* **Key**：配置项在代码/配置文件中的名称。
* **默认值**：系统缺省值。
* **范围/类型**：允许取值范围或类型说明。
* **修改角色**：允许修改该配置的用户角色（Operator/Admin）。
* **是否热更新**：修改后是否可在不停机情况下生效。

## 2. 后端核心配置项

| Key                    | 默认值  | 范围/类型                 | 修改角色 | 是否热更新 | 说明 |
|------------------------|---------|---------------------------|----------|------------|------|
| `thermal_threshold`    | `60.0`  | Float, 30.0–120.0        | Admin    | 是         | 触发高温告警与 `ALERT_RAISED` 的温度阈值 (°C)。|
| `heartbeat_timeout`    | `3.0`   | Float, 1.0–10.0          | Admin    | 否         | 超过该秒数未收到 `HEARTBEAT` 判定为失联。|
| `control_rate_limit_hz`| `20`    | Int, 5–50                | Admin    | 是         | `/ws/control` 单连接最大控制指令频率 (Hz)。|
| `ws_max_clients_per_ip`| `5`     | Int, 1–20                | Admin    | 否         | 单 IP 允许维持的最大 WebSocket 连接数。|
| `log_file_rotation`    | `500MB` | 字符串 (Loguru 语法)     | Admin    | 否         | 日志文件滚动大小阈值。|
| `log_file_retention`   | `10 days`| 字符串 (Loguru 语法)    | Admin    | 否         | 日志文件保留时间。|
| `video_watchdog_timeout_s`| `2.0`| Float, 1.0–10.0          | Admin    | 是         | 媒体看门狗超时时间，超出则重启 GStreamer 管线。|

## 3. 前端/客户端相关配置

| Key                        | 默认值  | 范围/类型            | 修改角色 | 是否热更新 | 说明 |
|----------------------------|---------|----------------------|----------|------------|------|
| `ui_alert_ack_timeout_s`   | `60`    | Int, 10–600          | Admin    | 是         | 告警未被确认时 UI 保持高亮/提示音的最小学时长。|
| `telemetry_display_hz`     | `15`    | Int, 5–30            | Admin    | 是         | 前端 HUD 刷新频率（可低于后端广播频率以减负）。|
| `map_tile_provider`        | `null`  | 字符串/URL           | Admin    | 否         | 地图底图服务地址（如后续集成在线地图时使用）。|
| `ui_lang`                  | `zh-CN` | `zh-CN` / `en-US`    | Operator | 是         | 控制终端界面的显示语言。|
| `ui_theme`                 | `dark`  | `dark` / `light`     | Operator | 是         | UI 主题风格。|

## 4. 存储与清理策略

| Key                              | 默认值    | 范围/类型         | 修改角色 | 是否热更新 | 说明 |
|----------------------------------|-----------|-------------------|----------|------------|------|
| `snapshot_retention_days`       | `30`      | Int, 7–365        | Admin    | 否         | 抓拍图片保留天数，到期可通过后台任务清理。|
| `max_snapshot_disk_usage_gb`    | `50`      | Int, 10–500       | Admin    | 否         | 抓拍目录最大允许磁盘占用，超过需触发清理策略。|
| `telemetry_retention_days`      | `90`      | Int, 30–365       | Admin    | 否         | 结构化遥测记录在 SQLite 中的保留时间。|

## 5. 配置存储与下发方式建议

* 建议集中存放于：
  * 后端：`.env` + 数据库 `config` 表（持久化可修改项）。
  * 前端：`.env`（构建时静态配置） + WebSocket/HTTP 下发的运行时配置。
* 可考虑提供：
  * `GET /api/v1/config`：查询当前生效配置（脱敏后）。
  * `POST /api/v1/config`：由 Admin 角色修改部分配置项（已在后端协议文档中定义）。

