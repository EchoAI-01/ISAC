# ISAC 进度总表

> 本文件是各节点进度的**唯一事实源**。`DEVELOPMENT_PLAN.md` 描述节点定义与验收,`AGENTS.md` 只做一句话概述并链接此处;二者不再各自维护进度表。
>
> 最近更新: 2026-07-24 (基于 dev 分支实测复审: 467 单测通过、Ruff/Mypy 全绿、主程序实测驻留)

## 节点总览

| 大节点 | 名称 | 进度 | 说明 |
|--------|------|------|------|
| A | 文档冻结 | 100% | A1-A5 完成 |
| B | 基础骨架 | 100% | 脚手架 + 核心契约 + 配置日志 + 入口 |
| C | 连接与路由 | 100% | OneBot + Gateway + Router + Registry |
| D | 单 Agent 核心 | 89% | D1-D8 完成;D9 任务进度报告待实现 |
| E | 多 Agent 运行时 | 100% | E1-E4 完成;E5 经 K6 端到端验收 |
| F | 插件生态 | 100% | AstrBot / MaiBot / Native / 加载器 |
| G | 控制面与自动化 | 100% | Admin API / MCP / Webhook / 安全默认值 |
| H | 平台与工具扩展 | 100% | Telegram/Discord/WebChat + MCP Client + 实用工具 |
| I | 生产化与交付 | 85% | 部署/文档/数据工具/监控完成;WebUI 仅 v1,浏览器测试待补 |
| J | 模型能力、计量与管理面 | 0% | J1-J4 仅设计,代码全部待实现 |
| K | 稳定化与可用版本闭环 | 95% | K1-K8 代码已落地;浏览器测试与发布准入收尾 |

## 可运行性状态

**已达到「可运行」完成度**(2026-07-24 实测):

- 主程序实测驻留(`RESIDENT_AFTER_3S=True`),支持 SIGINT/SIGTERM 优雅关闭。
- 467 单元测试通过;Ruff 通过;Mypy 全绿(162 文件)。
- 集成测试就位:单 Agent 全链、多 Agent × 工具 × 记忆 × 控制面、启动驻留 smoke。
- 真实 `OpenAICompatProvider`(httpx + SSE + Tool Call + 错误分类 + 连接池)可用。
- Agent / Session / 路由 / Link / 记忆可持久化恢复。

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

**新增需求(仅设计,代码待实现):**

| 节点 | 能力 | 依赖 |
|------|------|------|
| D9 | 任务进度报告 (ProgressEvent/ProgressReporter) | K1-K5 |
| J1 | Token 用量与成本计量 (ModelUsageEvent) | K1、G1 |
| J2 | 多模态 Provider 与能力选择 (ModelRouter/ArtifactStore) | D2-D4、J1 |
| J3 | WebUI v2 管理与观测 | G1-G4、D9、J1-J2 |
| J4 | 每个 Agent 的隔离 SubAgent 与可追溯日志 | K1-K5、D9、J1 |

**既有桩待补:**

- 记忆向量检索 (VectorStore / sqlite-vec)
- 记忆图谱 (GraphStore)
- Reranker 真实后端
- MemoryConsolidator
- 完整 ConversationRuntime(主动任务、等待、打断闭环)

## 编号约定

- 大节点 A/B/C… 为里程碑;小节点如 D9、K1 为最小可交付单元。
- 完成定义 = 非桩实现 + 单元/集成测试 + 实际运行验证 + 文档同步 + Ruff/Mypy 通过。
