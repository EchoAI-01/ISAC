# ISAC 代码审查报告

- **审查范围**：当前 `main` 分支代码基线及工作树中的未提交差异
- **审查日期**：2026-07-23（同日追加应用级可运行性复审）
- **审查方式**：静态代码审查、全量测试、关键控制面行为复现、主程序驻留动态验证
- **总体结论**：**Request changes / Alpha**。组件级单元测试基础较好，但主程序启动后立即返回、真实 LLM Provider 不可用、持久化恢复和应用级 E2E 缺失；不应按“可生产运行的 v1.0.0”验收。前期问题的最新状态见第 8.4 节。

## 1. 验证结果

| 检查项 | 结果 | 说明 |
|---|---:|---|
| Ruff | 通过 | `.venv/bin/ruff check .` |
| Mypy | 失败 | `aiocqhttp` 缺少 stubs/`py.typed`，检查 160 个源文件时 1 error |
| Pytest | 378 passed，1 warning | `.venv/bin/python -m pytest tests -q` |
| Statement coverage | 上次报告 71% | 本次未重新采集；CI 仍未设置 `--cov-fail-under` |
| Branch coverage | 上次报告 51% | 本次未重新采集；关键启动、网关、真实 Provider、外部适配器和安全路径覆盖不足 |
| 工作树 | 有既有差异 | `uv.lock` 中项目版本由 `0.1.0` 改为 `1.0.0`；本次审查未修改该文件 |

## 2. 必须优先修复的问题

### P0 / Critical：`agent_id` 可造成目录穿越写入

**位置**：

- `isac/runtime/config.py:25-55`
- `isac/control/api/routes_agents.py:29-31`
- `isac/control/api/routes_plugins.py:45-52`

**问题**：`AgentConfig` 没有校验 `agent_id`，控制面直接将其拼接进 `agents_dir`。认证用户可以提交 `../escaped` 等值，使配置文件写入 `agents_dir` 之外。

**已复现行为**：

```text
POST /api/v1/agents
Authorization: Bearer <valid-token>
{"agent_id":"../escaped"}
→ 200
→ 在 agents_dir 外创建 escaped/config.jsonc
```

**影响**：任意已获得控制面 Token 的调用方可写入应用工作目录之外的路径；结合后续配置加载、插件或运行时行为，可能进一步造成配置覆盖或代码执行风险。

**需要修改**：

1. 在 `AgentConfig.__post_init__` 建立统一 ID 边界，例如只允许 `[A-Za-z0-9_-]{1,64}`。
2. 持久化前对目标路径执行 `resolve()`，并验证其 `relative_to(agents_dir.resolve())` 成功。
3. 对空字符串、绝对路径、`..`、路径分隔符、过长 ID 返回明确的 400。
4. 增加 API 回归测试，验证非法 ID 不会创建越界文件。

---

### P0 / Critical：控制面审计与 JSON 指标端点绕过认证

**位置**：

- `isac/control/api/server.py:89-96`：`/api/v1/audit`
- `isac/control/api/server.py:105-108`：`/api/v1/metrics`
- 对比已有路由认证：`isac/control/api/server.py:54-82`

**问题**：Agents、Routing、Plugins 使用了 Router 级 `Depends(auth_dependency)`，但审计和 JSON 指标直接挂载到 `app`，没有认证依赖。

**已复现行为**：配置 `api_token` 后，匿名请求以下端点均返回 `200`：

```text
GET /api/v1/audit   → 200
GET /api/v1/metrics → 200
```

**影响**：未持有 Token 的调用方可读取管理操作、Agent 标识、目标资源路径、内部运行指标等信息。

**需要修改**：

- 为两个端点显式添加 `Depends(auth_dependency)`；或将所有 `/api/v1` 端点放进统一的认证 Router。
- `auth_dependency` 为空时只允许明确的开发模式，并在启动日志中发出高可见度警告。
- 增加无 Token、错误 Token、正确 Token 三组测试。

---

### P0 / Critical：默认 Docker Compose 部署配置不会进入应用

**位置**：

- `docker-compose.yml:22-35`
- `isac/utils/config.py:28-35`
- `isac/main.py:191-200`
- `Dockerfile:55-57`

**问题**：Compose 设置了 `ISAC_CONTROL_HOST`、`ISAC_CONTROL_PORT`、`ISAC_API_TOKEN`、`ISAC_LLM_MODEL` 和 `ISAC_ONEBOT_*`，但 `ENV_MAPPING` 没有映射这些变量。空数据卷首次启动时，`control.enabled` 不会被设置，控制面不启动；Docker healthcheck 却强制请求 `localhost:8765/health`。

**影响**：默认“一键启动”场景下容器不会提供控制面，且会持续被标记为 unhealthy，可能触发重启循环。文档中的 `.env` 配置实际上无法完整生效。

**需要修改**：

1. 扩充 `ENV_MAPPING`，覆盖控制面、LLM、OneBot 配置。
2. 对布尔值、整数和嵌套配置做类型解析，不能把字符串 `"false"` 当作真值。
3. 明确 `control.enabled` 的默认策略，并使 healthcheck 与该策略一致。
4. 增加配置加载集成测试：环境变量 → `load_config()` → 控制面启动配置。
5. 增加 Docker build/start/health smoke test，而不是只检查 YAML 文本是否包含变量名。

---

### P1 / Required：真实 LLM 配置被静默替换为 StubProvider

**位置**：

- `isac/main.py:123-132`
- `isac/provider/llm/openai_compat.py:31-48`

**问题**：即使配置了 `llm.provider` 和 `llm.api_key`，`main()` 仍然注册 `StubProvider`；`OpenAICompatProvider.chat()` 和 `chat_stream()` 仍抛出 `NotImplementedError`。

**影响**：用户提供真实 Provider 配置后，系统仍返回固定的 Stub 回复，生产行为与配置不一致，且不会在启动阶段暴露错误。

**需要修改**：

- 实现并注册 `OpenAICompatProvider`，至少覆盖 HTTP 错误映射、重试、工具调用响应解析和 SSE 流式解析；或
- 在 Provider 尚未实现时明确拒绝启动/处理请求，不要静默降级到 Stub；
- 增加真实 HTTP 客户端契约测试，覆盖 2xx、429、5xx、超时和 malformed response。

---

### P1 / Required：监控指标和告警没有接入生产主链路

**位置**：

- `isac/observability/metrics.py:192-221`
- `isac/control/api/server.py:50`
- `isac/observability/alerting.py:156-201`
- `isac/main.py:117-200`

**问题**：`get_default_metrics()` 每次创建新的 Collector；消息、Agent、LLM、工具和记忆路径没有实际更新指标；生产组装也没有创建或启动 `AlertManager`。

**影响**：`/metrics` 基本只会返回初始零值，默认告警规则无法反映真实运行状态。

**需要修改**：

1. 应用生命周期内只创建一个 Collector，并通过依赖注入传入核心组件。
2. 在消息接收/处理/丢弃/失败、Agent 生命周期、LLM 调用、工具调用和记忆检索处记录指标。
3. 启动 `AlertManager`，在应用停止时可靠取消并等待后台任务。
4. 增加端到端测试：处理一条消息后指标递增，错误路径触发对应告警。

## 3. 正确性与状态隔离问题

### P1：跨会话共享 Prompt Builder 与门控频率状态

**位置**：`isac/runtime/assembly.py`、`isac/runtime/manager.py:105-146`、相关 Prompt/TurnScheduler 组件

**问题**：审查发现新消息计数、`TurnScheduler`、`IdleBackoff` 等状态没有严格按会话隔离，可能在同一 Agent 的不同用户/群组之间互相影响。

**影响**：一个会话的消息量、回复频率或 idle 状态可能改变另一个会话的门控结果，导致漏回、过度回复或行为不稳定。

**需要修改**：

- 将 Prompt 频率状态、TurnScheduler 和 IdleBackoff 放到 Session 级别；
- Agent 级别只保留真正共享的不可变配置；
- 增加两个并发会话交错处理的测试，证明状态不会串扰。

### P1：路由处理后的内容未传入 Agent

**位置**：`isac/main.py:176-184`、`isac/router/router.py`、`isac/runtime/manager.py:151-157`

**问题**：路由可能返回剥离触发词后的 `RoutingDecision.content`，但主链路继续把原始 `message` 传给 Agent。

**影响**：Agent 仍收到包含路由触发词的原始内容，导致 Prompt 内容错误、触发词重复处理或路由语义失效。

**需要修改**：

- 路由成功后构造内容已替换的消息副本，或让 `handle_message()` 接受明确的 routed content；
- 增加“触发词被剥离后 Agent 只看到正文”的回归测试。

### P1：EventBus intercept 返回的替换 payload 被丢弃

**位置**：`isac/main.py:170-176`

**问题**：`fire_intercept()` 的返回值被赋给 `payload`，但后续路由仍使用原始 `message`。

**影响**：插件无法通过 intercept 修改消息内容或元数据；返回替换 payload 的接口契约不成立。

**需要修改**：使用 `payload` 继续执行后续流程，并明确其类型；增加插件修改消息后的端到端测试。

### P1：长期记忆查询丢弃 user/group/filter，shared namespace 可能跨用户注入

**位置**：`isac/memory/pipeline.py:67-78,101-106` 及其调用方

**问题**：查询参数没有完整传递用户、群组和过滤条件；当使用 shared namespace 时，检索范围可能超出当前会话授权边界。

**影响**：可能把其他用户或群组的记忆注入当前 Prompt，造成隐私泄漏和错误上下文。

**需要修改**：将 `agent_id`、namespace、user_id、group_id 和 scope filter 设为显式必传边界；为 shared namespace 设计明确 ACL；增加跨用户隔离测试。

### P1：工具调用后缺少 assistant `tool_calls` 消息

**位置**：`isac/agent/loop.py` 工具调用处理路径

**问题**：工具结果被追加时，没有完整保留 LLM 返回的 assistant `tool_calls` 消息。

**影响**：后续模型请求的消息序列可能不符合 OpenAI 兼容协议，导致工具调用循环失败或被 Provider 拒绝。

**需要修改**：保存并追加完整 assistant tool-call message，再追加每个 tool result；增加多轮工具调用测试。

### P1：Provider 非 `LLMError` 异常绕过统一回退

**位置**：`isac/provider/manager.py:52-80`

**问题**：`chat_with_retry()` 只捕获 `RateLimitError` 和 `LLMError`。网络库、JSON 解码、类型错误等异常会直接冒泡，绕过 fallback 和 degraded reply。

**需要修改**：在 Provider 边界将外部异常转换为带 `retriable` 属性的 `LLMError`，只在明确不可恢复时停止重试；增加 malformed response、连接错误和 fallback 失败测试。

## 4. 性能与资源管理问题

### P1：每次记忆写入全量重建 FTS

**位置**：`isac/memory/storage/metadata.py:240-242`

每次 `store_episode()` 都执行 FTS5 `rebuild`，随着数据增长单次写入退化为 O(N)，批量写入接近 O(N²)。

**修复**：按 `memory_id` 增量 insert/update/delete；仅在运维修复时执行全量 rebuild。

### P1：MCP stdio 子进程管道和 pending 请求泄漏

**位置**：`isac/agent/tools/mcp/client.py:67-78,131-178`

- `stderr=PIPE` 没有持续消费，可能填满后阻塞子进程；
- stdout reader task 未保存、取消或等待；
- kill 后未 `await process.wait()`；
- 超时/取消的 request 未从 `_pending` 删除。

**修复**：保存并管理 reader tasks，持续消费或重定向 stderr；断连时 fail/cancel 全部 pending；超时使用 `try/finally pop()`；终止后等待进程回收。

### P1：WebChat 请求体无大小和读取超时边界

**位置**：`isac/channel/adapters/webchat/adapter.py:134-145`

超大 `Content-Length`、不完整 body 或慢速客户端可长期占用内存、socket 和任务。

**修复**：限制 header/body 大小，校验 `Content-Length`，用 `asyncio.timeout()` 包装读取，并限制并发连接数。

### P1：Sparse BM25 每次查询同步扫描并重建全语料统计

**位置**：`isac/memory/storage/sparse.py:20-58`、`isac/memory/pipeline.py:67-78,101-106`

每次查询都重新 tokenize 全部文本并计算 TF/DF，且同步执行会阻塞 event loop。

**修复**：写入时增量维护倒排索引、TF、DF 和文档长度；查询只处理 query；规模增大后考虑 SQLite FTS/BM25。

### P1：Discord 轮询没有分页，可能永久漏消息

**位置**：`isac/channel/adapters/discord/adapter.py:110-131`

单次只拉取 10 条却直接推进 cursor；两次轮询间新增超过 10 条时，未返回的旧消息会被跳过。

**修复**：按 `after` 连续分页，按旧到新处理，完整批次成功后再提交最高 cursor，并设置单轮页数上限。

### P2：Session、Lock 和 WebChat 回复队列无界增长

**位置**：

- `isac/gateway/session.py:25-63`
- `isac/gateway/lock.py:20-29`
- `isac/channel/adapters/webchat/adapter.py:44-45,81-84,109-114`

长期运行会导致 Session、锁对象、空 session key 和未领取的回复永久积累；`get(session_id)` 还会线性扫描。

**修复**：Session 增加二级索引与 TTL/LRU；锁使用引用计数并在无 waiter 时删除；回复队列采用有界 deque，并增加后台过期清理。

### P2：bash/read_file 的资源上限在读取完成后才生效

**位置**：

- `isac/agent/tools/utility/bash.py`：`communicate()` 及 timeout kill 分支
- `isac/agent/tools/utility/read_file.py:59-63`

`bash` 在完整收集 stdout/stderr 后才截断，`read_file` 先读取整个文件后才截断到 64 KiB；均可能导致内存峰值和 event loop 阻塞。超时进程也没有完整等待回收。

**修复**：流式读取并限制总字节数；`read_file` 只读取 `MAX_READ_BYTES + 1`；同步文件操作放入 `asyncio.to_thread()`；kill 后等待进程退出。

## 5. 测试和 CI 门禁缺口

1. CI 没有最低覆盖率阈值，覆盖率下降不会阻止合并：`.github/workflows/ci.yml:29-30`。
2. CI 没有 wheel/sdist 构建、Docker build、容器启动和 healthcheck smoke test。
3. `tests/integration/` 没有实质集成测试。
4. 以下关键模块现有覆盖率为 0% 或明显不足：
   - `isac/main.py`
   - `isac/gateway/lock.py`
   - `isac/gateway/session.py`
   - `isac/gateway/user_mapper.py`
   - `isac/provider/llm/openai_compat.py`
   - `isac/utils/security.py`
   - 真实 MCP stdio 生命周期
   - WebChat 请求尺寸/超时
   - Discord 分页
5. `tests/unit/test_docker_deploy.py:15-120` 主要验证文本存在性，不验证实际容器行为。
6. `tests/unit/test_webui.py:57-113` 未在浏览器中验证 JavaScript 交互。
7. `tests/unit/test_docs.py:21-121` 是关键词/存在性测试，不代表文档描述的运行时行为。

**建议新增的最小回归测试集**：

- 控制面：认证绕过、路径穿越、非法 Agent ID、审计/指标权限；
- 配置：Compose 环境变量真实映射、布尔/整数转换；
- 消息链路：intercept payload、路由剥词、会话隔离、工具调用消息序列；
- Provider：真实配置不再静默 Stub、异常分类和 fallback；
- MCP：stderr 背压、EOF、超时 pending 清理、进程退出回收；
- WebChat/Discord：请求上限、超时、分页和队列淘汰；
- memory：大数据集增量索引性能和跨用户隔离。

## 6. 文档与版本状态不一致

`AGENTS.md:5-38` 和 `README.md:54-71` 仍描述“Phase 1 中期”和大量模块待实现；而 `DEVELOPMENT_PLAN.md` 又记录 v1.0.0 已整体完成。建议明确该版本到底是“框架预览版”还是“生产可用版”，同步更新 README、AGENTS、部署文档和变更记录，避免新开发者误判功能完成度。

## 7. 建议修复顺序

1. **先修安全边界**：Agent ID 路径穿越、控制面认证、shared memory ACL。
2. **再修可部署性**：环境变量映射、控制面启用逻辑、Docker healthcheck smoke test。
3. **修复核心正确性**：路由内容、EventBus payload、会话状态隔离、Provider 异常回退和工具调用消息序列。
4. **修复长期运行稳定性**：MCP 进程/pending、WebChat 输入、Session/Lock 生命周期、Discord 分页。
5. **优化记忆与索引**：FTS 增量维护、Sparse BM25 增量索引。
6. **补测试与 CI 门禁**：集成测试、覆盖率阈值、包构建、Docker smoke test。
7. **最后同步版本和文档状态**。

## 8. 2026-07-23 可运行性复审

本节是在前述安全/正确性审查之后进行的应用级复审。历史发现保留用于追踪；本节以当前工作树和实际运行结果为准。

### 8.1 当前定位

**当前项目是 Alpha 框架：组件可测试，但应用服务不可用。** 不应继续按“生产可用 v1.0.0”验收。

| 检查项 | 当前结果 | 判定 |
|---|---:|---|
| Pytest | 378 passed，1 warning | 组件级单元测试基础良好 |
| Ruff | 通过 | 静态风格通过 |
| Mypy | 失败：`aiocqhttp` 缺少 stubs/`py.typed` | 类型门禁未全绿 |
| 主程序驻留 | 失败：打印“ISAC 启动完成”后立即返回 `MAIN_RETURNED` | 服务不可运行 |
| Integration tests | `tests/integration/` 仅空 `__init__.py` | 无应用级证明 |
| 真实 LLM | `OpenAICompatProvider.chat/chat_stream` 抛 `NotImplementedError` | 无真实 AI 对话 |
| Docker | 未建立 build/start/health 真实 smoke | 不可宣称一键可用 |

### 8.2 新增 Critical / P0

#### P0：应用没有常驻与统一关闭生命周期

**位置**：`isac/main.py:258-274`、`isac/__main__.py:7-8`

**复现**：直接执行 `asyncio.run(main())` 后打印 `MAIN_RETURNED`。`main()` 在 `channel_registry.start_all()` 返回后结束，没有等待停止事件、信号处理、TaskGroup 或统一 close。Control、Alert 和 Channel 后台任务会随事件循环结束被取消。

**影响**：即使初始化日志显示成功，应用也不会持续接收消息或提供控制面；Docker healthcheck 随后失败。

**Required**：建立 `ApplicationRuntime`/`ServiceContainer`，统一管理 start/health/close、SIGINT/SIGTERM、启动回滚、后台任务异常传播和 graceful shutdown；增加进程级驻留与关闭测试。

#### P0：真实 Provider 不可用

**位置**：`isac/provider/llm/openai_compat.py:15-48`、`isac/main.py:113-140`

配置真实 Provider 后仍只会调用未实现方法并最终返回降级话术。当前代码比旧版“静默 Stub”更诚实，但仍不能完成真实模型调用。

**Required**：至少实现一个 Provider 的非流式、SSE、Tool Call、usage、错误分类、重试/fallback、健康检查和连接池关闭；用本地 Fake HTTP Server 做契约测试。

#### P0：Storage/Memory 生命周期未闭环

**位置**：`isac/main.py:143-188`、`isac/memory/pipeline.py`、`isac/memory/storage/{metadata,vector,graph}.py`

Store 会被构造，但生产启动链没有统一执行 schema migration/init、Episode 写入、Sparse 重建、重启恢复与连接关闭；Vector/Graph/Reranker 仍是降级桩。

**Required**：建立 StorageLifecycle 与 schema version/migration；接入真实 MemoryEncoder 写入；验证重启后检索和 shared namespace ACL。向量/图可以推迟，但必须明确为 experimental，不得计入 MVP 完成。

#### P0：多 Agent 核心状态不能恢复，Agent Mesh 未真实投递

**位置**：`isac/main.py:209-213`、`isac/runtime/manager.py:26-30,198-205`、`isac/gateway/{session,user_mapper}.py`

`InterAgentBus` 未设置 deliver 回调；AgentManager、SessionManager、UserMapper 仍以进程内状态为主；重启后只创建默认 Agent，控制面写出的 Agent 配置不会组成完整恢复流程。

**Required**：持久化并恢复 Agent registry/运行状态、Session、Identity、Routing、Link；完成 Bus deliver、超时和 handoff；增加重启恢复及双 Agent E2E。

### 8.3 新增 Required / P1

1. **真实集成测试为空**：`tests/integration/` 没有实际测试。必须覆盖单 Agent 纵向链、多 Agent/ACL、Control 配置生效、重启恢复、Docker 和浏览器黄金路径。
2. **CI 没有发布门禁**：`.github/workflows/ci.yml` 未设置 branch coverage/`--cov-fail-under`，也没有 wheel/sdist、安装 smoke、Docker 或浏览器测试。
3. **命令和密钥仍有桩**：`Focus/Agents/Mute/UnmuteCommand`、`SecretStore`、MemoryConsolidator 等仍未实现，不得在计划中按完整能力验收。
4. **Webhook 缺 SSRF 与持久化边界**：订阅 URL 未限制内网/重定向/DNS rebinding，订阅仅内存保存；生产 Client 生命周期也未统一管理。
5. **插件“沙箱”名不副实**：当前 `AstrBotImportFinder` 只是 import 兼容重定向，不能隔离文件、网络、进程或环境变量访问；应更名为兼容层或提供进程/容器级隔离。
6. **WebUI v1 Token 持久化不安全**：管理 Token 写入 `localStorage`，需迁移为 HttpOnly/SameSite Session Cookie + CSRF，生产 HTTPS 下启用 Secure。
7. **长期运行资源边界不足**：MCP pending/管道、Session/Lock/队列、Webhook Client、Bash 子进程树和同步文件读取仍需统一上限与关闭验证。
8. **文档/版本状态失真**：README 的 Phase 1 描述与 DEVELOPMENT_PLAN 的 v1.0 完成记录冲突。当前版本应标记 Alpha/Preview，待稳定化验收后再确定正式版本。

### 8.4 旧报告问题状态

| 历史问题 | 当前状态 | 说明 |
|---|---|---|
| Agent ID 路径穿越 | 已部分修复，需回归 | `AgentConfig` 已有格式校验描述，但仍需 API/持久化双重路径 containment 测试 |
| 审计/JSON metrics 认证绕过 | 已修复，需持续回归 | 当前端点使用认证 dependencies；`/metrics` 仍公开，需明确部署策略 |
| Compose 环境变量未映射 | 已修复基础映射 | `ENV_MAPPING` 已覆盖 Control/LLM/OneBot；仍受主进程立即退出阻塞 |
| 真实 LLM 静默 Stub | 部分修复 | 不再静默冒充，但真实 Provider 仍未实现 |
| Metrics/Alert 未接线 | 部分修复 | 已注入同一 Metrics 并启动 AlertManager，但生命周期与 E2E 未通过 |
| 路由剥词/EventBus payload | 需要重新验证 | 应纳入 K5 单 Agent 全链测试 |
| 会话状态隔离/shared memory ACL | 仍需修复/验证 | 单测不能替代并发会话和跨用户 E2E |
| MCP/WebChat/Discord/索引资源问题 | 仍需修复 | 长期运行和压力测试尚未建立 |

### 8.5 可用版本准入清单

只有以下条件全部满足，才可从 Alpha 提升为“可用版本”：

- [ ] 主程序持续驻留，支持信号、启动回滚和优雅关闭；
- [ ] 至少一个真实 LLM Provider 完成流式/工具/错误/usage 闭环；
- [ ] Storage 初始化、迁移、记忆写入和重启恢复通过；
- [ ] Agent/Session/Identity/Router/Link 可持久化恢复；
- [ ] 单 Agent 与多 Agent E2E 通过；
- [ ] 控制面、Webhook、插件和工具安全基线通过；
- [ ] CI 覆盖率、包构建、Docker、浏览器测试成为强制门禁；
- [ ] README、AGENTS、CHANGELOG、版本号与真实能力一致。

### 8.6 执行顺序

复审结果已映射为 `DEVELOPMENT_PLAN.md` 的 K1-K8：

1. K1 应用常驻与资源生命周期；
2. K2 真实 Provider；
3. K3/K4 存储与运行状态恢复；
4. K5 单 Agent E2E；
5. K6 多 Agent/Control E2E；
6. K7 安全与长期运行；
7. K8 CI/Docker/浏览器/版本准入。

K1-K5 完成前暂停 D9、J1-J3，避免继续横向扩展却没有可运行主链。

## 最终 Verdict

**Request changes / Alpha。** 当前组件级测试基础较好，但主程序不驻留、真实 Provider 不可用、持久化恢复和 E2E 缺失。K1-K8 完成前不得宣称生产可用或完成 v1.0 验收。
