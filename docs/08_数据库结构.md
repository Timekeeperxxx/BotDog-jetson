# BotDog 数据库表结构（SQLite）

来源：`db/schema.sql`（v1）

## 全局设置

- 启用外键：`PRAGMA foreign_keys = ON;`
- WAL 模式：`PRAGMA journal_mode = WAL;`

## 表关系概览

- `inspection_tasks` 1 — N `telemetry_snapshots`
- `inspection_tasks` 1 — N `anomaly_evidence`
- `inspection_tasks` 1 — N `operation_logs`（可为空，删除任务时日志 `task_id` 置空）
- `config` 独立表（持久化可修改配置）

---

## 1) `inspection_tasks`（巡检任务）

**用途**：一次巡检任务/会话的元数据与生命周期管理。

### 字段

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `task_id` | INTEGER | PK, AUTOINCREMENT | 任务 ID |
| `task_name` | TEXT | NOT NULL | 任务名称 |
| `status` | TEXT | NOT NULL, DEFAULT `'running'`, CHECK | `running/completed/stopped/failed` |
| `started_at` | TEXT | NOT NULL | ISO8601 |
| `ended_at` | TEXT |  | ISO8601 |
| `created_at` | TEXT | NOT NULL, DEFAULT `strftime(...)` | 创建时间（UTC ISO8601） |
| `updated_at` | TEXT | NOT NULL, DEFAULT `strftime(...)` | 更新时间（UTC ISO8601） |

### 索引

- `idx_inspection_tasks_status`：`(status)`
- `idx_inspection_tasks_started_at`：`(started_at)`

---

## 2) `telemetry_snapshots`（遥测快照/降采样留存）

**用途**：保存遥测快照（位置/姿态/电量），用于轨迹回放、历史查询与审计。

### 字段

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `snapshot_id` | INTEGER | PK, AUTOINCREMENT | 快照 ID |
| `task_id` | INTEGER | NOT NULL, FK → `inspection_tasks(task_id)`, ON DELETE CASCADE | 归属任务 |
| `timestamp` | TEXT | NOT NULL | ISO8601（建议写入 UTC） |
| `gps_lat` | REAL |  | 纬度 |
| `gps_lon` | REAL |  | 经度 |
| `gps_alt` | REAL |  | 高度 |
| `hdg` | REAL |  | 航向角 |
| `att_pitch` | REAL |  | 俯仰 |
| `att_roll` | REAL |  | 横滚 |
| `att_yaw` | REAL |  | 偏航 |
| `battery_voltage` | REAL |  | 电压 |
| `battery_remaining_pct` | INTEGER | CHECK `0..100` | 电量百分比 |
| `created_at` | TEXT | NOT NULL, DEFAULT `strftime(...)` | 入库时间 |

### 索引

- `idx_telemetry_snapshots_task_time`：`(task_id, timestamp)`
- `idx_telemetry_snapshots_time`：`(timestamp)`

---

## 3) `anomaly_evidence`（异常证据链/抓拍与告警）

**用途**：保存告警事件与证据链（图片路径、坐标、文本说明等）。

### 字段

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `evidence_id` | INTEGER | PK, AUTOINCREMENT | 证据 ID |
| `task_id` | INTEGER | NOT NULL, FK → `inspection_tasks(task_id)`, ON DELETE CASCADE | 归属任务 |
| `event_type` | TEXT | NOT NULL | 事件类型（如 `thermal_high`） |
| `event_code` | TEXT |  | 事件码（如 `E_THERMAL_HIGH`） |
| `severity` | TEXT | NOT NULL, DEFAULT `'CRITICAL'`, CHECK | `INFO/WARN/ERROR/CRITICAL` |
| `message` | TEXT |  | 人可读信息 |
| `confidence` | REAL | CHECK `NULL or 0..1` | 置信度（可空） |
| `file_path` | TEXT | NOT NULL | 抓拍文件路径 |
| `image_url` | TEXT |  | 可对外访问 URL（可空） |
| `gps_lat` | REAL |  | 纬度（可空） |
| `gps_lon` | REAL |  | 经度（可空） |
| `created_at` | TEXT | NOT NULL, DEFAULT `strftime(...)` | 记录创建时间 |

### 索引

- `idx_anomaly_evidence_task_time`：`(task_id, created_at)`
- `idx_anomaly_evidence_event_type`：`(event_type)`

---

## 4) `operation_logs`（操作与系统日志/审计）

**用途**：记录系统事件与审计日志；可关联任务，任务删除后日志保留但 `task_id` 置空。

### 字段

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `log_id` | INTEGER | PK, AUTOINCREMENT | 日志 ID |
| `level` | TEXT | NOT NULL, CHECK | `INFO/WARN/ERROR/CRITICAL` |
| `module` | TEXT | NOT NULL, CHECK | `BACKEND/UI/MEDIA/EDGE` |
| `message` | TEXT | NOT NULL | 日志内容 |
| `task_id` | INTEGER | FK → `inspection_tasks(task_id)`, ON DELETE SET NULL | 可空关联任务 |
| `created_at` | TEXT | NOT NULL, DEFAULT `strftime(...)` | 记录时间 |

### 索引

- `idx_operation_logs_time`：`(created_at)`
- `idx_operation_logs_level`：`(level)`
- `idx_operation_logs_task`：`(task_id)`

---

## 5) `config`（配置持久化）

**用途**：持久化运行时可修改的配置项，并提供默认值 seed（幂等）。

### 字段

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `key` | TEXT | PK | 配置键 |
| `value` | TEXT | NOT NULL | 配置值（文本形式存储） |
| `value_type` | TEXT | NOT NULL, DEFAULT `'string'`, CHECK | `string/int/float/bool/json` |
| `is_hot_reload` | INTEGER | NOT NULL, DEFAULT 0, CHECK | 0/1，是否支持热更新 |
| `updated_by` | TEXT |  | 更新人（预留） |
| `updated_at` | TEXT | NOT NULL, DEFAULT `strftime(...)` | 更新时间 |

### 索引

- `idx_config_updated_at`：`(updated_at)`

### 默认配置（Seed）

在 `schema.sql` 中使用 `INSERT OR IGNORE` 写入以下默认键值（幂等）：

- `thermal_threshold=60.0 (float, hot)`
- `heartbeat_timeout=3.0 (float)`
- `control_rate_limit_hz` 已废弃（FT24 直连后不再使用）。
- `ws_max_clients_per_ip=5 (int)`
- `video_watchdog_timeout_s=2.0 (float, hot)`
- `ui_alert_ack_timeout_s=60 (int, hot)`
- `telemetry_display_hz=15 (int, hot)`
- `snapshot_retention_days=30 (int)`
- `max_snapshot_disk_usage_gb=50 (int)`
- `telemetry_retention_days=90 (int)`

