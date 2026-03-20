# AI 抓拍时间与档案库改进计划

## 目标
- 修正抓拍与证据记录的时间戳格式，前端显示为本地时间不偏移。
- 档案库展示数据库中的全部抓拍记录，而不是仅当前会话告警。
- 在后端 .env 中补齐 AI 相关配置项（缺失即补）。

## 方案
1. **后端时间戳修正**
   - 在 [backend/alert_service.py](../backend/alert_service.py) 中，证据入库 `created_at` 改用 `utc_now_iso()`（带 `Z` 的 ISO8601），避免前端按本地时区误解析。
   - 保持告警广播 `timestamp` 仍为 `utc_now_iso()`。

2. **档案库数据源调整**
   - 在 [frontend/src/IndustrialConsoleComplete.tsx](../frontend/src/IndustrialConsoleComplete.tsx) 的“档案库”页签中，新增调用 `/api/v1/evidence` 拉取历史证据列表。
   - 以证据列表渲染卡片（优先使用 `image_url`），支持搜索过滤；不再仅依赖 WebSocket 的 `alerts` 内存列表。
   - 时间显示使用 `created_at`（若 `timestamp` 不存在则回退）。

3. **补齐后端 .env 配置**
   - 在 [backend/.env](../backend/.env) 中补齐缺失的 `AI_*` 配置项与默认值（若已存在则不改动）。

## 影响文件
- [backend/alert_service.py](../backend/alert_service.py)
- [frontend/src/IndustrialConsoleComplete.tsx](../frontend/src/IndustrialConsoleComplete.tsx)
- [backend/.env](../backend/.env)

## 验证方式
- 触发一条抓拍告警后，在“档案库”中可看到历史图片与正确时间。
- 关闭页面再打开，仍能从 `/api/v1/evidence` 看到历史记录。
- 前端时间显示与本地时间一致（无 UTC 偏移）。
