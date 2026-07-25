# ISAC 进度总表

> 本文件是各节点进度的**唯一事实源**。`DEVELOPMENT_PLAN.md` 描述节点定义与验收,`AGENTS.md` 只做一句话概述并链接此处;二者不再各自维护进度表。
>
> 最近更新: 2026-07-25 (J3 WebUI v2 完成; 792 测试通过、Ruff/Mypy 全绿、主程序实测驻留)

## 节点总览

| 大节点 | 名称 | 进度 | 说明 |
|--------|------|------|------|
| A | 文档冻结 | 100% | A1-A5 完成 |
| B | 基础骨架 | 100% | 脚手架 + 核心契约 + 配置日志 + 入口 |
| C | 连接与路由 | 100% | OneBot + Gateway + Router + Registry |
| D | 单 Agent 核心 | 100% | D1-D9 完成 |
| E | 多 Agent 运行时 | 100% | E1-E4 完成;E5 经 K6 端到端验收 |
| F | 插件生态 | 100% | AstrBot / MaiBot / Native / 加载器 |
| G | 控制面与自动化 | 100% | Admin API / MCP / Webhook / 安全默认值 |
| H | 平台与工具扩展 | 100% | Telegram/Discord/WebChat + MCP Client + 实用工具 |
| I | 生产化与交付 | 85% | 部署/文档/数据工具/监控完成;WebUI v2 完成 (浏览器测试 CI 接入待 K8-2) |
| J | 模型能力、计量与管理面 | 100% | J1+J2+J3+J4 完成 (非桩实现+测试+运行验证+文档同步) |
| K | 稳定化与可用版本闭环 | 95% | K1-K8 代码已落地;浏览器测试 CI 接入与发布准入收尾 |

## 可运行性状态

**已达到「可运行」完成度**(2026-07-25 实测):

- 主程序实测驻留(`RESIDENT_AFTER_3S=True`),支持 SIGINT/SIGTERM 优雅关闭。
- 792 单元/集成测试通过;Ruff 通过;Mypy 全绿(198 文件)。
- 集成测试就位:单 Agent 全链、多 Agent × 工具 × 记忆 × 控制面、启动驻留 smoke、J2 多模态全链 + Channel 投递、J4 SubAgent 全链 + Control API、J3 WebUI v2 SPA 十域。
- 真实 `OpenAICompatProvider`(httpx + SSE + Tool Call + 错误分类 + 连接池)可用。
- Agent / Session / 路由 / Link / 记忆可持久化恢复;SubAgent 任务可重启恢复 (running/queued → cancelled)。
- J3 WebUI v2 SPA 十域全部真实内容: Dashboard/Agents/Channels/Providers/Usage/Extensions/Memory/Sessions/Logs/System; 配置编辑事务 (Schema 校验 + Diff 预览 + 二次确认 + ETag 乐观锁); SSE 实时事件流; Playwright 浏览器黄金路径测试 (未装时 skip, CI 接入待 K8-2)。

## 稳定化节点 (K) 明细

| 节点 | 状态 | 交付 |
|------|------|------|
| K1 应用生命周期 | ✅ | ApplicationRuntime + TaskGroup + register_lifecycle + 优雅关闭 |
| K2 真实 Provider | ✅ | OpenAICompatProvider 真实 HTTP/SSE/Tool Call/429·5xx 分类/连接池 |
| K3 存储生命周期 | ✅ | Schema init/migration + BM25 预热 + shared namespace ACL |
| K4 配置持久化恢复 | ✅ | 原子写 (tmp+fsync+os.replace) + Agent/Link 恢复 |
| K5 单 Agent E2E | ✅ | FakeChannel + FakeLLMProvider 全链集成测试 |
| K6 多 Agent E2E | ✅ | 多 Agent × 工具 × 记忆 × 控制面集成测试 (含原 E5) |
| K7 安全基线 | ✅ | SSRF 防护 + SecretStore(AES-256-GCM) + TTL + 有界队列 + kill-wait |
| K8 CI/发布准入 | 🟡 | CI 覆盖率门禁 + wheel/sdist smoke + Docker health 已就位;WebUI 浏览器测试待补 |

## 待实现能力

**J3 已完成 (2026-07-25)**:

J3 WebUI v2 管理与观测已完整落地 (详见 DEVELOPMENT_PLAN.md J3 节"当前"):
- 后端 Control API 扩展 (routes_providers / routes_config / routes_sessions / routes_memory / routes_events SSE)
- AgentConfig 加 revision 字段 + PATCH If-Match 乐观锁
- WebUI v2 SPA shell 侧边栏 10 域导航
- Dashboard / Agents / Channels / Providers / Usage / Extensions / Memory / Sessions / Logs / System 十页真实内容
- 配置编辑事务 UI (Schema 校验 + Diff 预览 + 二次确认 + ETag 乐观锁)
- Playwright 浏览器黄金路径测试 (2 路径; 未装时 skip, CI 接入待 K8-2)

**剩余 experimental 桩 (本批次 EXP 节点补齐)**:

| 能力 | 状态 |
|------|------|
| MemoryConsolidator | 留后续迭代 (后台任务, 非本批次) |
| ConversationRuntime | 留后续迭代 (大型重构, 独立节点) |

**既有桩待补:**

- 记忆向量检索 (VectorStore / sqlite-vec)
- 记忆图谱 (GraphStore)
- Reranker 真实后端
- MemoryConsolidator
- 完整 ConversationRuntime(主动任务、等待、打断闭环)

## 编号约定

- 大节点 A/B/C… 为里程碑;小节点如 D9、K1 为最小可交付单元。
- 完成定义 = 非桩实现 + 单元/集成测试 + 实际运行验证 + 文档同步 + Ruff/Mypy 通过。
