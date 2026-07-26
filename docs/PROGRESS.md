# ISAC 进度总表

> 本文件是各节点进度的**唯一事实源**。`DEVELOPMENT_PLAN.md` 描述节点定义与验收,`AGENTS.md` 只做一句话概述并链接此处;二者不再各自维护进度表。
>
> 最近更新: 2026-07-26 (对照 `REQUIREMENTS.md` 十二条需求做 10 域并行代码取证 + 真实启动实测,发现 D8/E4/F1-F3/H1/H2/J1-J4/K1-K4/K7 等已交付节点存在与完成定义矛盾的未接线子行为,已逐条补记"MVP 缺口复核"说明;新增 **Q MVP 收尾** 节点组补齐 P 节点未覆盖的必需缺口,其中 **Q1 记忆写入回路** 为当前最高优先级缺口;K1-K7 复选框校正为 `[x]`(与本表一致);CR3 修复轮 14 项修复见下;1157 单测通过、ruff/mypy 全绿)

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
| Q | MVP 收尾(新增) | Q0/Q1 完成 | 2026-07-26 差距复核发现、未被 P0-P5 覆盖但 MVP 必需的缺口。**Q0 开箱可触达已完成 (2026-07-27)**: 四平台注册+裸部署默认路由+样例死键修正+WebChat 端到端可聊;**Q1 记忆写入回路与身份稳定化已完成 (2026-07-27)**: 回复后 episodic 写入+画像/关系回路+UserMapper SQLite 持久化, "越聊越熟"闭环打通 (聊→重启→检索命中);其余 Q2 人格差异化、Q3 插件/MCP 生态接线、Q4 多模态工具注册、Q5 WebUI/控制面收尾、Q6 SubAgent 补漏 未开始。定义见 DEVELOPMENT_PLAN §四 Q |
| 可观测性 | trace 贯穿 + 分级日志 (横切) | 100% | trace_id/session_id/agent_id 贯穿全链路;level + per_module 分级;默认零输出零开销 |

## 可运行性状态

**已达到「可运行」完成度**(2026-07-26 实测,不等于「MVP 可用」,见下方 2026-07-26 差距复核):

- 主程序实测驻留(无 `data/config.jsonc` 时兜底默认值 + StubProvider 也能启动;18 秒驻留无异常栈),支持 SIGINT/SIGTERM 优雅关闭(Windows 下 Ctrl+C 尚不走优雅关闭路径,见 Q0)。
- 1157 单元/集成测试通过;Ruff 通过;Mypy 全绿。
- 集成测试就位:单 Agent 全链、多 Agent × 工具 × 记忆 × 控制面、启动驻留 smoke、J2 多模态全链 + Channel 投递、J4 SubAgent 全链 + Control API、J3 WebUI v2 SPA 十域。
- 真实 `OpenAICompatProvider`(httpx + SSE + Tool Call + 错误分类 + 连接池)可用;主链路默认非流式,流式路径(CR3-H4 已修合并逻辑)尚未在生产启用。
- Agent / 路由 / Link / 记忆可持久化恢复;SubAgent 任务可重启恢复 (running/queued → cancelled)。**订正**:此前"Session 可持久化恢复"表述不准确 —— `SessionManager`/`UserMapper` 实为纯内存实现(无落盘/无恢复),重启后会话状态与跨平台用户绑定丢失(对话内容因记忆子系统独立持久化不受影响);补齐计划见 Q1。
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
| L2-L5 拟人化 | wait 闭环已接生产;debounce 合并 / 主动调度启停 / 打断闭环 / 恢复加载 未接线 (CR3-M6 已修调度器冷却饿死) | P0 → P1 |
| M1-M2 Mesh | 仲裁 / ACL / bus 投递 / 4 A2A 工具 已实现 (CR3-M2 已修 bus notify 假成功);observe_message / mesh_role / broker 注入 未接线 | P2 |
| N1 MemoryItem | 契约 + Adapter 实现;`pipeline.search()` 从不调用(悬空适配层) | P3 |
| N3 身份归一 | IdentityResolver 实现;gateway 无调用点(悬空库) | P4 |
| O1 多租户 | **已接线 (CR3-L2)**: `tenancy.enabled` 配置开启后 MetadataStore 读写带租户谓词/打标 + 记忆命名空间加前缀;默认关闭零行为变化 | 已完成 (跨租户测试见 test_tenant_isolation) |
| O2 插件隔离 | PluginIsolationHost 已支持子进程真实加载插件 (`load_plugin`, CR3-H2) + `on_load` 生命周期已接线;**默认加载路径仍在宿主进程内执行 (无隔离, 有护栏警告)**, 接管待做 | P5 |
| O3 Workflow | 引擎已修多入口+fan-in 汇合语义 (CR3-M7);生产中仍未实例化 | P5 |
| 向量召回 | **已接线 (CR3-H3)**: `pipeline.search()` 稠密召回 + RRF 融合 + ACL 一致过滤;`memory.embedding` 配 api_key+model 即生效 (main 注入 EmbeddingProvider)。图谱召回仍未接入 | P3 (图谱) |
| 流式工具调用 | 按 index 累积分片 + stream_options.include_usage + 首 chunk 前失败回退 chat_with_retry (CR3-H4);主链路未启用 streaming | P0 |

*未开始 (`[ ]`)*:

- **O4 平台适配器** — 微信 / Slack / 飞书 ≥1 真实实现(当前仅 `TemplateAdapter` 模板,未注册)。
- **O5 Video Provider** — 真实端点(`generate` 仍抛 `NotImplementedError`,端点开工前需二次确认)。
- **MemoryConsolidator** — 记忆整合后台任务(episodic → 画像/中期记忆归并与衰减,当前 `NotImplementedError`)。
- **I 节点复核** — WebUI 浏览器测试 CI 已随 K8 接入,复核 I 是否可由 85% 升 100%。

*已补齐*: N2 检索期软删除过滤已生效(CR2-Fix-12),N2 记忆治理已完整接入生产。

*订正(2026-07-26)*: 此前"Reranker 已接入检索 pipeline"表述不准确。真实后端 `OpenAICompatRerankerProvider`(Cohere/Jina 双协议,`isac/provider/rerank/openai_compat.py`)确已实现,但生产 `main.py` 构造 `Reranker(memory_config.get("reranker", {}))` 时**未传入 provider**,`is_available()` 恒 `False`,`pipeline.search()` 的 rerank 步骤永不执行。补齐(仿 CR3-H3 embedding 注入写法)见 P3。

**CR3 修复轮 (2026-07-26, 对应 Review/ISAC_待修复项清单.md 的 14 项)**: H2 插件隔离护栏+`on_load` 接线+隔离宿主真实加载 / H3 向量召回接入 pipeline(RRF+ACL)+生产 EmbeddingProvider 注入 / H4 流式工具调用按 index 累积+include_usage+失败回退 / M2 bus notify 真实投递 / M5 Gating-Focus LRU cap 1000 / M6 调度器冷却不再饿死其他会话 / M7 Workflow 多入口+fan-in 入度语义 / L1 自动化创建 Agent 强制受限沙箱 / L2 租户隔离进数据面(默认关闭) / L3 软删同步 BM25+预热过滤 / L4 SSRF 请求期固定 IP / L5 治理审计 operator+agent_id 归因 / L6 非 ASCII Token 401+/metrics 可选认证 / L8 write_file 线程池+journal 原子 seq+MCP sse 显式拒绝。附带: 控制面 sessions/memory/events 路由完成生产挂载(此前 services 键缺失恒 None), `resource` 模块 Windows 平台守卫。

## 2026-07-26 MVP 差距复核 (对照 REQUIREMENTS.md 逐条取证)

对照 `docs/REQUIREMENTS.md` 十二条原始需求,10 个领域并行验证(每条结论均落实到 文件:行号 证据,498 次代码检索 + 一次真实启动实测:无 `data/config.jsonc` 时兜底默认值也能启动、18 秒驻留无异常栈)。核心结论:**项目"能启动"但未达"MVP 可用"** —— 开箱只有 OneBot 一条可聊通道(WebChat/Telegram/Discord 已实现却零生产注册点)、**记忆写入回路完全缺失**(检索/注入/治理/持久化整条读链路就绪,但生产从未调用 `store_episode`,检索永远为空)、人格系统的情绪/表达风格/注意力漂移注入器是未注册的空桩、插件与 MCP 生态的数据面注册表在生产被硬编码为空、多模态语义工具从未注册进 ToolRegistry。

同时发现一批标 `[x]` **已交付**的节点(D8/E4/F1-F3/H1/H2/J1-J4/K1-K4/K7)存在与其"完成定义"(§二:非桩实现+单测+集成验证+**主链路接线**+文档+CI)矛盾的未接线子行为 —— 已在 `DEVELOPMENT_PLAN.md` 对应节点下补记"**2026-07-26 MVP 缺口复核**"说明并指向修复它的 Q 节点,不改动其余已验证部分的 `[x]` 标记(与 J2/J3/J4 既有的"补充修复"记录方式一致)。

为把这些**未被 P0-P5 任何节点覆盖**的必需缺口系统化,新增 **Q 节点组:MVP 收尾**(定义详见 `DEVELOPMENT_PLAN.md` §四 Q):

| 能力 | 现状 | 对应节点 |
|------|------|---------|
| **Q1 记忆写入回路与身份稳定化** | **已完成 (2026-07-27)**: 回复后后台写 episodic (整轮对话)+画像/关系每互动递增 (读写同键)+UserMapper SQLite 写穿持久化 (master_id 跨重启稳定);行话学习/画像 LLM 归纳留 MemoryConsolidator;Session 状态仍不持久化 (如实标注) | Q1 ✅ |
| Q0 开箱可触达与配置纠偏 | **已完成 (2026-07-27)**: 四平台注册分支+裸部署默认路由+样例死键修正+Dockerfile 冻结+Windows 优雅关闭+web_search deny+Provider 缓存失效+destroy 记忆清理+task 门修正;冒烟另修复出站平台会话键丢失 (WebChat 回复/进度帧落错队列) | Q0 ✅ |
| Q2 人格差异化实现 | `AgentConfig.persona` 文本不进 System Prompt;Mood/ExpressionStyle/AttentionDrift 三个注入器是返回空串的桩且未注册(`assembly.py` 自认"待落地") | Q2(新增,D8 delta) |
| Q3 插件与 MCP 生态数据面接线 | Native SDK `register_tool/command/injector` 在生产被硬编码 `None`;AstrBot/MaiBot 插件加载后不桥接,handler 永不触发;`PluginManager` 未传入 `EnableMatrix`(plugins_allow/deny 对插件钩子不生效);`AgentConfig.mcp_servers` 零消费者 | Q3(新增,E4/F1-F4/H2 delta) |
| Q4 多模态工具注册与计量收尾 | Provider/Router/Catalog/ArtifactStore 就绪,但 6 个语义媒体工具从未注册进 ToolRegistry;出站不经 MediaResolver;入站媒体无落盘;多模态 6 个 `record_*` 计量方法零调用;价目表恒空 | Q4(新增,J1/J2 delta) |
| Q5 WebUI 与控制面收尾 | 插件页占位假数据;SubAgent 任务表路径写死恒空;配置编辑伪造 revision;后端 SSE 未被前端消费;MCP Server/Webhook 无生产启动点/路由挂载 | Q5(新增,J3/G2/G3 delta) |
| Q6 SubAgent 用量与安全补漏 | supervisor 丢弃 `result.usage`/`evidence_refs`(时间线用量恒 0);背景摘要未传子 Agent;无并发上限;受限策略漏 `deny delegate_task` | Q6(新增,J4 delta) |

Q0/Q1 不依赖 P0 消息并发化,建议与/先于 P 节点推进;P2(Mesh)、P3(记忆检索深化)的验收范围已相应扩充(Link 细粒度 ACL、Reranker 注入),不在 Q 中重复列出。MVP 准入线(P0-P2 + Q0-Q1)见 [ROADMAP.md](./ROADMAP.md) MVP 里程碑。

## 编号约定

- 大节点 A/B/C… 为里程碑;小节点如 D9、K1 为最小可交付单元。
- 完成定义 = 非桩实现 + 单元/集成测试 + 实际运行验证 + **主链路接线** + 文档同步 + Ruff/Mypy 通过。
- **scaffolding (框架已搭建)** = 契约 + 骨架 + 惰性默认关闭接线 + 骨架单测 + 主链路零行为变化;**不满足完成定义,不标 100%/`[x]`**。技术路线见 [ROADMAP.md](./ROADMAP.md),范式见 [MODULE_GUIDE.md](./MODULE_GUIDE.md)。
- **三态标记** = `[x]` 已交付(含主链路接线) / `[~]` 实现完成待接线(核心逻辑 + 单测完成,但未接入生产,接线项归 DEVELOPMENT_PLAN §四 P 节点) / `[ ]` 未开始。演进链:scaffolding → `[~]` → `[x]`。
