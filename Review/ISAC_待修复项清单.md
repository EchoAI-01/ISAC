# ISAC 待修复项清单

> 配套文档：`ISAC_代码评审报告.md`（完整分析，含第八节「二次复核」）· 补丁：`isac_review_fixes.patch`
> 版本：原始评审 `main` @ `48d60b0`；2026-07-27 已在 `dev` @ `e23b334` 复核部分条目状态（标注"dev 已复核"）。未标注的条目仍以 `main@48d60b0` 快照为准，尚未在 `dev` 上重新验证，请勿据此推断已修复或未修复。
> 本清单只列**尚未修复（或仅部分修复）**的项。已确认修复的项不在正文重复列出，见下方"状态速览"。

## 状态速览

- ✅ 已修复并写回仓库（`main@48d60b0` 评审时直接修复）：**H1、M1、M3、M4** + README 过时文案（5 项）
- ✅ 已在 `dev@e23b334` 复核确认修复（2026-07-27，证据见 `ISAC_代码评审报告.md` 第八节）：**H3、M2、M6、L2、L3**（5 项）
- ⚠️ 已在 `dev@e23b334` 部分修复，仍有缺口（本清单继续列出，见对应条目）：**H2、H4、L5**（3 项）
- 🆕 `dev@e23b334` 新发现（P0/P2 新代码引入或暴露，本清单新增）：**R2-1 ~ R2-5**（5 项）
- 📋 本轮未复核，状态未知（仍以 `main@48d60b0` 原评审为准）：**M5、M7、L1、L4、L6、L7、L8**（7 项）

---

## 🔴 高优先级（2）

- [ ] **H2 · 插件"进程级隔离"仍未接入生产（dev 部分修复）** — 安全/设计
  - 位置：`isac/plugin/runtime/manager.py::PluginManager.load_all`（无条件走宿主内 loader）；`isac/plugin/isolation/host.py`（隔离子进程已改为通过 `PluginLoader` 真实加载插件，不再是 echo 桩，`dev@e23b334` 已修复这部分）
  - 影响：隔离能力本身已具备（子进程 worker 真实加载插件、拒绝私有方法调用），但没有任何生产编排逻辑会使用它——`PluginIsolationHost` 全仓生产代码 0 处实例化，插件 manifest 也没有 `isolated` 类字段可触发该路径。所有插件事实上仍在宿主进程内以完整权限运行，无沙箱
  - 建议：`PluginManager.load_all` 按 manifest 的隔离标志分流：需要隔离的插件走 `PluginIsolationHost`，其余走现有内部 loader；补一条"隔离插件在子进程崩溃后仍能提供服务"的主链路集成测试

- [ ] **H4 · 流式(streaming)工具调用解析根因已修复，但功能仍未激活** — 正确性（dev 部分修复）
  - 位置：`isac/provider/llm/openai_compat.py`（分片合并逻辑，`dev@e23b334` 已改为按 `index` 累积）
  - 影响：解析 bug 本身已修复，不再是"每个 delta 当完整调用"；但全仓生产代码仍无任何调用点把 `streaming=True` 传给 LLM Provider，功能路径依旧潜伏（触发面从"有 bug 且不可达"变为"已修复且不可达"），`get_capabilities()` 对外仍宣称 `supports_streaming=True`
  - 建议：接线流式前补一条真实流式响应的集成测试（多 chunk、并行工具调用），确认合并逻辑在生产配置下也成立，再对外启用

---

## 🟠 中优先级（2）

- [ ] **M5 · per-session 状态字典无上限、无回收（本轮未复核）** — 资源泄漏
  - 位置：`isac/gating/system.py:107-124`（`_turn_schedulers` / `_idle_backoffs` 每 session 一条、永不淘汰）；`FocusMode._active_until` 同样只在 `/unmute` 时清
  - 影响：服务大量不同会话的长跑进程内存持续增长、不回收已结束会话
  - 建议：对齐 `ConversationRuntimeRegistry`（cap 1000）/ `progress_reporters`（cap 500）加上限或 LRU/TTL 回收

- [ ] **M7 · Workflow 引擎入口/并行 join 错误（本轮未复核）** — 正确性
  - 位置：`isac/runtime/workflow/engine.py:94,101-104,127-128`（只启动 `entry_stages[0]`；`if stage_id in executed: return` 使 fan-in 在首个父分支到达时即执行）
  - 影响：多入口根节点被丢弃却仍标 SUCCEEDED；钻石 DAG 下汇合节点在上游未全部完成时提前运行
  - 建议：启动全部入口节点；fan-in 节点等所有父节点完成再执行（入度计数 / barrier）

---

## 🟡 低-中 / 低优先级（4）

- [ ] **L1 · 自动化创建的 Agent 无能力沙箱（本轮未复核）** — 安全
  - 位置：`isac/control/defaults.py:52`（`make_restricted_agent_config` 全仓无调用点=死代码）；`isac/control/api/routes_agents.py:186`、`isac/control/mcp_server.py:183`（直接吃调用方输入）；`isac/runtime/config.py:50`（默认 `plugins_allow=["*"]`）
  - 影响：持 `agent:write` 者可 `POST /agents` 造出开 bash、全插件的 Agent
  - 建议：自动化/受限创建路径接上 `make_restricted_agent_config`，默认拒 bash + `plugins_deny=["*"]`

- [ ] **L4 · SSRF 校验与请求分离（本轮未复核）** — 安全（当前无挂载路由，可达受限）
  - 位置：`isac/control/webhooks.py:79`(校验) vs `:153`(请求)；`isac/provider/image_gen/openai_compat.py:173` vs `:178`
  - 影响：低 TTL 域名可在校验后重指向 `169.254.169.254` 等内网/元数据地址（IP 分类器本身健壮、`follow_redirects=False` 已设）
  - 建议：改"校验即请求"——对已解析并通过校验的 IP 直接发起，或在连接层复核目标 IP

- [ ] **L5 · 记忆治理审计操作者归因仍不完整（dev 部分修复）** — 合规/审计
  - 位置：`isac/memory/storage/metadata.py`（`memory_audit` 表 `dev@e23b334` 已补齐 `agent_id` 列）；`isac/memory/model/governance.py`（`operator` 已由空字符串改为固定占位值 `"authenticated"`）
  - 影响：仍不是"记录具体是哪个 token/身份"的真实身份追踪；但这与本项目当前全局的审计粒度一致（`routes_agents.py` 等其他端点的 `actor` 同样是固定占位值），不算 `dev` 分支新引入的独立缺口，只是原缺陷未完全解决
  - 建议：若要做到真正的操作者归因，需要项目级统一方案（把控制面 token 指纹/身份透传进各治理操作），不宜只为 memory 单独引入新机制

- [ ] **L6 · 零散安全/健壮性（本轮未复核）** — 安全/健壮性
  - 位置：`isac/control/api/server.py:141-146`（`/metrics` 无认证，受 `enforce_safe_host` 强制 127.0.0.1 兜底）；`isac/control/auth.py:38-42`（非 ASCII Bearer Token → `hmac.compare_digest` 抛 `TypeError` → 500 而非 401）
  - 建议：`/metrics` 视部署加可选认证/仅内网；`verify_token` 对非 ASCII 输入 `try/except` 兜底为干净 401

- [ ] **L8 · 其他正确性/性能（本轮未复核）** — 正确性/性能
  - `isac/agent/tools/utility/write_file.py:59-62`：async `execute()` 里同步 `open/write`（最多 256KB）阻塞事件循环 → 改用 `asyncio.to_thread`（对齐已修的 `read_file`）
  - `isac/runtime/subagent/journal.py:114-139`：`seq` 用 `SELECT MAX+1` 后 `INSERT OR REPLACE`，并发同 task 可算出同 `seq` 互相覆盖丢事件 → 用事务/唯一约束或单写者串行化
  - `isac/agent/tools/mcp/client.py:57-58,206`：`transport="sse"` 实际走普通 `POST "/"`、无 SSE 处理，且 HTTP 响应无状态码检查 → 实现真正 SSE 或明确不支持并报错

---

## 📘 文档口径（贯穿性 · 强烈建议，本轮未复核）

- [ ] **L7 · README 状态表口径与代码不符** — 文档一致性
  - 现象：Mesh(M1/M2)、主动任务(L3)、拟人化 wait/interrupt(L2/L4)、多租户(O1)、Workflow(O3)、插件隔离(O2)、向量召回均标"✅ 完成"，但部分子系统在生产主链路上仍未接线或默认关闭（`AGENTS.md §剩余工作` 已诚实披露，README 口径未对齐）；`dev` 分支的 `docs/ROADMAP.md`/`docs/PROGRESS.md` 同样存在"称接线完成、实测生产侧无调用点"的个例（见下方 R2-2）
  - 建议：README/ROADMAP 状态表统一用三态标记（如 `实现✓/接线✗`）区分"核心逻辑+单测完成"与"生产主链路已调用"；发布/里程碑口径据此下修，或明确界定为"主链路 MVP + 待激活子系统"
  - ⚠️ 注：修复上面各"未接线"功能项时，请把对应 `[~]` 单测转为主链路集成测试，从机制上避免"有单测但主链路无调用点"再次发生——这正是 R2-2 在 `dev` 分支上重演的同一模式

---

## 🆕 dev 分支二次复核新增（`e23b334`，2026-07-27）

> 详细分析见 `ISAC_代码评审报告.md` 第 8.2 节。以下为可直接执行的修复项。

- [ ] **R2-1 · Mesh 跨 Agent 调用绕过 session 锁（Critical）** — 并发正确性
  - 位置：`isac/main.py:848-871`（`_deliver_to_agent`）、`isac/runtime/bus.py:146-191`（`InterAgentBus.send`）
  - 影响：两者直接调用 `agent_manager.handle_message`，绕开 `main.py:279-284` 的 `session_lock`；P0 引入跨会话真并行后，两次并发指向同一目标 session 的跨 Agent 调用（`ask_agent`/`notify_agent`）会在无锁状态下并发处理同一会话，可能导致回复错序或状态损坏
  - 建议：让 `_deliver_to_agent` 复用与普通消息入口相同的 `session_lock` 获取路径

- [ ] **R2-2 · 主动任务调度无生产者，功能实际不可达（Critical）** — 功能接线
  - 位置：`isac/runtime/conversation/scheduler.py`/`proactive.py`（内部机制正确）；全仓生产代码 `ProactiveTask(`/`.enqueue(` 零命中
  - 影响：调度器本身接线正确，但没有任何生产代码会把任务放入队列，真实部署中该功能永远不会自发触发，与 `docs/ROADMAP.md` 所称"全部接入生产主链路"不符
  - 建议：明确谁是"主动任务"的生产者（某个 injector/hook 在特定条件下调用 `enqueue`），补上这一环再对外宣称接线完成

- [ ] **R2-3 · Mesh observer/candidate 处理阻塞主回复延迟（Required）** — 性能
  - 位置：`isac/main.py:89-140`（`_apply_mesh_routing`，138-140 行顺序 `for...await` 写观察者记忆，且在 primary 处理前完整 `await`）
  - 影响：响应延迟随 observer/candidate 数量增加而变长，与代码注释所称"不影响主处理"矛盾；仅在配置 `mesh_role` 时触发
  - 建议：observer 写入改为 `asyncio.gather`/后台任务，不阻塞 primary 回复路径；或更新注释使其反映真实行为

- [ ] **R2-4 · `router.py` handoff 记录无独立过期清理（Nit）** — 资源泄漏
  - 位置：`isac/router/router.py:45`（`_handoffs`，仅同 key 被重新查询且过期时才清理）
  - 影响：某会话收到一次 handoff 后若无后续消息触发 `route()`，条目永久驻留内存；轻度、非致命
  - 建议：对齐 `SessionManager._gc_expired` 的做法，加独立周期性扫描

- [ ] **R2-5 · `isac/gateway/lock.py` 存在休眠死代码（Nit）** — 代码卫生
  - 位置：`isac/gateway/lock.py`（`_agent_running`/`_queues` 及配套 `handle_message`，约 54-79 行）；全仓生产 0 调用点
  - 影响：当前无实际泄漏，但若未来被误接线会无界增长
  - 建议：清理或明确标注废弃

---

## 建议推进顺序

1. **先处理新引入的并发缺陷**：R2-1（Mesh 绕过 session 锁）——这是唯一因新功能引入的真实并发 bug，优先级高于其余积压项
2. **再对齐"接线完成"口径**：R2-2（主动任务补生产者）、H2（插件隔离接生产编排）——与 L7/M2 属同一类"机制对但生产侧不调用"问题，建议一并按 L7 的三态标记方案治理
3. **安全/资源积压项（本轮未复核，仍按原优先级）**：L1（接 restricted 沙箱）、L6、M5（字典回收）、M7、L4
4. **工程增强**：H4 补流式集成测试后再启用、L5 视是否要做项目级操作者归因决定是否继续投入、L8、R2-3、R2-4、R2-5
