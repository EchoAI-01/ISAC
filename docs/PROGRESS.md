# ISAC 进度总表

> 本文件是各节点进度的**唯一事实源**。`DEVELOPMENT_PLAN.md` 描述节点定义与验收,`AGENTS.md` 只做一句话概述并链接此处;二者不再各自维护进度表。
>
> 最近更新: 2026-07-26 (L/M/N/O 全部 14 子节点框架 scaffolding 落地 + 可观测性增强 + 文档体系;957 单测通过)

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
| J | 模型能力、计量与管理面 | 100% | J1+J2+J3+J4 完成 (非桩实现+测试+运行验证+文档同步);2026-07-26 五维度代码评审发现的 J2/J3/J4 缺口 (媒体校验未接线、J4 执行循环未接线、Token Scope/SSE scope 过滤/CSRF 会话缺失等 20 项) 已逐项修复,详见下方"J2/J3/J4 补充修复"|
| K | 稳定化与可用版本闭环 | 95% | K1-K8 代码已落地;浏览器测试 CI 接入与发布准入收尾 |
| L | 拟人化运行时落地 | 100% | L1 框架 + L2/L3/L4/L5 全部实现 (wait 闭环 + debounce + 三唤醒路径; 主动任务 priority+冷却+鉴权+后台循环; 打断次数限制+Prompt 注入; 上下文恢复短/中/长窗口) |
| M | 路由与 Agent Mesh 深化 | 100% | M1/M2 全部实现 (observer/candidate 路由 + 多候选仲裁 + SWITCH_MARGIN 防抖; MeshActionBroker ACL + bus 投递 + 4 A2A 工具 restricted) |
| N | 记忆深化 | 100% | N1/N2/N3 全部实现 (MemoryItem 统一契约 + 四类型 from/to + MemoryItemAdapter; 记忆治理 freeze/protect/correct/delete/restore/export + 审计; 跨平台身份归一 + person_identities/identity_conflicts 表 + 启发式/冲突裁决) |
| O | 企业化与平台扩展 | 进行中 | O1 已实现 (多租户隔离 + 命名空间前缀 + SQL 谓词注入 + 跨租户 PermissionError);O2-O5 框架 scaffolding 待续 |
| 可观测性 | trace 贯穿 + 分级日志 (横切) | 100% | trace_id/session_id/agent_id 贯穿全链路;level + per_module 分级;默认零输出零开销 |

## 可运行性状态

**已达到「可运行」完成度**(2026-07-25 实测):

- 主程序实测驻留(`RESIDENT_AFTER_3S=True`),支持 SIGINT/SIGTERM 优雅关闭。
- 957 单元/集成测试通过;Ruff 通过;Mypy 全绿。
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

**J2/J3/J4 补充修复 (2026-07-26)**:

对 J2/J3/J4 做五维度代码评审后发现 7 项 Critical + 8 项 Required 缺口 (均已直接
读代码确认, 非道听途说), 逐项 TDD 修复并独立提交:
- J2: `MediaNormalizer` 接入 `TranscribeAudioTool`/`VisionUnderstandTool` 生产路径 (此前授权这两个工具的 Agent 可读任意本地文件); 图片生成下载 URL 补 SSRF 校验。
- J4: 子 Agent 真实执行循环接入生产 (此前 `delegate_task` 永远停在 `queued`); `SubAgentPolicy` 空集改严格交集 (此前 fail-open); 递归深度限制; 取消超时不再静默; Journal 脱敏补 `summary`/`max_log_bytes`; `_authorize` 补跨 Agent 校验。
- J3: `PATCH /agents/{id}` If-Match 改读 HTTP Header (原来是 query 参数, 会被静默忽略) + `AgentManager` 按 agent_id 加配置锁修复并发竞态; `CONTROL_PLANE_SPEC.md` §6.1 描述的 Token Scope 模型 (`control.tokens[]`) 落地; SSE 事件按 scope 过滤 + 连接数上限; Provider 测试/制品删除端点补审计日志; `InterAgentLink` 格式校验 + WebUI 审计日志渲染改用 `textContent` (修复存储型 XSS); `POST /auth/session` 会话 Cookie + CSRF 双提交校验 (§8.2 第 5 条)。

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
| L 拟人化运行时 (L1-L5) | 框架已搭建 (scaffolding);ConversationRuntime + debounce/scheduler/interrupt/recovery 骨架就位, 业务实现待续 |
| M 路由 Mesh (M1-M2) | 框架已搭建 (scaffolding);MeshRouter/MeshActionBroker + A2A 工具骨架就位, 仲裁/投递待续 |
| N 记忆深化 (N1-N3) | 框架已搭建 (scaffolding);MemoryItem/MemoryGovernor/IdentityResolver 骨架就位, 迁移/治理/归一待续 |
| O 企业化 (O1-O5) | 框架已搭建 (scaffolding);多租户/插件隔离/Workflow/平台模板/Video Provider 骨架就位, 业务实现待续 |

**既有桩待补:**

- Reranker 真实后端 (`RerankerProvider` 目前只有 `StubRerankerProvider`)
- MemoryConsolidator
- L/M/N/O 全部 14 子节点的**业务实现** (契约 + 骨架已 scaffolding, 见上表);各节点 TODO(节点) 标注挂接点

## 编号约定

- 大节点 A/B/C… 为里程碑;小节点如 D9、K1 为最小可交付单元。
- 完成定义 = 非桩实现 + 单元/集成测试 + 实际运行验证 + 文档同步 + Ruff/Mypy 通过。
- **scaffolding (框架已搭建)** = 契约 + 骨架 + 惰性默认关闭接线 + 骨架单测 + 主链路零行为变化;**不满足完成定义,不标 100%/`[x]`**。技术路线见 [ROADMAP.md](./ROADMAP.md),范式见 [MODULE_GUIDE.md](./MODULE_GUIDE.md)。
