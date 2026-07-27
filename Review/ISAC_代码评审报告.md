# ISAC 项目代码评审报告

> 评审对象：`EchoAI-01/ISAC`（Intelligent Social AI Companion，多 Agent AI 社交陪伴 Bot 框架）
> 评审版本：`main` @ `48d60b0`（v1.0.0rc1）
> 评审范围：全面体检 — 架构设计、代码正确性、安全性、文档与代码一致性
> 评审方式：4 组并行深度审读 + 逐条数据流验证 + 静态检查（compile / ruff / mypy 全绿）+ 关键修复运行时验证
> 代码规模：`isac/` 约 2.25 万行、`tests/` 约 2.07 万行、`docs/` 约 9 千行，169 次提交

> **📌 更新提示**：本报告后续在 `dev` 分支（`e23b334`，2026-07-27）做了一次独立复核，结论见文末「八、二次复核」——多项本报告标记"📋 报告"的问题已在 `dev` 上确认修复或部分修复，同时发现若干 `dev` 分支新引入的问题。建议先看该节的状态速览，再读本报告主体（主体内容为 `main@48d60b0` 快照，不做追溯改写）。

---

## 一、总体评价

这是一个**架构设计相当出色、工程规范扎实**的框架级项目。值得肯定的地方很多：

- **分层清晰、单向依赖**。`utils → provider → memory → persona → agent → gating → router → gateway → channel → commands → plugin → runtime → control → main` 的单向依赖在代码里被严格执行，跨层用运行时注入而非 import，这一点做得比多数同类项目好。
- **契约先行**。`core/types.py`、`core/events.py`、ABC 接口与 `docs/SPECIFICATION.md` 对齐，改契约先改文档。
- **安全基线的“底子”是对的**。密钥用 AES-256-GCM（`SecretStore`，强制 `ISAC_SECRET_KEY`，不做明文降级）；所有 SQL 都用 `?` 绑定参数，动态片段来自硬编码白名单；Token 比较用 `hmac.compare_digest`；会话 Cookie + CSRF 双提交模型设计合理；SSRF 的 IP 分类器本身很健壮（我实测它能挡住 IPv4-mapped IPv6、十六进制/八进制/十进制整数形式的 `127.0.0.1`、ULA、link-local）。
- **测试与静态检查规范**。ruff、mypy 在本次评审中全部通过；单测组织规范（unit / integration / browser 分层）。

但评审也发现了一个**必须正视的核心问题**，以及若干真实缺陷。核心问题不是“某段代码写错了”，而是**文档宣称的完成度与代码实际接线状态存在系统性偏差**——README 状态表把大量子系统标为“✅ 完成”，而这些子系统的核心逻辑虽然实现且有单测，却**没有接入生产消息主链路**（默认关闭、无调用点）。值得说明的是，`AGENTS.md` 自己是**诚实披露了**这一点的（§剩余工作明确写了“主链路尚未接线”），问题出在 README 面向用户的状态表口径与之不一致。

> ⚠️ 一句话结论：**把它当作“架构完备、核心链路可跑通的高质量骨架 + 大量已实现但待接线的子系统”来看待是准确的；把 README 状态表逐条当作“生产可用的已完成特性”则会踩坑。**

评审同时**直接修复了其中低风险、可独立收敛的高危/中危缺陷**（见第五节），已通过静态检查与运行时验证。

---

## 二、严重程度分级与清单

| # | 缺陷 | 类别 | 严重度 | 处理 |
|---|------|------|:---:|:---:|
| H1 | 记忆/会话读接口无 scope 校验，窄权限 Token 可读所有 Agent 会话内容与人物画像(PII) | 安全/越权 | **高** | ✅ 已修复 |
| H2 | “进程级插件隔离”并未生效：插件在宿主进程内 `exec_module` 执行，隔离宿主是 echo 桩 | 安全/设计 | **高** | ⚠️ dev 部分修复¹ |
| H3 | 向量/稠密检索从未在检索路径执行，语义召回实际缺失，且每次写入白算一次 embedding | 功能/正确性 | **高** | ✅ dev 已修复¹ |
| H4 | 流式(streaming)工具调用整体损坏：参数丢失 + 产生空工具调用 | 正确性 | **高**(潜伏) | ⚠️ dev 部分修复¹ |
| M1 | 会话锁只 acquire 不 release，主链路长期运行内存无界增长 | 资源泄漏 | 中高 | ✅ 已修复 |
| M2 | 跨 Agent `notify` 在 bus 层被静默丢弃，工具却报告成功 | 正确性 | 中 | ✅ dev 已修复¹ |
| M3 | Discord 时间戳解析未加保护，单条坏消息可令该频道轮询永久卡死 + 时区错误 | 正确性/健壮性 | 中 | ✅ 已修复 |
| M4 | 原子写未对父目录 fsync，掉电后刚写入的配置可能丢失 | 持久化 | 中 | ✅ 已修复 |
| M5 | 多个 per-session 状态字典（Gating/Focus）无上限、无回收 | 资源泄漏 | 中 | 📋 报告 |
| M6 | ProactiveScheduler 冷却期把任务退回队首反复重取，饿死其他会话 | 正确性 | 中 | ✅ dev 已修复¹ |
| M7 | Workflow 引擎只启动首个入口节点，且并行分支在首个到达时就 join | 正确性 | 中 | 📋 报告 |
| L1 | 自动化创建的 Agent 无能力沙箱（restricted 默认是死代码），可开 bash/全插件 | 安全 | 低-中 | 📋 报告 |
| L2 | 多租户隔离 `TenantIsolationGuard` 全程无调用点，隔离形同虚设 | 安全/设计 | 低-中 | ✅ dev 已修复¹ |
| L3 | 记忆软删除不同步 BM25 内存索引，删除后存活项的 BM25 打分被污染 | 正确性 | 低-中 | ✅ dev 已修复¹ |
| L4 | SSRF 校验与实际请求分离(TOCTOU/DNS rebinding 可绕过) | 安全 | 中(受限可达) | 📋 报告 |
| L5 | 记忆治理审计 `operator` 恒为空、无 agent_id 列，无法归因“谁操作” | 合规/审计 | 低 | ⚠️ dev 部分修复¹ |
| L6 | `/metrics` 无认证；非 ASCII Bearer Token 触发 500 而非 401 | 安全/健壮性 | 低 | 📋 报告 |
| L7 | 一批“✅ 完成”特性实际未接线：Mesh、主动任务、拟人化 wait/interrupt、多租户、Workflow | 文档一致性 | — | 📋 报告 |
| L8 | `write_file` 在事件循环里做同步磁盘 I/O；SubAgentJournal seq 并发下可能丢事件；MCP `sse` 传输未实现 | 正确性/性能 | 低 | 📋 报告 |

图例：✅ 已修复并验证 / 📋 仅报告（因属特性接线、架构决策或潜伏路径，不宜在评审阶段擅自改动） / ⚠️ 部分修复（仍有缺口）
¹ 见第八节「二次复核」：`dev` 分支（`e23b334`，2026-07-27）已发生大量后续开发（P0-P2/Q0-Q1 主链路激活 + 两轮独立修复），标注状态针对 `dev`，不追溯改写本报告 `main@48d60b0` 快照本身的结论。

---

## 三、高严重度问题详解

### H1（已修复）记忆/会话读接口越权：窄权限 Token 可读所有会话内容与画像

**位置**：`isac/control/api/server.py:277,283`、`isac/control/api/routes_memory.py`、`isac/control/api/routes_sessions.py`

控制面在启用 `control.tokens[]`（Token Scope 模型，Fix-12）后，路由级基线认证 `auth_dependency = make_token_only_dependency(...)` **只校验“是不是一个合法 Token”，不校验 scope**；具体 scope 由端点级 `scope_dependency` 把关。除记忆读、会话两个路由外，`routes_agents / routes_routing / routes_plugins / routes_usage / routes_subagent / routes_providers / routes_memory_admin` **都接了 `scope_dependency`** 做端点级收窄。

问题在于：`routes_memory`（`/memory/{agent_id}/episodes|profiles|jargon`）和 `routes_sessions`（`/sessions`、`/sessions/{id}`、`/sessions/{id}/messages`）**的 `build_router` 连 `scope_dependency` 参数都不接收**，端点上没有任何 scope 门禁。而 `routes_memory_admin` 里有一条明确的注释（CR2-Fix-10）承认治理路由“此前完全没有 scope 校验……绕开了 Fix-12 建立的 Token Scope 模型”，并给它补上了 `memory:read/memory:write`——却**漏掉了同样敏感、甚至直接返回会话原文的这两个读路由**。

**失败场景**：运维给某个只读集成配了 `{"token":"T1","scopes":["usage:read"]}`。T1 是合法 Token，因此通过这两个路由的基线认证，又没有端点级 scope 检查——于是 T1 可以：
- `GET /api/v1/memory/<任意 agent>/episodes` → 读到任意 Agent 的**全部会话内容**；
- `GET /api/v1/memory/<任意 agent>/profiles` → 读到**人物画像**（姓名、关系深度）；
- `GET /api/v1/sessions/{id}/messages` → 读到**消息历史原文**。

`scopes:[]` 的 Token 同样能读。这是一次**跨权限的 PII/会话内容泄露**（Broken Access Control）。

**修复**：给两个路由的 `build_router` 补 `scope_dependency` 参数，所有读端点加 `dependencies=[Depends(scope_dependency("memory:read"))]`；`server.py` 挂载时把 `scope_dependency` 透传进去。未配置 `tokens[]` 时 `scope_dependency` 为 `None`，`read_deps` 为空列表，行为与修复前完全一致（向后兼容，现有单测不受影响）。已用真实 `isac.control.auth` 原语验证授权判定：`usage:read`/空 scope → 403、未知 Token → 401、`memory:read`/`*` → 200。

### H2（报告）“进程级插件隔离”并未生效

**位置**：`isac/plugin/runtime/loader.py:158-162`、`isac/plugin/isolation/host.py:31-77`

实际接入生产的加载器（`main.py` → `PluginManager.load_all` → `PluginLoader`）用 `spec.loader.exec_module(module)` **在宿主进程内直接执行插件入口文件的顶层代码**——只要插件被加载，其代码就以宿主完整权限（fs/网络/os）运行，没有任何沙箱。README 宣称的 `PluginIsolationHost`（子进程隔离）**从未被加载器/管理器引用**，而且它的子进程 worker 是一个**硬编码的 echo 服务**，根本不导入或运行任何真实插件。此外 `PluginManager.call_on_load` 与 `make_plugin_context` 也**无调用点**——插件唯一能注册工具/命令/注入器的 `on_load(context)` 钩子从不被触发。也就是说，被加载的插件**既危险（顶层代码在宿主内运行）又行为惰性（钩子不生效）**。

**影响**：默认部署不加载任何第三方插件时无直接暴露；一旦按 README 的“进程级隔离已完成”预期去加载外部插件，隔离并不存在。**未修复**：实现真正的子进程隔离属于特性补全（工作量大、涉及 IPC/序列化边界），不宜在评审中擅动。建议：短期在文档与 `plugins/README.md` 明确“当前插件在宿主进程内运行、无隔离，仅加载可信插件”；中期把 `PluginIsolationHost` 从 echo 桩改为真正 fork 出 worker 加载插件，并接线 `call_on_load`。

### H3（报告）稠密/向量检索从未执行，语义召回缺失

**位置**：`isac/memory/pipeline.py:89-109`；死代码 `isac/memory/storage/vector.py`、`isac/memory/embedder.py`

`MemoryRetrievalPipeline.search()` 只跑 FTS5 + 内存 BM25 再融合，**从不调用 `self.vector.search()` 或 `self.embedder.embed_query()`**（二者全仓零调用点）。但 `store_episode()` 每次写入**都**算 embedding 并 upsert 进 `vectors.db`。

**影响**：配了 embedding provider 时，1 万条记忆 = 1 万次 embedding API 调用 + 1 万行向量，全部白算白存；纯语义匹配（与 query 无词面重叠）的记忆检索不到，检索质量静默退化为“关键词检索”。这与模块 docstring 承诺的“Dense Search + RRF Fusion”不符，但**与 `AGENTS.md` 的“召回待接入 pipeline”披露一致**。**未修复**：属检索深化的特性接线（需引入 RRF 融合与 ACL 一致性核对），建议按 `AGENTS.md` 的 P3 节点推进。

### H4（报告）流式工具调用整体损坏（潜伏）

**位置**：`isac/provider/llm/openai_compat.py:319-331`（`_parse_chunk`）+ `isac/agent/loop.py:330-336`（`_merge_chunks`）

`_parse_chunk` 把每个 SSE delta 当作**完整**工具调用，并对每个 `arguments` 片段单独 `json.loads`（片段非合法 JSON → 参数被静默丢成 `{}`）；`_merge_chunks` 又按“每 chunk 一个 ToolCall”而非**按 index 累积**。真实 OpenAI 流式里一个工具调用被拆到 N 个 delta（首块带 `id`+`name`，后续只带参数片段），合并结果是一个**参数为空**的 ToolCall + 若干 `id="" name=""` 的幽灵调用。并行工具调用（index≥1）被直接丢弃。

**影响**：`context.streaming=True` 且模型调用任何工具时必然出错（空参数 + `未知工具` + `tool_call_id=""` 导致下一轮 provider 400）。**当前无生产调用点设置 `streaming=True`（潜伏）**，但 `get_capabilities()` 对外宣称 `supports_streaming=True, supports_tools=True`。附带问题：流式路径**绕过** `chat_with_retry` 的重试/回退/降级，且未设 `stream_options.include_usage`，token 预算在流式回合永远记 0（不被强制）。建议接线流式前先修复合并逻辑并让流式复用重试/降级。

---

## 四、中低严重度问题（择要）

**M1（已修复）会话锁泄漏**：`main.py` 的 `handle_message` 只 `await session_lock.acquire(lock_key)` 却从不 `release`；K7 的“引用计数 + 无 waiter 时回收锁对象”回收逻辑只在 `SessionLockManager.handle_message` 里，而主链路没走那条路。结果 `_locks` / `_waiters` 按不同 `platform:user:group` **无界增长**（每条消息把 `_waiters[key]` +1 且永不减）。已修复为 `try/finally` 配对 `release()`，并用 1000 条消息的模拟验证字典完全回收、嵌套 waiter 引用计数正确。

**M3（已修复）Discord 轮询卡死 + 时区错误**：`_to_isac_message` 在 `_poll_channel` 提交 cursor **之前**、且**不在** try/except 内被调用；`int(time.mktime(time.strptime(ts[:19], ...)))` 遇到缺失/畸形时间戳会抛 `ValueError` 逃逸到轮询循环，而 cursor 只在整页处理完后才前进——**单条坏消息即可令该频道永远重拉同一页**（liveness 陷阱）。附带：`time.mktime` 把 UTC 时间戳按本地时区解释，偏移一个时区。已修复为独立 `_parse_timestamp` 静态方法：`calendar.timegm`（按 UTC）+ 解析失败兜底当前时间、绝不抛出。已验证 UTC 纪元正确（`2024-01-01T12:00:00Z → 1704110400`）且坏输入不抛异常。

**M4（已修复）原子写缺目录 fsync**：`utils/fs.py` 只对文件数据 `fsync`，`os.replace` 产生的目录项未落盘。掉电/崩溃紧接写入后，rename 可能未持久化，导致刚写入的配置（Agent 配置、路由规则、links、workflow/recovery 快照）静默回退到旧版——与本模块“重启仍能读上一份完整配置”的承诺矛盾。已修复为 `os.replace` 后 best-effort 对父目录 `fsync`，对不支持目录 fsync 的平台（Windows）静默降级。已验证写入往返正确、无临时文件残留。

**M2（报告）跨 Agent notify 被丢弃**：`runtime/bus.py:143` 对 `type=="notify"` **在调用 `_deliver` 之前就 return None**，目标 Agent 的 `handle_message` 从不被触发；而 `MeshActionBroker._send` 把“没抛异常”当成功、`NotifyAgentTool` 向 LLM 报告成功——一次“假成功”的丢消息。因整个 mesh 链路本就未接线（见 L7），生产影响暂时受限，故仅报告不擅改语义。

**M6（报告）主动任务调度饿死其他会话**：`conversation/scheduler.py:147` 冷却中的任务被 `insert(0, task)` 退回队首，`poll()` 又总取索引 0，于是循环反复重取同一任务，直到其会话冷却窗口结束，期间其他会话的就绪任务无法触发——恰好瓦解了 CR2-Fix-6 想提供的 per-session 冷却隔离。

**M7（报告）Workflow 引擎并行/入口处理错误**：`workflow/engine.py` 只启动 `entry_stages[0]`（多入口根节点被丢弃仍标记 SUCCEEDED），且 `if stage_id in executed: return` 使 fan-in 节点在**首个**父分支到达时就执行（钻石 DAG 下 D 在 C 完成前就跑）。

**L4（报告）SSRF TOCTOU**：`webhooks.py` / `image_gen` 在 `subscribe`/校验时解析一次 DNS 并放行，实际 `httpx` 请求时又独立重解析、不再校验——低 TTL 域名可在校验后重指向 `169.254.169.254`。IP 分类器本身健壮，`follow_redirects=False` 也已设，缺的是“校验即请求”（对已解析 IP 发起，或在连接层复核）。当前未发现挂载 webhook 的 HTTP 路由，可达性受限，但模式性弱点对任何调用方成立。

**L2 / L1（报告）多租户隔离与自动化沙箱是死代码**：`TenantIsolationGuard.enforce()`（谓词本身是安全的绑定参数、非注入）全程无调用点，数据面查询无租户谓词；`make_restricted_agent_config`（bash=deny、`plugins_deny=["*"]`）也从不被调用，两条 Agent 创建路径都直接吃调用方输入，dataclass 默认 `plugins_allow=["*"]`——持 `agent:write` 者可 `POST /agents` 造出开 bash、全插件的 Agent。二者在 `models.py` 均标注为 scaffolding，属披露范围，但“隔离/沙箱已完成”的口径不成立。

**L3 / L5（报告）记忆治理副作用**：软删除只置 `deleted=1`，不调用 `sparse.remove()`，且预热 `iter_episodes_by_namespace` 选了 `deleted` 行——墓碑残留在 BM25 内存索引里，抬高 `total_docs`/平均长度、污染存活项的 IDF 与长度归一（无内容泄露，`search_fts`/`get_episodes_by_ids` 会过滤 `deleted=0`，但排序被扰动）。治理审计 `operator` 恒写 `""`、`memory_audit` 无 `agent_id` 列，无法归因操作者。

**L6 / L8（报告）零散健壮性**：`/metrics` 无认证（被 `enforce_safe_host` 强制 127.0.0.1 兜底，暴露面限本机/SSRF）；非 ASCII Bearer Token 使 `hmac.compare_digest` 抛 `TypeError` → 500 而非干净 401（失败关闭、无绕过）；`write_file` 在 async `execute()` 里做同步 `open/write`（最多 256KB）阻塞事件循环，而 `read_file` 已用 `asyncio.to_thread` 卸载；`SubAgentJournal.append` 的 `seq` 用 `SELECT MAX+1` 后 `INSERT OR REPLACE`，并发同 task 可算出同 `seq` 互相覆盖丢事件；MCP `transport="sse"` 实际走普通 `POST "/"`、无 SSE 处理。

---

## 五、文档与代码一致性（L7 · 本次评审的重点关切）

生产消息主链路（`main.py::process_message`）实测为：
`fire_intercept(ON_MESSAGE)` → `MessageRouter.route` → `SessionManager.get_or_create` → `UserMapper.resolve` → `AgentManager.handle_message` → `_dispatch_message`（会话缓存[flag] → 命令拦截 → `GatingSystem.evaluate` → `loop.run`）→ `_send_reply` → `fire_async(POST_MESSAGE)`。**这就是全部生产路径**。据此逐条核对 README 状态表：

| README 声称“✅ 完成” | 实际状态 | 证据 |
|---|---|---|
| 记忆检索喂给 prompt（Vector/Graph/Embed/Rerank 真实实现） | **部分接线、召回退化** | 注入器每回合确会跑，但默认 `memory.enabled=false` → `NoOpMemoryPipeline` 返回 `[]`；即便开启，`search` 也只用 FTS+BM25+rerank，**vector/graph/embed 不参与召回**（见 H3） |
| MeshRouter observer/candidate（M1 100%） | **未接线** | `MeshRouter.route` 无调用点，主链路只有 `MessageRouter.route` |
| Mesh actions handoff/notify/memory_query（M2 100%） | **未接线（工具必报错）** | 4 个 A2A 工具 LLM 可见，但都 `services.get("mesh_action_broker")` 取不到 → 返回“未接入 mesh_action_broker”；全仓无处实例化该 broker |
| 主动任务（L3 100%） | **未接线** | `ProactiveScheduler` 生产中从不实例化/启动 |
| 拟人化 wait/interrupt（L1-L5 完成） | **默认关闭 + 循环不生效** | `conversation.enabled` 默认 false；开启后 manager 也只调 `register_message`，`ConversationRuntime.notify_new_message/should_trigger/request_interrupt` 零生产调用点（`manager.py` 调的是 `SystemPromptBuilder` 的同名方法，是另一回事）→ `wait` 只能靠超时结束 |
| 多租户隔离（O1 完成） | **未接线** | `TenantIsolationGuard` 从不实例化，`.enforce()` 无调用点 |
| Workflow 编排（O3 完成） | **未接线** | `WorkflowEngine` 生产中从不实例化；其 `__init__.py` 自标 scaffolding |
| 插件进程级隔离（O2 完成） | **未接线 + 惰性** | 见 H2（宿主内 `exec_module` + echo 桩隔离 + `call_on_load` 无调用点） |
| 监控告警（接入主链路） | **✅ 真实接线（属实）** | `process_message` 各节点自增计数器；`AlertManager` 经运行时生命周期构建/播种/启动 |
| 真实 LLM Provider | **✅ 属实**（但 README 自相矛盾） | `main.py:163` 配 `llm.provider`+`api_key` 即启用 `OpenAICompatProvider`；然而 README 快速开始处仍写“正在开发中……当前用 StubProvider 占位”，与状态表及代码矛盾（本次已修正该行文案） |

**结论**：真正接入主链路的“完成项”是**监控告警**与**真实 LLM Provider**（含单/多 Agent 基础回复链路、门控、命令、Gateway、OneBot 适配、Provider 重试/降级、控制面 CRUD/审计/持久化恢复、安全基线）；而 **Mesh(M)、主动任务/拟人化 wait&interrupt(L)、多租户(O1)、Workflow(O3)、插件隔离(O2)** 在生产路径上处于**未接线或默认关闭**状态。`AGENTS.md §剩余工作` 对此有诚实披露（“主链路尚未接线……生产路径无调用点”），只是 README 面向用户的状态表口径过于乐观。

**建议**：把 README 状态表的口径与 `AGENTS.md` 对齐——对未接线子系统统一改用类似 `docs/PROGRESS.md` 的三态标记（如 `[实现✓/接线✗]`），避免 rc/发布口径误导使用者；`v1.0.0-rc.1` 的“发布准入”措辞也宜据此下修，或明确界定为“主链路 MVP + 待激活子系统”。

---

## 六、已修复项与验证

本次已直接修复 **5 个低风险、可独立收敛**的缺陷（H1 高危越权 + M1/M3/M4 中危 + 1 处文档矛盾），改动集中在 7 个文件、约 +74/−22 行：

```
 README.md                                |  2 +-
 isac/channel/adapters/discord/adapter.py | 19 ++++++++++++++++++-
 isac/control/api/routes_memory.py        | 15 +++++++++++----
 isac/control/api/routes_sessions.py      | 12 +++++++++---
 isac/control/api/server.py               |  9 +++++++--
 isac/main.py                             | 28 +++++++++++++++++-----------
 isac/utils/fs.py                         | 11 +++++++++++
```

验证情况：

- **静态**：`python -m compileall`、`ruff check`、`mypy --ignore-missing-imports` 对改动文件全部通过。
- **运行时**（对真实模块，不含被 PyPI 代理拦截的第三方依赖）：H1 授权判定（窄 scope→403、未知→401、`memory:read`/`*`→200）、M1 锁 1000 次收发后字典完全回收 + 嵌套引用计数、M3 UTC 纪元正确 + 坏输入不抛、M4 写入往返 + 无临时残留，均通过。
- **未能执行完整 `pytest`**：本沙箱的包索引被代理拦截（PyPI/apt 403），无法安装 `structlog/aiosqlite/fastapi/pytest` 等运行依赖，故声称的“1093 单测全绿”本次**无法在此环境复跑**；所有修复均按“不破坏现有单测契约”原则设计（新增参数默认值保持向后兼容，`scope_dependency=None` 时行为完全不变）。建议在你本地 `uv run pytest` 复跑一遍确认。

未在评审阶段擅自修改的高/中危项（H2 插件隔离、H3 向量召回、H4 流式、M2/M6/M7、L 系列）均属**特性接线、架构决策或潜伏路径**，逐条修复建议已在正文给出，交由你按 `AGENTS.md` 的 P 节点规划推进。

---

## 七、优先级建议

**立即（安全）**：H1（已修复，请复核并复跑单测）；对 H2 至少先在文档/加载路径加“无隔离、仅可信插件”护栏；L1 给自动化创建路径接上 `make_restricted_agent_config`。

**近期（正确性/资源）**：M1（已修复）；M5 给 per-session 字典加上限/回收（对齐 `ConversationRuntimeRegistry` 的 cap 1000）；M3/M4（已修复）；修 M2 的 notify 语义（先投递再返回 None）。

**中期（口径与接线）**：按 L7 对齐 README 与 `AGENTS.md` 的完成度口径；按 P 节点推进 Mesh/拟人化/多租户/Workflow/向量召回的主链路接线，接线时把对应 `[~]` 单测转为主链路集成测试，避免“有单测但主链路无调用点”的再次发生。

**工程增强**：H4 流式合并逻辑；L4 SSRF 改“校验即请求”；L3/L5 记忆治理同步 BM25 + 补审计 actor；L8 `write_file` 异步化 / Journal seq 事务化。

---

## 八、二次复核（`dev` 分支 @ `e23b334`，2026-07-27）

> 本节针对与本报告主体（`main@48d60b0`）不同的代码谱系：`dev` 分支在本报告发布后经历了三轮后续工作——两轮独立的评审修复轮（内部代号“CR3 代码评审修复轮”“MVP 增量代码评审修复轮”）+ 一次面向 `docs/ROADMAP.md` 所称“P0-P2/Q0-Q1 主链路激活”的功能开发。复核方式：4 个并行子任务分别对照本报告原有的 H2/H3/H4/L2/L3/M2/M6 等条目直接读取 `dev@e23b334` 当前代码验证（而非采信文档/commit message 的自述），并额外检视 P0（消息并发）/P1（拟人化）/P2（Mesh）新落地代码本身引入的问题。

### 8.1 原有条目在 `dev@e23b334` 上的状态

| # | 原结论 | `dev@e23b334` 状态 | 证据 |
|---|------|------|------|
| H2 | 插件进程隔离未生效(echo 桩) | ⚠️ **部分修复** | 隔离子进程 worker 已改为通过 `PluginLoader` 真实加载插件入口（`isac/plugin/isolation/host.py` 的 `_worker_load`/`_worker_call`，含私有方法调用拒绝），不再是 echo 桩；但 `isac/plugin/runtime/manager.py::PluginManager.load_all` 仍无条件走宿主内 loader，全仓生产代码 0 处实例化 `PluginIsolationHost`，插件 manifest 也没有 `isolated` 类字段可触发该路径——**隔离能力本身已具备，但没有任何生产编排逻辑会使用它**，所有插件事实上仍在宿主进程内运行 |
| H3 | 向量/稠密检索从未执行 | ✅ **已修复** | `isac/memory/pipeline.py` 的检索路径已接入真实 dense+sparse 的 RRF 融合检索；未配置 embedding provider 时优雅降级为纯稀疏检索，不再是承诺功能的完全空转 |
| H4 | 流式工具调用解析损坏(潜伏) | ⚠️ **根因已修复，功能仍未激活** | 分片合并逻辑已改为按 OpenAI 流式协议的 `index` 字段正确累积，不再是“每个 delta 当完整调用”；但目前全仓生产代码仍无任何调用点把 `streaming=True` 传给 LLM Provider，功能路径依旧潜伏（触发面从“有 bug 且不可达”变为“已修复且不可达”） |
| M2 | 跨 Agent notify 被静默丢弃、假报成功 | ✅ **已修复** | `isac/runtime/bus.py` 的 notify 分支已改为先真实 `await self._deliver(...)` 再返回，投递异常会被 `MeshActionBroker` 捕获并转为 `False`，`notify_agent` 工具据此向 LLM 报告准确的失败，不再假成功 |
| M6 | ProactiveScheduler 冷却期饿死其他会话 | ✅ **已修复** | 队列改为优先级/公平调度，`poll_ready` 不再固定重取队首同一任务，不同 session 的冷却窗口互不干扰 |
| L2 | 多租户隔离全程无调用点 | ✅ **已修复** | `isac/main.py` 生产启动路径已真实构造 `TenantIsolationGuard` + 非默认 `TenantContext` 并注入 `MetadataStore`；`tenancy.enabled` 配置开关打开即可在数据面生效，不再是“谓词安全但从不执行”的死代码 |
| L3 | 记忆软删除不同步 BM25 索引 | ✅ **已修复** | `isac/memory/model/governance.py::delete()` 已同步调用稀疏索引的 `remove()`，`restore`/`correct` 也做了对应处理，墓碑不再残留在 BM25 内存索引里 |
| L5 | 审计 `operator` 恒空、无 `agent_id` 列 | ⚠️ **部分修复** | `memory_audit` 表已补齐 `agent_id` 列，`operator` 由空字符串改为固定占位值 `"authenticated"`；仍不是“记录具体是哪个 token/身份”的真实身份追踪，但这与本项目当前**全局**的审计粒度一致（`routes_agents.py` 等其他端点的 `actor` 同样是固定占位值），不算 `dev` 分支新引入的缺口 |

M5、M7、L1、L4、L6、L7、L8 **本轮未复核**，状态维持本报告主体所述，请勿据此推断已修复。

### 8.2 `dev@e23b334` 新引入的问题

**R2-1（Critical）Mesh 跨 Agent 调用绕过 session 锁，破坏并发安全承诺**

- 位置：`isac/main.py:848-871`（`_deliver_to_agent`）、`isac/runtime/bus.py:146-191`（`InterAgentBus.send`）
- 问题：两者都直接调用 `agent_manager.handle_message`，完全绕开 `main.py:279-284` 保护“同 session 严格串行”的 `session_lock`。P0 引入跨会话真并行后，若两次跨 Agent 调用（`ask_agent`/`notify_agent`）恰好并发指向同一目标 session，会在无锁状态下并发处理同一会话的消息，破坏原本的串行保证。
- 影响：可能导致回复错序或状态损坏；仅在启用 Mesh（`ask_agent`/`notify_agent` 实际被调用）场景触发。
- 建议：让 `_deliver_to_agent` 复用与普通消息入口相同的 `session_lock` 获取路径，而不是绕过它直接调 `handle_message`。

**R2-2（Critical）主动任务调度链路完整，但生产环境没有任何入口会触发它**

- 位置：`isac/runtime/conversation/scheduler.py`/`proactive.py` 全链路（生命周期驱动、唤醒、真实出站发送、冷却公平性均正确）；全仓库（排除 `tests/`）搜索 `ProactiveTask(`/`.enqueue(` 零命中
- 问题：调度器内部各段接线正确，但没有任何生产代码（插件、定时任务、记忆事件、控制面 API）会把任务放入队列——只有集成测试手工构造过任务对象。
- 影响：`docs/ROADMAP.md`/`docs/PROGRESS.md` 称该功能“全部接入生产主链路”与实际不符：机制存在但生产侧的入口缺失，真实部署中该功能永远不会自发触发。
- 建议：明确谁是“主动任务”的生产者（例如某个 injector/hook 在特定条件下调用 `enqueue`），补上这一环再对外宣称接线完成。

**R2-3（Required）Mesh observer/candidate 处理是同步阻塞，与代码注释所述“不影响主处理”矛盾**

- 位置：`isac/main.py:89-140`（`_apply_mesh_routing`），第 138-140 行对多个 observer 的记忆写入是顺序 `for...await`，且整段在 89 行被完整 `await` 完，发生在 primary 的 `handle_message`（102 行）之前
- 问题：每条消息的响应延迟会被 N 个 observer 写入（可能含 embedding 调用）与 M 个 candidate 评分串行拖慢。仅在配置 `mesh_role` 时触发，默认路径零影响。
- 建议：把 observer 写入改为真正的 `asyncio.gather`/后台任务，不阻塞 primary 的回复路径；或至少更新注释使其反映真实行为。

**R2-4（Nit）`router.py` 的 handoff 记录无独立过期清理**

- 位置：`isac/router/router.py:45`（`_handoffs`），仅在同一 key 被 `get_handoff`（100-111 行）重新查询且已过期时才清理
- 问题：若某会话收到一次 handoff 后再无后续消息触发 `route()`，该条目会永久驻留内存。非致命，但会随运行时间累积。
- 建议：对齐 `SessionManager._gc_expired` 的做法，加一个独立的周期性扫描。

**R2-5（Nit）`isac/gateway/lock.py` 存在从未被调用的休眠死代码**

- 位置：`isac/gateway/lock.py`（`_agent_running`/`_queues` 及配套的 `handle_message` 方法，约 54-79 行）
- 问题：生产路径走的是另一套 `acquire`/`release`（见 R2-1 提到的 `session_lock`），这套 `_agent_running`/`_queues` 全仓零调用点，当前不构成实际泄漏，但如果未来被误接线会无界增长。
- 建议：随手清理或明确标注废弃，避免后来者误用。

### 8.3 本轮结论

`dev` 分支相比本报告主体描述的 `main@48d60b0` 快照，在“文档宣称完成度 vs 实际接线状态”这一核心问题上**有实质性收窄**：H3/M2/M6/L2/L3 五项已被独立验证为真实修复（非文档自述）。但同一类问题并未被根除——本轮新发现的 R2-2（主动任务无生产者）与 H2/H4 残留的部分修复状态，说明“内部机制正确 + 生产侧从不调用”这一模式在本项目里仍在持续出现，是比任何单个 bug 更值得关注的结构性风险。R2-1 是本轮唯一一项因新功能（P0 并发化）而**新引入**的真实并发缺陷，建议优先处理。
