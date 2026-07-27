# ISAC 待修复项清单

> 配套文档：`ISAC_代码评审报告.md`（完整分析）· 补丁：`isac_review_fixes.patch`
> 版本：`main` @ `48d60b0` · 生成于评审后
> 本清单只列**尚未修复**的项。已修复的 5 项（H1 越权 / M1 锁泄漏 / M3 Discord / M4 原子写 / README 文案）已写回本地仓库，不在此列。

## 状态速览

- ✅ 已修复并写回仓库：**H1、M1、M3、M4** + README 过时文案（5 项）
- 📋 待修复（本清单）：**14 项** — 高 3、中 4、低-中/低 7

---

## 🔴 高优先级（3）

- [ ] **H2 · 插件“进程级隔离”并未生效** — 安全/设计
  - 位置：`isac/plugin/runtime/loader.py:158-162`（宿主进程内 `exec_module` 执行插件顶层代码）；`isac/plugin/isolation/host.py:31-77`（隔离宿主是硬编码 echo 桩，从不加载真实插件）；`PluginManager.call_on_load` / `make_plugin_context` 无调用点
  - 影响：被加载的插件以宿主完整权限运行、无沙箱；同时 `on_load` 钩子不触发，插件行为惰性
  - 建议：短期在 `plugins/README.md` 与加载路径加护栏“当前无隔离、仅加载可信插件”；中期把 `PluginIsolationHost` 从 echo 桩改为真正 fork worker 加载插件，并接线 `call_on_load`

- [ ] **H3 · 向量/稠密检索从未执行，语义召回缺失** — 功能/正确性
  - 位置：`isac/memory/pipeline.py:89-109`（`search` 只跑 FTS5+BM25，从不调 `self.vector.search()` / `self.embedder.embed_query()`）；写入路径 `store_episode` 却每次都算 embedding
  - 影响：配了 embedding provider 时全部白算白存；纯语义匹配的记忆检索不到，退化为关键词检索
  - 建议：按 `AGENTS.md` P3 节点把向量召回接入 pipeline，加 RRF 融合并与 shared-namespace ACL 保持一致

- [ ] **H4 · 流式(streaming)工具调用整体损坏** — 正确性（当前潜伏，无生产调用点设 `streaming=True`）
  - 位置：`isac/provider/llm/openai_compat.py:319-331`（`_parse_chunk` 把每个 delta 当完整调用、对参数片段单独 `json.loads`）；`isac/agent/loop.py:330-336`（`_merge_chunks` 未按 index 累积）
  - 影响：流式 + 任何工具 → 参数丢空 + 幽灵空调用 + 下一轮 `tool_call_id=""` 触发 400；并行工具调用被丢弃；流式路径还绕过重试/降级、token 预算记 0
  - 建议：接线流式前先按 index 累积工具调用分片、复用 `chat_with_retry`、补 `stream_options.include_usage`

---

## 🟠 中优先级（4）

- [ ] **M2 · 跨 Agent notify 被静默丢弃、却报告成功** — 正确性
  - 位置：`isac/runtime/bus.py:143`（`type=="notify"` 在调 `_deliver` 之前就 `return None`）
  - 影响：目标 Agent 收不到 notify，工具却向 LLM 报告成功（假成功丢消息）。因 mesh 链路本就未接线，生产影响暂受限
  - 建议：notify 应“先投递再返回 None”（投递后不等响应），修正 fire-and-forget 语义

- [ ] **M5 · per-session 状态字典无上限、无回收** — 资源泄漏
  - 位置：`isac/gating/system.py:107-124`（`_turn_schedulers` / `_idle_backoffs` 每 session 一条、永不淘汰）；`FocusMode._active_until` 同样只在 `/unmute` 时清
  - 影响：服务大量不同会话的长跑进程内存持续增长、不回收已结束会话
  - 建议：对齐 `ConversationRuntimeRegistry`（cap 1000）/ `progress_reporters`（cap 500）加上限或 LRU/TTL 回收

- [ ] **M6 · 主动任务冷却期饿死其他会话** — 正确性
  - 位置：`isac/runtime/conversation/scheduler.py:147`（冷却中任务 `insert(0, task)` 退回队首，`poll()` 又总取索引 0，反复重取同一任务）
  - 影响：某会话冷却期间，其他会话的就绪任务无法触发，瓦解 CR2-Fix-6 的 per-session 冷却隔离
  - 建议：冷却任务改为退回队尾或跳过、按会话就绪度轮转，而非固定重取队首

- [ ] **M7 · Workflow 引擎入口/并行 join 错误** — 正确性
  - 位置：`isac/runtime/workflow/engine.py:94,101-104,127-128`（只启动 `entry_stages[0]`；`if stage_id in executed: return` 使 fan-in 在首个父分支到达时即执行）
  - 影响：多入口根节点被丢弃却仍标 SUCCEEDED；钻石 DAG 下汇合节点在上游未全部完成时提前运行
  - 建议：启动全部入口节点；fan-in 节点等所有父节点完成再执行（入度计数 / barrier）

---

## 🟡 低-中 / 低优先级（7）

- [ ] **L1 · 自动化创建的 Agent 无能力沙箱** — 安全
  - 位置：`isac/control/defaults.py:52`（`make_restricted_agent_config` 全仓无调用点=死代码）；`isac/control/api/routes_agents.py:186`、`isac/control/mcp_server.py:183`（直接吃调用方输入）；`isac/runtime/config.py:50`（默认 `plugins_allow=["*"]`）
  - 影响：持 `agent:write` 者可 `POST /agents` 造出开 bash、全插件的 Agent
  - 建议：自动化/受限创建路径接上 `make_restricted_agent_config`，默认拒 bash + `plugins_deny=["*"]`

- [ ] **L2 · 多租户隔离形同虚设** — 安全/设计
  - 位置：`isac/runtime/tenancy/isolation.py:25-87`（`TenantIsolationGuard.enforce()` 无调用点，数据面查询无租户谓词）
  - 影响：README 宣称的 O1 多租户隔离在运行时零保护（谓词本身安全，但从不生效）
  - 建议：按 P5 节点在数据面接入 `TenantContext` 并调用 `enforce()`，补跨租户访问测试

- [ ] **L3 · 记忆软删除不同步 BM25 内存索引** — 正确性
  - 位置：`isac/memory/model/governance.py:174-194`（`delete` 只置 `deleted=1`，不调 `sparse.remove()`）；`isac/memory/storage/metadata.py:268-274`（预热 `iter_episodes_by_namespace` 选了 `deleted` 行）
  - 影响：墓碑残留抬高 `total_docs`/平均长度，污染存活项的 IDF 与长度归一（排序被扰动；无内容泄露）
  - 建议：`delete` 同步 `sparse.remove()`；预热查询加 `deleted = 0`

- [ ] **L4 · SSRF 校验与请求分离（TOCTOU / DNS rebinding）** — 安全（当前无挂载路由，可达受限）
  - 位置：`isac/control/webhooks.py:79`(校验) vs `:153`(请求)；`isac/provider/image_gen/openai_compat.py:173` vs `:178`
  - 影响：低 TTL 域名可在校验后重指向 `169.254.169.254` 等内网/元数据地址（IP 分类器本身健壮、`follow_redirects=False` 已设）
  - 建议：改“校验即请求”——对已解析并通过校验的 IP 直接发起，或在连接层复核目标 IP

- [ ] **L5 · 记忆治理审计无法归因操作者** — 合规/审计
  - 位置：`isac/memory/model/governance.py:70-81`（审计 `operator` 恒写 `""`）；`isac/memory/storage/metadata.py`（`memory_audit` 无 `agent_id` 列）
  - 影响：freeze/protect/correct/delete/restore 只能证明“发生过”，无法证明“谁做的”
  - 建议：把控制面 token/actor 透传进 `MemoryGovernor` 各操作并落审计；`memory_audit` 补 actor/agent_id 列

- [ ] **L6 · 零散安全/健壮性** — 安全/健壮性
  - 位置：`isac/control/api/server.py:141-146`（`/metrics` 无认证，受 `enforce_safe_host` 强制 127.0.0.1 兜底）；`isac/control/auth.py:38-42`（非 ASCII Bearer Token → `hmac.compare_digest` 抛 `TypeError` → 500 而非 401）
  - 建议：`/metrics` 视部署加可选认证/仅内网；`verify_token` 对非 ASCII 输入 `try/except` 兜底为干净 401

- [ ] **L8 · 其他正确性/性能** — 正确性/性能
  - `isac/agent/tools/utility/write_file.py:59-62`：async `execute()` 里同步 `open/write`（最多 256KB）阻塞事件循环 → 改用 `asyncio.to_thread`（对齐已修的 `read_file`）
  - `isac/runtime/subagent/journal.py:114-139`：`seq` 用 `SELECT MAX+1` 后 `INSERT OR REPLACE`，并发同 task 可算出同 `seq` 互相覆盖丢事件 → 用事务/唯一约束或单写者串行化
  - `isac/agent/tools/mcp/client.py:57-58,206`：`transport="sse"` 实际走普通 `POST "/"`、无 SSE 处理，且 HTTP 响应无状态码检查 → 实现真正 SSE 或明确不支持并报错

---

## 📘 文档口径（贯穿性 · 强烈建议）

- [ ] **L7 · README 状态表口径与代码不符** — 文档一致性
  - 现象：Mesh(M1/M2)、主动任务(L3)、拟人化 wait/interrupt(L2/L4)、多租户(O1)、Workflow(O3)、插件隔离(O2)、向量召回均标“✅ 完成”，但生产主链路**未接线或默认关闭**（`AGENTS.md §剩余工作` 已诚实披露，README 口径未对齐）
  - 建议：README 状态表改用 `docs/PROGRESS.md` 式三态标记（如 `实现✓/接线✗`）；`v1.0.0-rc.1` 的“发布准入”措辞据此下修，或明确界定为“主链路 MVP + 待激活子系统”
  - ⚠️ 注：修复上面各“未接线”功能项（H2/H3/M2/L2/Workflow…）时，请把对应 `[~]` 单测转为主链路集成测试，从机制上避免“有单测但主链路无调用点”再次发生

---

## 建议推进顺序

1. **先安全**：L1（接 restricted 沙箱）、H2 护栏、L6
2. **再资源/正确性**：M5（字典回收）、M2（notify 语义）、M6/M7、L3/L4/L5
3. **口径对齐**：L7（README ↔ AGENTS.md）
4. **特性接线（按 P 节点）**：H3 向量召回、多租户 L2、Workflow、Mesh、拟人化 —— 每接一个补一条主链路集成测试
5. **工程增强**：H4 流式、L8
