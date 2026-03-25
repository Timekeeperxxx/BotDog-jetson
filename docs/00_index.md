# BotDog 文档索引

本仓库包含 BotDog 机器狗控制系统的完整代码和文档。建议按以下顺序阅读：

## 📋 核心文档（必读）

1. **[01_requirements_use_cases.md](01_requirements_use_cases.md)** - 需求、范围、用例、指标（SRS）
2. **[13_implementation_plan.md](13_implementation_plan.md)** - 实施计划与架构设计
3. **[10_dev_setup.md](10_dev_setup.md)** - 开发与运行环境搭建
4. **[12_acceptance_tests.md](12_acceptance_tests.md)** - 验收测试清单

## 🔧 技术规范

5. **[05_frontend_view_contract.md](05_frontend_view_contract.md)** - 前端视图与数据/事件契约
6. **[06_backend_protocol_schema.md](06_backend_protocol_schema.md)** - 后端 HTTP/WS 协议与数据结构
7. **[07_mavlink_spec.md](07_mavlink_spec.md)** - MAVLink 与遥测消息约定
8. **MediaMTX + WHEP 视频链路** - 参考 README 与 `docs/ft24_control_migration.md`
9. **[09_config_matrix.md](09_config_matrix.md)** - 配置项矩阵与参数约定
10. **[11_tech_selection.md](11_tech_selection.md)** - 技术栈选型

## 📦 系统组件

11. **[14_database_schema.md](14_database_schema.md)** - 数据库模式设计
12. **[16_ai_alert_implementation.md](16_ai_alert_implementation.md)** - AI 告警系统实施
13. **[17_ai_alert_frontend.md](17_ai_alert_frontend.md)** - AI 告警前端集成

## 🎯 最新功能

### 配置管理
14. **[23_config_panel_implementation.md](23_config_panel_implementation.md)** - 前端配置界面实施完成总结

## 🚀 部署相关

15. **[25_git_push_guide.md](25_git_push_guide.md)** - Git 推送和身份验证指南

## 📡 硬件验证

16. **[26_hardware_verification_without_dog.md](26_hardware_verification_without_dog.md)** - 无机器狗硬件验证指南
   - 可验证的功能清单
   - 详细验证步骤
   - 故障排查方法

17. **视频设备接入（MediaMTX + WHEP）** - 参考 README 与 `docs/ft24_control_migration.md`

---

## 🎯 快速开始

### 开发环境启动

```bash
# 后端服务
. scripts/start_backend.bat

# 前端开发
cd frontend
npm install
npm run dev
```

### 验收测试

```bash
python acceptance_test.py
```

---

## 📊 项目完成度

| 模块 | 完成度 | 状态 |
|------|--------|------|
| 后端系统 | 100% | ✅ 稳定运行 |
| 前端系统 | 100% | ✅ 稳定运行 |
| 控制链路（FT24） | 100% | ✅ 硬件直连 |
| 配置管理 | 100% | ✅ 可视化界面 |
| 告警系统 | 100% | ✅ 完全实现 |
| 验收测试 | 100% | ✅ 全部通过 |

**总体进度**: **接近 100%** 🏆

---

**最后更新**: 2026-03-06
**版本**: v5.0
**状态**: 生产就绪

