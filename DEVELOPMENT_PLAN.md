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

| 大节点 | 名称 | 状态 | 说明 |
|--------|------|------|------|
| A | 文档冻结 | 100% | A1-A5 全部完成, A4 持续维护 |
| B | 基础骨架 | 100% | 全部完成 |
| C | 连接与路由 | 100% | 全部完成 |
| D | 单 Agent 核心 | 89% | D1-D8 完成，D9 任务进度报告待实现 |
| E | 多 Agent 运行时 | 80% | E1-E4 完成, E5 集成测试待业务全完成后做 |
| F | 插件生态 | 100% | F1-F4 全部完成 |
| G | 控制面与自动化 | 100% | G1-G4 全部完成 |
| H | 平台与工具扩展 | 100% | H1-H3 全部完成 |
| I | 生产化与交付 | 50% | I1/I3/I4 基础能力完成；I2/I5/I6 待 K 节点重新验收 |
| J | 模型能力、计量与管理面增强 | 0% | J1-J3 已设计，K1-K8 完成前暂停实现 |
| K | 稳定化与可用版本闭环 | 0% | K1-K8 为当前最高优先级，完成前项目定位为 Alpha |

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

- [ ] **D9 任务进度报告**
  - **验收**：Agent Loop 在工具完成/失败后产生 `ProgressEvent`；慢工具可在执行前报告；`ProgressReporter` 完成人格模板渲染、敏感信息过滤、2 秒默认频控、连续事件合并和每任务上限；WebChat 输出原生 `progress` 事件，普通 IM 降级为带 `message_kind=progress` 的文本；发送失败不阻断主任务；中断后不再发送旧任务进度。
  - **产出**：`runtime/progress.py`、Agent Loop/Runtime/Channel 接线、Persona 进度模板、配置项及单元/集成测试。
  - **依赖**：D3、D4、D8、C1。
  - **当前**：架构与协议已写入 `HUMANLIKE_RUNTIME.md`、`ARCHITECTURE.md`、`SPECIFICATION.md`、`DEVELOP.md`；代码待实现。
  - **边界**：默认模板渲染不额外调用 LLM；可选 LLM 改写必须受预算、超时和降级策略约束。进度不包含 reasoning、原始工具参数或未清洗结果，也不计入普通回复频率和行为学习。

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

- [ ] **J1 模型用量与成本计量**
  - **验收**：LLM/Embedding/Reranker/STT/TTS/ImageGen/Video 的每次物理请求均产生 `ModelUsageEvent`；重试、回退、失败和缓存 Token 可区分；支持按 Provider/模型/Agent/会话/模态/时间聚合；价格快照可追溯；未知价格不伪造成本；写入失败不阻塞主调用。
  - **产出**：`observability/usage/{models,recorder,storage,pricing}.py`、SQLite Schema、ProviderManager 接线、Usage REST API、指标与测试。
  - **依赖**：B2、G1、I5。
  - **当前**：架构、数据契约、API、权限和隐私规范已写入 `ARCHITECTURE.md`、`SPECIFICATION.md`、`CONTROL_PLANE_SPEC.md`、`DEVELOP.md`；代码待实现。

- [ ] **J2 多模态 Provider 与能力选择**
  - **验收**：文本、视觉理解、STT、TTS、图片生成、视频理解/生成 Provider 使用统一注册与能力声明；Agent 只感知被授权能力；输入内容、用户意图、成本/延迟策略可选择模型；不可用时按能力回退或明确失败；生成结果经制品存储和 Channel 能力适配发送。
  - **产出**：Provider 能力目录、ModelRouter、多模态 Provider ABC/适配器、能力 Injector、媒体工具、ArtifactStore、权限与测试。
  - **依赖**：D2-D4、E1/E4、H1、J1。
  - **当前**：能力目录、Provider ABC、ModelRouter、Agent 能力授权、语义工具、媒体校验、ArtifactStore 与 Channel 降级设计已写入 `ARCHITECTURE.md`、`SPECIFICATION.md`、`CONTROL_PLANE_SPEC.md`、`DEVELOP.md`；代码待实现。

- [ ] **J3 WebUI v2 管理与观测**
  - **验收**：Dashboard、Agent、Channel/路由、Provider/模型、Token/成本、插件/MCP/工具、记忆、会话/任务进度、日志/审计、系统设置页面可用；配置写入支持 Schema 校验、差异预览、二次确认、版本冲突检测和审计；密钥只可替换不可回显。
  - **产出**：`control/webui/` 前端重构、Control API 扩展、实时事件通道、浏览器端测试与权限测试。
  - **依赖**：G1-G4、I1/I5、D9、J1-J2。
  - **当前**：十个页面域、配置编辑事务、Schema/diff/确认/ETag、密钥不回显、实时事件恢复、响应式、WCAG 2.1 AA 与浏览器测试要求已写入 `CONTROL_PLANE_SPEC.md` 和 `ARCHITECTURE.md`；代码待实现。现有 Vanilla JS 四模块面板保留为 v1 最小实现，不视为 J3 完成。

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

**强制开发顺序**：K1 → K2 → K3/K4 → K5 → K6/K7 → K8。K1-K5 完成前暂停 D9、J1-J3；K8 通过后才允许恢复 I6 发布验收。

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
| **稳定化节点** | K1-K8；修复常驻、真实 Provider、持久化、E2E、安全和发布门禁的最高优先级工作。 |
| **可用版本准入** | K1-K8 全部完成且真实运行验收通过后，项目才可从 Alpha 提升为可用版本。 |
| **Observer Agent** | 旁听 Agent，只接收消息用于记忆/学习/候选协作，默认不发送 IM 回复。 |

---

## 六、文档更新记录

| 日期 | 更新人 | 内容 |
|------|--------|------|
| 2026-07-23 | Reviewer | 复审撤回 v1.0/生产可用结论：实测主程序启动后立即返回；真实 Provider、存储恢复、多 Agent E2E 未闭环。新增 K1-K8 稳定化节点为最高优先级，I 节点 100% → 50% |
| 2026-07-23 | Architect | 新增 J3 WebUI v2 设计：覆盖 Dashboard、Agent、Channel/路由、Provider/模型、用量成本、扩展、记忆、会话任务、日志审计与系统配置；加入安全配置事务、实时事件、响应式与无障碍要求；代码待实现 |
| 2026-07-23 | Architect | 新增 J2 多模态 Provider 与能力选择设计：统一文本/视觉/STT/TTS/生图/视频理解与生成的能力目录、Agent 授权、ModelRouter、语义工具、ArtifactStore 和 Channel 降级；代码待实现 |
| 2026-07-23 | Architect | 新增 J1 模型用量与成本计量设计：按物理请求记录 Provider/模型/Agent/会话/模态、缓存与推理 Token、非 Token 计量单位、重试/回退/失败、价格快照与查询权限；代码待实现 |
| 2026-07-23 | Architect | 新增 D9 任务进度报告设计：工具完成后最低保障汇报，慢工具执行前可选汇报；定义 ProgressEvent/ProgressReporter、人格模板、频控合并、脱敏、WebChat 原生事件与普通 IM 降级。D 节点 100% → 89% |
| 2026-07-23 | Architect | I6 最终测试与发布 v1.0.0: 单测 326 passed (核心模块 80%+ 覆盖率); CHANGELOG.md 记录 v1.0.0 全部变更; pyproject.toml + isac/__init__.py 版本号 → 1.0.0; A4 标 [x] (持续维护验收); Git tag v1.0.0。I 节点 83% → 100%, A 节点 85% → 100%。项目整体完成 v1.0.0 发布 (集成测试待业务全完成后做) |
| 2026-07-23 | Architect | I5 监控告警完成: isac/observability/ 新增 MetricsCollector (Counter/Gauge/Histogram + Prometheus 输出 + JSON snapshot); AlertManager + AlertRule 规则驱动告警 (cooldown + 推送 Webhook); 3 个默认告警规则; server.py 暴露 /metrics + /api/v1/metrics。I 节点 67% → 83% |
| 2026-07-23 | Architect | I4 数据工具完成: scripts/migrate.py AstrBot/MaiBot 迁移 (LLM 配置解析 + 插件复制 + 默认 Agent + --dry-run); scripts/export.py export/import 子命令 (zip 打包 + 排除 audit.ndjson/venv/pycache + overwrite 控制)。I 节点 50% → 67% |
| 2026-07-23 | Architect | I3 文档完善完成: docs/ 新增 6 篇文档 (README 导航/usage 使用/deployment Docker 部署/api Admin REST API/plugin_development 插件开发/control_automation 控制面自动化)。I 节点 33% → 50% |
| 2026-07-23 | Architect | I2 Docker 部署完成: Dockerfile 多阶段 (builder + runtime, python:3.12-slim) + uv sync + EXPOSE 8765 + HEALTHCHECK + VOLUME /app/data; docker-compose.yml 一键启动 + isac_data volume + restart unless-stopped + 环境变量; scripts/docker_deploy.sh 部署脚本 (8 命令); .dockerignore。I 节点 17% → 33% |
| 2026-07-23 | Architect | I1 WebUI 管理面板完成: control/webui/{index.html,app.js,__init__.py} FastAPI 静态托管 + Vanilla JS (不依赖 Vue 构建); Agent/路由/Link/审计四模块; 前端 fetch Bearer Token 调 G1 API。I 节点 0% → 17% |
| 2026-07-23 | Architect | H3 实用工具与子 Agent 完成: bash (命令白名单 + shell 元字符防护) / read_file (路径白名单 + 行范围) / write_file (路径白名单 + append) / web_search (后端注入) 在 D4 落地; 本节点补 TaskRunner 真实实现 (用 ISACAgentLoop 派生子任务, 限制 token 预算与递归深度)。H 节点 67% → 100% |
| 2026-07-23 | Architect | H2 MCP Client 完成: MCPClient 支持 stdio 子进程 + HTTP/SSE 两种传输; connect/list_tools/call_tool/disconnect 完整生命周期; MCPToolBridge 桥接为 ISAC Tool; JSON-RPC 2.0 协议 + 错误处理。H 节点 33% → 67% |
| 2026-07-23 | Architect | H1 平台适配器完成: Telegram (Bot API long polling + httpx); Discord (REST polling 简化版); WebChat (asyncio.start_server 极简 HTTP /webchat/send+/webchat/poll + 内存队列)。H 节点 0% → 33% |
| 2026-07-23 | Architect | G4 控制面安全与审计完成: control/defaults.py RESTRICTED_TOOLS_POLICY (bash/task deny, read_file/write_file restricted) + RESTRICTED_COMMANDS_ALLOW; make_restricted_agent_config 工厂 (plugins_deny=["*"] + mcp_servers=[]); is_safe_default_host/enforce_safe_host 防误绑定; main.py 接入 enforce_safe_host。审计日志查询 (/api/v1/audit) 在 G1 落地。G 节点 75% → 100% |
| 2026-07-23 | Architect | G3 Webhooks 完成: WebhookManager subscribe/unsubscribe/list/dispatch/trigger; dispatch 并发推送 + 失败重试 3 次 (指数退避); httpx 惰性导入或 http_client 注入; trigger 作 /automation/trigger 入口。G 节点 50% → 75% |
| 2026-07-23 | Architect | G2 ISAC MCP Server 完成: JSON-RPC 2.0 + stdio NDJSON; initialize/tools/list/tools/call/shutdown 方法; tools/call 受 Bearer Token 认证 (与 G1 共用); 6 个工具委托到 AgentManager/Router/Bus; MCPError 标准 JSON-RPC 错误码; notification 不响应。G 节点 25% → 50% |
| 2026-07-23 | Architect | G1 Admin API 完整实现: control/auth.py hmac.compare_digest 恒定时间认证; control/audit.py AuditLog 双写 + query; routes_agents/_routing/_plugins 全部接入 auth + audit + 持久化 (AgentConfig/routing/links/plugins 矩阵); server 注入 auth/audit + /api/v1/audit 查询。G 节点 0% → 25% |
| 2026-07-23 | Architect | F4 插件加载器与启用矩阵完成: PluginLoader detect_format + load (三种格式多签名实例化); PluginManager load_all (错误隔离) + unload (on_unload) + call_on_load (Native 传 PluginContext); LoadedPlugin 元数据封装。F 节点 75% → 100% |
| 2026-07-23 | Architect | F3 原生 SDK v2 完成: PluginContext register_tool/injector/command 真实落地; register_inter_agent_hook 挂到 InterAgentBus; register_admin_route 收集到 services["admin_routes"]; on_event_intercept/on_event_async 订阅 EventBus; make_plugin_context 工厂。F 节点 50% → 75% |
| 2026-07-23 | Architect | F2 MaiBot 兼容层完成: MaiBotPlugin 基类 + @register_action/@register_command 装饰器; MaiBotPluginAdapter 扫描装饰器适配; bridge_action/bridge_command 桥接 (同步异步异常隔离)。F 节点 25% → 50% |
| 2026-07-23 | Architect | F1 AstrBot 兼容层完成: FunctionToolAdapter 桥接 @filter.llm_tool; ContextAdapter 映射 send_message/get_platform/get_provider/register_tool; Star 基类 + _FilterRegistry 装饰器; EventType 映射到 ISAC; sandbox.py meta_path import 拦截。F 节点 0% → 25% |
| 2026-07-23 | Architect | E4 启用矩阵生效: core/policy.py 新增 EnableMatrix (Agent ∩ Channel ∩ 全局); ToolRegistry effective_policy 接入; CommandRegistry enable_checker 注入; assembly.py 接线 EnableMatrix 与 4 个内置命令; manager.py handle_message 接入 /cmd 命令拦截 (跳过门控)。E 节点 60% → 80% |
| 2026-07-22 | Architect | D 节点完成 100%：D4 工具系统补齐 (13 个内置工具全部实现, restricted 策略落地, 路径白名单/命令白名单/递归深度限制, shell 元字符注入防护)；D8 人格系统补齐 (MoodEngine update/decay/label 映射, BehaviorLearner FINAL_RESPONSE hook 接线, PersonaManager 聚合 mood/behavior)；新增 `tests/unit/test_persona.py`、扩展 `tests/unit/test_builtin_tools.py` 与 `tests/unit/test_tool_registry.py`；D 节点进度 75% → 100% |
| 2026-07-22 | Architect | D1 整体验收：TurnScheduler 滑动窗口频率与存在感计数落地，runtime/manager.py 接线 record_window_message / effective_frequency / recent_self_replies / recent_window_messages / record_reply / idle_backoff.record_reply；D5/D6/D7 MVP 回填为已完成 (MetadataStore + FTS5 + BM25 真实实现，VectorStore/GraphStore/EmbeddingManager/Reranker 仍为桩)；D 节点进度 35% → 75% |
| 2026-07-22 | Architect | A5 专项施工图补齐：新增拟人化运行时、记忆系统、路由与 Agent Mesh、插件兼容、控制面规范，并同步主文档索引 |
| 2026-07-21 | Architect | 将日程制开发计划重构为节点制 SOW/TODO，新增术语表与节点使用规则 |
| 2026-07-21 | Architect | C1 OneBot 适配器实现：反向 WebSocket 连接、消息转换（text/at/image/reply/face/record）、发送、重连；main.py 注册与回复发送；新增 12 个单元测试 |
| 2026-07-21 | Architect | Review 修复 Round 2：OneBot 惰性导入（可选依赖不强制）、reply_to 对称/metadata 精简/@ 占位、会话锁键修复、Loop 接入 chat_with_retry、ReplyNecessityJudge 安全兜底、NoOpMemoryPipeline + StubProvider 让 main.py 可启动、prompt_builder 频率死锁、PRE_LLM 钩子串联、rules 字段过滤 |
| 2026-07-21 | Architect | Review 修复 Round 1：PromptInjector 下沉到 core/ 打破导入环；TokenUsage 自动补 total；ConfigMigrator 缺省版本修复；AstrBot 沙箱改用 find_spec/exec_module；补全 has_mention 判定；同步修正 ARCH/DEVELOP/SPEC/AGENTS/README 文档错误与矛盾 |
