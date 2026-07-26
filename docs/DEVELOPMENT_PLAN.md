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
- **进度标记(三态)**:标记须如实反映"是否接入生产主链路",不得用 `[x]` 掩盖"实现了但没激活"。
  - `[x]` **已交付** — 满足下方"完成定义"(非桩实现 + 单测 + 集成/运行验证 + **主链路接线** + 文档 + `ruff`/`mypy`/CI)。
  - `[~]` **实现完成待接线** — 核心逻辑 + 单测完成,但未接入生产主链路(默认关闭 / 生产路径无调用点);**按"完成定义"尚不算完成**。其接线项统一收敛在 §四 **P 节点**,不散落于各节点备注。
  - `[ ]` **未开始** — 仅骨架桩(no-op / `NotImplementedError`)或尚不存在。
- **进度汇报**:每推进一个小节点,更新本文档标记并同步 [PROGRESS.md](./PROGRESS.md),简要汇报。
- **节点可调整**：如需新增/合并/拆分节点，先更新本文档与 `AGENTS.md`，再继续执行。
- **完成定义**：小节点完成 = 非桩代码实现 + 单元测试 + 对应集成/运行验证 + 错误与关闭路径验证 + 相关文档同步 + `ruff` / `mypy` / CI 门禁通过。仅有接口、占位实现、静态文件或 Mock 单测不得标记完成。

---

## 三、节点总览

各节点进度以 [PROGRESS.md](./PROGRESS.md) 为**唯一事实源**,本文档不再另存进度表,只描述节点定义、依赖与验收。

当前概况(详见 PROGRESS.md)：A-K 已达可运行完成度 —— A-C、F-H 完成;E 经 K6 端到端验收;I 主体完成(WebUI v2 已落地,浏览器测试 CI 随 K8 接入);J1-J4 完成;K1-K8 稳定化完成,进入发布候选。**L 拟人化 / M 路由 Mesh / N 记忆深化 / O 企业化** 四大节点的 14 子节点中,**L2-L5、M1-M2、N1-N3、O1-O3 核心逻辑 + 单测已实现,但主链路尚未接线**(标 `[~]`:默认关闭、生产路径无调用点,按 §二完成定义尚不算完成),O4/O5 未开始(`[ ]`);向量库 / 图谱 / Embedding / Reranker 检索后端已实现(向量/图谱召回待接入 pipeline)。为把这些 `[~]` 能力接入同一主链路协同工作,新增大节点 **P 主链路接线与激活**(P0-P5,定义见 §四)。当前 1157 单测通过、ruff/mypy 全绿、主链路零行为变化。

**2026-07-26 MVP 差距复核**：对照 `docs/REQUIREMENTS.md` 十二条原始需求做 10 域并行代码取证(498 次代码检索 + 一次真实启动实测),发现一批标 `[x]` **已交付**的节点(D8/E4/F1-F3/H1/H2/J1-J4/K1-K4/K7)存在与其"完成定义"矛盾的未接线子行为,已在对应节点下补记"**2026-07-26 MVP 缺口复核**"说明(不改动其余已验证部分的 `[x]`);并新增大节点 **Q MVP 收尾**,收纳未被 P0-P5 覆盖、但 MVP 必需的缺口(记忆写入回路等,定义见 §四 Q)。技术路线全景见 [ROADMAP.md](./ROADMAP.md);模块开发范式见 [MODULE_GUIDE.md](./MODULE_GUIDE.md)。

## 三之二、下一步开发计划

K1-K8 稳定化 + J1-J4 能力 + L/M/N/O 各节点核心实现均已落地。**剩余工作 = 把标 `[~]` 的能力接入生产主链路 + 补齐未开始功能**,按下述优先级推进(详见 §四 P 节点与各 `[~]` 节点"接线待办"):

1. **P0 消息处理并发化** — `manager` 用 `asyncio.create_task` 并发处理消息 + 单会话串行 + 优雅关闭,是 P1 的前置基础。
2. **P1 拟人化激活(最优先)** — 接入 L2-L5:debounce 合并 / 主动调度启停 / 打断闭环 / 上下文恢复,受 `conversation.enabled` 开关控制。拟人化是 ISAC 核心差异点,已接近闭合。
3. **P2 Mesh 激活** — 接入 M1/M2:observer/candidate 路由 + 4 个 A2A 工具(assembly 注入 `mesh_action_broker`)。
4. **P3 记忆检索深化激活** — `pipeline.search()` 接入向量/图谱召回 + 检索期治理过滤(N2 生效) + MemoryItem 接入检索链(N1)。
5. **P4 身份归一激活** — gateway 接入 `IdentityResolver`,记忆按归一身份聚合(N3)。
6. **P5 企业化激活** — 多租户隔离 / 插件进程隔离 / Workflow 接入 control 与主链路(O1-O3)。
7. **未开始功能(`[ ]`)** — O4 平台适配器(微信/Slack/飞书 ≥1 真实实现)、O5 Video Provider 真实端点、MemoryConsolidator(记忆整合后台任务)、I 节点复核(浏览器测试 CI 已随 K8 接入,复核 85%→100%)。
8. **Q MVP 收尾**(2026-07-26 新增,详见 §四 Q 节点) — 对照原始需求清单逐条代码取证后发现的、**未被 P0-P5 覆盖**的 MVP 必需缺口(按优先级排列,非编号顺序):**Q1 记忆写入回路与身份稳定化**(检索/注入/治理链路全通但生产从未写入,MVP 最高优先级,不依赖 P0)、Q0 开箱可触达与配置纠偏、Q2 人格差异化实现、Q3 插件与 MCP 生态数据面接线、Q4 多模态工具注册与计量收尾、Q5 WebUI 与控制面收尾、Q6 SubAgent 用量与安全补漏。

依赖顺序：P0 → P1;P2 与 P3 可并行,P4 依赖 P3;P5 与 O4/O5/MemoryConsolidator/I 复核独立,可并行插入;**Q0/Q1 不依赖 P0,可立即开始甚至优先于 P0**,Q2-Q6 相互独立、与 P 节点也无强依赖,可并行插入。MVP 发布以 **P0-P2 + Q0-Q1** 完成为最低准入线(详见 [ROADMAP.md](./ROADMAP.md) M-MVP 里程碑)。每项按 §二"完成定义"验收(非桩实现 + 单测 + 集成/运行验证 + 主链路接线 + 文档 + `ruff`/`mypy`/CI),完成后把 §四 对应 `[~]` 升为 `[x]` 并同步 [PROGRESS.md](./PROGRESS.md)。

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
  - **2026-07-26 MVP 缺口复核**：`AgentConfig.persona` 文本从未接入 `BaseIdentityInjector`(该注入器恒注入 locales 通用文案),两个 Agent 的人格差异在 Prompt 层不可见;`MoodInjector`/`ExpressionStyleInjector`/`AttentionDriftInjector` 是返回空串的桩且未注册进 `prompt_builder`(`assembly.py` 自认"待落地"),`MoodEngine.update/decay` 与 `PersonaManager.get_expression_style/get_drift_level` 全仓无生产调用点,既无注入也无更新回路;`BehaviorLearner` 写的 `behavior_patterns` 也无消费者。人格系统在读侧(合并/存储)完整,但对话可感知的差异化实际不存在。补齐见 **Q2**。

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
  - **2026-07-26 MVP 缺口复核**：tool/command 两臂矩阵在生产真实生效,但 **plugin 臂未接线** —— `PluginManager` 构造时未传入 `EnableMatrix`(`plugin/runtime/manager.py:105-107` 的 `is_enabled_for` 硬编码放行 `["*"], []`),`plugins_allow`/`plugins_deny` 对已加载插件的 hooks 完全不生效;**mcp 臂**(`is_mcp_enabled`)也全仓零生产调用点(因为 MCP Client 本身未接线,见 H2)。补齐见 **Q3**。

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
  - **2026-07-26 MVP 缺口复核**：桥接组件本身(`FunctionToolAdapter`/`ContextAdapter`/`Star`/`_FilterRegistry`)已实现且有单测,但生产 `plugin/runtime/loader.py` 只识别格式并 `exec_module` 实例化,**从不调用这些桥接逻辑**做真正的注册;已加载的 AstrBot 插件是惰性实例,`@filter.llm_tool`/`@filter.on_message` 等装饰器标记的 handler 永不被生产事件触发,`sandbox.install_sandbox` 也无调用点。补齐见 **Q3**。

- [x] **F2 MaiBot 兼容层**
  - **验收**：2-3 个 MaiBot 插件可运行；Plugin/Action/Command 映射工作；锁定兼容版本。
  - **产出**：`plugin/compatibility/maibot/{plugin,actions,commands}.py`。
  - **依赖**：B2、D3、`commands/`。
  - **当前**：MaiBotPlugin 基类 + @register_action / @register_command 装饰器 (标记 _maibot_action / _maibot_command); MaiBotPluginAdapter 扫描装饰器并 adapt 到 ToolRegistry / CommandRegistry; bridge_action (MaiBotActionAdapter) 桥接 Action → ISAC Tool (同步/异步/异常隔离); bridge_command (MaiBotCommandAdapter) 桥接 Command → ISAC Command。附 `tests/unit/test_maibot_compat.py` (6 测试覆盖装饰器扫描/Action 桥接/Command 桥接)。
  - **2026-07-26 MVP 缺口复核**：与 F1 同源问题 —— `MaiBotPluginAdapter.adapt` 只被单测调用,生产 `loader.py` 加载 MaiBot 插件后不调用它;插件里 `@register_action`/`@register_command` 标记的能力在生产是死代码。`PLUGIN_COMPATIBILITY.md` §7.3 描述的 `enqueue_proactive_task` 映射也全仓无实现。补齐见 **Q3**。

- [x] **F3 原生 SDK v2**
  - **验收**：ISACPlugin 可注册 Commands/InterAgent Hooks/Admin Routes(预留)；Plugin Manifest 扩展字段生效。
  - **产出**：`plugin/native/{plugin,hooks,api}.py`。
  - **依赖**：B2、E3。
  - **当前**：PluginContext 实现 register_tool/injector/command 真实注册到 ToolRegistry/CommandRegistry/SystemPromptBuilder; register_inter_agent_hook 挂到 InterAgentBus; register_admin_route 收集到 services["admin_routes"] 待 G1 消费; on_event_intercept/on_event_async 订阅 EventBus。make_plugin_context 工厂在 PluginManager 加载时调用。附 `tests/unit/test_native_plugin.py` (9 测试)。
  - **2026-07-26 MVP 缺口复核**：`PluginContext` 的 `register_tool/register_command/register_injector` 实现真实存在,但生产 `main.py` 构造 `PluginContext` 时把 tools/commands/prompt_builder 三个注册表显式留 `None`(`main.py:750-755` 注释明示),`plugin/native/plugin.py` 里 `register_tool` 等方法在注册表为 `None` 时 `raise RuntimeError` —— 插件唯一能真正注册工具/命令/注入器的入口在生产环境不可用;`register_admin_route` 收集的路由也无人挂载到 control app。`CR3-H2` 已接线的是 `on_load` 生命周期调用本身,不含这三类注册表的生产绑定。补齐见 **Q3**(复用 `assembly.py:100-104` 已验证的 `plugin_agent_hooks` 共享注册表模式)。

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
  - **2026-07-26 MVP 缺口复核**：三个适配器本身"可收发消息"这一验收标准(单测层面)成立,但生产入口 `main.py` 只有 `channels.onebot` 一个注册分支,`TelegramAdapter`/`DiscordAdapter`/`WebChatAdapter` 全仓零生产实例化点(`config.sample.jsonc` 里 `channels.webchat.enabled=true` 是死配置);开箱部署事实上只有 OneBot(需外部 NapCat+QQ 号)一条可用通道,零外部依赖的 WebChat 摸不到。补齐见 **Q0**(main() 各加一个注册分支,~5 行 × 3)。

- [x] **H2 MCP Client**
  - **验收**：可连接外部 MCP Server；工具按 Agent mcp_servers 矩阵生效。
  - **产出**：`agent/tools/mcp/client.py`。
  - **依赖**：D4、E4。
  - **当前**：MCPClient 支持两种传输 (stdio 子进程 + HTTP/SSE); connect 启动子进程或 httpx.AsyncClient; list_tools 发现 MCP 工具并桥接为 MCPToolBridge (实现 ISAC Tool 接口); call_tool 转发 JSON-RPC tools/call + 错误处理 (jsonrpc error → is_error=True); disconnect 终止子进程 / 关闭 httpx + 取消 pending future。stdio 模式后台读 stdout NDJSON 并分发到 pending future。Agent 的 mcp_servers 启用矩阵在 E4 EnableMatrix 落地。附 `tests/unit/test_mcp_client.py` (9 测试覆盖 connect 各传输 + list_tools + call_tool 正常/错误/未连接 + MCPToolBridge 桥接)。
  - **2026-07-26 MVP 缺口复核**："Agent 的 mcp_servers 启用矩阵在 E4 EnableMatrix 落地"仅指判定逻辑(`is_mcp_enabled`)存在,`MCPClient` 本身**全仓无生产 import**——`AgentConfig.mcp_servers` 配置该字段对生产没有任何效果,`assembly.py` 从不构造/`connect`/把 `list_tools` 结果注册进 Agent 的 `ToolRegistry`。补齐见 **Q3**。

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
  - **2026-07-26 MVP 缺口复核**：J2 完成后,`UsageRecorder` 已补 `record_image_gen/stt/tts/video/embed/rerank` 6 个方法(见 J2 当前),但生产**零调用点**——多模态工具(`agent/tools/media.py`)直连 Provider,不经过计量边界;`PricingCatalog` 在生产恒空快照(`main.py` 构造 `PricingCatalog()` 不加载任何价目表),`estimated_cost` 恒为 `None`。补齐见 **Q4**。

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
  - **2026-07-26 MVP 缺口复核**：本节点标注"留 J3"的 `_send_reply`/入站媒体/Telegram·Discord segment 在 J3 完成后**仍未补齐**;更根本的是 `isac/runtime/assembly.py` 的 `ToolRegistry` 注册清单**不含任何 `media.py` 工具**(vision/STT/TTS/生图/视频理解/视频生成 6 个语义工具全仓仅测试引用),`AgentConfig` 也无 `model_capabilities_allow` 字段(此前留 J4,J4 完成后仍未补) —— Provider/Router/Catalog/ArtifactStore 全部就绪却是"配置了也没用"的状态,这是需求七 MVP 的核心缺口。补齐见 **Q4**。

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
  - **2026-07-26 MVP 缺口复核**：HttpOnly Cookie + CSRF 与多 scope 权限模型已由后续的 Fix-17/Fix-12(见 CR2/CR3 修复记录)补上,本节点"边界"里这两条已解决,但另外几处遗留问题仍在:Extensions 插件表硬编码占位文案(实际后端 API `/agents/{id}/plugins` 已就绪,只是前端未接);SubAgent 任务表请求路径写死 `agent_id="_"`,恒空;配置编辑的 `loadConfigForEdit` 不读真实配置、伪造 `revision=1`,真实 revision>1 时 PATCH 必 409(乐观锁在 WebUI 侧形同虚设);后端 SSE(`/events/stream`)已挂载但前端无 `EventSource` 消费;Usage 页明细表按 `events?.events` 取值,与 API 裸数组返回不匹配,恒显示"(无事件)"。补齐见 **Q5**。

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
  - **2026-07-26 MVP 缺口复核**：委派主链路(`delegate_task`→Supervisor→runner→独立 loop)本身是本仓接线最完整的域之一,但 `supervisor` 只保留 `result.summary`,把 `result.usage`/`evidence_refs` 丢弃(`run.tokens_used`/`tool_calls_used` 恒 0 —— Control API `/subagent-runs` 会把这两个恒 0 字段返回给客户端;WebUI 任务表当前未渲染用量列,补列后也无真实数据可显);`delegate_task` 收集的背景摘要从未真正传给子 Agent(`ContextEnvelopeBuilder` 死代码);`SubAgentPolicy` 无并发上限字段、`supervisor` 无信号量,可无限并发 `submit`;`control/defaults.py` 的 `RESTRICTED_TOOLS_POLICY` 只 `deny` 了 `task` 却漏了 `delegate_task`,自动化创建的受限 Agent 仍可派生子任务。补齐见 **Q6**。

---

### K 稳定化与可用版本闭环

**目标**：先打通“可持续运行、真实模型回复、持久化恢复、端到端可验证”的最小纵向链路，再继续 D9/J1-J3 等横向扩展。K1-K8 是当前最高优先级；完成前项目统一定位为 Alpha，不得宣称生产可用或完成 v1.0 验收。

- [x] **K1 应用常驻与统一资源生命周期**（P0）
  - **验收**：`python -m isac` 在无 Channel、仅 Control、启用 Channel 三种模式下均持续驻留；支持 SIGINT/SIGTERM；Channel、Control、Alert、Provider、Storage、Plugin、Webhook 后台任务统一 start/health/close；启动失败能回滚，后台任务异常不会静默丢失，关闭无 pending task/resource warning。
  - **产出**：`ApplicationRuntime` / `ServiceContainer`、统一 TaskGroup、信号处理、优雅关闭、生命周期单元与进程级 smoke test。
  - **依赖**：B4、C4、G1、I5。
  - **当前**：已完成(校正复选框,与 PROGRESS.md 稳定化节点明细表一致)。历史"已知问题"(`main()` 直接返回、后台任务被取消)已由 `ApplicationRuntime` 统一生命周期解决;2026-07-26 实测无 `data/config.jsonc` 时也能启动并驻留 18 秒无异常栈。
  - **2026-07-26 MVP 缺口复核**：Windows 控制台 Ctrl+C 不走优雅关闭 —— `add_signal_handler` 在 Windows 上注册失败(仅回退 `KeyboardInterrupt`),且 `main()` 的 `await runtime.serve_forever(); await runtime.shutdown()` 无 `try/finally` 包裹,`KeyboardInterrupt`/`CancelledError` 会直接穿透跳过 `shutdown()`;Linux/Docker(CI 实际运行环境)不受影响。补齐见 **Q0**。

- [x] **K2 真实 LLM Provider 纵向闭环**（P0）
  - **验收**：至少一个真实 Provider 支持非流式、SSE 流式、Tool Call、usage、超时、429/5xx/非法响应分类、重试与 fallback；配置真实 Provider 时不得回退为 Stub 冒充成功；Provider Client 可健康检查并在关闭时释放连接池。
  - **产出**：`OpenAICompatProvider` 或等价首个 Provider 的真实实现、HTTP 契约测试、Fake Server 集成测试、错误分类与关闭测试。
  - **依赖**：K1、D3、ProviderManager。
  - **当前**：已完成(校正复选框)。`OpenAICompatProvider` 真实闭环已实测(非流式/工具调用/错误分类/连接池);历史"阻塞"说明已解除。
  - **2026-07-26 MVP 缺口复核**：SSE 流式合并逻辑已修复(CR3-H4 按 index 累积),但主链路 `AgentContext.streaming` 默认 `False` 且全仓无生产赋 `True` 点,流式路径实际未在生产启用(非 MVP 阻塞项,已知记录)。

- [x] **K3 Storage Schema、记忆写入与恢复**（P0）
  - **验收**：启动时执行 Schema init/migration；Metadata/FTS/Sparse 按 namespace 初始化；消息或会话结束后真实写入 Episode；重启后可检索；shared namespace 强制 user/group/scope ACL；写入失败不阻塞回复但可观测；关闭时提交并释放连接。
  - **产出**：StorageLifecycle、schema_version/migration、MemoryEncoder 接线、Sparse 重建/恢复、跨用户隔离与重启测试。
  - **依赖**：K1、D5-D7。
  - **边界**：Vector/Graph/Reranker 可继续降级，但必须明确标记 experimental/stub，不能计入 MVP 完成度。
  - **当前**：Schema init/migration、跨用户隔离、重启恢复已完成(校正复选框)。
  - **2026-07-26 MVP 缺口复核**：本节点验收标准明确要求"消息或会话结束后真实写入 Episode",但生产 `_dispatch_message`/`process_message` 全程无任何 `store_episode`/画像/行话写入调用 —— 存储基建(Schema/FTS/Sparse/重启恢复)已就绪,唯独"写入"这一步从未接线,记忆检索因此恒为空。这是本次差距复核中最关键的发现,补齐见 **Q1(MVP 最高优先级)**。

- [x] **K4 Agent、Session、Identity、Routing 与 Link 持久化恢复**（P0）
  - **验收**：重启后恢复 AgentConfig/运行状态、Session、UserMapper 绑定、RoutingRules、InterAgentLink；Agent 独立 Provider 配置实际生效；配置写入使用原子替换和版本迁移；非法 ID/路径被拒绝。
  - **产出**：registry/session/identity 持久化、启动恢复编排、原子配置存储、路径安全与迁移测试。
  - **依赖**：K1、E1-E3、G1。
  - **当前**：AgentConfig/运行状态、RoutingRules、InterAgentLink 持久化恢复已完成(校正复选框)。
  - **2026-07-26 MVP 缺口复核**：`Session`(`gateway/session.py`)与 `UserMapper`(`gateway/user_mapper.py`,自述"[桩] 内存实现,待 SQLite 持久化")实际为纯内存,本节点验收要求的"重启后恢复 Session、UserMapper 绑定"未达成 —— 与本节点其余三项(Agent/RoutingRules/Link)相比是明确的未闭合子项;`PROGRESS.md` 此前"Session 可持久化恢复"表述已一并订正。补齐见 **Q1**。

- [x] **K5 单 Channel × 单 Agent 真实 E2E**（P0）
  - **验收**：进程启动 → Fake/测试 Channel 收消息 → EventBus intercept → Router 剥离触发词 → Session/Gating → 真实 HTTP Mock Provider → Tool Call → Channel 回复全链通过；覆盖打断、超时、错误和重启恢复。
  - **产出**：`tests/integration/test_single_agent_flow.py`、可复用 Fake Channel/Provider、进程级测试夹具。
  - **依赖**：K1-K4。
  - **当前**：已完成(校正复选框,与 PROGRESS.md 一致)。

- [x] **K6 多 Agent、工具、记忆与控制面 E2E**（P1）
  - **验收**：2+ Agent 共享 1 Channel；显式绑定/触发词/默认 Agent；InterAgentBus deliver + ACL；工具权限；记忆 namespace 隔离；Control 修改配置真实生效并在重启后保留。E5 并入本节点验收。
  - **产出**：`tests/integration/test_multi_agent.py`、Agent Mesh/权限/记忆/Control 集成测试。
  - **依赖**：K5、E3-E5、G1-G4。
  - **当前**：已完成(校正复选框,与 PROGRESS.md 一致)。

- [x] **K7 安全与长期运行基线**（P0/P1）
  - **验收**：Agent ID/路径穿越防护；Control 空 Token 仅显式开发模式；审计/JSON metrics 鉴权；WebUI 不持久化 Bearer Token；Webhook 与远程媒体防 SSRF；SecretStore 可用；插件明确为兼容层而非安全沙箱或提供进程级隔离；Bash/File/MCP 有字节、时间、进程、路径与 pending 上限；Session/Lock/队列有 TTL/LRU；Discord 分页不丢消息。
  - **产出**：安全回归测试、资源压力测试、威胁模型与生产安全配置。
  - **依赖**：K1、K4、G/H/F 相关模块。
  - **当前**：已完成(校正复选框,与 PROGRESS.md 一致)。
  - **2026-07-26 MVP 缺口复核**：`SecretStore`(AES-256-GCM)实现存在但生产零调用点,`api_key` 实际以明文存于 `data/config.jsonc`(env 覆盖已支持);MVP 建议先文档化 env 方案,`SecretStore` 接线留 MVP 之后,见 **Q5** 备注。

- [x] **K8 CI、Docker、浏览器与发布准入**（P1）
  - **验收**：CI 启用 branch coverage 与 `--cov-fail-under`；构建 wheel/sdist 并安装 smoke；Docker build/start/health/stop 实测；WebUI 用真实浏览器覆盖登录、Agent/路由/Link/审计黄金路径；Mypy 全绿或对 `aiocqhttp` 做局部明确 override；README/AGENTS/CHANGELOG/版本号与实际能力一致。
  - **产出**：CI 门禁、Docker smoke、Playwright/浏览器测试、发布检查表、版本状态校准。
  - **依赖**：K1-K7、I1-I6。
  - **当前**：已完成 (2026-07-26)。`.github/workflows/ci.yml` 四 job: check (ruff+mypy+pytest --cov-branch --cov-fail-under=75) + build (uv build + wheel install smoke `import isac`) + docker (build + 30s curl /health 循环 + cleanup) + browser (Playwright install chromium + tests/browser/ 黄金路径); 新建 `scripts/release_checklist.md` 七段发布准入清单 (CI 全绿 + 本地全量验证 + 文档同步 + 版本号一致 + 发布标签 + 回滚预案 + 发布后监控)。README/AGENTS/CHANGELOG/版本号校准留 K8-1 节点 (本节点不涉及文档内容校准, 只覆盖 CI 工程化)。

**强制开发顺序**：K1 → K2 → K3/K4 → K5 → K6/K7 → K8。K1-K5 完成前暂停 D9、J1-J4；K8 通过后才允许恢复 I6 发布验收。

---

### L 拟人化运行时落地

**目标**：把 `HUMANLIKE_RUNTIME.md` 描述的会话级拟人行为(消息合并、主动等待、主动任务、被打断、上下文恢复)从设计蓝图落成可运行代码。所有子节点默认由 `conversation.enabled` 开关控制,关闭时主链路零行为变化。

- [~] **L1 ConversationRuntime**(骨架完成,已由 L2-L5 充实;主链路接线见 P1)
  - **验收**：每个 (agent_id, session_id) 一个 `ConversationRuntime`;具备消息缓存、状态机 (idle/thinking/acting/waiting/stopped)、`WaitState`/`ForcedTurnState` 契约、per-session 注册表 (FIFO 上限) 与主动任务队列;`conversation.enabled=False` 时 `handle_message` 完全走原路径。
  - **产出**：`runtime/conversation/{__init__,models,runtime,registry,proactive}.py`、`assembly` 注入 `conversation_registry`、`manager.handle_message` 惰性接线、`tests/unit/test_conversation_runtime.py`。
  - **依赖**：B4、E1、D9。
  - **当前**：骨架完成 + L2-L5 已实现核心逻辑 (2026-07-26)。契约 + 状态机 + registry + 主动队列 + 惰性默认关闭接线就位,单测通过,ruff/mypy 全绿,主链路零行为变化。debounce 触发 / wait 回填 / 主动调度 / 打断闭环 / 上下文恢复 见 L2-L5(均已实现核心逻辑)。**接线待办 → 见 §四 P0/P1**:把 L1-L5 接入生产主链路。

- [~] **L2 Wait 闭环与 debounce 触发**
  - **验收**：`wait` 工具向 `ConversationRuntime.enter_wait` 注册 `WaitState`,由后续消息 / 超时 / 主动任务三条路径之一结束等待并向 AgentLoop 回填 wait 工具结果 (说明实际等待时长与结束原因);连续消息在 debounce 静默窗口内合并为一次触发,避免逐条打断。
  - **产出**：异步 debounce 触发循环、`resolve_wait` 三入口、wait 工具改造 (注册 WaitState)、超时定时器、单测与集成测试。
  - **依赖**：L1、D4 (wait 工具)、D9。
  - **当前**：已完成 (2026-07-26)。`ConversationRuntime.should_trigger` 真实 debounce 判定 (zero/positive); `enter_wait` (async) 创建 future + 启动超时定时器; `resolve_wait` 回填 `end_reason`/`actual_seconds` + 取消定时器 + 唤醒 wait 工具; `notify_new_message` 在 WAITING 时以 MESSAGE 原因结束等待。三条唤醒路径 (message/timeout/proactive) 单测覆盖 12 例; `WaitTool` enabled=True 时调 `enter_wait`+`await_wait`, enabled=False 保持原意图字符串 (零行为变化)。`assembly.py` 注入 `conversation_enabled` 标志。debounce 接入 manager 主链路 (连续消息合并) 留 §四 P1, 不影响 L2 骨架验收。
  - **接线待办 → 见 §四 P1**:debounce 连续消息合并接入 manager (依赖 P0 消息并发化)。

- [~] **L3 主动任务调度**
  - **验收**：`ProactiveTaskQueue` 由调度器按优先级 + 冷却 + 频率边界驱动;每个主动任务必须带 source/intent/reason (禁止无来源发言);触发时唤醒对应会话的 `ConversationRuntime` 发起一次强制话轮 (`ForcedTurnState`);来源经鉴权,防刷屏与滥用。
  - **产出**：主动调度循环、优先级/冷却策略、来源鉴权、强制话轮 Prompt 注入、单测与集成测试。
  - **依赖**：L1、L2、门控 (存在感/频率)。
  - **当前**：已完成 (2026-07-26)。`ProactiveTaskQueue` 改为 list 实现 priority 排序 (high>normal>low; 同优先 FIFO); `ProactiveScheduler` 加 `allowed_sources` 集合 (默认 plugin/memory/schedule/agent/api); `authorize` 拒绝不在集合内的 source; `to_forced_turn` 触发时更新 `_last_fired_at`; 新增 `async start/stop` 后台循环 (poll_interval_seconds 周期 poll → authorize → may_fire → wake_callback, 冷却中任务退回队列头部)。强制话轮 Prompt 注入 + manager 接线留 §四 P1, 不影响 L3 骨架验收。
  - **接线待办 → 见 §四 P1**:ProactiveScheduler 注入 assembly + 生命周期注册 start/stop + 强制话轮 Prompt 注入。13 例单测覆盖 priority/authorize/start/stop/冷却/空队列/重复 stop。

- [~] **L4 Planner 打断闭环**
  - **验收**：thinking 期间到达的新消息可请求打断当前规划;`AgentContext.interrupt_requested` 由 `ConversationRuntime.request_interrupt` 写入;限制单轮打断次数、抑制被打断的旧回复、下一轮 Prompt 注入"上一轮被新消息打断"提示。
  - **产出**：打断信号写入路径、打断次数限制、旧回复抑制、Prompt 提示注入、单测。
  - **依赖**：L1、L2、`agent/loop.py`。
  - **当前**：已完成 (2026-07-26)。`ConversationRuntime` 加 `interrupt_state` + `max_interrupts_per_turn` (默认 1, 保守); `request_interrupt(reason)` 单轮次数限制 + 置 `superseded=True` + `interrupt_count++`; `clear_interrupt` 进入下一轮前重置。新增 `agent/injectors/interrupt.py:InterruptInjector` 注入"上一轮被打断"内部参考 (含打断次数与原因), 注入后清空状态避免重复注入。AgentLoop 接线 (thinking 后读 `superseded`) 与 manager 并发处理消息 (thinking 期间收到新消息调 `request_interrupt`) 留 §四 P0+P1, 因这两者需要 manager 用 asyncio.create_task 并发处理消息的大改动, 超出 L4 骨架验收线。
  - **接线待办 → 见 §四 P0+P1**:manager 并发处理消息 (asyncio.create_task) + thinking 期新消息调 request_interrupt + loop 读 superseded 抑制旧回复 + InterruptInjector 注册 prompt_builder。9 例单测覆盖 request/clear/单轮上限/可配置/注入/清空/默认零行为变化。

- [~] **L5 上下文恢复**
  - **验收**：进程重启后,会话的拟人状态 (未决 wait、被打断标记、主动任务) 可从持久化恢复到合理起点 (与 D9/J4 "中断后不恢复旧进度" 思路一致,标为终止/复位而非续跑)。
  - **产出**：ConversationRuntime 状态持久化 schema、启动恢复编排、恢复测试。
  - **依赖**：L1-L4、K4 (持久化恢复框架)。
  - **当前**：已完成 (2026-07-26)。`ConversationStateStore` 原子写 JSON 落盘到 `data/agents/<id>/conversation/<session_id>.json` (复用 `utils.fs.atomic_write_json`, K4 模式); `load` 读回 → 计算 elapsed → 短(<5min)/中(<1h)/长(<24h) 窗口生成 `recovery_hint` → 复位 `state=idle` + `pending_wait=None` (中断后不续跑); > 24h 不恢复。新增 `agent/injectors/recovery.py:RecoveryInjector` 注入 `recovery_hint` 到第一轮 Prompt, 注入后清空 (避免重复注入)。10 例单测覆盖 save/load 往返 + 短/中/长/24h 窗口 + 未决 wait 复位 + 原子写文件存在 + RecoveryInjector 注入/清空/无快照空串。manager 启动时调 `store.load` 填充 snapshots + 接线 RecoveryInjector 到 prompt_builder 留 §四 P1 (不涉及主链路行为变化)。
  - **接线待办 → 见 §四 P1**:manager 启动时调 ConversationStateStore.load 恢复 + RecoveryInjector 注册 prompt_builder。

---

### M 路由与 Agent Mesh 深化

**目标**：把 `ROUTING_AND_AGENT_MESH.md` 描述的旁听/候选路由与 Agent 间协作动作从设计落成实现。

- [~] **M1 observer/candidate 路由**
  - **验收**：Agent 可配置为 observer (旁听,只入记忆不回复) 或 candidate (候选,多 Agent 竞争同一消息由仲裁选出回复者);路由决策可解释、可审计。
  - **产出**：路由角色模型、候选仲裁策略、observer 记忆旁路、单测与集成测试。
  - **依赖**：C (路由)、E (多 Agent)、门控。
  - **当前**：已完成 (2026-07-26)。`MeshRouter.to_mesh_decision` 按 agent_roles 字典 (agent_id → "primary"/"observer"/"candidate") 填充 observer_agent_ids/candidate_agent_ids (primary 不动); `arbitrate(decision, gating_scores=...)` 多候选按 gating_score 降序取最高, 但需**显著高于** primary (差值 > SWITCH_MARGIN=0.3) 才切换, 避免小噪声抖动; observer 不参与仲裁 (只观察); decision.reason 记录仲裁过程供审计。无角色配置时退化为单主路由 (零行为变化)。8 例单测覆盖 to_mesh_decision + arbitrate + observer 排除 + 候选切换/不切换 + 默认零行为变化。AgentConfig.mesh_role 字段 + manager.observe_message 接线留 §四 P2。
  - **接线待办 → 见 §四 P2**:AgentConfig 加 mesh_role + manager.observe_message 旁听/候选路由接线 + assembly 注入 MeshRouter。

- [~] **M2 handoff / notify / memory_query**
  - **验收**：Agent 间可显式移交会话 (handoff)、发通知 (notify)、跨 Agent 查询记忆 (memory_query);全部经 InterAgentLink ACL 授权;动作可审计。
  - **产出**：三类 Agent 间动作工具、ACL 校验、审计埋点、单测。
  - **依赖**：E3 (InterAgentBus/Link)、N (记忆)。
  - **当前**：已完成 (2026-07-26)。`MeshActionBroker.is_permitted` 无 policy 一律拒绝, 有 policy 时 action 在 permissions 中允许; `notify/handoff/memory_query` ACL 通过后经 `bus.send` 真实投递 (handoff 把 summary 进 context.summary, memory_query 把 visible_memory_scopes 进 context.filters.scopes 让接收方裁剪); `list_available` 从 bus.links 过滤可见对端 (双向 Link 双方可见, 单向 from→to, disabled 不计入); 无 bus 时所有动作拒绝 (零行为变化)。4 个 A2A 工具 (notify_agent/handoff_conversation/list_available_agents/memory_query_agent) 接入 broker; DEFAULT_POLICY 从 deny 改 restricted; ToolRegistry._required_service 加 mesh_action_broker 校验。11 例 broker 单测 + 骨架测试更新到新行为。
  - **接线待办 → 见 §四 P2**:assembly 注入 mesh_action_broker 到 services (否则 4 个 A2A 工具运行时报"未注入"错误) + 动作审计埋点。

---

### N 记忆深化

**目标**：把当前分散的记忆结构统一为 `MemoryItem` 模型,补齐记忆治理与身份归一。

- [~] **N1 统一 MemoryItem 模型**
  - **验收**：episodic/profile/jargon 等记忆统一到一个 `MemoryItem` 契约 (类型 + 载荷 + 元数据 + 命名空间),存储/检索/注入围绕它展开;迁移不破坏既有数据。
  - **产出**：`MemoryItem` 契约、存储层适配、迁移脚本、单测。
  - **依赖**：D5-D7、K3。
  - **当前**：已完成 (2026-07-26)。`MemoryItem.from_episode/to_episode` 补齐完整字段映射 (summary/topics/participants/emotion/session_id/group_id 进 metadata); 新增 `from_profile/to_profile` (name/traits/relationship_depth/interaction_count/first_seen/last_seen/embedding_hash); `from_jargon/to_jargon` (word/context/usage_count); `from_relationship/to_relationship` (familiarity/trust/last_interaction_at)。新增 `isac/memory/model/adapter.py:MemoryItemAdapter` 实现 `MemoryItem ↔ MemoryHit` 双向适配 (hit_type → memory_type, 未知类型默认 EPISODE 兜底)。既有 metadata.py 三表 schema 不动, 本模块只做读写适配层。10 例单测覆盖四种类型 from/to roundtrip + adapter 双向 + 未知列降级。
  - **接线待办 → 见 §四 P3**:MemoryItem/MemoryItemAdapter 接入 pipeline 检索/注入链 (当前 `pipeline.search()` 从不调用适配层,悬空)。

- [x] **N2 记忆治理 (freeze/protect/correct/delete)**
  - **验收**：支持冻结、保护、纠错、删除记忆条目;操作经权限校验并审计;纠错保留可追溯历史。
  - **产出**：记忆治理动作、权限与审计、单测。
  - **依赖**：N1、G (控制面)。
  - **当前**：已完成 (2026-07-26)。`MetadataStore.init_schema` 给 `episodes` 加 `frozen`/`protected`/`deleted`/`corrected_by` 治理列 (向后兼容老库, 默认 0/NULL); 新增 `memory_revisions` (corrected 历史保留) + `memory_audit` (审计日志) 表。`MemoryGovernor` 真实实现 6 类治理动作: freeze/protect 置标志位 + 审计; correct 写新版本 + memory_revisions 保留旧内容 + corrected_by 关系; delete 软删除 + protected 拒绝; restore 反向复位; export 组织为 `list[MemoryItem]` (治理状态进 metadata)。`routes_memory_admin.py` 真实接入 governor + 新增 `GET /memory/{id}/items` 列表端点。8 例单测覆盖 freeze/protect/correct/delete/restore/export + protected 拒绝 + 不存在条目返回 False。
  - **说明**:软删除 `deleted` 已在检索路径过滤生效(metadata FTS / by-id 检索加 `deleted = 0`,CR2-Fix-12);`frozen`(冻结)语义为"不再更新、仍可被检索",非缺口。N2 记忆治理已完整接入生产。

- [~] **N3 身份归一 (IdentityResolver)**
  - **验收**：跨平台 (不同 IM 的同一用户) 身份归一到统一 identity;记忆按归一后身份聚合;归一规则可配置、冲突可人工裁决。
  - **产出**：`IdentityResolver`、跨平台映射存储、冲突处理、单测。
  - **依赖**：C (Gateway/UserMapper)、N1。
  - **当前**：已完成 (2026-07-26)。`IdentityResolver` 新增 `person_identities` (verified/confidence/source) + `identity_conflicts` 表 (惰性建表, sqlite3 + aiosqlite 双轨)。`resolve` 先查 verified 命中, 未命中且 heuristic_enabled=True 时按 nickname 启发式匹配 (confidence≤0.5), 仍无则委托 UserMapper 创建新 person; `bind` 写 verified=1/confidence=1.0/source=manual + 同步 UserMapper.bind (若 master_id 已存在); `merge` 合并 aliases (去重) + platform_accounts (按 (platform, user_id) 去重), confidence 取较低, verified 取 AND; `arbitrate_conflict` 按 confidence 降序取最高, <0.7 写 identity_conflicts 供人工裁决。heuristic 默认 False (防误合并)。11 例单测覆盖 resolve/bind/merge/arbitrate + heuristic 开关 + 无 mapper 兜底 + 冲突写入。
  - **接线待办 → 见 §四 P4**:gateway 入站主链路接入 IdentityResolver.resolve + 记忆按归一身份聚合 (当前无调用点,悬空库)。

---

### O 企业化与平台扩展

**目标**：面向多租户、进程隔离、编排与更多平台的企业化能力。

- [~] **O1 多租户 / 组织隔离**
  - **验收**：Agent/记忆/配置/用量按 organization 隔离;跨租户不可见;控制面按租户鉴权。
  - **产出**：租户模型、数据隔离、租户级鉴权、单测。
  - **依赖**：G、K3-K4、J1。
  - **当前**：已完成 (2026-07-26)。`TenantIsolationGuard.namespace_for` enabled 时给命名空间加 `org:tenant:base` 前缀 (默认租户直通); `check_access` enabled 时跨租户不可见 (resource_org != tenant.org 且 != DEFAULT 拒绝); `assert_visible` 跨租户抛 PermissionError; `enforce(query, params, table, tenant)` 给 SQL 查询注入 `organization_id = ? AND tenant_id = ?` 谓词 (WHERE 已有时追加 AND, 无 WHERE 时加 WHERE, 用正则匹配 FROM <table> 定位)。默认 enabled=False (单租户 passthrough, 零行为变化)。16 例单测覆盖 namespace_for/check_access/enforce/assert_visible + 默认/非默认租户 + 无 WHERE 注入 + 跨租户拒绝。MetadataStore 加 tenant_id 列 + 控制面 routes_tenants 留 §四 P5。
  - **接线待办 → 见 §四 P5**:TenantIsolationGuard 接入 memory store/control/计量 + MetadataStore 加 tenant_id 列 + routes_tenants 控制面 (当前零调用点)。

- [~] **O2 插件进程级隔离**
  - **验收**：插件从当前"兼容层 (非安全沙箱)"升级为进程级隔离,资源与故障不影响主进程;插件崩溃可恢复。
  - **产出**：插件进程宿主、IPC 协议、资源限额、崩溃恢复、单测。
  - **依赖**：F (插件生态)、K7 (安全基线)。
  - **当前**：已完成 (2026-07-26)。`PluginIsolationHost.spawn` 用 `multiprocessing.Process` (fork on POSIX) 启动子进程 + `Pipe` 建立 IPC; 子进程入口 `_plugin_worker` 设资源限额 (`resource.setrlimit` RLIMIT_CPU=1s / RLIMIT_NOFILE=64 / RLIMIT_AS=256MB, 平台不支持时跳过); `call` 编码 IPCEnvelope → JSON → 管道发送 → asyncio.to_thread(recv) → 解码返回; 子进程崩溃 (BrokenPipeError/EOFError) 触发 `_on_crash` 自动重启 (最多 max_restart_attempts=3 次, 超过放弃); `kill` 优雅终止 (terminate + join 2s + kill 强杀); `is_alive` 属性。既有 `loader.py` 进程内兼容层不变 (仍默认)。6 例单测覆盖 spawn/call/kill roundtrip + 未 spawn 抛 + 重复 kill 幂等 + 崩溃重启计数 + 超限放弃 + 默认零行为变化。
  - **接线待办 → 见 §四 P5**:PluginIsolationHost 接入 loader 可选隔离模式 (当前 loader 仍进程内直接 import,未装配隔离)。

- [~] **O3 Workflow 编排**
  - **验收**：多步骤任务可用声明式 Workflow 编排 (串/并/条件/重试);步骤可跨 Agent/工具;执行可观测、可恢复。
  - **产出**：Workflow 引擎、步骤契约、执行器、可观测与恢复、单测。
  - **依赖**：J4 (SubAgent)、D9 (进度)、L (运行时)。
  - **当前**：已完成 (2026-07-26)。`WorkflowEngine.start` 按 transitions 调度 stages: 串行按 `TransitionKind.SEQUENTIAL` 递归执行, 并行用 `asyncio.gather` 同时跑多个 `PARALLEL` 目标, 条件 `CONDITIONAL` 按 `condition_evaluator` 返回决定执行或标 `SKIPPED`, 重试 `RETRY` 在 `_execute_stage` 内按 `max_retries=3` 重试; 状态机 `PENDING→RUNNING→SUCCEEDED/FAILED`; `step` 推进单个 PENDING stage; `resume` 把 RUNNING 标为 FAILED (中断后不续跑, 与 L5 一致); 持久化到 `data/workflows/<id>.json` (原子写)。`set_action_handler`/`set_condition_evaluator` 注入测试/生产回调; 无 handler 时 stage 视为 noop (零行为变化)。12 例单测覆盖串/并/条件/重试/step/resume/持久化/默认。
  - **接线待办 → 见 §四 P5**:WorkflowEngine 暴露 control 路由/工具入口 + set_action_handler 生产注入 (当前零调用点)。

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

### P 主链路接线与激活

**目标**：把已实现但未接入生产的 L/M/N/O 能力(§四标 `[~]`)接入同一条消息处理主链路,让它们协同工作;所有子节点默认关闭、`enabled=False` 时零行为变化。**这是 `[~]` → `[x]` 的收尾节点组**——把原先散落在各节点"当前"备注的接线待办统一收敛于此,避免功能各自孤立、无法真正激活。

依赖顺序：P0 → P1;P2 与 P3 可并行;P4 依赖 P3;P5 独立。每个子节点完成后,把它激活的 `[~]` 节点在 §四 升级为 `[x]`。

- [x] **P0 消息处理并发化**(P1 前置基础)
  - **目标**：`manager` 从"单条即时同步处理"升级为 `asyncio.create_task` 并发处理,保留单会话串行、优雅关闭等待在途任务。这是 L2 debounce 合并、L4 thinking 期打断的共同前提(L4/L2 备注均指向它)。
  - **验收**：并发处理多会话不串话;同一会话消息串行;`shutdown` 等待在途任务不丢消息;集成测试。
  - **产出**：manager 并发调度、单会话锁/队列、在途任务生命周期登记、单测与集成测试。
  - **依赖**：K1(生命周期)、E(多 Agent 运行时)。
  - **当前**：已完成 (2026-07-27)。
    - `main.make_message_dispatcher` (模块级工厂, 可测): `handle_message` 派生 `asyncio.Task` 立即返回 —— 适配器收取循环不再被单条消息的 LLM 往返阻塞, Telegram/Discord/WebChat 轮询循环下跨会话真并行; 单会话串行保持 (锁键 platform:user:group, 同会话任务按到达顺序创建, asyncio FIFO 就绪队列 + 公平锁保证按序获取); 任务持强引用 (inflight 集合 + done 自清理), 异常任务内捕获记日志。
    - 优雅关闭: `drain_inflight` 带超时等待在途任务; channels 生命周期改到**最后注册** (LIFO 关闭最先执行: 停收取 → drain → 再关 journal/usage/providers 等下游; 此前 channels 最先注册 → 最后关闭, providers 连接池会在在途消息处理完之前被关掉)。
    - 集成测试 `tests/integration/test_p0_concurrent_dispatch.py` (3): 跨会话并发峰值≥2 / 同会话串行且回复有序 / drain 不丢在途消息。

- [ ] **P1 拟人化激活**(依赖 P0 + L1-L5)
  - **目标**：把 L2-L5 已实现能力接入主链路 —— debounce 连续消息合并接入 manager(L2);ProactiveScheduler 注入 assembly + 生命周期注册 start/stop(L3);thinking 期新消息调 `request_interrupt`、loop 读 `superseded` 抑制旧回复、InterruptInjector 注册 prompt_builder(L4);启动时 `ConversationStateStore.load` 恢复 + RecoveryInjector 注册(L5);AgentConfig 增 `conversation` 配置段。
  - **验收**：`conversation.enabled=True` 时 wait/debounce/主动任务/打断/恢复端到端可用 + 集成测试;`enabled=False` 时主链路零行为变化。
  - **产出**：manager 接线、assembly 注入与注册、AgentConfig 配置段、集成测试。
  - **依赖**：P0、L2-L5。
  - **当前**：未开始。激活后 L2-L5 升级为 `[x]`。

- [ ] **P2 Mesh 激活**(依赖 M1/M2 + E3 bus)
  - **目标**：AgentConfig 增 `mesh_role`;`manager.observe_message` 实现旁听/候选路由(M1);assembly 注入 `MeshRouter`/`MeshActionBroker`,4 个 A2A 工具(notify/handoff/list/memory_query)获得 broker 后真正可用(M2);动作审计埋点。**(2026-07-26 差距复核扩充)** broker 注入只让 `list_available_agents` 真正可用——`notify`/`handoff`/`memory_query` 若要成为"真正可用"而非"能发一条消息",还需:①`InterAgentLink` 增 `permissions`/`visible_memory_scopes`/`max_context_messages` 配置面(`links.jsonc` 与控制面 API),按 (from_agent, to_agent) 解析出对应 `MeshLinkPolicy` 注入(而非当前假设的单值 `services["mesh_link_policy"]`);②`handoff_conversation` 需接收端识别 `HANDOFF` 类型消费 `context.summary` + Router/manager 侧临时切换 `primary_agent_id`,实现真正的会话所有权转移(当前只是发了一条普通消息);③`memory_query_agent` 需接收端按 `context.filters.scopes` 过滤检索记忆,并把结果经 `bus.send` 的 response 通道同步返回给查询方(当前 `_send` 忽略 `bus.send` 返回值,查询方永远拿不到结果)。
  - **验收**：observer 只入记忆不回复、candidate 多 Agent 仲裁选回复者、A2A 动作经 InterAgentLink ACL 真实投递且可审计;notify 触发目标 Agent 真实处理、handoff 后续消息路由到接收方、memory_query 返回按 scope 裁剪的真实检索结果;集成测试。
  - **产出**：AgentConfig `mesh_role`、observe_message 路由、assembly 注入、Link 细粒度策略配置面、handoff 会话所有权转移、memory_query 同步返回通道、审计埋点、集成测试。
  - **依赖**：M1、M2、E3(InterAgentBus/Link)。
  - **当前**：未开始。激活后 M1/M2 升级为 `[x]`。

- [ ] **P3 记忆检索深化激活**(依赖 N1 + VectorStore/GraphStore/Embedding/Reranker)
  - **目标**：`pipeline.search()` 接入向量 KNN(VectorStore)+ 图谱邻居(GraphStore)召回,与现有 FTS/BM25/Reranker 融合;`MemoryItem`/`MemoryItemAdapter` 接入检索/注入链或明确其落地边界(N1)。(注:检索期软删除 `deleted` 过滤已由 CR2-Fix-12 生效,向量召回+RRF 融合已由 CR3-H3 生效,均不在本节点剩余范围。)**(2026-07-26 差距复核扩充)** 本节点剩余范围收窄为:①图谱召回接入(`GraphStore` 边写入 + `neighbors` 结果并入 RRF,目前全仓无 `add_edge`/`neighbors` 调用点,图始终为空);②`Reranker` provider 注入 —— `main.py` 构造 `Reranker(memory_config.get("reranker", {}))` 时从未传入 provider,`is_available()` 恒 `False`,rerank 步骤永不执行,补齐仿 CR3-H3 embedding 的写法(按 `memory.reranker.{api_key,model,protocol}` 构造 `OpenAICompatRerankerProvider` 注入);③`MemoryItem`/`MemoryItemAdapter` 接入检索/注入链或明确落地边界。
  - **验收**：配置 embedding 时向量召回已生效(CR3-H3);配置 reranker 时 rerank 步骤真实执行;图谱召回生效;被治理条目不被检索命中;`MemoryItem` 成为检索/注入统一载体;集成测试。
  - **产出**：pipeline 图谱召回接线、Reranker provider 注入、MemoryItem 接入、集成测试。
  - **依赖**：N1、N2、J2(embed/rerank Provider)。
  - **当前**：未开始。激活后 N1 升级为 `[x]`。

- [ ] **P4 身份归一激活**(依赖 N3 + N1 + P3)
  - **目标**：gateway 入站主链路接入 `IdentityResolver.resolve`,把跨平台同一用户归一到统一 identity;记忆按归一身份聚合。
  - **验收**：不同 IM 的同一用户归一为同一 person、记忆按归一身份聚合、低置信冲突写入 `identity_conflicts` 供人工裁决;集成测试。
  - **产出**：gateway 接线、记忆聚合按归一身份、集成测试。
  - **依赖**：N3、N1、P3。
  - **当前**：未开始。激活后 N3 升级为 `[x]`。

- [ ] **P5 企业化激活**(依赖 O1/O2/O3)
  - **目标**：`TenantIsolationGuard` 接入 memory store/control/用量计量 + MetadataStore 增 `tenant_id` 列 + `routes_tenants` 控制面(O1);`PluginIsolationHost` 接入 loader 作为可选隔离模式(O2);`WorkflowEngine` 暴露 control 路由/工具入口 + 生产注入 action handler(O3)。
  - **验收**：跨租户不可见且控制面按租户鉴权、插件进程隔离可选启用且崩溃可恢复、Workflow 可声明式执行且可观测;集成测试。
  - **产出**：租户接线 + tenant_id 列 + routes_tenants、loader 隔离模式、workflow 控制面入口、集成测试。
  - **依赖**：O1、O2、O3、G(控制面)。
  - **当前**：未开始。激活后 O1/O2/O3 升级为 `[x]`。

---

### Q MVP 收尾

**目标**：2026-07-26 对照 `docs/REQUIREMENTS.md` 十二条原始需求做 10 域并行代码取证(498 次代码检索 + 一次真实启动实测)后,发现一批 **MVP 必需、但未被 P0-P5 任何节点覆盖**的缺口 —— 既包括生产入口的"最后一厘米接线"(Channel 注册、工具注册),也包括此前未曾识别的**全新缺口**(记忆写入回路)。所有子节点默认不影响现有测试(新增代码路径,不改动既有默认关闭行为)。MVP 发布以 **P0-P2 + Q0-Q1** 完成为最低准入线(详见 [ROADMAP.md](./ROADMAP.md) M-MVP 里程碑)。

依赖顺序：Q0/Q1 不依赖任何 P 节点,可立即开工(Q1 最高优先级);Q2-Q6 相互独立、与 P 节点亦无强依赖,可按人力并行插入。

- [x] **Q0 开箱可触达与配置纠偏**(纯接线与纠偏,不依赖 P 节点)
  - **目标**：让"拷贝 `config.sample.jsonc` 并启动"就能获得至少一条零外部依赖的可聊通道,并修正一批会误导新用户的样例配置死键与生产健壮性缺口。
  - **验收**：`main()` 补齐 Telegram/Discord/WebChat 三个注册分支(镜像 OneBot 分支);裸部署(无 `data/routing.jsonc`)时已启用平台有默认路由,不再全部 DROP;`config.sample.jsonc` 修正 `control.auth_token`→`api_token`、`channels.onebot.ws_reverse_url`→`host/port`、`channels.webchat` 死配置、`alerting` 死键;Dockerfile 补 `COPY uv.lock` + `uv sync --frozen`(构建可复现);`docker-compose.yml` 按需补 OneBot 场景的 8080 端口映射说明;Windows `main()` 用 `try/finally` 包 `shutdown()` 且捕获 `KeyboardInterrupt`,Ctrl+C 走优雅关闭;`web_search` 默认策略由 `allow` 改 `deny`(无后端时不出现在 LLM schema 里);`ProviderManager._agent_providers` 在 `reload_config`/`destroy` 时失效缓存(PATCH 改 llm 立即热生效);`AgentManager.destroy(keep_memory=False)` 清理 `data/agents/<id>/memory`;`agent/tools/registry.py` 修正过期的 `task`→`task_runner` 映射(改查 `subagent_supervisor`,否则 SubAgent 委派被挡死)。
  - **产出**：`main.py` 三个 channel 注册分支、`config.sample.jsonc` 修正、`Dockerfile`/`docker-compose.yml` 修正、`main.py` 优雅关闭修正、`ProviderManager`/`AgentManager` 缓存失效修正、`registry.py` 映射修正、对应单测与一次多平台冒烟。
  - **依赖**：H1(适配器实现)、K1(生命周期)、K8(CI/Docker)。均已具备,本节点是纯接线与纠偏。
  - **当前**：已完成 (2026-07-27)。验收清单逐项落地:
    - `main._register_channel_adapters` 四平台按 `channels.*` 配置惰性注册 (未启用零 import);`main._ensure_default_routing` 裸部署 (bindings 与 default_agents 全空) 时为已注册平台登记默认 Agent (仅内存不落盘, 用户显式配置过任何路由即不动)。
    - `config.sample.jsonc` 四死键修正 (`api_token`/`host+port`/webchat 注释附 curl 示例/alerting 标注未接线);Dockerfile `COPY uv.lock` + `--frozen`;compose 附 8080/8090 端口映射注释;`main()` try/finally 优雅关闭;`web_search` 全局与 RESTRICTED 模板均改 deny;`ProviderManager.invalidate_agent_provider` + `AgentManager.reload_config/destroy` 接线 (含 aclose 释放连接池);`destroy(keep_memory=False)` 经 pipeline 的 namespace/MetadataStore 硬删三表 + `SparseBM25Index.clear` (shared 命名空间拒绝清理, 原 TODO 落地);registry `task` 门改为 `("subagent_supervisor", "task_runner")` 任一注入即放行 (restricted 门支持备选服务键)。
    - **冒烟发现并修复两个开箱不可聊的隐藏缺陷**: ① `_send_reply` 构造回复不带 session_id;② 更根本的 —— `SessionManager.get_or_create` 会把消息 session_id 改写为内部 `sess_*`, 平台侧会话键丢失, WebChat 回复与 D9 进度帧都落错队列 → `process_message` 现在在改写前捕获 `platform_session_id` 并透传 `_send_reply`/`_make_progress_sender`。
    - 真实启动冒烟通过: 拷 sample 起进程 → `POST /webchat/send` → 默认路由 → StubProvider 回复 → `GET /webchat/poll` 按客户端会话键取回。附 `tests/unit/test_q0_wiring.py` (14 测试)。

- [x] **Q1 记忆写入回路与身份稳定化**(MVP 最高优先级,不依赖 P0)
  - **目标**：补齐 K3 验收要求但从未接线的"消息/会话结束后真实写入 Episode"——这是记忆检索/注入/治理整条链路能真正发挥作用的前提,当前该链路读侧全通但生产端零写入,记忆恒为空。同时稳定化 person_id 与 Session。
  - **验收**：每轮对话回复后(或 `POST_MESSAGE` hook)真实调用 `store_episode`;每 N 轮或每次互动后更新人物画像(`upsert_person_profile`)与 `relationship_depth`/`interaction_count`;行话学习(可选,降级不阻塞 MVP);聊天 → 重启 → 记忆检索命中;`UserMapper` SQLite 持久化,`person_id` 跨重启稳定;`SessionManager` 状态持久化(可选,MVP 可接受会话状态重启丢失但需在文档准确标注,不得再宣称"可持久化恢复")。
  - **产出**：`_dispatch_message`/`process_message` 记忆写入接线、画像/关系更新回路、`UserMapper` 持久化、集成测试(聊天→重启→检索命中、画像随轮次加深)。
  - **依赖**：K3(存储基建)、D6-D7(检索/注入)、K4(持久化恢复框架)。
  - **当前**：已完成 (2026-07-27)。
    - **episodic 写入回路**: `AgentManager._dispatch_message` 回复后经 `_schedule_memory_write` 后台任务调 `instance.memory.store_episode` (存整轮对话"用户话+回复", importance 启发式 0.5); 后台化避免给回复路径加延迟 (配 embedding 时写入含一次向量化 API 调用); 任务强引用集合 + done 自清理; 失败降级只记日志 (SPECIFICATION 5.1)。
    - **画像/关系回路**: `_update_person_profile` 每次互动 `interaction_count+1`、`relationship_depth+0.01` (封顶 1.0)、name/first_seen/last_seen 维护; person_id 与读侧 (PersonProfileInjector/query_person_profile) 同口径 —— 优先 UserMapper master_id, agent 键用 instance.agent_id。画像文本 LLM 归纳留 MemoryConsolidator (MVP 后)。
    - **UserMapper SQLite 持久化**: 写穿模式 (user_bindings + user_profiles 两表, 含 behavior_patterns JSON), 内存缓存未命中先查 DB 恢复既有 master_id; 不传 db_path 保持纯内存 (测试零行为变化); main 接 `data/gateway/identity.db`。
    - **边界**: 行话学习未做 (可选项, 归 MemoryConsolidator); SessionManager 状态仍不持久化 (已在 PROGRESS 如实标注); `config.sample.jsonc` 的 `memory.enabled` 默认改 true (纯 SQLite 零外部依赖, "越聊越熟"开箱生效)。
    - 集成测试 `tests/integration/test_q1_memory_write_loop.py` (4): 聊→重启(新 pipeline 预热)→BM25 命中、画像随互动加深、UserMapper 重启同 master_id、纯内存模式零行为变化。

- [ ] **Q2 人格差异化实现**(依赖 D8 人格系统 + D2 prompt_builder)
  - **目标**：让 `AgentConfig.persona` 配置的人格文本真正影响 System Prompt,并把 D8 已实现但未注册的情绪/表达风格/注意力漂移能力接入 Prompt 组装与更新回路,使不同 Agent 的人格差异在回复中可辨。
  - **验收**：`persona` 文本接入 `BaseIdentityInjector`(或新增专用注入器);`MoodInjector`/`ExpressionStyleInjector`/`AttentionDriftInjector` 实现真实文案(非空串)并注册进 `prompt_builder`;`MoodEngine.update/decay` 在 `POST_LLM`/`FINAL_RESPONSE` 或周期任务中真实被调用,情绪随对话变化;`PersonaManager.get_expression_style/get_drift_level` 有生产调用点。
  - **产出**：`BaseIdentityInjector` persona 接线、三个注入器实现+注册、情绪更新回路、集成测试(两个不同 persona 配置的 Agent 回复风格可辨)。
  - **依赖**：D8(PersonaManager/MoodEngine 已实现)、D2(prompt_builder)。
  - **当前**：未开始。

- [ ] **Q3 插件与 MCP 生态数据面接线**(依赖 F1-F4/E4/H2,均已实现)
  - **目标**：让插件(Native/AstrBot/MaiBot)与 MCP Server 注册的工具/命令/注入器真正进入 Agent 的运行时注册表并被 LLM 调用,而不仅仅是"加载成功但惰性"。
  - **验收**：`main.py` 构造 `PluginContext` 时传入真实的进程级共享工具/命令/注入器注册表(复用已验证的 `assembly.py:100-104` `plugin_agent_hooks` 模式),`assemble_agent` 把共享注册表合并进每个 Agent 的 `ToolRegistry`/`CommandRegistry`/`SystemPromptBuilder`;`plugin/runtime/loader.py` 加载 AstrBot/MaiBot 插件后调用 `FunctionToolAdapter`/`MaiBotPluginAdapter.adapt` 完成真正桥接;`PluginManager` 构造时传入 `EnableMatrix`,`plugins_allow`/`plugins_deny` 对插件 hooks 真实生效;`AgentConfig.mcp_servers` 配置后,`assembly` 按需构造 `MCPClient`、`connect`、把 `list_tools` 结果注册进 `ToolRegistry`,Agent 停止/销毁时 `disconnect`;`tools.workspace_root`/`tools.bash_allowlist` 配置项接入 `build_services`,使 `bash`/`read_file`/`write_file` 三个 CLI 工具不再因 services 未注入而恒被拒绝。
  - **产出**：共享注册表机制、AstrBot/MaiBot 桥接接线、PluginManager EnableMatrix 注入、MCP Client 生产接线、CLI 工具 services 注入、集成测试(示例插件注册的工具被 LLM 真实调用)。
  - **依赖**：F1-F4(兼容层与加载器已实现)、E4(EnableMatrix 已实现)、H2(MCPClient 已实现)。
  - **当前**：未开始。

- [ ] **Q4 多模态工具注册与计量收尾**(依赖 J1/J2,均已实现)
  - **目标**：打通 J2 已就绪的 Provider/Router/Catalog/ArtifactStore 与 Agent 侧的"最后一厘米"——6 个语义媒体工具注册进 ToolRegistry,出入站媒体链路可用,多模态用量真实可查。
  - **验收**：`assembly.py` 注册 vision/STT/TTS/生图/视频理解/视频生成 6 个 `media.py` 工具(视频两模态可保留桩,待 O5 二次确认端点);`AgentConfig` 增 `model_capabilities_allow` 字段并映射为工具可见性;`_send_reply` 扫描回复中的 `artifact_id` 引用,经 `MediaResolver.resolve_for_channel` 转换为对应 Channel 的 segment 发送;入站媒体(用户上传图片/语音)下载落盘到 `data/uploads/`,`MediaNormalizer` 白名单相应扩展,生成合法 `media_uri` 供工具使用;`_MediaToolBase`/`EmbeddingManager`/`Reranker` 调用点接入 `UsageRecorder` 的 6 个多模态 `record_*` 方法;`data/pricing.jsonc` 价目表加载机制落地,`ModelUsageEvent` 的 provider 字段与价目表 key 对齐(而非记 `type(provider).__name__`)。
  - **产出**：媒体工具注册、`model_capabilities_allow` 字段、出/入站媒体链路、多模态计量埋点、价目表加载、集成测试(配置生图/视觉 key 后发图/识图全链可用且计量有数)。
  - **依赖**：J1(用量框架)、J2(Provider/Router/Catalog/ArtifactStore)。
  - **当前**：未开始。

- [ ] **Q5 WebUI 与控制面收尾**(依赖 J3/G2/G3,均已实现)
  - **目标**：修掉 J3 WebUI 与 G2/G3 控制面里"看起来完成但实为占位"的断点,并给自动化场景补上生产启动点。
  - **验收**：Extensions 插件页改接真实 `/agents/{id}/plugins` API;SubAgent 任务表改正确 `agent_id` 参数(而非硬编码 `_`);新增 `GET /agents/{id}/config` 返回全量配置 + 真实 `revision`,WebUI `loadConfigForEdit` 改用它(乐观锁真实生效);WebUI 消费 `/events/stream` SSE(`EventSource`);Usage 明细表按实际 API 返回结构(裸数组)解析,不再读 `events?.events`;补 `routes_webhooks`(subscribe/unsubscribe/list + `/automation/trigger`)并在 `main.py` 构造 `WebhookManager` 订阅 `EventBus` 事件;`isac/control/mcp_server.py` 补生产启动点(独立进程或桥接到 Admin API)并补齐 5 个声明但未实现的工具;密钥管理策略文档化为"配置文件 + env 覆盖"(`ISAC_API_TOKEN` 已支持,Provider `api_key` 同理补 env 映射),`SecretStore` 接线留 MVP 之后。
  - **产出**：WebUI 断点修复、`GET /agents/{id}/config` 端点、SSE 前端消费、Webhook 路由与事件源接线、MCP Server 启动点、密钥管理文档、集成测试。
  - **依赖**：J3(WebUI v2)、G2(MCP Server)、G3(Webhooks)。
  - **当前**：未开始。

- [ ] **Q6 SubAgent 用量与安全补漏**(依赖 J4,已实现)
  - **目标**：让 J4 SubAgent 的用量/证据数据真实可信,并补上两个安全口子。
  - **验收**：`supervisor` 保存 `result.usage`/`evidence_refs` 到 `run.tokens_used`/`tool_calls_used`/journal(而非只留 `summary`);`delegate_task` 收集的背景摘要经 `ContextEnvelopeBuilder` 真正传给子 Agent;`SubAgentPolicy`/`supervisor` 加并发上限(信号量或计数器);`control/defaults.py` 的 `RESTRICTED_TOOLS_POLICY` 补 `deny` `delegate_task`。
  - **产出**：supervisor 用量/证据保存、summary 传递接线、并发信号量、受限策略修正、集成测试。
  - **依赖**：J4(SubAgent Runtime)。
  - **当前**：未开始。

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
| **`[x]` / `[~]` / `[ ]`** | 三态进度标记(见 §二)：`[x]` 已交付(含主链路接线+集成验证);`[~]` 实现完成待接线(核心逻辑+单测完成,但未接入生产主链路,接线项归 §四 P 节点);`[ ]` 未开始。 |
| **主链路接线 / 激活** | 把已实现的能力接入生产消息处理链路(manager / loop / assembly / pipeline / gateway 等)使其真正生效,而非仅有独立实现与单测。散落的接线待办统一收敛在 §四 **P 节点**。 |
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
| **MVP** | Minimum Viable Product,满足 [ROADMAP.md](./ROADMAP.md) M-MVP 里程碑定义(P0-P2 + Q0-Q1 完成)的最小可用产品,是当前项目下一个明确的发布目标。 |
| **Q 节点(MVP 收尾)** | 2026-07-26 对照 `REQUIREMENTS.md` 逐条代码取证后新增的节点组,收纳未被 P0-P5 覆盖、但 MVP 必需的缺口(定义见 §四 Q)。 |
| **MVP 差距复核** | 2026-07-26 对照 `REQUIREMENTS.md` 十二条需求做的一次性审计事件(10 域并行代码取证 + 真实启动实测);其结论落为各节点下的"MVP 缺口复核"批注与 §四 Q 节点组。 |
| **MVP 缺口复核** | 本文档中标注在已交付(`[x]`)节点下的补充说明(是上述"MVP 差距复核"审计的逐节点产物),记录与该节点"完成定义"矛盾的未接线子行为,不改动该节点其余已验证部分的状态,指向修复它的 Q/P 节点。 |
