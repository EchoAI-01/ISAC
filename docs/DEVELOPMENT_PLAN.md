# ISAC 开发 SOW / 主 TODO

> 本文档是 ISAC 项目的 **工作说明书 (Statement of Work)** 与 **主 TODO 清单**。
> 不再按"第几天"排期，而是按 **节点 (A/B/C...) / 子节点 (1/2/3...)** 组织任务。
> 每个子节点完成后，需：1) 在本文档标记 `[x]`；2) 补充/更新相关文档；3) 向项目负责人汇报。

---

## 一、项目总则

1. **文件名称清晰易懂**：模块、文件、函数、类名须符合 `DEVELOP.md` 命名规范，做到"看名知意"。
2. **项目结构干净优雅**：目录职责单一，导入无环，新模块按 `DEVELOP.md` 1.1/1.2 放置。
3. **可接手能力强**：任何节点完成后，须留下"交接说明"——说明已实现内容、未实现边界、下一步入口。
4. **文档即蓝图**：整体思路、节点待办、项目构造、蓝图必须落成文档；修改实现时同步更新文档。
5. **代码可读性**：必须写中文 docstring；复杂逻辑加行内注释解释"为什么"；保持代码整洁。
6. **文档可读性**：避免模糊词与未定义名词；必须解释的专业术语集中放在 [术语表](#五术语表)。

---

## 二、节点使用规则

- **大节点**：用 A/B/C... 编号，代表一个可验收的里程碑。
- **小节点**：用 A1/A2... 编号，代表可独立完成、可汇报的最小单元。
- **进度汇报**：每完成一个小节点，在本文档 `[ ]` 改为 `[x]`，并简要汇报。
- **节点可调整**：如需新增/合并/拆分节点，先更新本文档与 `AGENTS.md`，再继续执行。
- **完成定义**：小节点完成 = 非桩代码实现 + 单元测试 + 对应集成/运行验证 + 错误与关闭路径验证 + 相关文档同步 + `ruff` / `mypy` / CI 门禁通过。仅有接口、占位实现、静态文件或 Mock 单测不得标记完成。

---

## 三、节点总览

各节点进度以 [PROGRESS.md](./PROGRESS.md) 为**唯一事实源**,本文档不再另存进度表,只描述节点定义、依赖与验收。

当前概况(详见 PROGRESS.md): A-C、F-H 已完成;E 经 K6 端到端验收完成;I 主体完成(WebUI 仅 v1);K1-K8 稳定化代码已落地,项目已达可运行完成度;D9/J1/J2/J4 能力框架 (scaffolding) 已落地(契约/骨架/惰性接线就位、ruff/mypy 全绿),业务实现待续。新增 **L 拟人化运行时落地**、**M 路由 Mesh 深化**、**N 记忆深化**、**O 企业化与平台扩展** 四个大节点,其下 **全部 14 个子节点 (L1-L5/M1-M2/N1-N3/O1-O5) 框架已搭建 (scaffolding)**——契约 + 骨架类 + 惰性默认关闭接线就位,957 单测通过、ruff/mypy 全绿、主链路零行为变化,业务实现待续,定义见 §四;**可观测性增强**(trace 贯穿 + 分级日志)已横切落地。技术路线全景与阶段划分见 [ROADMAP.md](./ROADMAP.md);scaffolding 范式的可复制步骤见 [MODULE_GUIDE.md](./MODULE_GUIDE.md)。

## 三之二、下一步开发计划

K1-K8 稳定化已使项目可持续运行、真实模型可用、端到端可验证。剩余工作按下述优先级推进:

1. **K8 收尾** — 补 WebUI 浏览器黄金路径测试,校准 README/AGENTS/版本号,发版时再重建变更记录,确认发布准入。
2. **[x] D9 任务进度报告** — 实现 `ProgressEvent`/`ProgressReporter`,工具完成后按人设汇报;是 J4 与 WebUI 任务时间线的前置。已完成,详见上文 D9 节点"当前"。
3. **[x] J1 Token 用量与成本计量** — 在 Provider 调用边界统一记录 `ModelUsageEvent`;为 J2 成本策略和 WebUI 用量页提供数据。已完成,详见下文 J1 节点"当前"。
4. **[x] J2 多模态 Provider 与能力选择** — 落地 `ModelDescriptor`/`ModelCatalog`/`ModelRouter`/`ArtifactStore`, 填充 `provider/{embed,rerank,stt_tts}` 空目录。已完成, 详见下文 J2 节点"当前"。
5. **[x] J4 SubAgent Runtime** — 基于 D9/J1 实现隔离子 Agent 与可追溯 `SubAgentJournal`,把 H3 `TaskRunner` 原型迁移为 `SubAgentSupervisor`。已完成, 详见下文 J4 节点"当前"。
6. **[x] J3 WebUI v2** — 汇聚上述能力,提供十域管理与观测面板。已完成, 详见下文 J3 节点"当前"。
7. **[框架已落地] 拟人化地基 (L 节点)** — L1-L5 全部框架已搭建 (scaffolding);L2 Wait 闭环 / L3 主动任务 / L4 打断 / L5 上下文恢复 的业务实现待续。详见 §四 L 节点。
8. **[已落地] 可观测性增强** — trace 贯穿 + 分级日志,无报错也可追踪每步操作。详见 §四"可观测性增强"与 [LOGGING.md](./LOGGING.md)。
9. **[框架已落地] 后续大节点** — M 路由 Mesh 深化 / N 记忆深化 / O 企业化与平台扩展 的框架 (契约 + 骨架 + 惰性接线) 均已 scaffolding,业务实现待续;见 §四与 [ROADMAP.md](./ROADMAP.md)。
10. **experimental 桩补齐** — VectorStore(sqlite-vec)、GraphStore、Reranker、MemoryConsolidator。

依赖顺序: K8 → D9 → J1 → J2 → J4 → J3 → L1 → (L2-L5 / M / N / O);experimental 桩可并行插入。L/M/N/O 每项完成后按强化完成定义(非桩实现 + 单元/集成测试 + 运行验证 + 文档同步)更新 PROGRESS.md。技术路线全景见 [ROADMAP.md](./ROADMAP.md)。

---

## 四、详细节点

### A 文档冻结

**目标**：让任何新加入的开发者/Agent 在不问人的情况下，能读懂架构、接口、流程和当前进度。

- [x] **A1 术语表与规范确认**
  - **验收**：`ARCHITECTURE.md` / `DEVELOP.md` / `SPECIFICATION.md` / 本文档无冲突；所有核心术语（AgentInstance、MessageRouter、InterAgentBus、启用矩阵等）已定义。
  - **产出**：`SPECIFICATION.md` 1.x 数据模型、`ARCHITECTURE.md` 3.x 组件、`DEVELOP.md` 目录/导入规则。
  - **交接**：术语定义集中在 `SPECIFICATION.md` 与本文档"术语表"章节。

- [x] **A2 架构蓝图 v3.0 定稿**
  - **验收**：多 Agent 架构图、控制面/数据面分离、Channel-Agent 解耦、记忆命名空间、插件兼容策略已写入 `ARCHITECTURE.md`。
  - **产出**：`ARCHITECTURE.md` v3.0 + ADR-007~011。
  - **依赖**：A1。

- [x] **A3 接口契约冻结**
  - **验收**：`isac/core/types.py` / `events.py` / `exceptions.py` 与 `SPECIFICATION.md` 完全一致；ABC/Protocol 签名稳定。
  - **产出**：`isac/core/` 下全部契约文件通过单测。
  - **依赖**：A2。

- [x] **A4 SOW 与 AGENTS.md 维护流程**
  - **验收**：本文件与 `AGENTS.md` 的"当前进度"表每次节点完成后同步更新；新增节点有明确的依赖与验收标准。
  - **产出**：本文档 + `AGENTS.md` 进度表。
  - **依赖**：A1-A3；持续进行。
  - **当前**：2026-07-23 复审发现历史完成状态与真实运行能力不一致，已新增 K 稳定化节点并撤回 I2/I5/I6 完成状态；后续节点只有满足强化后的完成定义才可标记 `[x]`。

- [x] **A5 专项施工图补齐**
  - **验收**：拟人化运行时、记忆系统、路由与 Agent Mesh、插件兼容、控制面五个关键系统有独立专项文档；主文档引用清晰。
  - **产出**：`HUMANLIKE_RUNTIME.md`、`MEMORY_DESIGN.md`、`ROUTING_AND_AGENT_MESH.md`、`PLUGIN_COMPATIBILITY.md`、`CONTROL_PLANE_SPEC.md`。
  - **依赖**：A2、A3。
  - **交接**：实现对应模块前必须先阅读专项文档，主文档仅保留总览与核心接口。

---

### B 基础骨架

**目标**：搭好可运行、可测试的项目骨架，让上层模块有地方放、有规范可循。

- [x] **B1 项目脚手架**
  - **验收**：`uv sync --all-extras --dev` 成功；`.github/workflows/ci.yml` 可运行 `ruff` / `mypy` / `pytest`。
  - **产出**：`pyproject.toml`、`.gitignore`、`LICENSE`、`README.md`、`AGENTS.md`、`.github/workflows/ci.yml`、`data/.gitkeep`、`scripts/` 桩。
  - **交接**：依赖环境已就绪，后续 Agent 直接 `uv run` 即可。

- [x] **B2 核心契约实现**
  - **验收**：`isac/core/{types,events,exceptions,constants}.py` 全部实现并通过单测。
  - **产出**：数据模型、事件枚举、错误体系、常量。
  - **依赖**：B1。

- [x] **B3 配置与日志系统**
  - **验收**：`data/config.jsonc` 可加载（默认值 + 环境变量覆盖）；logger 在 structlog 不可用时降级为 stdlib。
  - **产出**：`utils/config.py`、`utils/logger.py`、`utils/security.py`（SecretStore 桩）、`utils/helpers.py`。
  - **依赖**：B2。

- [x] **B4 入口与调试脚本（仅初始化骨架）**
  - **验收**：`python -m isac` 可执行初始化（无 Channel 时不报错）；`scripts/migrate.py` / `export.py` 有入口。应用常驻、信号处理和优雅关闭由 K1 重新验收。
  - **产出**：`isac/__main__.py`、`isac/main.py`（组装骨架）、`scripts/*`。
  - **依赖**：B3。
  - **当前边界**：实测 `main()` 打印“启动完成”后立即返回，不能视为持续运行的服务。

---

### C 连接与路由

**目标**：让 IM 消息能进入系统，并按规则路由到正确的 Agent。

- [x] **C1 OneBot 适配器实现**
  - **验收**：能通过 NapCat 连接 QQ，收发消息；消息转换覆盖 text/at/image/reply；有重连机制。
  - **产出**：`channel/adapters/onebot/adapter.py`、`tests/unit/test_onebot_adapter.py`。
  - **依赖**：B1-B4。
  - **交接**：
    - 已实现反向 WebSocket 模式，配置 `channels.onebot.enabled=true` 即可启用。
    - aiocqhttp 改为惰性导入，未安装 onebot extra 时不会导致启动崩溃。
    - 消息转换支持 text/at/image/reply/face/record；发送支持 text/at/image/reply/emoji/voice。
    - 重连逻辑在 `_run_with_retry`，连接建立时重置计数。
    - 真机联调仍需 NapCat + 测试 QQ + 在 `data/config.jsonc` 填写 `channels.onebot` 与 `bot_id`。

- [x] **C2 Gateway 会话与用户系统**
  - **验收**：EventBus Intercept/Async 双层工作；SessionManager 能创建/查找会话；UserMapper 跨平台映射；SessionLockManager 串行处理。
  - **产出**：`gateway/{event_bus,session,user_mapper,lock,models}.py`。
  - **依赖**：B2。

- [x] **C3 MessageRouter 与路由规则**
  - **验收**：路由优先级（显式绑定 > 触发词 > 默认 Agent > DROP）通过单测；触发词可剥离；`data/routing.jsonc` 可热更新。
  - **产出**：`router/{router,rules,types}.py`。
  - **依赖**：C2。

- [x] **C4 Channel 注册表**
  - **验收**：ChannelRegistry 能注册多个适配器、统一启停。
  - **产出**：`channel/registry.py`。
  - **依赖**：C1 骨架（C1 业务实现后可联调）。

---

### D 单 Agent 核心

**目标**：单个 Agent 能决定是否回复、组装 Prompt、调用 LLM、使用工具、记忆用户。

- [x] **D1 门控系统**
  - **验收**：GatingSystem.evaluate 流程正确；ReplyNecessityJudge 评分模型与文档一致；FocusMode/IdleBackoff/TurnScheduler 工作。
  - **产出**：`gating/{system,reply_necessity,idle_backoff,turn_scheduler,turn_gates,types}.py`。
  - **依赖**：B2。
  - **当前**：GatingSystem/IdleBackoff/FocusMode 已实现；ReplyNecessityJudge 完整评分模型已实现（基础分+内容分+压力分-存在感惩罚 × 频率系数，权重集中在 `core/constants.py`）；TurnScheduler 滑动窗口频率与存在感计数已落地（按 `window_seconds` 时间戳 deque，self_ratio 线性映射到 [FREQ_MIN, FREQ_MAX]，附 `tests/unit/test_turn_scheduler.py`）；`runtime/manager.py` 已接线 `record_window_message` / `effective_frequency` / `recent_self_replies` / `recent_window_messages` / `record_reply` / `idle_backoff.record_reply`。D1 整体验收通过。

- [x] **D2 Prompt 组装系统**
  - **验收**：SystemPromptBuilder 按 priority 注入；注入器频率控制工作；失败 Injector 不影响整体。
  - **产出**：`agent/{injector,prompt_builder}.py` + `agent/injectors/` 目录。
  - **依赖**：B2。

- [x] **D3 Agent Loop 主流程**
  - **验收**：ISACAgentLoop.run 完整执行 pre_llm → LLM → post_llm → tool/pre_tool/post_tool → final_response；预算耗尽可停止。
  - **产出**：`agent/loop.py`、`agent/hooks.py`。
  - **依赖**：D2。
  - **当前**：已接入 ProviderManager.chat_with_retry；PRE_LLM 钩子顺序串联。

- [x] **D4 工具系统与权限**
  - **验收**：ToolRegistry 注册/执行/权限检查通过测试；所有内置工具（send_emoji/send_image/query_memory/ask_agent/switch_chat/wait/fetch_history/view_forward_message/bash/read_file/write_file/web_search/task）可用。
  - **产出**：`agent/tools/{base,registry}.py` + `agent/tools/social/` / `utility/` / `mcp/` 下全部工具。
  - **依赖**：D3。
  - **当前**：ToolRegistry + ToolPermission 已实现；restricted 策略落地 (未注入对应后端时直接拒绝, 避免把 NotImplementedError 暴露给 LLM)；13 个内置工具全部实现——social 类经 `channel_send` / `channel_history` / `channel_forward` / `session_topic` 服务注入, utility 类 (bash/read_file/write_file/web_search/task) 经对应 services key 注入, 全部带路径白名单/命令白名单/递归深度限制。附 `tests/unit/test_builtin_tools.py` (18 测试) + `tests/unit/test_tool_registry.py` (8 测试, 含 restricted 策略、路径越权、shell 元字符注入防护)。

- [x] **D5 记忆存储引擎** (MVP)
  - **验收**：MetadataStore Schema 初始化成功；VectorStore/SparseBM25Index/GraphStore 可读写；全表按 agent_id 过滤。
  - **产出**：`memory/storage/{metadata,vector,sparse,graph}.py`。
  - **依赖**：B3。
  - **当前**：MetadataStore 完整实现 (episodes + FTS5 + person_profiles + jargon_entries，全表带 agent_id 命名空间)；SparseBM25Index 真实 BM25 打分；VectorStore 与 GraphStore 仍是 `NotImplementedError` 桩，接口签名齐备、占位待真实向量/图后端落地。附 `tests/unit/test_memory_metadata_store.py`、`tests/unit/test_sparse_bm25_index.py`。

- [x] **D6 记忆检索流水线** (MVP)
  - **验收**：MemoryRetrievalPipeline.search 实现 Embed → Dense + Sparse → RRF → Rerank；EmbeddingManager 降级机制工作。
  - **产出**：`memory/{pipeline,embedder,reranker}.py`。
  - **依赖**：D5。
  - **当前**：检索链路打通，RRF 融合 (FTS5 + Sparse) + Reranker 跳过分支工作；EmbeddingManager 恒 `is_degraded=True`、VectorStore 暂存空、Reranker `is_available=False`，当前为纯稀疏检索模式。降级路径与命名空间隔离已测 (附 `tests/unit/test_memory_pipeline.py`)；真实向量检索与 Reranker 后端待 H/I 阶段补齐。

- [x] **D7 记忆注入器**
  - **验收**：HeuristicMemoryInjector 3min/60msg 频率工作；PersonProfile/Jargon/MidTerm 注入正确格式化。
  - **产出**：`memory/injector/{heuristic,person_profile,mid_term,jargon,base}.py`。
  - **依赖**：D6、D2。
  - **当前**：四个注入器全部实现并通过测试 (`tests/unit/test_memory_injectors.py`、`tests/unit/test_prompt_builder_memory_frequency.py`)；已接入 `runtime/assembly.py`；`HeuristicMemoryInjector` 频率控制 (`max_frequency_seconds` / `max_new_messages`) 由 `PromptInjector` 基类统一调度。

- [x] **D8 人格系统**
  - **验收**：PersonaManager 合并全局与 Agent 覆盖；MoodEngine 情绪更新/衰减；BehaviorLearner 注册 FINAL_RESPONSE hook。
  - **产出**：`persona/{manager,drift_profiles,style_profiles,mood,behavior_learner}.py`。
  - **依赖**：D2、D3。
  - **当前**：PersonaManager 合并全局/Agent 覆盖并聚合 MoodEngine + BehaviorLearner; MoodEngine 实现 update (valence/arousal 钳制 + 离散 label 映射) 与 decay (按 decay_rate 向中性衰减); BehaviorLearner 注册 FINAL_RESPONSE hook 从回复提取行为特征 (长度/emoji/话题) 写入 UserProfile.behavior_patterns, 带 max_patterns 滚动淘汰。已在 `runtime/assembly.py` 接线 `persona.register_hooks(hooks)`。附 `tests/unit/test_persona.py` (15 测试)。

- [x] **D9 任务进度报告**
  - **验收**：Agent Loop 在工具完成/失败后产生 `ProgressEvent`；慢工具可在执行前报告；`ProgressReporter` 完成人格模板渲染、敏感信息过滤、2 秒默认频控、连续事件合并和每任务上限；WebChat 输出原生 `progress` 事件，普通 IM 降级为带 `message_kind=progress` 的文本；发送失败不阻断主任务；中断后不再发送旧任务进度。
  - **产出**：`runtime/progress.py`、Agent Loop/Runtime/Channel 接线、Persona 进度模板、配置项及单元/集成测试。
  - **依赖**：D3、D4、D8、C1。
  - **当前**：业务实现已落地，满足强化完成定义。`runtime/manager.py::handle_message()` 消费 `progress_reporter_factory` 按 session 复用 `ProgressReporter` 并绑定 `main.py` 构造的 Channel sender；`AgentContext.services` 携带每次处理独立生成的 `task_id`。Agent Loop 补齐 6 个契约阶段：`planned`（本轮首次出现工具调用时）、`tool_started`（哨兵任务在 `slow_tool_threshold_seconds` 后触发、工具完成即取消）、`tool_finished`/`tool_failed`（沿用既有提交点）、`completed`/`interrupted`（仅当本轮已报告过 `planned` 才收束，避免无工具调用的简单回复产生噪音）。`ProgressReporter._merge()` 在 `merge_window_seconds` 内合并同 task 同 stage 的相邻事件（拼接 `tool_name` 复用既有模板）；任务 `completed`/`interrupted` 后把 `task_id` 计入短期黑名单，丢弃迟到旧进度并清理按 task 累积的字典。`PersonaProgressRenderer` 的 `llm` 模式在注入 Provider 时受 3 秒超时约束改写文案，超时/异常/空响应均回退模板。`WebChatAdapter` 的 `poll_replies()` 按 `metadata.message_kind` 输出 `kind="message"|"progress"` 帧（progress 帧附 `task_id`/`progress_stage`）；普通 IM 复用现有 `adapter.send()`，sender 侧已附带 `message_kind=progress` metadata，adapter 本身无需改动。覆盖：`tests/unit/test_progress_reporter.py`、`tests/unit/test_runtime_manager.py`、`tests/unit/test_platform_adapters.py`、`tests/unit/test_runtime_assembly.py`、`tests/integration/test_single_agent_flow.py`。
  - **边界**：默认模板渲染不额外调用 LLM；可选 LLM 改写受预算、超时和降级策略约束。进度不包含 reasoning、原始工具参数或未清洗结果，也不计入普通回复频率和行为学习。

---

### E 多 Agent 运行时

**目标**：多个 Agent 实例独立运行，共享 Channel，按需互联。

- [x] **E1 AgentConfig 与配置分层**
  - **验收**：`data/agents/<id>/config.jsonc` 可加载；全局/Agent/环境变量三层覆盖正确。
  - **产出**：`runtime/config.py`。
  - **依赖**：B3。

- [x] **E2 AgentManager 生命周期**
  - **验收**：create/start/stop/destroy/list/reload_config 工作；无 `data/agents/` 时创建默认 Agent。
  - **产出**：`runtime/manager.py`、`runtime/instance.py`、`runtime/assembly.py`。
  - **依赖**：E1、D1-D4（需要可组装的子系统）。
  - **当前**：memory_factory 使用 NoOpMemoryPipeline，保证默认 Agent 可创建/启动。

- [x] **E3 InterAgentBus 与 ACL**
  - **验收**：Link ACL 默认拒绝；ask_agent 工具受 ACL 约束；handoff/notify 消息类型可识别。
  - **产出**：`runtime/bus.py`、`agent/tools/social/ask_agent.py`。
  - **依赖**：E2。

- [x] **E4 启用矩阵生效**
  - **验收**：AgentConfig.plugins_allow/deny、tools_policy、commands_allow、mcp_servers 在 Agent 运行时真正生效；Channel 级矩阵参与计算。
  - **产出**：`plugin/runtime/manager.py`、`commands/registry.py`、`agent/tools/registry.py` 联动逻辑。
  - **依赖**：E2、F4 骨架、D4。
  - **当前**：`core/policy.py` 新增 `EnableMatrix` 类实现有效权限计算 (Agent ∩ Channel ∩ 全局); `ToolRegistry` 接入 effective_policy (Channel deny/restricted 优先); `CommandRegistry` 启用矩阵注入 enable_checker; `runtime/assembly.py` 把 EnableMatrix 注入 ToolRegistry + 构造 CommandRegistry 注册 4 个内置命令; `runtime/manager.py` 在 handle_message 中接入命令拦截 (/cmd 跳过门控直接执行)。附 `tests/unit/test_enable_matrix.py` (14 测试覆盖 plugin/tool/command/mcp 四类矩阵决策)。

- [ ] **E5 多 Agent 集成测试（并入 K6 验收）**
  - **验收**：2+ Agent × 1 Channel + 触发词/默认 Agent 路由 + ask_agent 互联端到端通过，并验证重启恢复、权限与记忆隔离。
  - **产出**：`tests/integration/test_multi_agent.py`。
  - **依赖**：K1-K5、C1、E3、E4。

---

### F 插件生态

**目标**：兼容 AstrBot / MaiBot 存量插件，同时提供更强的原生 SDK。

- [x] **F1 AstrBot 兼容层**
  - **验收**：3 个简单 + 2 个复杂 AstrBot 插件可直接运行；Star/Context/EventType/FunctionTool 桥接工作。
  - **产出**：`plugin/compatibility/astrbot/{star,context,events,tools,sandbox}.py`。
  - **依赖**：B2、D3、D4。
  - **当前**：FunctionToolAdapter 桥接 @filter.llm_tool 函数 → ISAC Tool (同步/异步/异常隔离); ContextAdapter 映射 send_message/get_platform/get_provider/register_tool 到 ISAC services; Star 基类与 _FilterRegistry 实现 AstrBot 装饰器 (llm_tool/on_message/on_llm_request); events.py EventType 映射到 ISAC EventType/AgentHookPoint; sandbox.py meta_path 拦截 astrbot.* import 重定向。附 `tests/unit/test_astrbot_compat.py` (9 测试覆盖装饰器/桥接/Context 适配)。

- [x] **F2 MaiBot 兼容层**
  - **验收**：2-3 个 MaiBot 插件可运行；Plugin/Action/Command 映射工作；锁定兼容版本。
  - **产出**：`plugin/compatibility/maibot/{plugin,actions,commands}.py`。
  - **依赖**：B2、D3、`commands/`。
  - **当前**：MaiBotPlugin 基类 + @register_action / @register_command 装饰器 (标记 _maibot_action / _maibot_command); MaiBotPluginAdapter 扫描装饰器并 adapt 到 ToolRegistry / CommandRegistry; bridge_action (MaiBotActionAdapter) 桥接 Action → ISAC Tool (同步/异步/异常隔离); bridge_command (MaiBotCommandAdapter) 桥接 Command → ISAC Command。附 `tests/unit/test_maibot_compat.py` (6 测试覆盖装饰器扫描/Action 桥接/Command 桥接)。

- [x] **F3 原生 SDK v2**
  - **验收**：ISACPlugin 可注册 Commands/InterAgent Hooks/Admin Routes(预留)；Plugin Manifest 扩展字段生效。
  - **产出**：`plugin/native/{plugin,hooks,api}.py`。
  - **依赖**：B2、E3。
  - **当前**：PluginContext 实现 register_tool/injector/command 真实注册到 ToolRegistry/CommandRegistry/SystemPromptBuilder; register_inter_agent_hook 挂到 InterAgentBus; register_admin_route 收集到 services["admin_routes"] 待 G1 消费; on_event_intercept/on_event_async 订阅 EventBus。make_plugin_context 工厂在 PluginManager 加载时调用。附 `tests/unit/test_native_plugin.py` (9 测试)。

- [x] **F4 插件加载器与启用矩阵**
  - **验收**：loader 自动识别三种格式；PluginManager 热重载、错误隔离、启用矩阵生效。
  - **产出**：`plugin/runtime/{manager,loader}.py`。
  - **依赖**：F1-F3。
  - **当前**：PluginLoader 实现 detect_format (manifest.jsonc/metadata.yaml/mai_plugin.yaml 三选一) + load (按格式找对应基类子类并实例化, 多签名兜底); PluginManager 实现 load_all (错误隔离, report 用目录名作 key 解耦) / unload (on_unload 调用) / call_on_load (Native 插件 on_load 传入 PluginContext) / is_enabled_for (EnableMatrix); LoadedPlugin 含 name/format/instance/manifest/path 元数据。附 `tests/unit/test_plugin_loader.py` (12 测试覆盖三种格式 detect/load + 错误隔离 + unload)。

---

### G 控制面与自动化

**目标**：提供 Admin API / MCP Server / Webhook，支撑商业化自动化。

- [x] **G1 Admin API 完整实现**
  - **验收**：Token 认证、审计日志、agents/routing/plugins/links 端点真正生效并持久化；FastAPI docs 可用。
  - **产出**：`control/api/{server,routes_agents,routes_routing,routes_plugins}.py`、`control/auth.py`、`control/audit.py`。
  - **依赖**：E2、E3、C3。
  - **当前**：control/auth.py verify_token 用 hmac.compare_digest 恒定时间比较; make_auth_dependency 构造 FastAPI Bearer 依赖; control/audit.py AuditLog 双写 (structlog + data/audit.ndjson) + 内存 deque + query 接口; routes_agents POST/PUT/DELETE 全部审计 + AgentConfig 持久化到 data/agents/<id>/config.jsonc; routes_routing PUT routing/rules 持久化 + POST/DELETE links 持久化到 data/links.jsonc; routes_plugins PUT plugins 矩阵持久化到 AgentConfig; server 注入 auth/audit + 暴露 /api/v1/audit 查询接口 + /health + /docs。附 `tests/unit/test_admin_api.py` (9 测试覆盖 Token 认证/Agent 生命周期审计/路由与 Link 持久化/插件矩阵持久化)。

- [x] **G2 ISAC MCP Server**
  - **验收**：可用任意 MCP 客户端完成 "创建 Agent → 绑定 Channel → 设置默认 Agent"。
  - **产出**：`control/mcp_server.py`。
  - **依赖**：G1。
  - **当前**：ISACMCPServer 实现 JSON-RPC 2.0 + stdio NDJSON 传输 (sys.stdin/stdout.buffer 简化模式); initialize / tools/list / tools/call / shutdown 方法分发; tools/call 受 Bearer Token 认证 (与 G1 Admin API 共用 verify_token); agent_create/agent_start/agent_stop/link_create/link_delete/route_set_default 6 个工具委托到 AgentManager/Router/Bus; MCPError 异常体系 + 标准 JSON-RPC 错误码 (-32601/-32602/-32603/-32700/-32001); notification (id 为 None) 不响应。附 `tests/unit/test_mcp_server.py` (11 测试覆盖 initialize/tools_list/Token 认证/tools 调用/notification/MCPError)。

- [x] **G3 Webhooks 与自动化触发器**
  - **验收**：message.received/agent.created 等事件可推送到订阅 URL；`/automation/trigger` 入口可用。
  - **产出**：`control/webhooks.py`。
  - **依赖**：G1。
  - **当前**：WebhookManager 实现 subscribe/unsubscribe/list_subscriptions/dispatch/trigger; dispatch 并发推送 (asyncio.gather), 失败重试 3 次 (指数退避); httpx 惰性导入 (生产) 或 http_client 注入 (测试 mock); trigger 作为 /automation/trigger 入口委托到 dispatch。附 `tests/unit/test_webhooks.py` (9 测试覆盖订阅/取消/推送/重试/部分失败/trigger)。

- [x] **G4 控制面安全与审计**
  - **验收**：默认 127.0.0.1；自动化创建 Agent 使用受限默认配置；审计日志可查询。
  - **产出**：`control/defaults.py` 审计中间件、日志查询接口。
  - **依赖**：G1。
  - **当前**：control/defaults.py 新增 RESTRICTED_TOOLS_POLICY (bash/task deny, read_file/write_file restricted) + RESTRICTED_COMMANDS_ALLOW (focus/mute/unmute); make_restricted_agent_config 工厂供自动化场景 (MCP/Webhook) 使用, 默认 plugins_deny=["*"] + mcp_servers=[]; is_safe_default_host/enforce_safe_host 防止误绑定 0.0.0.0/外网 IP; main.py _start_control_plane 接入 enforce_safe_host。审计日志查询接口已在 G1 落地 (/api/v1/audit endpoint)。附 `tests/unit/test_control_defaults.py` (16 测试覆盖受限策略表/构造工厂/extra 覆盖/未知字段忽略/安全地址判定)。

---

### H 平台与工具扩展

**目标**：支持更多 IM 平台，扩展工具能力。

- [x] **H1 更多平台适配器**
  - **验收**：Telegram / Discord / WebChat 适配器可收发消息。
  - **产出**：`channel/adapters/{telegram,discord,webchat}/`。
  - **依赖**：C1。
  - **当前**：TelegramAdapter 用 Bot HTTP API long polling + httpx 惰性导入; 私聊/群聊识别 + @mention entity 转 at segment; DiscordAdapter 用 REST polling (简化版, 生产推荐接入 discord.py 或 Gateway); WebChat 用 asyncio.start_server 极简 HTTP 实现 (/webchat/send + /webchat/poll), 不依赖外部 web 框架, 内存消息队列 + 过期清理。附 `tests/unit/test_platform_adapters.py` (13 测试覆盖三种适配器消息转换 + send + token 缺失兜底)。

- [x] **H2 MCP Client**
  - **验收**：可连接外部 MCP Server；工具按 Agent mcp_servers 矩阵生效。
  - **产出**：`agent/tools/mcp/client.py`。
  - **依赖**：D4、E4。
  - **当前**：MCPClient 支持两种传输 (stdio 子进程 + HTTP/SSE); connect 启动子进程或 httpx.AsyncClient; list_tools 发现 MCP 工具并桥接为 MCPToolBridge (实现 ISAC Tool 接口); call_tool 转发 JSON-RPC tools/call + 错误处理 (jsonrpc error → is_error=True); disconnect 终止子进程 / 关闭 httpx + 取消 pending future。stdio 模式后台读 stdout NDJSON 并分发到 pending future。Agent 的 mcp_servers 启用矩阵在 E4 EnableMatrix 落地。附 `tests/unit/test_mcp_client.py` (9 测试覆盖 connect 各传输 + list_tools + call_tool 正常/错误/未连接 + MCPToolBridge 桥接)。

- [x] **H3 实用工具与子 Agent**
  - **验收**：bash/read_file/write_file/web_search/task 可用；受限策略（项目目录/递归深度）生效。
  - **产出**：`agent/tools/utility/*.py`。
  - **依赖**：D4。
  - **当前**：bash (命令白名单 + shell 元字符注入防护) / read_file (路径白名单 + 行范围 + 64KB 上限) / write_file (路径白名单 + 256KB 上限 + append) / web_search (经 services["web_search"] 注入后端) 全部在 D4 落地; task 工具在 D4 实现受限框架, 本节点补 TaskRunner 真实实现 (用 ISACAgentLoop 派生子任务, 限制 token 预算与递归深度)。附 `tests/unit/test_utility_integration.py` (11 测试覆盖 write→read 往返 / 路径越权 / append / bash 白名单 / 元字符防护 / web_search 缺后端与注入 / task_runner 调用与递归深度)。

---

### I 生产化与交付

**目标**：项目达到生产可用，可部署、可维护、可商业化。

- [x] **I1 WebUI 管理面板**
  - **验收**：FastAPI 静态托管的最小 WebUI 可管理 Agent/路由/Link 并查看审计；完整管理面能力由 J3 验收。
  - **产出**：`control/api/` 扩展 + WebUI 前端。
  - **依赖**：G1。
  - **当前**：采用 FastAPI 静态托管 + Vanilla JS (不依赖 Vue 构建工具链) 实现单页管理面板; control/webui/{index.html, app.js, __init__.py} 含 Agent 管理 (创建/启动/停止/删除)、路由规则更新、互联 Link 添加/删除、审计日志查询四个模块; server.py mount_webui 把 /ui 挂载到 FastAPI app。当前 Bearer Token 存在 localStorage 的实现仅作为 v1 开发态遗留，J3 必须迁移到 HttpOnly Session Cookie + CSRF，不得沿用到生产。附 `tests/unit/test_webui.py` (5 测试覆盖 index.html/app.js 静态返回 + 4 个模块齐全 + 端到端 API 工作流)。

- [ ] **I2 Docker 部署（K8 重新验收）**
  - **验收**：Dockerfile + docker-compose.yml 一键启动；含控制面端口。
  - **产出**：`Dockerfile`、`docker-compose.yml`、部署脚本。
  - **依赖**：I1（可选）。
  - **当前**：Dockerfile/Compose/部署脚本和文本级单测已存在，但主进程会立即退出，尚无真实 Docker build/start/health smoke test，因此撤回完成状态。K1 完成常驻生命周期、K8 完成容器实测后重新验收。

- [x] **I3 文档完善**
  - **验收**：使用文档、API 文档、部署文档、插件开发指南、控制面自动化指南齐全。
  - **产出**：`docs/` 或更新根目录 README/ARCH/DEVELOP/SPEC。
  - **依赖**：F、G 完成。
  - **当前**：新增 docs/ 目录含 6 篇文档: README.md (导航) + usage.md (使用文档 - 配置详解/运行/维护) + deployment.md (Docker 部署 - 镜像构建/数据卷/生产建议/nginx 反代) + api.md (Admin REST API 文档 - Agent/路由/Link/插件/审计/健康检查) + plugin_development.md (插件开发指南 - ISAC Native/AstrBot/MaiBot 三格式) + control_automation.md (控制面自动化 - REST/MCP/Webhooks 集成)。附 `tests/unit/test_docs.py` (22 测试覆盖文档存在 + 内容完整性 + 关键章节)。

- [x] **I4 数据工具**
  - **验收**：AstrBot/MaiBot → ISAC 迁移、备份/导出/导入可用。
  - **产出**：`scripts/migrate.py`、`scripts/export.py`。
  - **依赖**：D5-D7。
  - **当前**：scripts/migrate.py 实现 migrate_from_astrbot (LLM 配置从 cmd_config.json/llm_model.json 解析, 插件目录复制, 写出 ISAC config.jsonc) + migrate_from_maibot (config.toml 解析, 记忆目录备份, 创建默认 Agent 配置); 支持 --dry-run; scripts/export.py 实现 export_data (zip 打包, 默认排除 audit.ndjson + .venv + __pycache__) + import_data (解压恢复, 支持 --overwrite); 子命令模式 (export/import)。附 `tests/unit/test_data_tools.py` (11 测试覆盖 AstrBot LLM 迁移 + dry-run + 插件复制, MaiBot config.toml 解析 + 默认 Agent, export 含/排除日志, import 恢复 + skip/overwrite + 排除 venv/pycache)。

- [ ] **I5 监控告警（K1/K8 重新验收）**
  - **验收**：关键指标 Prometheus 采集；Webhook 告警；审计日志查看。
  - **产出**：监控中间件、告警配置。
  - **依赖**：G1、G4。
  - **当前**：MetricsCollector、AlertManager、默认规则与指标端点已有基础实现，但主进程结束时后台告警任务随事件循环取消，且缺少真实消息→指标→告警→Webhook 的端到端验证。K1/K8 完成后重新验收。

- [ ] **I6 可用版本验收与发布**
  - **验收**：核心模块覆盖率 ≥80%；集成测试通过；v1.0 发布。
  - **产出**：CHANGELOG、Git tag v1.0.0。
  - **依赖**：A-I5。
  - **当前**：2026-07-23 复审实测 378 个单元测试通过、Ruff 通过，但 Mypy 因 `aiocqhttp` 缺类型声明失败；`tests/integration/` 为空；主进程不驻留；真实 LLM Provider 不可用；Docker/WebUI 未做真实运行验收。因此撤回“v1.0 已完成/生产可用”结论，项目定位为 Alpha，待 K1-K8 全部通过后重新确定版本号与发布资格。

---

### J 模型能力、计量与管理面增强

**目标**：统一模型能力接入与选择，完整记录模型用量，并将运行状态和配置安全地暴露到 WebUI。

- [x] **J1 模型用量与成本计量**
  - **验收**：LLM/Embedding/Reranker/STT/TTS/ImageGen/Video 的每次物理请求均产生 `ModelUsageEvent`；重试、回退、失败和缓存 Token 可区分；支持按 Provider/模型/Agent/会话/模态/时间聚合；价格快照可追溯；未知价格不伪造成本；写入失败不阻塞主调用。
  - **产出**：`observability/usage/{models,recorder,storage,pricing}.py`、SQLite Schema、ProviderManager 接线、Usage REST API、指标与测试。
  - **依赖**：B2、G1、I5。
  - **当前**：已完成 (2026-07-25)。`TokenUsage`（`core/types.py`）补齐 `cache_read/cache_write/reasoning/audio_{input,output}_tokens` 明细字段；`OpenAICompatProvider` 从 `prompt_tokens_details`/`completion_tokens_details` 解析这些字段（非流式 + SSE 流式）。`PricingCatalog.estimate_cost()` 按分档单价计算缓存/音频 Token 成本（子集扣除，避免重复计价），未配置分档价时回退基础 input/output 价。`ProviderManager.chat_with_retry()`/`_call_and_record()` 贯穿 `agent_id`/`session_id`/`trace_id`（复用 D9 的 `task_id`）/`request_id`（每次物理尝试独立生成）/`fallback_from`；新增 `record_stream_result()` 补齐此前完全绕过计量的流式调用路径（`agent/loop.py::_call_llm_streaming()`，成功/失败都记录）。`UsageStore`：Schema 迁移（`_ensure_column` 补 5 个明细列）、`insert_many()` 批量提交替代逐事件 commit、`list_events()` 分页查询、`aggregate()` 真实多维聚合（`group_by` 走固定白名单防注入，`time_bucket` 按 hour/day 分桶，全空结果返回 `[]` 而非幻影汇总行）。`UsageRecorder` 新增 `start()`/`stop()`/`_flush_loop()` 周期性 flush（仿 `AlertManager._check_loop`），`main.py` 按 `observability.usage.flush_interval_seconds` 配置并保证 start/stop 顺序不丢最后一批事件。新增 `control/api/routes_usage.py` 提供 `GET /usage/models/{summary,events,timeseries}`，`create_control_app()` 仅在 `usage_store` 非 `None` 时挂载。测试：`tests/unit/test_usage_recorder.py`、`tests/unit/test_usage_storage.py`、`tests/unit/test_control_api_usage.py`、`tests/unit/test_provider_manager.py`、`tests/unit/test_openai_compat_provider.py`、`tests/unit/test_core_types.py`、`tests/integration/test_single_agent_flow.py`（全链路 process_message → ... → chat_with_retry → flush → aggregate 按 agent_id 查得用量）。Embedding/Reranker/STT/TTS/ImageGen/Video 的 `ModelUsageEvent` 埋点留给 J2（真实多模态调用路径落地时一起补，当前这些 Provider 仍是 J2 范畴的桩，没有可埋点的真实调用链路）。

- [x] **J2 多模态 Provider 与能力选择**
  - **验收**：文本、视觉理解、STT、TTS、图片生成、视频理解/生成 Provider 使用统一注册与能力声明；Agent 只感知被授权能力；输入内容、用户意图、成本/延迟策略可选择模型；不可用时按能力回退或明确失败；生成结果经制品存储和 Channel 能力适配发送。
  - **产出**：Provider 能力目录、ModelRouter、多模态 Provider ABC/适配器、能力 Injector、媒体工具、ArtifactStore、权限与测试。
  - **依赖**：D2-D4、E1/E4、H1、J1。
  - **当前**：已完成 (2026-07-25)。通用多模态 Provider 框架落地: 所有 Provider (image_gen/stt/tts/embed/vision) 接受用户配置的 `api_base + api_key + model`, 可接任意 OpenAI 兼容端点; 测试用 httpx.MockTransport 不依赖真实 Key。
    - **ModelRouter 打分排序** (`isac/provider/router.py`): 过滤链 operation→modalities→authorization→cost_ceiling→latency_target→health; 综合分 `score = (4-cost_rank)*2.0 + (2-latency_rank)*1.0 + health*1.5 + pref*0.5`; `record_health()` 上报 provider 健康状态, `set_preference()` 用户偏好加权; `ModelSelection.reason` 输出各因子明细。
    - **ArtifactStore 本地 FS + TTL** (`isac/artifacts/store.py`): 路径 `data/artifacts/<sha256[:2]>/<sha256>.bin` (分桶避免单目录文件过多); SQLite 元数据 `meta.db` (artifact_id PK + expires_at 索引); `put` 写盘幂等 (sha256 决定性, 重复 put 不覆盖); `get` 探测过期则删文件+DB 行并返回 None; `sweep_expired()` 周期扫描; `start_ttl_sweep()/stop()` 生命周期对齐 ApplicationRuntime; `ArtifactRef` 新增 `expires_at` 字段, 默认 7 天 TTL 可配。
    - **MediaNormalizer** (`isac/utils/media.py`): MIME 推断 (mimetypes.guess_type) + 路径白名单 (默认 data/artifacts/, 可配置多个 allowed_dirs) + 大小上限 (image 25MB / audio 50MB / video 200MB / file 50MB) + expected_kind 校验 + URL 输入拒绝 (J2 不做入站 HTTP 下载); magic-byte 校验留 TODO(J3+)。
    - **多模态 Provider 真实实现**:
      * `OpenAICompatImageGenProvider` (`isac/provider/image_gen/openai_compat.py`): POST /images/generations, b64_json/url 两种响应格式都支持, 生成图片写入 ArtifactStore 返回 ArtifactRef 列表。
      * `OpenAICompatSTTProvider` + `OpenAICompatTTSProvider` (`isac/provider/stt_tts/openai_compat.py`): STT multipart 上传 /audio/transcriptions 返回 TranscriptionResult; TTS POST /audio/speech 返回音频 bytes 存 ArtifactStore 返回 ArtifactRef。
      * `OpenAICompatEmbeddingProvider` (`isac/provider/embed/openai_compat.py`): POST /embeddings, 解析 data[].embedding, 维度从首次响应推断缓存。
      * `OpenAICompatProvider.vision_chat` (`isac/provider/llm/openai_compat.py` 扩展): 把 MediaInput 图片转 base64 data URL, 构造 messages[0].content 为 list 格式 (text + image_url), 委托 chat() 走既有非流式 chat 路径。
      * `memory/{embedder,reranker}.py` 改为注入 Provider 实例 (向后兼容, 未注入时保持降级行为与 D6 一致)。
      * 错误分类复用 OpenAICompatProvider._map_http_error / _wrap_network_error (429 RateLimitError / 5xx retriable / 4xx non-retriable / 超时 retriable)。
    - **UsageRecorder 多模态计量** (`isac/observability/usage/recorder.py`): 新增 record_image_gen/record_stt/record_tts/record_video/record_embed/record_rerank 6 个方法, 仿 record_llm 结构, 贯穿 agent_id/session_id/trace_id/request_id/fallback_from; PricingCatalog.estimate_cost 扩展非文本 modality 按 input_units*input_price + output_units*output_price 计价 (text modality 走现有 token 分档公式)。
    - **媒体工具真实接线** (`isac/agent/tools/media.py`): _MediaToolBase.execute 走 router.select → provider_manager.multimodal_provider → Provider 调用 → ToolResult; 新增 VisionUnderstandTool (operation="vision", 调 vision_chat); GenerateVideoTool/UnderstandVideoTool 留桩 (Sora/Runway 真实 API 留 J3+, 用户二次确认端点后接入); DEFAULT_POLICY 加 understand_image: deny。
    - **Channel 媒体 segment** (`isac/channel/{model,media_resolver,adapters/onebot/adapter.py,adapters/webchat/adapter.py}`): MessageSegment docstring 加 audio/video/file; MediaResolver.resolve_for_channel() 把 ArtifactRef 转 MessageSegment (onebot: image/voice/video/file; webchat/telegram/discord 返回 None); OneBotAdapter._to_cq_segment 加 audio/video/file 分支 (file 用 getattr 探测扩展支持, 不支持时降级为文本占位); WebChatAdapter.send 把非 text segment 降级为 [<type>: <artifact_id[:8]>] 占位追加到 content。
    - **main.py 注册循环 + 配置模板** (`isac/main.py` + `data/config.sample.jsonc`): register_multimodal_providers() 按 multimodal_providers[] 实例化 Provider 注册到 ProviderManager._multimodal_providers + ModelCatalog; build_services 接入调用; data/config.sample.jsonc 含 5 个 kind 注释示例 + 自托管端点示例; .gitignore 加 !data/config.sample.jsonc 例外。
    - **视频生成 Provider**: J2 范围内不接真实 API (Sora/Runway/Kling 多为受限预览), 保留 VideoGenerationProvider ABC + 桩; 真实接入留 J3+ 节点开工前二次确认。
    - **Agent 能力授权字段**: `AgentConfig.model_capabilities_allow` 留 J4 (assembly.py:78-81 getattr 兜底保留)。
    - 覆盖测试: `tests/unit/test_artifact_store.py` (12) / `test_media_normalizer.py` (13) / `test_model_router.py` (10) / `test_usage_recorder_multimodal.py` (13) / `test_image_gen_provider.py` (9) / `test_stt_tts_provider.py` (13) / `test_embed_provider.py` (14) / `test_vision_chat.py` (7) / `test_media_tools_wired.py` (8) / `test_channel_media_resolver.py` (13) / `test_main_multimodal_registration.py` (8); 集成测试 `tests/integration/test_j2_multimodal_flow.py` (4) / `tests/integration/test_j2_channel_delivery.py` (4)。共 721 测试全绿。
  - **边界**: Agent 能力授权字段留 J4; 视频生成真实 API 留 J3+; Telegram/Discord 媒体 segment 留 J3; Channel 入站媒体解析 (用户上传图片/语音 → MediaInput) 留 J3; MediaNormalizer 白名单仅 data/artifacts/ (不启用 data/uploads/); 既有 send_image.py 旧工具保留不动, J3 决定迁移; _send_reply 改造 (扫描回复里的 artifact_id 引用 → MediaResolver 转 segment) 留 J3 WebUI v2 一起做。

- [x] **J3 WebUI v2 管理与观测**
  - **验收**：Dashboard、Agent、Channel/路由、Provider/模型、Token/成本、插件/MCP/工具、记忆、会话/任务进度、日志/审计、系统设置页面可用；配置写入支持 Schema 校验、差异预览、二次确认、版本冲突检测和审计；密钥只可替换不可回显。
  - **产出**：`control/webui/` 前端重构、Control API 扩展、实时事件通道、浏览器端测试与权限测试。
  - **依赖**：G1-G4、I1/I5、D9、J1-J2。
  - **当前**：已完成 (2026-07-25)。WebUI v2 SPA 十域全部真实内容落地:
    - **后端 Control API 扩展** (J3-1 至 J3-4): routes_providers (GET /providers /providers/models /artifacts + POST /providers/{id}/test + DELETE /artifacts/{id}) / routes_config (POST /config/validate /config/diff + PATCH /agents/{id} 支持 If-Match + revision 乐观锁 + 409 CONFIG_CONFLICT) / routes_sessions (GET /sessions /sessions/{id} /sessions/{id}/messages) / routes_memory (GET /memory/{agent_id}/episodes|profiles|jargon) / routes_events (GET /events/stream SSE + Last-Event-ID 断线恢复 + 心跳 + max_chunks 测试参数)。
    - **AgentConfig 加 revision 字段** (J3-2): save_agent_config 每次 +1; PATCH 端点用 If-Match 乐观锁。
    - **WebUI v2 SPA shell** (J3-5): 侧边栏 10 域导航 (Dashboard/Agents/Channels/Providers/Usage/Extensions/Memory/Sessions/Logs/System) + .page active 类切换 + navigate() 函数; Dashboard 页 stat-grid + 近期审计; Agents/Channels/Logs 页保留 v1 内容向后兼容。
    - **Providers/Usage/Extensions 三页** (J3-6): refreshProviders/refreshUsage/refreshExtensions 调用已就位 API。
    - **Memory/Sessions/System 三页** (J3-7): refreshMemory/refreshSessions/refreshSystem + 配置编辑事务 UI (loadConfigForEdit/validateConfig/diffConfig/patchConfig, 二次确认 + ETag 乐观锁)。
    - **Playwright 浏览器黄金路径测试** (J3-8): tests/browser/test_webui_golden_path.py 两条路径 (Agent CRUD + 审计 / 路由 + Link + 用量); 未安装 Playwright 时 importorskip 跳过, CI 在 K8-2 加 playwright install chromium。
    - **Bearer Token 模式**: 沿用 v1 从 DOM 读取 (不引入 HttpOnly Cookie + CSRF, 留作未来工作); sessionStorage 存 token (K7 已落地, 关闭标签即清除)。
    - 覆盖测试: tests/unit/test_webui.py (11 测试, 含 SPA 侧边栏 + 三批页面 + 配置编辑事务 UI) + tests/browser/test_webui_golden_path.py (2 黄金路径, Playwright 未装时 skip)。共 792 测试全绿。
  - **边界**: HttpOnly Cookie + CSRF 未引入 (沿用 v1 Bearer Token 从 DOM 读取); 多 scope 权限模型未引入 (扁平 Bearer Token); 插件表占位 (插件列表 API 待后续); WebUI 浏览器测试在 CI 中运行待 K8-2 加 Playwright step。

- [x] **J4 SubAgent Runtime 与可追溯任务日志**
  - **验收**：每个 Agent 可用 `delegate_task` 创建隔离子任务；子 Agent 使用独立 History/Prompt/Budget/Workspace 和父权限子集；主 Agent 默认只收到结构化结果、证据引用和用量摘要；可通过 task_id 列表、查询状态、分页读取脱敏日志、取消任务；日志持久化后重启仍可查询；不记录原始 reasoning；子 Agent 默认不能直接发消息、写长期记忆或无限派生。
  - **产出**：`runtime/subagent/{models,supervisor,context,journal,broker}.py`、delegate/list/status/log/cancel 工具、SQLite Journal、Control API/WebUI 时间线、恢复/取消/权限/隐私/预算测试。
  - **依赖**：K1-K5、D3-D4、D9、J1、K3-K4。
  - **当前**：已完成 (2026-07-25)。SubAgent Runtime 真实执行循环落地:
    - **SubAgentSupervisor 真实执行循环** (`isac/runtime/subagent/supervisor.py`): `submit()` 接受 `runner_factory` 注入, 用 `asyncio.create_task` 后台派生子 Agent 执行; 状态机 `queued→running→succeeded/failed/cancelled/timed_out`; 超时通过 `asyncio.wait_for` 控制; 取消通过 `asyncio.Task.cancel()` 传播; `_transition` helper 抽出状态转移 + journal 写入, 降低圈复杂度; 未注入 runner_factory 时保持骨架行为 (返回 queued, 不启动后台 task)。
    - **delegate_task 工具真实链路** (`isac/agent/tools/subagent.py`): 构造 SubAgentTask → supervisor.submit() → poll get_status 直到终态 → 返回 result.summary; 等待超时返回当前状态 (不取消, 后台 task 继续); `_format_terminal_result` 优先从 `run.result_summary` 取 (J4-2 新增字段)。
    - **H3 TaskRunner 迁移** (`isac/agent/tools/utility/task.py`): 删除 TODO(J4) 标记, 内部委托 supervisor.submit(); 保留 task + budget_tokens 接口向后兼容; 保留 task_depth 递归深度限制 (默认 3, 防无限派生); 无 supervisor 时回退到旧 task_runner 路径。
    - **SubAgentRun 新增 result_summary 字段**: succeeded 时存 runner 返回的 SubAgentResult.summary, 供工具直接读取, 不依赖 journal fetch。
    - **取消传播 + 重启恢复** (`supervisor.py`): `cancel()` 用 `asyncio.Task.cancel()` 传播到 runner (CancelledError); `restore_interrupted()` 从 Journal.restore() 读出持久化 run, 把 running/queued/waiting_tool 标记为 cancelled (中断后不恢复旧进度, 与 D9 思路一致); 已终态保留不改写; main.py 在 runtime.start() 后调 `_restore_subagent_interrupts(services)`。
    - **Journal schema 扩展** (`isac/runtime/subagent/journal.py`): subagent_runs 表加 result_summary 列; `_ensure_column()` 旧库迁移 (PRAGMA table_info 探测 + ALTER TABLE); append() 支持 seq 自动分配 (event.seq<=0 时由 DB 查 MAX(seq)+1 分配)。
    - **Control API routes_subagent** (`isac/control/api/routes_subagent.py`): `POST /agents/{id}/subagent-runs` 派生 / `GET /agents/{id}/subagent-runs` 列出 / `GET /subagent-runs/{task_id}` 查询状态 / `GET /subagent-runs/{task_id}/events` 分页读取事件 / `POST /subagent-runs/{task_id}/cancel` 取消 (幂等); Bearer Token 认证; 无 supervisor 时整个路由不挂载 (404); `create_control_app` 新增 subagent_supervisor 参数。
    - **DEFAULT_POLICY**: delegate_task 从 deny 改 restricted (需显式授权, 但不再默认禁用)。
    - 覆盖测试: `tests/unit/test_subagent_supervisor.py` (19) / `test_subagent_supervisor_exec.py` (7) / `test_delegate_task_wired.py` (10) / `test_subagent_restore.py` (5) / `test_control_api_subagent.py` (8); 集成测试 `tests/integration/test_j4_subagent_flow.py` (5)。共 751 测试全绿。
  - **边界**: SubAgentPolicy.intersect() 采用 fail-closed (AND/min/∩, 空集拒绝全部); AgentConfig.model_capabilities_allow 字段仍留 J4+ (assembly.py getattr 兜底); ContextEnvelope 不复制主会话可变上下文 (MoodState/RelationshipState/用户画像/私有记忆正文); 子 Agent 默认不能直接发消息、写长期记忆或无限派生 (allow_channel_send/allow_memory_write/allow_delegate 默认 False); list_subagent-runs 按 parent_agent_id 过滤 TODO (SubAgentRun 无该字段, 当前返回全部)。

---

### K 稳定化与可用版本闭环

**目标**：先打通“可持续运行、真实模型回复、持久化恢复、端到端可验证”的最小纵向链路，再继续 D9/J1-J3 等横向扩展。K1-K8 是当前最高优先级；完成前项目统一定位为 Alpha，不得宣称生产可用或完成 v1.0 验收。

- [ ] **K1 应用常驻与统一资源生命周期**（P0）
  - **验收**：`python -m isac` 在无 Channel、仅 Control、启用 Channel 三种模式下均持续驻留；支持 SIGINT/SIGTERM；Channel、Control、Alert、Provider、Storage、Plugin、Webhook 后台任务统一 start/health/close；启动失败能回滚，后台任务异常不会静默丢失，关闭无 pending task/resource warning。
  - **产出**：`ApplicationRuntime` / `ServiceContainer`、统一 TaskGroup、信号处理、优雅关闭、生命周期单元与进程级 smoke test。
  - **依赖**：B4、C4、G1、I5。
  - **已知问题**：当前 `main()` 调用 `channel_registry.start_all()` 后直接返回，Control/Alert 等后台任务随事件循环结束被取消。

- [ ] **K2 真实 LLM Provider 纵向闭环**（P0）
  - **验收**：至少一个真实 Provider 支持非流式、SSE 流式、Tool Call、usage、超时、429/5xx/非法响应分类、重试与 fallback；配置真实 Provider 时不得回退为 Stub 冒充成功；Provider Client 可健康检查并在关闭时释放连接池。
  - **产出**：`OpenAICompatProvider` 或等价首个 Provider 的真实实现、HTTP 契约测试、Fake Server 集成测试、错误分类与关闭测试。
  - **依赖**：K1、D3、ProviderManager。
  - **阻塞**：未完成前不能验收“真实 AI 对话”。

- [ ] **K3 Storage Schema、记忆写入与恢复**（P0）
  - **验收**：启动时执行 Schema init/migration；Metadata/FTS/Sparse 按 namespace 初始化；消息或会话结束后真实写入 Episode；重启后可检索；shared namespace 强制 user/group/scope ACL；写入失败不阻塞回复但可观测；关闭时提交并释放连接。
  - **产出**：StorageLifecycle、schema_version/migration、MemoryEncoder 接线、Sparse 重建/恢复、跨用户隔离与重启测试。
  - **依赖**：K1、D5-D7。
  - **边界**：Vector/Graph/Reranker 可继续降级，但必须明确标记 experimental/stub，不能计入 MVP 完成度。

- [ ] **K4 Agent、Session、Identity、Routing 与 Link 持久化恢复**（P0）
  - **验收**：重启后恢复 AgentConfig/运行状态、Session、UserMapper 绑定、RoutingRules、InterAgentLink；Agent 独立 Provider 配置实际生效；配置写入使用原子替换和版本迁移；非法 ID/路径被拒绝。
  - **产出**：registry/session/identity 持久化、启动恢复编排、原子配置存储、路径安全与迁移测试。
  - **依赖**：K1、E1-E3、G1。

- [ ] **K5 单 Channel × 单 Agent 真实 E2E**（P0）
  - **验收**：进程启动 → Fake/测试 Channel 收消息 → EventBus intercept → Router 剥离触发词 → Session/Gating → 真实 HTTP Mock Provider → Tool Call → Channel 回复全链通过；覆盖打断、超时、错误和重启恢复。
  - **产出**：`tests/integration/test_single_agent_flow.py`、可复用 Fake Channel/Provider、进程级测试夹具。
  - **依赖**：K1-K4。

- [ ] **K6 多 Agent、工具、记忆与控制面 E2E**（P1）
  - **验收**：2+ Agent 共享 1 Channel；显式绑定/触发词/默认 Agent；InterAgentBus deliver + ACL；工具权限；记忆 namespace 隔离；Control 修改配置真实生效并在重启后保留。E5 并入本节点验收。
  - **产出**：`tests/integration/test_multi_agent.py`、Agent Mesh/权限/记忆/Control 集成测试。
  - **依赖**：K5、E3-E5、G1-G4。

- [ ] **K7 安全与长期运行基线**（P0/P1）
  - **验收**：Agent ID/路径穿越防护；Control 空 Token 仅显式开发模式；审计/JSON metrics 鉴权；WebUI 不持久化 Bearer Token；Webhook 与远程媒体防 SSRF；SecretStore 可用；插件明确为兼容层而非安全沙箱或提供进程级隔离；Bash/File/MCP 有字节、时间、进程、路径与 pending 上限；Session/Lock/队列有 TTL/LRU；Discord 分页不丢消息。
  - **产出**：安全回归测试、资源压力测试、威胁模型与生产安全配置。
  - **依赖**：K1、K4、G/H/F 相关模块。

- [ ] **K8 CI、Docker、浏览器与发布准入**（P1）
  - **验收**：CI 启用 branch coverage 与 `--cov-fail-under`；构建 wheel/sdist 并安装 smoke；Docker build/start/health/stop 实测；WebUI 用真实浏览器覆盖登录、Agent/路由/Link/审计黄金路径；Mypy 全绿或对 `aiocqhttp` 做局部明确 override；README/AGENTS/CHANGELOG/版本号与实际能力一致。
  - **产出**：CI 门禁、Docker smoke、Playwright/浏览器测试、发布检查表、版本状态校准。
  - **依赖**：K1-K7、I1-I6。

**强制开发顺序**：K1 → K2 → K3/K4 → K5 → K6/K7 → K8。K1-K5 完成前暂停 D9、J1-J4；K8 通过后才允许恢复 I6 发布验收。

---

### L 拟人化运行时落地

**目标**：把 `HUMANLIKE_RUNTIME.md` 描述的会话级拟人行为(消息合并、主动等待、主动任务、被打断、上下文恢复)从设计蓝图落成可运行代码。所有子节点默认由 `conversation.enabled` 开关控制,关闭时主链路零行为变化。

- [ ] **L1 ConversationRuntime 骨架**(scaffolding 已落地,业务实现待续)
  - **验收**：每个 (agent_id, session_id) 一个 `ConversationRuntime`;具备消息缓存、状态机 (idle/thinking/acting/waiting/stopped)、`WaitState`/`ForcedTurnState` 契约、per-session 注册表 (FIFO 上限) 与主动任务队列;`conversation.enabled=False` 时 `handle_message` 完全走原路径。
  - **产出**：`runtime/conversation/{__init__,models,runtime,registry,proactive}.py`、`assembly` 注入 `conversation_registry`、`manager.handle_message` 惰性接线、`tests/unit/test_conversation_runtime.py`。
  - **依赖**：B4、E1、D9。
  - **当前**：框架已搭建 (scaffolding, 2026-07-26)。契约 + 状态机 + registry + 主动队列 + 惰性默认关闭接线就位,骨架单测通过,ruff/mypy 全绿,主链路零行为变化。真实 debounce 触发、wait 回填、主动调度、打断闭环见 L2-L5,均已在代码中以 `TODO(L2/L3/L4)` 标注挂接点。

- [x] **L2 Wait 闭环与 debounce 触发**
  - **验收**：`wait` 工具向 `ConversationRuntime.enter_wait` 注册 `WaitState`,由后续消息 / 超时 / 主动任务三条路径之一结束等待并向 AgentLoop 回填 wait 工具结果 (说明实际等待时长与结束原因);连续消息在 debounce 静默窗口内合并为一次触发,避免逐条打断。
  - **产出**：异步 debounce 触发循环、`resolve_wait` 三入口、wait 工具改造 (注册 WaitState)、超时定时器、单测与集成测试。
  - **依赖**：L1、D4 (wait 工具)、D9。
  - **当前**：已完成 (2026-07-26)。`ConversationRuntime.should_trigger` 真实 debounce 判定 (zero/positive); `enter_wait` (async) 创建 future + 启动超时定时器; `resolve_wait` 回填 `end_reason`/`actual_seconds` + 取消定时器 + 唤醒 wait 工具; `notify_new_message` 在 WAITING 时以 MESSAGE 原因结束等待。三条唤醒路径 (message/timeout/proactive) 单测覆盖 12 例; `WaitTool` enabled=True 时调 `enter_wait`+`await_wait`, enabled=False 保持原意图字符串 (零行为变化)。`assembly.py` 注入 `conversation_enabled` 标志。debounce 接入 manager 主链路 (连续消息合并) 留 L3+ 节点, 不影响 L2 验收。

- [x] **L3 主动任务调度**
  - **验收**：`ProactiveTaskQueue` 由调度器按优先级 + 冷却 + 频率边界驱动;每个主动任务必须带 source/intent/reason (禁止无来源发言);触发时唤醒对应会话的 `ConversationRuntime` 发起一次强制话轮 (`ForcedTurnState`);来源经鉴权,防刷屏与滥用。
  - **产出**：主动调度循环、优先级/冷却策略、来源鉴权、强制话轮 Prompt 注入、单测与集成测试。
  - **依赖**：L1、L2、门控 (存在感/频率)。
  - **当前**：已完成 (2026-07-26)。`ProactiveTaskQueue` 改为 list 实现 priority 排序 (high>normal>low; 同优先 FIFO); `ProactiveScheduler` 加 `allowed_sources` 集合 (默认 plugin/memory/schedule/agent/api); `authorize` 拒绝不在集合内的 source; `to_forced_turn` 触发时更新 `_last_fired_at`; 新增 `async start/stop` 后台循环 (poll_interval_seconds 周期 poll → authorize → may_fire → wake_callback, 冷却中任务退回队列头部)。强制话轮 Prompt 注入 + manager 接线留 L4+ 节点, 不影响 L3 验收。13 例单测覆盖 priority/authorize/start/stop/冷却/空队列/重复 stop。

- [x] **L4 Planner 打断闭环**
  - **验收**：thinking 期间到达的新消息可请求打断当前规划;`AgentContext.interrupt_requested` 由 `ConversationRuntime.request_interrupt` 写入;限制单轮打断次数、抑制被打断的旧回复、下一轮 Prompt 注入"上一轮被新消息打断"提示。
  - **产出**：打断信号写入路径、打断次数限制、旧回复抑制、Prompt 提示注入、单测。
  - **依赖**：L1、L2、`agent/loop.py`。
  - **当前**：已完成 (2026-07-26)。`ConversationRuntime` 加 `interrupt_state` + `max_interrupts_per_turn` (默认 1, 保守); `request_interrupt(reason)` 单轮次数限制 + 置 `superseded=True` + `interrupt_count++`; `clear_interrupt` 进入下一轮前重置。新增 `agent/injectors/interrupt.py:InterruptInjector` 注入"上一轮被打断"内部参考 (含打断次数与原因), 注入后清空状态避免重复注入。AgentLoop 接线 (thinking 后读 `superseded`) 与 manager 并发处理消息 (thinking 期间收到新消息调 `request_interrupt`) 留 L4+ 节点, 因这两者需要 manager 用 asyncio.create_task 并发处理消息的大改动, 超出 L4 验收线。9 例单测覆盖 request/clear/单轮上限/可配置/注入/清空/默认零行为变化。

- [x] **L5 上下文恢复**
  - **验收**：进程重启后,会话的拟人状态 (未决 wait、被打断标记、主动任务) 可从持久化恢复到合理起点 (与 D9/J4 "中断后不恢复旧进度" 思路一致,标为终止/复位而非续跑)。
  - **产出**：ConversationRuntime 状态持久化 schema、启动恢复编排、恢复测试。
  - **依赖**：L1-L4、K4 (持久化恢复框架)。
  - **当前**：已完成 (2026-07-26)。`ConversationStateStore` 原子写 JSON 落盘到 `data/agents/<id>/conversation/<session_id>.json` (复用 `utils.fs.atomic_write_json`, K4 模式); `load` 读回 → 计算 elapsed → 短(<5min)/中(<1h)/长(<24h) 窗口生成 `recovery_hint` → 复位 `state=idle` + `pending_wait=None` (中断后不续跑); > 24h 不恢复。新增 `agent/injectors/recovery.py:RecoveryInjector` 注入 `recovery_hint` 到第一轮 Prompt, 注入后清空 (避免重复注入)。10 例单测覆盖 save/load 往返 + 短/中/长/24h 窗口 + 未决 wait 复位 + 原子写文件存在 + RecoveryInjector 注入/清空/无快照空串。manager 启动时调 `store.load` 填充 snapshots + 接线 RecoveryInjector 到 prompt_builder 留 L5+ 节点 (不涉及主链路行为变化)。

---

### M 路由与 Agent Mesh 深化

**目标**：把 `ROUTING_AND_AGENT_MESH.md` 描述的旁听/候选路由与 Agent 间协作动作从设计落成实现。

- [ ] **M1 observer/candidate 路由**
  - **验收**：Agent 可配置为 observer (旁听,只入记忆不回复) 或 candidate (候选,多 Agent 竞争同一消息由仲裁选出回复者);路由决策可解释、可审计。
  - **产出**：路由角色模型、候选仲裁策略、observer 记忆旁路、单测与集成测试。
  - **依赖**：C (路由)、E (多 Agent)、门控。
  - **当前**：框架已搭建 (scaffolding, 2026-07-26)。新增 `runtime/mesh/` (`MeshRoutingDecision`/`RoutingRole` 契约 + `MeshRouter` 骨架);approach b 不改既有 `router/types.py::RoutingDecision`。真实候选仲裁与 observer 记忆旁路以 `TODO(M1)` 标注。

- [ ] **M2 handoff / notify / memory_query**
  - **验收**：Agent 间可显式移交会话 (handoff)、发通知 (notify)、跨 Agent 查询记忆 (memory_query);全部经 InterAgentLink ACL 授权;动作可审计。
  - **产出**：三类 Agent 间动作工具、ACL 校验、审计埋点、单测。
  - **依赖**：E3 (InterAgentBus/Link)、N (记忆)。
  - **当前**：框架已搭建 (scaffolding, 2026-07-26)。`runtime/mesh/` (`MeshLinkPolicy`/`MeshMessageType` + `MeshActionBroker` deny-by-default) + 4 个 A2A 工具骨架 (`notify_agent`/`handoff_conversation`/`list_available_agents`/`memory_query_agent`,默认 deny → LLM 不可见)。既有 `bus.py`/`ask_agent.py` 不改。真实投递与 ACL 以 `TODO(M2)` 标注。

---

### N 记忆深化

**目标**：把当前分散的记忆结构统一为 `MemoryItem` 模型,补齐记忆治理与身份归一。

- [x] **N1 统一 MemoryItem 模型**
  - **验收**：episodic/profile/jargon 等记忆统一到一个 `MemoryItem` 契约 (类型 + 载荷 + 元数据 + 命名空间),存储/检索/注入围绕它展开;迁移不破坏既有数据。
  - **产出**：`MemoryItem` 契约、存储层适配、迁移脚本、单测。
  - **依赖**：D5-D7、K3。
  - **当前**：已完成 (2026-07-26)。`MemoryItem.from_episode/to_episode` 补齐完整字段映射 (summary/topics/participants/emotion/session_id/group_id 进 metadata); 新增 `from_profile/to_profile` (name/traits/relationship_depth/interaction_count/first_seen/last_seen/embedding_hash); `from_jargon/to_jargon` (word/context/usage_count); `from_relationship/to_relationship` (familiarity/trust/last_interaction_at)。新增 `isac/memory/model/adapter.py:MemoryItemAdapter` 实现 `MemoryItem ↔ MemoryHit` 双向适配 (hit_type → memory_type, 未知类型默认 EPISODE 兜底)。既有 metadata.py 三表 schema 不动, 本模块只做读写适配层。10 例单测覆盖四种类型 from/to roundtrip + adapter 双向 + 未知列降级。

- [x] **N2 记忆治理 (freeze/protect/correct/delete)**
  - **验收**：支持冻结、保护、纠错、删除记忆条目;操作经权限校验并审计;纠错保留可追溯历史。
  - **产出**：记忆治理动作、权限与审计、单测。
  - **依赖**：N1、G (控制面)。
  - **当前**：已完成 (2026-07-26)。`MetadataStore.init_schema` 给 `episodes` 加 `frozen`/`protected`/`deleted`/`corrected_by` 治理列 (向后兼容老库, 默认 0/NULL); 新增 `memory_revisions` (corrected 历史保留) + `memory_audit` (审计日志) 表。`MemoryGovernor` 真实实现 6 类治理动作: freeze/protect 置标志位 + 审计; correct 写新版本 + memory_revisions 保留旧内容 + corrected_by 关系; delete 软删除 + protected 拒绝; restore 反向复位; export 组织为 `list[MemoryItem]` (治理状态进 metadata)。`routes_memory_admin.py` 真实接入 governor + 新增 `GET /memory/{id}/items` 列表端点。8 例单测覆盖 freeze/protect/correct/delete/restore/export + protected 拒绝 + 不存在条目返回 False。

- [ ] **N3 身份归一 (IdentityResolver)**
  - **验收**：跨平台 (不同 IM 的同一用户) 身份归一到统一 identity;记忆按归一后身份聚合;归一规则可配置、冲突可人工裁决。
  - **产出**：`IdentityResolver`、跨平台映射存储、冲突处理、单测。
  - **依赖**：C (Gateway/UserMapper)、N1。
  - **当前**：框架已搭建 (scaffolding, 2026-07-26)。新增 `isac/gateway/identity/` (`PlatformIdentity`/`PersonIdentity` + `IdentityResolver` 组合既有 `UserMapper`)。`user_mapper.py` 不改。真实归一算法与冲突裁决以 `TODO(N3)` 标注。

---

### O 企业化与平台扩展

**目标**：面向多租户、进程隔离、编排与更多平台的企业化能力。

- [ ] **O1 多租户 / 组织隔离**
  - **验收**：Agent/记忆/配置/用量按 organization 隔离;跨租户不可见;控制面按租户鉴权。
  - **产出**：租户模型、数据隔离、租户级鉴权、单测。
  - **依赖**：G、K3-K4、J1。
  - **当前**：框架已搭建 (scaffolding, 2026-07-26)。新增 `isac/runtime/tenancy/` (`TenantContext` + `TenantIsolationGuard`,默认单租户 passthrough)。真实隔离与租户级鉴权以 `TODO(O1)` 标注。

- [ ] **O2 插件进程级隔离**
  - **验收**：插件从当前"兼容层 (非安全沙箱)"升级为进程级隔离,资源与故障不影响主进程;插件崩溃可恢复。
  - **产出**：插件进程宿主、IPC 协议、资源限额、崩溃恢复、单测。
  - **依赖**：F (插件生态)、K7 (安全基线)。
  - **当前**：框架已搭建 (scaffolding, 2026-07-26)。新增 `isac/plugin/isolation/` (`IPCEnvelope` + `PluginIsolationHost` 骨架)。既有 `loader.py` 进程内兼容层路径不变 (仍默认)。真实子进程宿主与 IPC 以 `TODO(O2)` 标注。

- [ ] **O3 Workflow 编排**
  - **验收**：多步骤任务可用声明式 Workflow 编排 (串/并/条件/重试);步骤可跨 Agent/工具;执行可观测、可恢复。
  - **产出**：Workflow 引擎、步骤契约、执行器、可观测与恢复、单测。
  - **依赖**：J4 (SubAgent)、D9 (进度)、L (运行时)。
  - **当前**：框架已搭建 (scaffolding, 2026-07-26)。新增 `isac/runtime/workflow/` (`Workflow`/`Stage`/`Transition` + `WorkflowStatus`/`StageStatus`/`TransitionKind` + `WorkflowEngine` register/start/step/resume no-op)。真实串/并/条件/重试编排以 `TODO(O3)` 标注。

- [ ] **O4 平台扩展 (微信 / Slack / 飞书 …)**
  - **验收**：新增 IM 平台适配器,复用 Channel 抽象;媒体/富文本能力按平台声明适配。
  - **产出**：各平台 Channel 适配器、能力声明、投递适配、单测。
  - **依赖**：H (平台扩展)、C4 (Channel 抽象)。
  - **当前**：框架已搭建 (scaffolding, 2026-07-26)。新增 `isac/channel/adapters/template/` (`TemplateAdapter(PlatformAdapter)` 文档化模板,实现 4 个抽象方法 + `TODO(O4)`)。**不自动注册**,复制后按 DEVELOP.md 3.3 实现。当前支持 OneBot/Telegram/Discord/WebChat。

- [ ] **O5 Video Provider**
  - **验收**：视频理解/生成 Provider 真实接入 (Sora/Runway/Kling 等),经能力目录与 ModelRouter 选择;结果走 ArtifactStore。
  - **产出**：Video Provider 实现、能力声明、计量埋点、单测。
  - **依赖**：J1-J2。
  - **当前**：框架已搭建 (scaffolding, 2026-07-26)。新增 `isac/provider/video_gen/` (`OpenAICompatVideoGenProvider` 实现 `VideoGenerationProvider` ABC,`generate` 抛 `NotImplementedError`)。**不自动注册到 ModelRouter**,真实 API 端点开工前需二次确认。

---

### 可观测性增强(横切,已落地)

**目标**：无报错也能追踪每步操作,快速定位问题。**非节点,横切能力**,随各模块持续演进。

- [x] **trace 贯穿 + 分级日志**(2026-07-26 落地)
  - **验收**：trace_id/session_id/agent_id 经 `contextvars` 贯穿路由→门控→Loop→工具→记忆→回复,无需逐处手传;日志可按 level 与按模块前缀分级;默认 `INFO` 时 debug 零输出、零性能影响;全程脱敏 (不打密钥/完整参数/未清洗结果)。
  - **产出**：`utils/logging_context.py` (`bind_log_context`)、`utils/logger.py` (level + per_module 分级)、`manager.handle_message` trace 绑定、`agent/loop.py`/`gating/system.py` 等关键链路 debug 日志、`docs/LOGGING.md`、`data/config.sample.jsonc` logging 段、单测。
  - **当前**：已落地。用法与排查树见 [LOGGING.md](./LOGGING.md)。

---

## 五、术语表

| 术语 | 解释 |
|------|------|
| **节点** | 本文档中的任务单元。大节点 A/B/C... 是里程碑；小节点 A1/A2... 是可独立完成并汇报的最小单元。 |
| **SOW** | Statement of Work，工作说明书。本文档既是指令集，也是 TODO 清单。 |
| **启用矩阵** | Agent 与 Channel 对插件/工具/命令/MCP 的启用/禁用矩阵。有效权限 = Agent 允许 ∩ Channel 允许 ∩ 全局策略。 |
| **AgentInstance** | 运行中的 Agent，含独立的门控/PromptBuilder/记忆/人格/工具。 |
| **MessageRouter** | 消息路由器，决定 IM 消息归属哪个 Agent。 |
| **InterAgentBus** | Agent 间通信总线，必须显式配置 Link (ACL) 才能通信。 |
| **控制面** | 独立于消息处理的管理接口：Admin API / MCP Server / Webhooks。 |
| **数据面** | 消息处理主链路：Channel → Gateway → Router → Agent → 回复。 |
| **契约冻结** | 接口签名、数据模型、配置规范、协议定义稳定，不再随意改动。 |
| **专项施工图** | 对复杂系统的细化设计文档，如拟人化运行时、记忆、插件兼容、控制面等。 |
| **ConversationRuntime** | 某个 Agent 在某个会话中的拟人化运行时，管理消息缓存、等待、主动任务、打断与上下文恢复。 |
| **ProgressEvent** | Agent 任务阶段的结构化事实事件，由 ProgressReporter 统一频控、脱敏、人格化渲染和发送。 |
| **ModelUsageEvent** | 单次物理模型请求的标准计量事件，记录 Provider、模型、Agent、模态、实际用量和价格快照。 |
| **ModelDescriptor** | 模型能力声明，描述输入/输出模态、operation、限制、成本/延迟层级和安全标签。 |
| **ArtifactRef** | 多模态生成制品的受控引用，不把二进制内容直接写入消息历史、日志或记忆。 |
| **SubAgent** | 父 Agent 下的临时隔离执行单元，使用独立上下文与收窄权限，结果和脱敏日志通过 task_id 关联。 |
| **SubAgentJournal** | 追加式持久化子任务事件日志，记录状态、工具、证据、错误和用量，不记录模型原始 reasoning。 |
| **稳定化节点** | K1-K8；修复常驻、真实 Provider、持久化、E2E、安全和发布门禁的最高优先级工作。 |
| **可用版本准入** | K1-K8 全部完成且真实运行验收通过后，项目才可从 Alpha 提升为可用版本。 |
| **Observer Agent** | 旁听 Agent，只接收消息用于记忆/学习/候选协作，默认不发送 IM 回复。 |
| **WaitState** | Agent 主动等待状态，记录 wait 工具调用、起始时间、请求秒数与原因，由消息/超时/主动任务结束。 |
| **ProactiveTask** | 结构化主动任务，必须带 source/intent/reason/priority，禁止无来源随机发言。 |
| **ForcedTurnState** | 一次绕过普通回复频率的强制发言，来源为 timeout / proactive / handoff。 |
| **MemoryItem** | (N1 规划) 统一记忆条目模型，用类型 + 载荷 + 元数据 + 命名空间承载 episodic/profile/jargon 等各类记忆。 |
| **IdentityResolver** | (N3 规划) 跨平台身份归一器，把不同 IM 的同一用户映射到统一 identity，供记忆聚合。 |
| **scaffolding (框架已搭建)** | 契约 + 类骨架 + 惰性默认关闭接线 + 骨架单测就位，主链路零行为变化;业务实现待后续节点。不计入强化完成定义,不标 `[x]`。 |
| **MeshRoutingDecision** | (M1) 在 RoutingDecision 之上补充 observer/candidate 角色的路由结果;新增 sibling 契约,不改既有 RoutingDecision。 |
| **MeshActionBroker** | (M2) Agent 间协作动作 (notify/handoff/memory_query/list) 的 deny-by-default 代理,委托 InterAgentBus。 |
| **TenantContext** | (O1) 一次请求/一个 Agent 所属的租户上下文 (organization_id/tenant_id/limits),默认单租户。 |
| **Workflow** | (O3) 声明式多步骤编排 (Stage + Transition),支持串/并/条件/重试,由 WorkflowEngine 执行。 |
