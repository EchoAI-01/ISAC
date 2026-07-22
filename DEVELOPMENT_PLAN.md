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
- **完成定义**：小节点完成 = 代码实现 + 单元/集成测试 + 相关文档同步 + `ruff` / `mypy` 通过。

---

## 三、节点总览

| 大节点 | 名称 | 状态 | 说明 |
|--------|------|------|------|
| A | 文档冻结 | 85% | A1-A3 完成，A4 持续，A5 专项施工图已补齐 |
| B | 基础骨架 | 100% | 全部完成 |
| C | 连接与路由 | 100% | 全部完成 |
| D | 单 Agent 核心 | 100% | D1-D8 全部完成 |
| E | 多 Agent 运行时 | 80% | E1-E4 完成, E5 集成测试待业务全完成后做 |
| F | 插件生态 | 100% | F1-F4 全部完成 |
| G | 控制面与自动化 | 100% | G1-G4 全部完成 |
| H | 平台与工具扩展 | 100% | H1-H3 全部完成 |
| I | 生产化与交付 | 0% | 全部待实现 |

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

- [ ] **A4 SOW 与 AGENTS.md 维护流程**
  - **验收**：本文件与 `AGENTS.md` 的"当前进度"表每次节点完成后同步更新；新增节点有明确的依赖与验收标准。
  - **产出**：本文档 + `AGENTS.md` 进度表。
  - **依赖**：A1-A3；持续进行。

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

- [x] **B4 入口与调试脚本**
  - **验收**：`python -m isac` 可启动（无 Channel 时不报错）；`scripts/migrate.py` / `export.py` 有入口。
  - **产出**：`isac/__main__.py`、`isac/main.py`（组装骨架）、`scripts/*`。
  - **依赖**：B3。

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

- [ ] **E5 多 Agent 集成测试**
  - **验收**：2+ Agent × 1 OneBot 连接 + 触发词/默认 Agent 路由 + ask_agent 互联端到端通过。
  - **产出**：`tests/integration/test_multi_agent.py`。
  - **依赖**：C1、E3、E4。

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

- [ ] **I1 WebUI 管理面板**
  - **验收**：FastAPI + Vue 可管理 Agent/路由/Link/记忆。
  - **产出**：`control/api/` 扩展 + WebUI 前端。
  - **依赖**：G1。

- [ ] **I2 Docker 部署**
  - **验收**：Dockerfile + docker-compose.yml 一键启动；含控制面端口。
  - **产出**：`Dockerfile`、`docker-compose.yml`、部署脚本。
  - **依赖**：I1（可选）。

- [ ] **I3 文档完善**
  - **验收**：使用文档、API 文档、部署文档、插件开发指南、控制面自动化指南齐全。
  - **产出**：`docs/` 或更新根目录 README/ARCH/DEVELOP/SPEC。
  - **依赖**：F、G 完成。

- [ ] **I4 数据工具**
  - **验收**：AstrBot/MaiBot → ISAC 迁移、备份/导出/导入可用。
  - **产出**：`scripts/migrate.py`、`scripts/export.py`。
  - **依赖**：D5-D7。

- [ ] **I5 监控告警**
  - **验收**：关键指标 Prometheus 采集；Webhook 告警；审计日志查看。
  - **产出**：监控中间件、告警配置。
  - **依赖**：G1、G4。

- [ ] **I6 最终测试与发布**
  - **验收**：核心模块覆盖率 ≥80%；集成测试通过；v1.0 发布。
  - **产出**：CHANGELOG、Git tag v1.0.0。
  - **依赖**：A-I5。

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
| **Observer Agent** | 旁听 Agent，只接收消息用于记忆/学习/候选协作，默认不发送 IM 回复。 |

---

## 六、文档更新记录

| 日期 | 更新人 | 内容 |
|------|--------|------|
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
