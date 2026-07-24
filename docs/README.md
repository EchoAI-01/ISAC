# ISAC 文档导航

根目录只保留 `README.md`(项目总览)与 `AGENTS.md`(AI 协作约定)。所有说明性文档集中在本 `docs/` 目录。

## 设计与规范

| 文档 | 用途 |
|------|------|
| [../README.md](../README.md) | 项目总览与快速介绍 |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | 多 Agent 架构蓝图 v3.0 + ADR |
| [SPECIFICATION.md](./SPECIFICATION.md) | 数据模型与接口契约 (规范冻结) |
| [DEVELOP.md](./DEVELOP.md) | 开发规范 (目录/导入/命名/测试) |
| [REQUIREMENTS.md](./REQUIREMENTS.md) | 统一需求清单 |
| [../AGENTS.md](../AGENTS.md) | Agent 协作指南 (根目录约定文件) |

## 计划与进度

| 文档 | 用途 |
|------|------|
| [DEVELOPMENT_PLAN.md](./DEVELOPMENT_PLAN.md) | 开发 SOW / TODO 清单 / 下一步计划 |
| [PROGRESS.md](./PROGRESS.md) | 各节点唯一进度事实源 |
| [CODE_REVIEW_REPORT.md](./CODE_REVIEW_REPORT.md) | 复审报告 (可运行性与需求完成度) |
| [CHANGELOG.md](./CHANGELOG.md) | 变更记录 |

## 专项施工图

| 文档 | 覆盖系统 |
|------|---------|
| [HUMANLIKE_RUNTIME.md](./HUMANLIKE_RUNTIME.md) | 拟人化运行时 (Gating/TurnScheduler/Prompt) |
| [MEMORY_DESIGN.md](./MEMORY_DESIGN.md) | 记忆系统 (Storage/Pipeline/Injector) |
| [ROUTING_AND_AGENT_MESH.md](./ROUTING_AND_AGENT_MESH.md) | 路由与 Agent Mesh (Router/Bus/ACL) |
| [PLUGIN_COMPATIBILITY.md](./PLUGIN_COMPATIBILITY.md) | 插件兼容策略 (AstrBot/MaiBot/Native) |
| [CONTROL_PLANE_SPEC.md](./CONTROL_PLANE_SPEC.md) | 控制面规范 (Admin API/MCP/Webhooks) |

## 使用文档

| 文档 | 用途 |
|------|------|
| [使用文档](./usage.md) | 快速开始、配置详解、运行、维护 |
| [Docker 部署](./deployment.md) | 容器化部署、数据持久化、生产建议 |
| [API 文档](./api.md) | Admin REST API 端点与示例 |
| [插件开发指南](./plugin_development.md) | 三种插件格式开发 (Native/AstrBot/MaiBot) |
| [控制面自动化指南](./control_automation.md) | REST API / MCP / Webhooks 自动化集成 |

## 阅读建议

- **新加入开发者**: ../README → ARCHITECTURE → DEVELOP → SPECIFICATION → DEVELOPMENT_PLAN → PROGRESS
- **运维 / 部署**: usage → deployment → control_automation
- **API 集成方**: api → control_automation
- **插件开发者**: plugin_development → PLUGIN_COMPATIBILITY → SPECIFICATION (2.6 Manifest)
- **架构研究**: ARCHITECTURE → 五个专项施工图 → ADR (在 ARCHITECTURE.md 末尾)
