# ISAC 代码审查报告

**审查模型**：doubao-seed-evolving
**审查日期**：2026-07-28
**审查范围**：`isac/` 全量源码（252 个 Python 源文件）
**审查方法**：五轴并行审查（正确性 / 可读性 / 架构 / 安全 / 性能），ruff + mypy + pytest 建立基线

---

## 一、总览

| 维度 | 评价 |
|------|------|
| **正确性** | 整体良好，1359 测试通过；发现若干竞态和数据丢失问题 |
| **可读性** | 注释详实、命名清晰、模块边界明确；`main.py`(1407行) 和 `manager.py`(1071行) 偏大 |
| **架构** | 分层清晰、依赖注入合理、控制面/数据面分离做得好；存在少量跨层泄漏 |
| **安全** | SSRF/SQL注入/路径遍历防护扎实；发现 5 个需修复项 |
| **性能** | 无重大瓶颈；SQLite 并发配置和 SSE buffer 扫描需优化 |

**基线结果**：
- **测试**：1359 通过 / 8 失败（全部因 `cryptography` 模块未安装，非代码问题）/ 1 跳过
- **Lint**：ruff 全绿（`ruff check isac/`）
- **类型检查**：mypy 全绿，252 源文件无错误

---

## 二、Critical（阻塞级，共 4 项）

### C1. VectorStore/GraphStore 共享 aiosqlite 连接导致写入交错 + 连接泄漏

- **文件**：`isac/memory/storage/vector.py:29-54`、`isac/memory/storage/graph.py:27-60`、`isac/main.py:1077`
- **问题**：
  1. 持久连接在多个协程间共享，`upsert` 的 `DELETE→INSERT→commit` 未包事务，并发写入可能交错
  2. `init_schema()` 存在 TOCTOU 竞态：`if self._db is not None: return` 后的 `await aiosqlite.connect(...)` 是 yield 点，两个协程可同时通过检查，第二个覆盖第一个导致连接泄漏
  3. shutdown 生命周期注册的是 `_noop_start` 作为 stop（`main.py:1077`），`vector.close()` 和 `graph.close()` 从不被调用，WAL/SHM 文件残留
- **影响**：嵌入启用时高并发下出现 `database is locked`、部分写入丢失、FD 泄漏
- **修复建议**：
  - 为 `init_schema` 加 `asyncio.Lock()`
  - 每个公共方法加 `asyncio.Lock()` 或改为每次调用新建连接（仿 `MetadataStore`）
  - `init_schema` 中设置 `PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;`
  - 添加 storage 生命周期 stop 钩子，遍历 `vector_stores.values()` 和 `graph_store` 调用 `close()`

### C2. MCP Server 绕过 tokens[] scope 模型

- **文件**：`isac/control/mcp_server.py:131-137`
- **问题**：HTTP API 正确执行了 per-scope 权限检查（`make_auth_dependency` 传入 `parsed_tokens`），但 MCP stdio 桥接只校验扁平 `api_token`，完全忽略 scope。一个被限制为 `usage:read` 的 token 可以通过 MCP 调用 `agent_create`/`link_create`/`route_set_default` 等写操作
- **修复建议**：将 `parsed_tokens`/`scope_dependency` 传入 `ISACMCPServer.__init__`，在 `_call_tool` 中按工具→scope 映射校验（如 `agent_create` 要求 `agent:write`）

### C3. 流式响应中途失败后已推送部分内容，无错误/回滚信号

- **文件**：`isac/agent/loop.py:338-352`
- **问题**：`chat_stream` 异常时（line 352 re-raise），如果已有 chunk 通过 `context.on_chunk` 推送给客户端，用户看到半截回复后静默失败。fallback 到 `chat_with_retry` 仅在 `chunks=[]` 时触发，无法补救已推送的部分
- **修复建议**：添加 `on_error`/`on_finish(ok=False)` 回调，或 buffer chunks 直到流完成成功后再转发（延迟换正确性）

### C4. 工具结果无截断 + Budget 仅计算 completion 不累计 prompt 增长

- **文件**：`isac/agent/loop.py:163-169`、`isac/core/types.py:138-141`
- **问题**：
  1. 工具结果（`read_file` 64KB、`bash` stderr 无上限）原文追加到消息历史，无长度上限
  2. `Budget.consume()` 只加 `response.usage.total_tokens`，不追踪多轮迭代中 prompt 增长（每轮 assistant tool_calls + tool results 都追加），导致 `remaining_tokens` 计算不准，可能溢出 context window 导致反复 400 错误
  3. `should_compress()` 是硬编码 stub 返回 `False`（`core/types.py:209-214`，标注 TODO）
- **修复建议**：
  - 工具结果统一截断（如 8000 字符）并标注 truncation
  - Budget 语义明确化：要么追踪累计花费（当前实现 over-counts），要么追踪当前 prompt size
  - 实现 `should_compress()` 或在 context 溢出时主动触发摘要

---

## 三、Required（必须修复，共 18 项）

### 3.1 安全类（5 项）

| # | 问题 | 位置 | 修复建议 |
|---|------|------|----------|
| R1 | 飞书 webhook token 用 `!=` 比较，存在时序攻击风险 | `feishu/adapter.py:224` | 改用 `hmac.compare_digest`（仿 `control/auth.py:47`） |
| R2 | QQ 官方 webhook 未校验 Ed25519 签名 timestamp 新鲜度，可重放攻击 | `qq_official/adapter.py:185-212` | 拒绝 timestamp 偏离本地时间 >5 分钟的请求 |
| R3 | WebChat 适配器无认证，本地任意进程可伪造用户消息/读取他人回复 | `webchat/adapter.py:244-267` | 添加 shared token 或绑定到 loopback 时明确文档标注 dev-only |
| R4 | 空 `api_token` 静默禁用所有控制面认证（含 config edit/plugin load/memory admin） | `control/api/server.py:79,98` | 启动时若 `control.enabled=true` 且无 token，拒绝启动或输出 CRITICAL 级警告 |
| R5 | Session cookie 中 Bearer token 仅 base64 编码（`payload.signature`），未加密；窃取 cookie 即可获得长期 token | `control/auth.py:96-100` | 改为不透明 session ID + 服务端 token 查找表，或用 AES-GCM 加密 payload |

### 3.2 并发 / 数据完整性类（8 项）

| # | 问题 | 位置 | 修复建议 |
|---|------|------|----------|
| R6 | SQLite 连接未设 `PRAGMA journal_mode=WAL`/`busy_timeout`，并发写报 `SQLITE_BUSY` | `metadata.py`/`vector.py`/`graph.py`/`usage/storage.py` | `init_schema` 或连接工厂中统一设置 `WAL; busy_timeout=5000; foreign_keys=ON` |
| R7 | `_purge_memory` 不清理 `vectors-<ns>.db` 文件和 graph edges，重建同名 Agent 时孤儿向量召回污染 | `runtime/manager.py:158-182` | 调用 `vector.close()` 后 `os.remove()` DB 文件；调用 `graph_store.delete_by_namespace(namespace)` |
| R8 | 治理 delete/correct/restore 仅翻转 `episodes.deleted` 并同步 BM25，稠密向量行永不删除，残留向量占用 KNN 槽位 | `memory/governance.py:227-277` | 注入 `vector_resolver`，delete 时 `vector.delete(memory_id)`，correct/restore 时 `vector.upsert(...)` |
| R9 | `get_episodes_by_ids` 的 `IN (?, ?, ...)` 列表无上限，`recall_limit*3` 理论可超 SQLITE_MAX_VARIABLE_NUMBER（默认 999） | `metadata.py:288-303` | cap `candidate_ids` 到 500 或分批查询 |
| R10 | `EventBus.fire_async` 直接迭代 handler 列表，handler 在执行中注册同事件 handler 会触发 `RuntimeError: list changed size during iteration` | `event_bus.py:58-64` | 迭代前快照 `handlers = list(self._async.get(event, ()))` |
| R11 | `AuditLog.record` 在 async 函数内调用同步 `_append_to_file`（`mkdir`/`open`/`write`），审计爆发时阻塞整个事件循环 | `control/audit.py:71-78` | 包装为 `await asyncio.to_thread(self._append_to_file, entry)` |
| R12 | `upsert_person_profile` 先读后写（`get_person_profile` → 修改 → `upsert`），同一人的并发消息导致 interaction_count/relationship_depth 增量丢失 | `metadata.py:354-379` | 改用 `INSERT ... ON CONFLICT DO UPDATE SET interaction_count = interaction_count + 1, relationship_depth = MIN(1.0, relationship_depth + ?)` |
| R13 | `SessionLockManager.release` 在 `lock.locked()=True` 时跳过 pop，永不回访的 session 导致 Lock 对象无限期驻留 `_locks`，内存缓慢泄漏 | `gateway/lock.py:28-38` | release 时无条件弹出 dict（持锁者仍持有 Lock 引用，安全） |

### 3.3 正确性类（5 项）

| # | 问题 | 位置 | 修复建议 |
|---|------|------|----------|
| R14 | 控制面多个端点将 `str(exc)` 直接返回到 `detail.message`，泄露 Python 类型/字段路径/磁盘 IO 信息（如 "permission denied: /full/path"） | `routes_agents.py:157,193`、`routes_routing.py:81,116`、`mcp_server.py:148` | 添加全局 FastAPI exception handler，服务端 `exc_info=True` 日志，客户端返回通用错误码 |
| R15 | `/docs` Swagger UI 和 `/openapi.json` 无认证，枚举所有 admin 端点 + 参数形状；若端口误暴露则相当于完整攻击地图 | `control/api/server.py:105` | 生产环境 `docs_url=None`，或挂在 auth dependency 之后 |
| R16 | 打断逻辑将用户消息原文（前 50 字符）注入 system prompt，未做 prompt injection 防护；构造以"【系统指令】"开头的消息可越权指示模型 | `runtime/manager.py:604`、`injectors/interrupt.py:74-80` | 用 `<user_excerpt>...</user_excerpt>` 标签包裹，或剥离指令前缀（"system:"、"/ignore"、"###"等） |
| R17 | `AgentResult.content` 类型为 `str`（默认 ""），但 `response.content` 在纯 tool_call 响应中为 `None`，`AgentResult(content=None)` 传入下游 f-string/channel.send | `agent/loop.py:147,173` | 统一归一化为 `response.content or ""` |
| R18 | Wait 工具的 `await_wait()` 无硬上限 `asyncio.wait_for` 包装；协程被取消（shutdown/lock 释放/subagent 超时）时 future 永不 resolve，永久挂起 | `tools/social/wait.py:41` | 包装为 `asyncio.wait_for(runtime.await_wait(...), timeout=seconds+1)` |

---

## 四、Optional（建议改进，共 17 项）

### 4.1 高优先级建议

| # | 问题 | 位置 |
|---|------|------|
| O1 | **Histogram bucket 非累积**：`metrics.py:143-145` 中 `cumulative = counts[i]` 覆盖而非累加，Prometheus 直方图语义错误；应 `cumulative += counts[i]` |
| O2 | **MCP 未检查 `_initialized`**：客户端可跳过 `initialize` 直接调用 `tools/call`，绕过能力协商（`mcp_server.py:72`） |
| O3 | **bash stderr 无截断**：stdout 限 4000 字符，stderr 无上限，恶意命令可输出 MB 级数据撑爆消息历史（`bash.py:113-115`） |
| O4 | **ProactiveScheduler `_last_fired_at` 无界增长**：per-session cooldown 时间戳字典永不 GC（`scheduler.py:63`） |
| O5 | **SSE 事件流 O(n) 扫描**：每个 SSE 连接每 50ms 遍历最多 1000 事件的 buffer（`routes_events.py:164,193-209`），100 连接 = 200k 比较/秒；改用按 seq 索引 |
| O6 | **`MoodEngine.decay()` 从未被调用**：persona 注册时只挂了 `BehaviorLearner` hooks，mood 永不向中性衰减，deltas 永久累积（`persona/manager.py:58`） |
| O7 | **无速率限制**：`/auth/session` 和 Bearer 端点无暴力破解防护（`routes_auth.py:40`） |

### 4.2 中优先级建议

| # | 问题 | 位置 |
|---|------|------|
| O8 | POST 端点使用裸 `dict` 而非 Pydantic `BaseModel`，字段缺失/超长/未知字段处理 ad-hoc；`routes_subagent.py:48-63` 的 `summary` 无长度限制 | 多个 `routes_*.py` |
| O9 | `ProviderManager.chat_with_retry` 不尊重 `Retry-After` 头，429 后按 `2**attempt`（1s/2s/4s）重试过快（`manager.py:225-229`，有 TODO 标注） |
| O10 | Feishu adapter 在 token mismatch 时日志记录 `self._verification_token[:4]`，应改用 `token_fingerprint`（SHA-256 前 8 位）（`feishu/adapter.py:225`） |
| O11 | QQ 官方适配器默认 `_DEFAULT_WEBHOOK_HOST = "0.0.0.0"`，与其他适配器默认 `127.0.0.1` 不一致（`qq_official/adapter.py:56`） |
| O12 | `ConversationRuntimeRegistry` FIFO 驱逐时不取消被驱逐 runtime 的 pending `_wait_futures`/`_timeout_tasks`，timeout task 仍会回调 resolve_wait 到孤儿 runtime（`registry.py:32-38`） |
| O13 | `/metrics` 默认无认证（`metrics_auth_enabled=false`），绑定 loopback 时风险低，但建议默认开启（`server.py:150-161`） |
| O14 | CORS 未配置：当前默认安全（浏览器跨域无法带 Authorization），但缺中央策略，未来添加 CORS 时可能意外放宽 CSRF 防护 |
| O15 | `SecretStore` 写入文件未设 `chmod 0600`，AES-GCM 加密未用 AAD（`utils/security.py:70-76,93,104`） |
| O16 | `InterAgentBus.list_links` 返回内部列表引用，外部可直接 mutate bus 状态（`bus.py:127`）；应返回 `list(self._links)` |
| O17 | `_fts_query` 对所有词项加双引号并用 OR 连接，用户输入的 FTS5 操作符（`*`、`^`、`-`）全部被转义为字面量；这是安全选择但损失表达力，应文档化（`metadata.py:427-429`） |

---

## 五、Nits（细节问题）

- `N1`：`get_session_messages` 用 `except Exception: return {"messages": []}` 吞掉所有异常，掩盖 DB locked 等运维问题（`routes_sessions.py:67`）
- `N2`：Session secret 是 per-process 随机 32 字节，每次重启使所有 WebUI 会话失效，运维痛点（`auth.py:81-88`）；可选持久化 secret 配置
- `N3`：`agent_id` 路径参数未用 FastAPI `Path(pattern=AGENT_ID_PATTERN)` 约束，畸形 ID 返回 404 而非 422（多个 `routes_*.py`）
- `N4`：`DEGRADED_REPLY` 硬编码中文字符串，未走 `locales/` 路径（`provider/manager.py:26`）
- `N5`：`/audit` 的 `limit` 参数无 `Query(le=...)` 上界约束（`server.py:138-145`）
- `N6`：`webhooks.py` docstring 仍提及 `/automation/trigger` HTTP 端点，但无对应路由挂载
- `N7`：MCP server 返回英文错误，HTTP 端点返回中文，一致性问题
- `N8`：`MetricsCollector.snapshot()` 直接读 `Histogram._count/_sum` 不持锁，可能读到撕裂值（`metrics.py:200-207`）
- `N9`：`IdleBackoffController.should_delay(pending_count)` 参数被忽略（`idle_backoff.py:26-28`），突发消息也被节流
- `N10`：`DateReminderProducer._in_trigger_window` 用非闰年 DOY，2/29 被拒绝（`producer.py:467-472`）

---

## 六、正面评价

1. **安全基线扎实**
   - SSRF 防护考虑了 DNS rebinding：`pin_validated_url` 对 HTTP 固定 IP + 保留 Host 头，HTTPS 依赖 TLS 证书验证，redirect 不跟随
   - SQL 查询全部参数化（`?` 占位符），唯一的 f-string SQL 是 `_ensure_column` 且仅接受硬编码标识符
   - 路径遍历用 `Path.resolve()` + `is_relative_to(root)` 双重防护，symlink 攻击被阻断
   - 无 `eval`/`exec`/`pickle.loads`/`yaml.load`/`os.system`/`shell=True`/硬编码密钥
   - 插件在 spawned 子进程运行，带 rlimits 和 `_` 前缀方法保护
   - Bash 工具默认禁用 + 白名单 + shell 元字符拒绝 + 用 `create_subprocess_exec(*tokens)`（无 shell）

2. **并发设计深思熟虑**
   - 会话锁（platform:user:group）串行化同会话处理，跨会话真并行
   - inflight 任务集合持有强引用 + done_callback 自清理，无 "Task exception was never retrieved"
   - 优雅关闭 LIFO 顺序：先停适配器收取 → drain 在途消息 → drain 后台记忆写入 → 停调度 → 关下游资源（providers/usage/journal），不丢消息

3. **测试覆盖优秀**
   - 1387 个测试覆盖单元到集成各层
   - Scaffolding 测试为未激活子系统（graph_recall、identity_resolver、memory_consolidator、o4_platform_adapters）提供行为契约，默认关闭零行为变化的设计通过测试固化
   - 测试命名清晰，多使用真实 HTTP mock 而非过度 mock

4. **配置驱动的渐进式激活**
   - 每个子系统（memory、conversation、workflow、identity、tenancy、subagent 等）都有独立的 `enabled` 开关
   - 默认关闭时确实零行为变化，主链路不被半成品代码污染
   - "opt-in" 设计让 MVP 先发布，子系统按节点打磨

5. **错误恢复路径完善**
   - Provider 降级（Stub → OpenAICompat → chat_with_retry fallback → DEGRADED_REPLY）
   - 身份归一失败降级用基础画像，不冒泡到主链路
   - 插件加载失败不阻塞控制面启动
   - 所有跨边界调用都有 try/except + 日志，控制面异常不影响数据面

6. **代码注释质量高**
   - 每个设计决策都有中文注释说明 WHY，包含 ADR 引用和历史 fix 追溯（CR3-H4、Q0、S2、CR3-Fix、MVP-Fix 等标签）
   - 注释解释了 trade-off（如 https 不 pin IP 的原因、加密模式 fail-closed 的选择）
   - 阅读注释即可追溯每个分支的历史动机，代码考古成本低

---

## 七、优先修复路线图

### 第一批（安全 + 数据完整性，建议 1 周内）

| 顺序 | 项 | 工作量 |
|------|-----|--------|
| 1 | C2：MCP scope 绕过 | 小 |
| 2 | R1：飞书 token 常量时间比较 | 极小 |
| 3 | R4：空 api_token 启动拒绝/警告 | 极小 |
| 4 | R14：异常信息泄露 + 全局 exception handler | 小 |
| 5 | R6：SQLite WAL + busy_timeout | 小 |
| 6 | C1：VectorStore/GraphStore 锁 + 生命周期关闭 | 中 |
| 7 | R10：EventBus handler 列表快照 | 极小 |
| 8 | R13：SessionLockManager 泄漏修复 | 极小 |

### 第二批（正确性，建议 2 周内）

| 顺序 | 项 | 工作量 |
|------|-----|--------|
| 9 | R17：AgentResult.content None 归一化 | 极小 |
| 10 | R16：打断 reason 的 prompt injection 防护 | 小 |
| 11 | C3：流式 on_error 回调/buffer | 中 |
| 12 | R2：QQ 官方 timestamp 新鲜度校验 | 小 |
| 13 | R5：Session cookie 不透明化/加密 | 中 |
| 14 | R18：Wait 工具 hard timeout | 极小 |
| 15 | O1：Histogram 累积 bucket bug | 极小 |
| 16 | R12：person profile UPSERT 原子化 | 小 |

### 第三批（健壮性 + 性能，建议 1 月内）

| 顺序 | 项 | 工作量 |
|------|-----|--------|
| 17 | R7/R8：purge_memory 清理 vector/graph，治理同步 vector | 中 |
| 18 | C4：工具结果截断 + Budget 语义修正 | 中 |
| 19 | R3：WebChat 认证 | 小 |
| 20 | R11：AuditLog 异步 IO | 极小 |
| 21 | R15：/docs 生产环境关闭 | 极小 |
| 22 | R9：candidate_ids cap | 极小 |
| 23 | O6：MoodEngine.decay 接线 | 小 |
| 24 | O7：auth 速率限制 | 小 |
| 25 | O5：SSE 按 seq 索引替代 O(n) 扫描 | 小 |

---

## 八、架构层面的观察（非阻塞）

1. **`main.py` (1407行) 与 `runtime/manager.py` (1071行) 偏大**
   - main.py 承担了过多的"组装"职责：`build_services`、`_build_memory_stack`、`_build_usage_stack`、`_build_multimodal_provider`、`_register_control_plane`、`_register_channel_adapters` 等可以抽到独立的 `isac/bootstrap/` 包
   - manager.py 的 `handle_message` + `_run_loop_with_conversation` + `_schedule_memory_write` + 各种 helper 混合了消息处理、记忆调度、人格应用、子任务管理，按职责拆分为 `message_handler.py` / `memory_scheduler.py` / `conversation_driver.py` 更清晰

2. **`services: dict[str, Any]` 作为服务容器缺少类型约束**
   - 所有代码用 `services.get("xxx")` 取值，类型全靠注释约定，拼错 key 只在运行时以 None 形式暴露
   - 可考虑用 `dataclass`/`TypedDict` 定义 Services 契约，或使用轻量 DI 容器

3. **三个 store 共享 SQLite 但连接管理策略不一致**
   - `MetadataStore`：每次调用新建连接（最安全但开销大）
   - `VectorStore`/`GraphStore`：持久连接 + 无锁（最高风险）
   - 统一成连接池或统一的 per-call 连接 + WAL 会降低心智负担

---

**审查结论**：ISAC 整体代码质量处于较高水平——架构清晰、测试扎实、安全防护考虑周到、渐进式激活策略有效。4 个 Critical 项集中在 SQLite 并发管理和 MCP scope 模型上，属于生产部署前必须修复的问题，但修复范围明确、工作量可控。其余 Required 项多为边缘场景下的数据丢失/泄漏，按优先级分批修复即可。

— **doubao-seed-evolving** @ 2026-07-28
