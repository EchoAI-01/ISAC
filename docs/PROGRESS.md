# ISAC 进度总表

> 本文件是各节点进度的**唯一事实源**。`DEVELOPMENT_PLAN.md` 描述节点定义与验收,`AGENTS.md` 只做一句话概述并链接此处;二者不再各自维护进度表。
>
> 最近更新: 2026-07-26 (L2-L5/M1-M2/N1-N3/O1-O3 核心逻辑+单测已实现但主链路待接线;新增 P 主链路接线与激活节点组;1091 单测通过、ruff/mypy 全绿)

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
| I | 生产化与交付 | 85% | 部署/文档/数据工具/监控完成;WebUI v2 完成;浏览器测试 CI 已随 K8 接入,待复核升 100% |
| J | 模型能力、计量与管理面 | 100% | J1+J2+J3+J4 完成 (非桩实现+测试+运行验证+文档同步);2026-07-26 五维度代码评审发现的 J2/J3/J4 缺口 (媒体校验未接线、J4 执行循环未接线、Token Scope/SSE scope 过滤/CSRF 会话缺失等 20 项) 已逐项修复,详见下方"J2/J3/J4 补充修复"|
| K | 稳定化与可用版本闭环 | 100% | K1-K8 全部完成 (K8-2 Playwright CI + release_checklist 已落地) |
| L | 拟人化运行时落地 | 实现待接线 | L1-L5 核心逻辑+单测完成;wait 闭环已接生产,但 debounce 合并/主动调度启停/打断闭环/上下文恢复 **主链路未接线**(默认关闭)→ 见 P0/P1 |
| M | 路由与 Agent Mesh 深化 | 实现待接线 | M1/M2 核心逻辑+单测完成(observer/candidate 仲裁+SWITCH_MARGIN; MeshActionBroker ACL+投递; 4 A2A 工具);但 observe_message/mesh_role/broker 注入 **未接线** → 见 P2 |
| N | 记忆深化 | 部分接线 | N2 治理已完整接入生产(含检索期软删除过滤,CR2-Fix-12);N1 MemoryItem/Adapter、N3 IdentityResolver 核心+单测完成但 **无调用点**(悬空)→ 见 P3/P4 |
| O | 企业化与平台扩展 | 实现待接线 | O1/O2/O3 核心+单测完成但 **零调用点**(未接 store/loader/control)→ 见 P5;O4 平台适配器/O5 Video Provider 未开始(`[ ]`) |
| P | 主链路接线与激活 | 未开始 | P0 消息并发化→P1 拟人化→P2 Mesh→P3 检索深化→P4 身份归一→P5 企业化;把上述 `[~]` 能力接入主链路,是 `[~]`→`[x]` 的收尾。定义见 DEVELOPMENT_PLAN §四 P |
| 可观测性 | trace 贯穿 + 分级日志 (横切) | 100% | trace_id/session_id/agent_id 贯穿全链路;level + per_module 分级;默认零输出零开销 |

## 可运行性状态

**已达到「可运行」完成度**(2026-07-25 实测):

- 主程序实测驻留(`RESIDENT_AFTER_3S=True`),支持 SIGINT/SIGTERM 优雅关闭。
- 1091 单元/集成测试通过;Ruff 通过;Mypy 全绿。
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
| K8 CI/发布准入 | ✅ | CI 四 job (check+build+docker+browser) + wheel/sdist smoke + Docker 30s health 循环 + Playwright CI 接入 + scripts/release_checklist.md 七段发布清单 |

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

**剩余工作 (接线 + 未实现;定义详见 DEVELOPMENT_PLAN.md §四 P 节点)**:

*已实现待主链路接线 (`[~]`:核心逻辑 + 单测完成,默认关闭 / 生产路径无调用点)*:

| 能力 | 现状 | 接线节点 |
|------|------|---------|
| L2-L5 拟人化 | wait 闭环已接生产;debounce 合并 / 主动调度启停 / 打断闭环 / 恢复加载 未接线 | P0 → P1 |
| M1-M2 Mesh | 仲裁 / ACL / bus 投递 / 4 A2A 工具 已实现;observe_message / mesh_role / broker 注入 未接线 | P2 |
| N1 MemoryItem | 契约 + Adapter 实现;`pipeline.search()` 从不调用(悬空适配层) | P3 |
| N3 身份归一 | IdentityResolver 实现;gateway 无调用点(悬空库) | P4 |
| O1-O3 企业化 | 租户隔离 / 插件隔离 / Workflow 实现;零调用点(未接 store/loader/control) | P5 |
| 向量 / 图谱召回 | VectorStore / GraphStore / Embedding 已实现;`pipeline.search()` 只写不读 | P3 |

*未开始 (`[ ]`)*:

- **O4 平台适配器** — 微信 / Slack / 飞书 ≥1 真实实现(当前仅 `TemplateAdapter` 模板,未注册)。
- **O5 Video Provider** — 真实端点(`generate` 仍抛 `NotImplementedError`,端点开工前需二次确认)。
- **MemoryConsolidator** — 记忆整合后台任务(episodic → 画像/中期记忆归并与衰减,当前 `NotImplementedError`)。
- **I 节点复核** — WebUI 浏览器测试 CI 已随 K8 接入,复核 I 是否可由 85% 升 100%。

*已补齐*: Reranker 真实后端 `OpenAICompatRerankerProvider`(Cohere/Jina 双协议,`isac/provider/rerank/openai_compat.py`,已接入检索 pipeline);N2 检索期软删除过滤已生效(CR2-Fix-12),N2 记忆治理已完整接入生产。

## 编号约定

- 大节点 A/B/C… 为里程碑;小节点如 D9、K1 为最小可交付单元。
- 完成定义 = 非桩实现 + 单元/集成测试 + 实际运行验证 + **主链路接线** + 文档同步 + Ruff/Mypy 通过。
- **scaffolding (框架已搭建)** = 契约 + 骨架 + 惰性默认关闭接线 + 骨架单测 + 主链路零行为变化;**不满足完成定义,不标 100%/`[x]`**。技术路线见 [ROADMAP.md](./ROADMAP.md),范式见 [MODULE_GUIDE.md](./MODULE_GUIDE.md)。
- **三态标记** = `[x]` 已交付(含主链路接线) / `[~]` 实现完成待接线(核心逻辑 + 单测完成,但未接入生产,接线项归 DEVELOPMENT_PLAN §四 P 节点) / `[ ]` 未开始。演进链:scaffolding → `[~]` → `[x]`。
