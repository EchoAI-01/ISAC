# ISAC 代码审查报告

- **审查范围**：当前 `main` 分支 v1.0.0 代码基线及工作树中的未提交差异
- **审查日期**：2026-07-23
- **审查方式**：静态代码审查、现有测试检查、关键控制面行为动态复现
- **总体结论**：**Request changes**。Ruff、Mypy 和现有单元测试表现良好，但当前版本仍存在可被认证用户利用的路径穿越、匿名读取管理数据、Docker 默认部署失效、真实 LLM 配置被静默替换，以及多项长期运行资源泄漏和状态隔离问题。不建议按“可生产运行的 v1.0.0”验收。

## 1. 验证结果

| 检查项 | 结果 | 说明 |
|---|---:|---|
| Ruff | 通过 | `.venv/bin/python -m ruff check .` |
| Mypy | 通过 | `.venv/bin/python -m mypy isac/`，160 个源文件无错误 |
| Pytest | 326 passed | `.venv/bin/python -m pytest --cov=isac --cov-report=term-missing` |
| Statement coverage | 71% | 低于项目文档声明的核心模块 80% 门槛；CI 未设置 `--cov-fail-under` |
| Branch coverage | 现有报告 51% | 关键启动、网关、真实 Provider、外部适配器和安全路径覆盖不足 |
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

## 最终 Verdict

**Request changes**。当前代码可以通过现有静态检查和单元测试，但上述 P0/P1 问题必须在合并或宣称生产可用前处理。尤其是路径穿越、认证绕过和默认 Docker 部署失效，不应以“后续清理”方式延期。
