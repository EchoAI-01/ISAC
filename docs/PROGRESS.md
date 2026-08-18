# ISAC 进度总表

> 本文件是各节点进度的**唯一事实源**。`DEVELOPMENT_PLAN.md` 描述节点定义与验收,`AGENTS.md` 只做一句话概述并链接此处;二者不再各自维护进度表。
>
> ⚠️ **最近更新: 2026-08-18 —— 第三轮审查批 7 清偿 (Fix-130~137: 剩余 Minor 清零, 全量 2078 通过), 第三轮 Critical/Major/Minor 代码级全清**。
> **Fix-130** `SubAgentSupervisor._runs` 内存索引封顶 (默认 500), 超限只淘汰最旧**终态** run (活跃 run 绝不淘), 终态已落 Journal 可回读。
> **Fix-131** 主动任务生产者四处去重标记表 LRU 封顶 (默认 1000 会话), 修按 session_id 无界增长。
> **Fix-132** `event_store.append` 改 `INSERT...SELECT ... RETURNING seq` 原子取回 seq, 消除回读竞态 (并发 append 拿错 seq)。
> **Fix-133** upload 安装 `zip_b64` 体积封顶 (对齐 100MB), b64 长度预检 + 解码后复核, 防超大串打爆内存。
> **Fix-134** `audit.ndjson` 尺寸轮转 (默认 10MB / 保留 3 份编号备份), 修只追加不轮转无界增长。
> **Fix-135** 隔离插件 reload/uninstall 经 `_cached_path_for` 取真实路径 (覆盖 `_loaded` 与 `_iso_hosts` 两种加载), 修 manifest.name≠目录名时误报 not_found/删错目录; `PluginIsolationHost` 补 `plugin_path` 属性。
> **Fix-136** `DenyGuard._denials` LRU 封顶 + 事件流惰性重建 —— 单调拒绝不因逐出翻回 (仅绑定事件存储时才逐出, 逐出后 `is_denied` 从事件流重建); `is_denied` 改异步。
> **Fix-137** 反应式门控移除死代码空闲退避判定 (`record_idle` 恒不被触发, `should_delay` 恒 False; 接线反而会延迟合法回复) —— 主动冷却归 `ProactiveScheduler.min_interval_seconds`; 组件保留。
> 顺带: 新增 16 例批 7 回归测试。**全量 2078 通过**, ruff/mypy (295 源文件) 全绿, 红线全绿。**第三轮最终**: 1 Critical + 21 Major + 44 Minor 全部代码级清零 (Fix-89~137 共 49 项); 唯一留档非代码项 = 全局配置无控制面持久化路径 (`mcp.servers` 等全局定义需手编 config.jsonc + 重启; Agent 级 MCP 绑定已持久化 + 热重连), 属"全局配置持久化 + 热重载"专门特性, 建议另立节点, 见 DEVELOPMENT_PLAN N1d 小结。
>
> ⚠️ **最近更新: 2026-08-18 —— 第三轮审查批 6 清偿 (Fix-120~129: 工具/Agent + 资源边界卫生, 全量 2062 通过)**。
> **Fix-120** DenyGuard 重建扫全量事件流 (`restore_from_store` 按 seq 分页) —— 此前只取每分区最近 500 条, 较早的 DENIED 事件重启后丢失、被拒工具翻回放行 (瓦解 U5 单调拒绝不变量)。
> **Fix-121** `generate_image` 的 `n` 夹到 [1,10], 修 0/负数/超大值造成空调用或批量生成放大。
> **Fix-122** bash 工具 stderr 与 stdout 同口径截断 (MAX_OUTPUT_CHARS), 修海量报错无上限进工具结果膨胀 prompt。
> **Fix-123** Agent Loop tool_calls 分支 assistant 消息 content None 归一为 "" (对齐 R17)。
> **Fix-124** MCP client stdio reader 对响应 id 非数字显式捕获, 不再冒泡到宽 except 被误记为"非 JSON 行"。
> **Fix-125** `SystemPromptBuilder` 会话频率表按 session 数封顶 (默认 1000, 逐出最旧), 修长期运行无界增长。
> **Fix-126** `SessionWriteGate.reserve` 顺带全量回收过期/已消费/已取消租约 (`_purge_stale`), `_active` 不再残留无人触及的过期条目。
> **Fix-127** J4 5 个 SubAgent 工具补 `_required_service` 映射 → subagent_supervisor, 修 restricted 无映射等效 allow。
> **Fix-128** 插件工具命名空间收紧 —— 仅名字已含本源前缀才跳过, 修 `mcp:x:y`/`别的插件:tool` 含 ':' 即整体绕过命名空间的冒充漏洞 (生产 MCP 以 builtin 注册不受影响)。
> **Fix-129** host 插件工具 (AstrBot/MaiBot) 执行受超时约束 (默认 60s 可配), 异步 wait_for / 同步 to_thread 限时, 挂死插件函数不再无限阻塞 Agent Loop。
> 顺带: Fix-120 分页重建移入 `DenyGuard.restore_from_store`, bootstrap 维持 ≤500 行红线; 新增 21 例批 6 回归测试 (并更新 Fix-88 命名空间既有测试以反映加固语义)。**全量 2062 通过**, ruff/mypy (295 源文件) 全绿, 红线全绿。**第三轮进度**: 1 Critical + 21 Major 全部清零, 44 Minor 已清绝大部分 (批 1~6 合计 Fix-89~129 共 41 项); 余 9 项 Minor (subagent _runs 无界 / 生产者去重表无界 / event_store seq 回读竞态 / 隔离插件 manifest.name≠目录回退 / zip_b64 无大小上限 / MCP 路由绑定未持久化 / gating idle-backoff 死代码 / DenyGuard _denials 无界 (单调约束) / audit.ndjson 轮转) 另立批次, 见 DEVELOPMENT_PLAN N1d。
>
> ⚠️ **最近更新: 2026-08-18 —— 第三轮审查批 5 清偿 (Fix-111~119: 正确性 + 会话内核, 全量 2041 通过)**。
> **Fix-111** A2A `bus.send` 补投递超时 (默认 60s, `asyncio.wait_for` 到期取消投递并抛 `InterAgentTimeoutError`) + 递归深度保护 (contextvar 沿投递链传播, 默认 8 层, 超限抛 `InterAgentRecursionError`) —— 修目标 Agent 挂起则发起方无限等待、A↔B 互调链无限嵌套耗尽资源。
> **Fix-112** `observe_message` 旁听记忆 `episode.user_id` 改用归一 master_id (与 `_write_memory` 口径一致), 修旁听/主写键分裂致按 master_id 检索召回不到旁听记忆; user_profile 为 None 回退平台 id。
> **Fix-113** `_apply_mesh_routing` 退出时还原 primary 的 `message.session_id` —— observer/candidate 的 get_or_create 会覆写该字段, 仲裁未切换回复者时主链路此前带着别人的会话 id 继续处理。
> **Fix-114** `SubAgentSupervisor.cancel` 用 `Task.cancelling()` 区分"后台任务被取消"(吞) 与"当前任务自身被取消"(重新抛出), 不再无差别吞 CancelledError 致优雅关闭/打断传播失效。
> **Fix-115** 强制话轮产出落 U1 事件流 —— 主动发言的合成 prompt (带 proactive 标记) 与回复成对写 message.user/turn.completed, 后续回合历史窗口可见主动说过什么。
> **Fix-116** 强制话轮取会话锁移入 try, 取锁阶段异常/取消时租约也能被 finally cancel, 不泄漏到 hold 超时挡住会话写入。
> **Fix-117** handoff 工具: 预约 SessionWriteGate 前置 (拿不到租约立即返回, 不再先投递摘要造成半程移交); 仅成功路径 commit, 失败/异常一律 cancel。
> **Fix-118** 主动任务唤醒回调失败重入队 (attempts 达 MAX_WAKE_RETRIES=3 或队列满才放弃), 修提醒被 poll_ready 取出后静默丢失。
> **Fix-119** Agent Loop 预算耗尽退出前发 `budget_exhausted` 终态进度事件 (登记进终态集合 + 模板), 修多步任务进度无声消失。
> 顺带: `handoff execute`/`scheduler._loop` 触 C901 上限, 抽 `_transfer_ownership`/`_produce_tasks`/`_fire_task` 降复杂度; services 残余访问维持 204。新增 20 例批 5 回归测试。**全量 2041 通过**, ruff/mypy (295 源文件) 全绿。剩余 Minor 见 DEVELOPMENT_PLAN N1d。
>
> ⚠️ **最近更新: 2026-08-18 —— 第三轮审查批 4 清偿 (Fix-104~110: 注入安全 + 鉴权/审计加固, 全量 2021 通过)**。
> **Fix-104** 行话 `context` 与 `meaning` 同为 LLM 归纳产物 (素材是攻击者可控的群聊原文), 此前仅 meaning 过注入防护, context 直接落盘并被 JargonInjector 拼入系统 prompt; 两者同口径 `_sanitize_llm_induction`, 间接 prompt injection 不得经 context 进入。
> **Fix-105** 中期记忆压缩摘要落盘 `episodes.summary` 前补注入防护 (此前仅去引号/代码块), 该摘要由 MidTermMemoryInjector 注入, 指令前缀行不得经压缩摘要进入系统 prompt (对齐 profile_text 口径)。
> **Fix-106** `secret:` 前缀覆盖扩面 —— `resolve_secrets_in_config` 增扫 `multimodal_providers[*].api_key` 与 `mcp.servers[*].token`; 此前仅 llm.api_key + llm.multimodal, 用户在这两处写 `secret:xxx` 字面透传致注册失败/鉴权恒错。
> **Fix-107** GET /api/v1/audit scope 门禁 —— 审计是最敏感数据面, 此前只挂基线认证, tokens[] scope 模型下窄 scope token 也能读全量; 对齐 routes_logs 要求 `*` 通配 scope (未配 tokens[] 行为不变)。
> **Fix-108** CSRF 空 Bearer 缺口 —— 此前只判 `startswith("bearer ")`, 空 Bearer 也跳过 CSRF, 但空 token 令认证回退会话 Cookie, 构成"空 Bearer 绕过 CSRF + 受害者 Cookie 认证"跨站写组合; 改用 `extract_bearer` 判定仅非空 token 放行。
> **Fix-109** webhook URL 日志/审计脱敏 —— 订阅 URL 常内嵌凭据 (query token/userinfo), 此前全量写入 audit.ndjson 与运行日志; 新增 `utils/ssrf.redact_url` (掩 userinfo + query, 保留 scheme/host/path), 审计与订阅/派发日志统一脱敏, 投递/存储仍用原 URL。
> **Fix-110** 插件 install/reload/retry 失败不再回显原始异常 —— git clone stderr 等可含 URL/路径/凭据; `_client_error_message` 仅回显受控 ValueError, 其余掩为通用消息, 明细留服务端审计/日志。
> 顺带: `create_control_app`/`resolve_secrets_in_config` 触 C901 上限, 抽 `_audit_read_deps`/`_resolve_secret_field` 降复杂度。新增 13 例批 4 回归测试 (注入剥离/secret 覆盖/audit scope/CSRF 空 bearer/URL 脱敏/错误受控)。**全量 2021 通过**, ruff/mypy (295 源文件) 全绿。其余 Major/Minor 见 DEVELOPMENT_PLAN N1d。
>
> ⚠️ **最近更新: 2026-08-18 —— 第三轮审查批 3 清偿 (Fix-100~103: 会话内核正确性, 全量 2008 通过)**。
> **Fix-100** U1 打断回合的 user 输入已在 LLM 请求前落盘 (Model-visible ⟺ Logged) 但回复被抑制成孤儿, 接替回合重新 drain 同一 burst 再落一条相同内容 → 历史窗口重复用户内容; 新增 `turn.aborted` ignorable 补偿事件 (payload.aborted_user_seq 指向作废的 user 事件), 回合被打断时 `_record_turn_aborted` 落盘, `SessionHistoryDeriver.fold` 跳过孤儿 user 事件。
> **Fix-101** /命令短路返回吞掉 Fix-57 回拨的积压 burst —— "问题 Q1 → 被 /cmd 打断 → 命令分支不 drain 即返回"让 Q1 永久滞留缓存 (无回复/无记忆/无历史); 命令分支抽出 `_try_command_shortcut`: 命中命令且 drain 出被打断回拨的非命令输入时接续为本回合 pending 走正常门控→Loop→回复, 无积压时行为不变。
> **Fix-102** ArtifactStore 同内容重复 put 时 `INSERT OR IGNORE` 连带保留首次 `expires_at`, 首次短 TTL 过期后 (sweep 未及清扫) 再 put 拿到的 ref 已过期、下次 get 直接删文件; 改 `ON CONFLICT DO UPDATE` 令 `expires_at` 只延长不缩短 (0=永不过期优先), kind/mime/metadata 仍首次登记为准 (Fix-69 不变)。
> **Fix-103** SessionManager Fix-78 per-key 锁"会话没了且锁空闲就删"会在取锁-持锁的 await 空隙误删锁 (该刻 locked()==False 且会话未建), 新来者拿到新锁并行 check-then-create 双创建 session_id; `_key_locks` 升级为引用计数 `{key:(lock,refs)}` + `_held_key_lock` 上下文, 持有期条目不可回收、归零自排空。
> 顺带: `fold`/`_dispatch_message` 触 ruff C901 上限, 抽辅助方法降复杂度; U1 三历史方法共用 `_history_parts` 收口 services 字符串键访问, U9 红线棘轮 205→204 (只减不增)。新增 13 例批 3 回归测试 (打断孤儿去重/命令接续/TTL 延长/锁引用计数)。**全量 2008 通过**, ruff/mypy (295 源文件) 全绿。其余 Major/Minor 另立批次, 见 DEVELOPMENT_PLAN N1d。
>
> ⚠️ **最近更新: 2026-08-18 —— 第三轮审查批 2 清偿 (Fix-95~99: 平台协议可用性, 全量 1995 通过)**。
> **Fix-95** QQ 官方频道回复出站不带 metadata → source 恒 "" → 100% 走错群端点发送失败; `_send_reply`/进度帧透传 incoming.metadata (qq_official_source)。
> **Fix-96** QQ webhook 无事件级去重 → 平台重推同一事件被处理两次 (重复回复 + 记忆写两份); 顶层事件 id LRU+TTL 去重表。
> **Fix-97** 飞书群 @机器人信号丢失 (不解析 mentions、无 at segment) → 门控 has_at 恒 False, 群 @ 基本不回复; 解析 message.mentions 产出 at segment。
> **Fix-98** Telegram/Discord 超长回复整条提交 → 平台 400 → 回复静默丢失; 新增 text_chunk 按上限分段 (Telegram 4096/Discord 2000, 优先换行边界)。
> **Fix-99** OneBot/NapCat 同机入站媒体 URL 是 loopback, SSRF 守卫恒拒 → R1-② 闭环在主力平台断链; 新增 global_config inbound_media.allow_loopback (仍逐跳复校验)。
> 顺带: dispatch.py 触 U2 的 500 行红线 (只减不增), 出站三件套抽到新模块 isac/outbound.py (dispatch re-export 保既有 import 路径)。新增分段/去重/mention/metadata/loopback 回归测试。**全量 1995 通过**, ruff/mypy (295 源文件) 全绿。批 3 (会话内核正确性) 见 DEVELOPMENT_PLAN N1d。
>
> ⚠️ **最近更新: 2026-08-18 —— 第三轮全量代码审查批 1 清偿 (Fix-89~94: C1 沙箱逃逸 + 5 项安全治理)**。U0-U9 演进后再做 5 路并行全量审查 (通道/运行时/记忆/控制面/Agent 核心), 去重后 1 Critical + 21 Major + 44 Minor。批 1 清偿最高优先级 6 项:
> **Fix-89 [Critical]** 隔离插件 IPC 用 multiprocessing.Pipe (recv=pickle 反序列化) → 承载不可信插件的子进程可构造恶意 pickle 载荷在宿主 recv 时 RCE, 击穿 U6 信任倒转边界; 已实测复现。换 socketpair + 长度前缀 JSON 字节帧 (_JsonFrameTransport, 解码路径零代码执行) + 帧长上限 16MB; 顺带 _on_crash 补 SIGKILL 兜底 (抗 SIGTERM 插件不再泄漏孤儿进程/阻塞线程)。
> **Fix-90** IM 审批回流零鉴权 → ApprovalGate.decide 增会话归属 + 发起人校验 (审批码发回群聊, 此前任何成员/得知审批码者均可裁决 ask 档高危工具)。
> **Fix-91** GET /agents/{id}/config 明文回显 llm.api_key → 序列化脱敏 + PATCH 哨兵还原 (防 WebUI 编辑回存覆盖真 key; 修 _restore_redacted 列表 zip 截断丢更新回归)。
> **Fix-92** 审批 decide 审计误把 AuditLog 当可调用对象 → 恒抛 TypeError 被静默吞, HITL 写操作零审计; 改 record()。
> **Fix-93** MCP 11 个写工具绕过审计 → 注入共享 AuditLog (与 HTTP 控制面同实例), 写工具成功即留痕 (token 指纹 actor)。
> **Fix-94** /sessions/{id}/messages 裸 SQL 绕过 U4 租户谓词 (多租户共库可跨租户读会话原文) → 改 store._tenant_db.scoped() 同构 routes_memory; 收紧 U4 裸 SQL 守卫清单。
> 新增对抗性回归测试 (pickle 载荷不执行 / 超长帧拒绝 / 审批越权 / 凭据脱敏 / MCP 审计 / 跨租户隔离)。**全量 1979 通过**, ruff/mypy (293 源文件) 全绿。批 2 (平台协议可用性) / 批 3 (会话内核) 见 DEVELOPMENT_PLAN N1d。
>
> ⚠️ **最近更新: 2026-08-18 —— U9 A+ 复评门禁完成, U 架构演进轮 U0-U9 全部清偿**。
> **①复评报告**归档 docs/U9_ARCHITECTURE_REVIEW.md: 12 模块逐项评级**无 C 项、B 项 2** (B-1 services 残余访问棘轮 / B-2 语义关系抽取层架构债, 均带收敛路径), 其余 A-/A; 实测 1962 passed 零失败 + ruff/mypy (293 源文件) 全绿。
> **②"定义了未接线"清零常驻**: test_u9_release_gate.py UNWIRED_LEDGER 登记册 (7 历史符号使用点审计) + 安全模块零 TODO 卫生检查, 零残留。
> **③红线指标 CI 常驻**: scripts/check_redlines.py (main.py ≤120 行 / 模块 ≤500 / services 键 ≤36 / 门控词 ≤27 只减不增 / services 残余 ≤205 棘轮) 入 CI catalog-drift job。
> **④Minor 批清**: smoke_main_resident flake **根治** (固定 sleep → 就绪标记轮询, 5/5 稳定); CHANGELOG 补齐 07-26 后全部轮次; 版本号策略定稿 (SemVer, 1.0.0=GA 目标, GA 前不打 tag); services.get 首批迁移 (215→205 棘轮冻结)。
> **代码侧 GA 门槛就绪** (U0-U9 全 [x] + 复评通过 + 红线常驻); 环境准入 N2/N3/N4 按既有排期。
>
> ⚠️ **2026-08-18 —— U2 装配层重构完成 (main.py 2046→82 行 + ServiceContainer, U 节点全部清偿)**。架构债 Z1+Z2 收敛, 全部验收项落地:
> **①main.py 薄入口**: 2046 行 → **82 行**纯 re-export 兼容面 (既有 `from isac.main import ...` 零改动), AST 精确抽取零转写拆出 —— **dispatch.py** 481 行 (消息主链路)、**wiring.py** 499 行 (build_services + 服务构造器)、**bootstrap.py** 499 行 (main() 运行时生命周期); cli 早已分离 `isac/__main__.py`。卫星模块层级归位: control/bootstrap.py、runtime/plugin_bootstrap.py、channel/registration.py、runtime/mesh/query.py、memory/stack.py (记忆构造器归记忆层)、observability/usage/stack.py、tenancy/media 构造器各归其层。
> **②ServiceContainer** (runtime/services.py): dict 子类 + **14 核心键类型化属性**, build_services 返回 ServiceContainer —— 键错配在类型层不可能 (mypy strict 293 源文件全绿); dict 语义全保持, 下游字符串键访问渐进迁移 ("先核心 10 键, 再清其余"第一阶段完成, 残余 ~215 处列 U9 批清)。
> **③lint 红线常驻** (test_u2_assembly_redlines.py): main.py ≤120 行、四模块各 ≤500 行只减不增、薄入口禁函数定义、ServiceContainer 核心键哨兵、拆分模块禁反向 import main (单向链)。
> 全量 **1962 通过 + 4 skip** 零失败 (smoke_main_resident 本批亦过, U9 根治项不变)、ruff/mypy 全绿。**U2 完成 —— U0-U8 全部清偿, 进入 U9 A+ 复评门禁 (最后节点)**。
>
> ⚠️ **2026-08-18 —— U8 注入仲裁门 + 治理门禁完成 (可穿插节点全部清偿)**。会话写入面从"补丁约定"升级为机制仲裁 + 治理门禁, 全部验收项落地:
> **①SessionWriteGate** (`isac/runtime/write_gate.py`): 主动/注入式写入统一仲裁门 —— 先预约后写入 (`reserve(session_key, source)`, 同会话单活跃租约先到者得; 门内名单 proactive/handoff/plugin_injection/memory_injection, 未登记来源拒绝); hold 窗口默认 30s (clamp 1~600s) 超时作废; `commit` 过期/已取消/被接手 → **fail-closed 丢弃产出** —— Fix-81/82 两次补丁的状态机互踩根因 (多写者无仲裁) 收编进该门。接线: 强制话轮经 `_reserve_forced_turn_write` 预约 (让位不抢, finally 幂等取消) + handoff 归属转移经门; build_services 注入; 未接门零行为变化。**AST 审计常驻**: 门之外 `forced_turn` 赋值/`transition_to` 调用即失败 —— 故意绕过当场捕获。
> **②治理门禁**: 工具 catalog (自动发现 29 工具: name/description/默认策略) + 配置 catalog (config.sample.jsonc 21 顶层键) 生成脚本, `--check` 漂移检测入 CI catalog-drift job —— 工具面/配置面变更未重新生成入库即失败, 强制变更留档。
> **③快照回放**: 脱敏 IM 事件流 JSON 夹具 (5 事件: 私聊/@/群聊短反应) 经真实主链路 EventBus→Router→Gating→AgentManager→LLM→Channel 回放, **无真实凭据跑整条 bot 链路** —— 回复序列按 scripted 消费对齐 (WAIT 不消耗回复) + 门在场反应式链路零干扰零残留。
> **④evidence 规范化**: `scripts/new_evidence_dir.py` 建 `evidence/YYYY-MM-DD-<slug>/` + README 骨架, 真机证据必留档; U8 验收证据留档 `evidence/2026-08-18-u8-gate-and-governance/` (PASS)。
> 测试: U8 专项单测 12 例 + 快照回放集成 2 例。全量 **1958 通过 + 4 skip** (smoke_main_resident 本批亦通过, 仍为 U9 根治项)、ruff/mypy (283 源文件) 全绿。**U8 完成, 可穿插节点已清 U3/U6/U7/U8, 剩 U2 装配层重构 → 之后 U9 复评门禁**。
>
> ⚠️ **2026-08-17 —— U7 Agent 数据化完成 (prompt 文件化 + 能力快照 + category 路由)**。Agent 的"人格与模型选择"从代码/配置常量升级为数据文件驱动, 全部验收项落地:
> **①prompt 文件化** (`isac/agent/prompt_files.py`): `<control.agents_dir>/<agent_id>/prompts/*.md` frontmatter 声明 family/variant/priority/enabled (无依赖子集解析器); persona 族文件**替代** config 身份注入, 其余族 (rules 等) 追加; 变体按当前模型族选择 (config.llm.model_family 覆盖优先, 否则模型名前缀推断 16 族), 未命中回落 default —— **改人格=改文件, 新增一个模型族=加一个 variant 文件零代码改动**; 无 prompt 文件落回 config 路径零行为变化。
> **②模型能力快照管线**: `scripts/gen_model_capabilities.py` (仅标准库) 拉 models.dev api.json 归一化 (拍板 #4 数据源) + `data/model_capabilities.overrides.json` 手动补录合并 (国产新模型晚收录兜底); **首份快照已生成入库 6666 模型**; CapabilitySnapshot 加载/查询/新鲜度检查; **drift CI 报警**: 专项测试断言快照在库 + ≤60 天新鲜 + 规模≥1000 + 关键模型 supports_tools (过期即失败); `.github/workflows/model-capabilities.yml` 每周一刷新有差异自动提交。启动接线 `_wire_llm_capabilities`: primary LLM ModelDescriptor 合并快照能力注册 ModelCatalog; **record_health 生产接线** (此前"定义未接线"): chat_with_retry 成功/最终失败上报健康 (限流除外), fallback 链按能力与可达性过滤。
> **③category 路由** (`isac/provider/category_routing.py`): qa/creative/tool_heavy/chat 四类画像 (成本/延迟上限 + requires_tools 能力过滤, ModelRouter.select 新增能力过滤参数), `config.model_routing.categories` 覆盖画像不改代码; delegate_task 增 category 参数, 子 Agent runner 经 ModelRouter 选型命中另一已注册 LLM provider 时切换执行 (ProviderManager._llm_registry 注册表), 无候选回落父模型 fail-safe。
> 测试: U7 专项 23 例 (frontmatter/模型族推断/变体选择四路/快照容错/新鲜度/生成器归一化+overrides/committed 快照 drift/四档 category 选型/能力过滤/健康上报三路/runner 切换与回落) + provider 域 41 例回归全绿。全量 **1943 通过 + 4 skip** (smoke_main_resident 全量批负载 flake 单独复跑稳定, U9 根治项)、ruff/mypy (282 源文件) 全绿。**U7 完成, 可穿插节点剩 U2/U8, 之后 U9 复评门禁**。
>
> ⚠️ **2026-08-17 —— U3 门控策略化完成 (配置 + i18n + LLM judge, 可穿插节点续清)**。门控从硬编码中文词表升级为配置化可插拔策略, 全部验收项落地:
> **①GatingProfile** (`isac/gating/profile.py`): 评分权重/阈值/三类问询词表/策略档位统一收口 —— 全部可经 `config.gating` 覆盖 (weights/markers/locale/strategy/reply_necessity_threshold/llm_judge_max_per_minute/hybrid_escalate_band), 未配置回落 constants 默认; 数据类默认 = zh_CN 词表 (constants 同源), 裸构造亦与 U3 前一致; strategy 非法值归一 keywords。
> **②GatingStrategy 四档** (`isac/gating/strategy.py`): off (恒无内容信号) / keywords (默认, U3 前语义原样) / llm-judge (小模型判相关性; 缺失/异常/None/超频率上限 fail-safe 回落 keywords, 滑动窗口上限默认 10 次/分钟) / hybrid (keywords 先行, 无问询信号才升级 judge)。策略只产出内容信号, 分数换算仍归 ReplyNecessityJudge —— 单一调用点, 策略可换评分模型不变。
> **③i18n 词表** (locales GATING_MARKERS): zh_CN 为 constants 三组中文词表原样迁入, en_US 新增英文词表; `load_gating_markers(locale)` 未知语言回退默认; config markers 覆盖优先于 locale。drift test: 双语包键集合 == GATING_MARKER_KINDS 三类且非空 (CI 常驻)。
> **④装配接线** (runtime/assembly.py): `_merged_gating_config` 全局 config.gating 与 Agent 级浅合并 (嵌套 weights/markers 子键合并, Agent 优先); `_build_gating_judge_fn` 仅 llm-judge/hybrid 档且 provider 在场时构造, 经 ProviderManager.chat_with_retry 走 **fallback 链最便宜档** (拍板 #3), yes/no 解析异常归 None 回落。config.sample.jsonc 增全局 gating 节样例。
> **成本**: llm-judge 每条待判定消息 ≤1 次最便宜档短请求 + 频率上限兜底, 单群中等活跃度约每分钟 ≤10 次小模型调用成本近零 (ARCHITECTURE.md §3.7 落档)。
> 测试: U3 专项 17 例 (四档策略/fail-safe/频率上限/hybrid 升级/权重词表阈值配置化/**英文群聊 e2e 双语对照**/默认零行为回归/词表 drift/全局-Agent 合并) + 既有门控域 236 例回归全绿。全量 **1920 通过 + 4 skip** (smoke_main_resident 全量批负载 flake 单独复跑稳定, U9 根治项)、ruff/mypy (279 源文件) 全绿。**U3 完成, 可穿插节点剩 U2/U7/U8, 之后 U9 复评门禁**。
>
> ⚠️ **2026-08-17 —— U6 插件隔离默认化完成 (信任分级倒转, 含 Z3 兼容层处置决策)**。隔离从 opt-in 倒转为默认:
> **①信任分级倒转** (`PluginManager._should_isolate`/`_manifest_trust`): 有 manifest 的原生插件**默认隔离加载** (子进程 PluginIsolationHost; trust 缺省=sandboxed, 旧 `isolated:true` 等价向后兼容); `trust: "hosted"` 仅当目录名在部署配置 `control.plugins.trust_hosted` 确认清单内才宿主进程内加载 (运营方显式确认信任), **未确认仍隔离** (不轻信 manifest); `isolated_plugins` 强制清单优先级最高保持。市场/git/url/upload 安装的插件未显式 hosted 即进沙箱。
> **②rlimits/ipc_timeout 部署接线** (`_isolation_host_kwargs`): `control.plugins.isolation` 节 rlimits(cpu/nofile/as)/ipc_timeout_seconds/max_restart_attempts 解析传入 PluginIsolationHost (此前构造恒用内置默认配置不可达); 非法值安全忽略。
> **③hooks 零残留**: 卸载经共享表 deregister_by_source + sync_plugin_tools_to_agents 按来源同步运行中 Agent (机制批次 C 已接线, 补验收测试)。
> **④兼容层处置决策 (Z3 收敛)**: 选"文档化降级承诺" —— 无 manifest 的 AstrBot/MaiBot 插件当前机制无法真正隔离 (依赖宿主内 import 沙箱与 PluginContext 直接桥接), 宿主进程内加载 + 启动显式告警 (信任责任在部署方); 强制隔离兼容层插件时清晰报错不静默退回; compat 隔离迁移保留架构债 C7。落 PLUGIN_COMPATIBILITY.md §5.4 + ARCHITECTURE.md §3.8。
> 测试: U6 专项 7 例 (市场安装默认隔离/hosted 未确认仍隔离/兼容层降级/rlimits 解析与生效/卸载零残留) + 既有插件域测试适配信任分级 (hosted+trust_hosted 快路径)。全量 **1903 通过 + 4 skip** (smoke_main_resident 全量批负载偶发 flake, 单独复跑稳定, U9 根治项)、ruff/mypy (277 源文件) 全绿。**U6 完成, 可穿插节点剩 U2/U3/U7/U8, 之后 U9 复评门禁**。
>
> ⚠️ **2026-08-17 —— U5 工具权限管线 + HITL 卡片审批完成 (U 轮第四节点)**。工具权限从静态三态表升级为四段管线, 全部验收项落地:
> **①四段管线** (`ToolRegistry.execute` 重构): pre-execute waterfall (effective_policy 四档 allow/restricted/**ask**/deny, 未知档位值 fail-closed 归 deny) → 单调 **DenyGuard** (会话×工具拒绝账本, 只增不删无撤销 API; 拒绝经 `tool.outcome=DENIED` 事件持久化, 启动时 `restore_from_events` 从 U1 事件流重建 —— 跨重启拒绝仍不可翻回) → 执行 (异常隔离) → post 审计留痕 (tool.called 执行前副作用前 flush / tool.outcome 执行后, payload 带 decision+decider+reason)。
> **②ask 档 HITL 闭环** (ApprovalGate): 审批卡片经 channel_registry 投递本会话 (审批码+工具+参数摘要); 回流两路 —— IM 回复"同意/拒绝 <审批码>" 经 process_message 入口拦截直达 gate.decide (不触发对话回合; 过期/未知码按普通消息继续路由不误吞) + 控制面 `POST /api/v1/approvals/{id}/decide`; 超时 (tools.approval.timeout_seconds 默认 300s) fail-closed 拒绝并登记 guard; 审批门未接线时 ask 档直接拒绝 (不静默放行)。
> **③决策理由词汇表** (`decision_reasons.py`): 10 规范 reason / 5 decision / 3 decider, `validate_reason` 越表 raise; drift test 扫描 registry 源码引用的全部常量 ∈ 词汇表。决策留痕可查询: `GET /api/v1/approvals/history` 聚合事件表全部 tool.* 决策记录。
> **④命名空间管线机制化** (Fix-88): 不变量测试断言非 builtin 来源工具注册名必含 ':' 前缀 (同名插件工具机制上不可能覆盖内置), 已含 ':' 不二次前缀。
> 既有 restricted 服务门/EnableMatrix channel 覆盖/三态语义全回归一致。测试: U5 专项单测 22 例 + HITL 全链路集成 4 例 (同意/拒绝/超时三路经真实 process_message 主链路闭环)。全量 **1895 通过 + 4 skip**、ruff/mypy (277 源文件) 全绿 (smoke_main_resident 全量批负载下偶发 flake, 单独复跑稳定, U9 根治项)。**U5 完成, 按 §三之五 顺序 U0→U1→U4→U5 主链清偿完毕, 进入可穿插节点 (U2/U3/U6/U7/U8)**。
>
> ⚠️ **2026-08-17 —— U4 租户机制强制完成 (半墙 → 整墙, U 轮第三节点)**。隔离从"调用方自觉"升级为"机制强制", 全部验收项落地:
> **①TenantBoundDB 机制强制层** (新建 `isac/memory/storage/tenant_bound.py`): 租户读写原语唯一入口 —— `scoped()` SELECT 自动经 enforce() 子查询包裹 (CR2-Fix-18 防绕过语义唯一实现)、`predicate()` UPDATE/DELETE 规范谓词片段、`row_values()` INSERT 打标值、`connect()` 连接收口。MetadataStore 与 MemoryGovernor 的谓词逻辑全部委托该层 (此前两处各维护一份 + 调用方可自行拼 SQL 绕过)。
> **②四表补租户列 + 打标/作用域**: person_profiles/jargon_entries/memory_revisions/memory_audit 经 _ensure_column 迁移补 organization_id/tenant_id (默认 'default', 存量免回填); profile/jargon 写入打标、读取经租户作用域 (get_person_profile/list_jargon); governor 审计与 revision 行打租户标, list_audit 跨租户不可见, 治理 SELECT 改走 scoped() 子查询 (UPDATE 走 predicate())。
> **③QueryMemoryTool 改 master_id 检索**: user_id 取 user_profile.user_id (与 _write_memory 落盘 episode.user_id=master_id 口径一致) —— 修私聊场景工具召回系统性漏 (此前按平台 id 检索 master_id 存储的记忆恒漏); query_person_profile 同步修 (person_id 回落链 + agent 键统一)。
> **④三处键统一**: manager._update_person_profile、三注入器 (person_profile/jargon/mid_term)、两工具的 agent 键统一为 pipeline.namespace —— 租户前缀/自定义 namespace 下与 consolidator 写侧同键 (此前 consolidator 写前缀键、manager/injector 读写裸键, 画像归纳写入 injector 永远读不到); 默认单租户 namespace==agent_id 零行为变化。
> **顺带清偿两处裸 SQL 绕过点** (审计认定): consolidator._fetch_episode_meta 直连 db_path 裸 SQL (无租户/agent 谓词) 改经新增 metadata.get_episode_meta_by_ids (租户作用域内分块, Fix-67 语义保留); routes_memory 控制面三读端点直连裸 SQL 改经 store._tenant_db.scoped()。审计测试常驻: 允许清单外 isac/ 零 aiosqlite.connect 记忆库直连。
> 测试: U4 专项单测 12 例 (三态原语/四表两租户共库隔离/delete 谓词双保险/meta 读作用域/审计行打标+跨租户不可见/默认租户零行为/工具取键口径/绕过点审计) + test_p5 集成 3 例 (画像行话元数据跨租户不可见、键统一写读一致、master_id 召回回归)。全量单测 **1770 通过 + 1 skip**、integration **100 通过**、ruff/mypy (273 源文件) 全绿。**U4 完成, 下一站 U5 工具权限管线 + HITL 卡片审批 (按 §三之五 顺序)**。
>
> ⚠️ **2026-08-17 —— U1 事件溯源会话内核完成 (架构演进地基, U 轮第二节点)**。会话存储从可变表升级为事件溯源, 全部验收项落地:
> **内核 (新建 `isac/session/` 包)**: `models.py` SessionEvent + 事件类型白名单 (message.user/turn.completed/turn.compressed/tool.called/tool.outcome; 未知事件默认拒绝重建 `UnknownSessionEventError`, ignorable 白名单首个成员 session.migrated); `event_store.py` SessionEventStore (append-only 分区事件表, 分区键 session_key 与 SessionManager 口径一致, WAL + busy_timeout, 原子 seq 分配 `INSERT...SELECT COALESCE(MAX(seq),0)+1` 并发不冲突, write-behind 批处理 + 显式 flush, payload 敏感键剔除 + 256KB 截断, `repair_torn_tail` 孤儿 tool.called 合成 OUTCOME_UNKNOWN 不猜结果); `history.py` SessionHistoryDeriver (fold 全量折叠含 turn.compressed source_seqs 溯源替代、derive_window 滑动窗口 window_turns×2 + budget 感知截断从最旧丢弃、`validate_compression` 摘要≥原文拒绝提交)。
> **主链路接线**: `AgentManager._dispatch_message` 每回合派生历史窗口 (messages = 窗口历史 + 当前 burst), 入站消息在 LLM 请求 (副作用) 前 flush 落盘 —— "Model-visible ⟺ Logged"; 回复成功追加 turn.completed 事件; **episodes 写入改事件投影** (`_write_memory` 按 turn_seq 从事件流读回本回合 message.user/turn.completed 事件对为内容源, 检索面 store_episode 不变, 投影失败回退直写)。生产装配 `_build_session_history_kernel` + 生命周期注册 (启动建表 + 逐分区 torn-tail 修复, 关闭 flush)。旧数据: `migrate.py` 迁移脚本 (旧 sessions 表 → session.migrated 标记事件, 幂等 + dry-run, `python -m isac.session.migrate`)。配置: config.sample.jsonc 增 `session.history` 节 (enabled 默认 true / window_turns 10 / budget_tokens)。
> **验收证据**: kill -9 重放无损 (重启 reopen 重放 + torn-tail 修复单测/集成); 压缩溯源 (source_seqs 替代 + 负压缩拒绝); 滑动窗口开箱可用 (memory 关闭仍工作底线场景); "隔天回到同一群聊仍保持上下文" 真机留档 `scripts/smoke_u1_history_continuity.py` (两进程跨 SIGTERM 重启同会话, 事件流 seq 连续, PASS); 专项单测 18 例 + 全链路集成 6 例 (LLM 前落盘/二轮见历史/重启保持上下文/episodes 投影/关闭零行为/启动 repair)。文档: ARCHITECTURE.md §3.14 + MEMORY_DESIGN.md §4.4。
> 全量单测 **1758 通过 + 1 skip**、integration **97 通过**、ruff/mypy (272 源文件) 全绿。**U1 完成, 下一站 U4 租户机制强制 (按 §三之五 顺序 U0→U1→U4→U5)**。
>
> ⚠️ **2026-08-17 —— U0 安全清偿完成 (Fix-85~88 + 顺带批清, U 架构演进轮首个节点)**。2026-08-17 全景 Review 认定 4 项安全实洞, 本轮全部清偿:
> **Fix-85 治理面租户谓词**: `MemoryGovernor` 直连 db_path 裸 SQL 只按 agent_id 过滤, 绕过租户谓词 —— 两租户共享同一 memory.db 时租户 A 凭据可对租户 B 记忆 freeze/correct/delete 越权。修复: governor 注入/继承 tenant_guard+tenant_context (未显式注入时从所包装 MetadataStore 读), 新增 `_tenant_predicate()` (guard.enabled 且非默认租户时返回 organization_id/tenant_id 谓词, 否则空=零行为变化, 与 metadata enforce 语义一致), `_item_exists`/freeze/protect/correct/delete/restore/export 全部 episodes SQL 追加租户谓词; 治理操作经 `_item_exists` 租户门后跨租户 item 视为不存在 (幂等拒绝不泄露存在性)。routes_memory_admin 无需改接线 (governor 包装的 store 已带租户上下文, 数据层机制强制)。test_p5 新增跨租户治理一律拒绝 + 默认租户直通 2 例。
> **Fix-86 解压体积上限接线**: installer.py `MAX_EXTRACTED_BYTES` (500MB) 全仓零引用, safe_extractall 只做 zip slip 路径防护 → zip bomb 可撑爆磁盘。修复: safe_extractall 增 `max_extracted_bytes` 参数, 流式解压累计**实际写盘字节** (中央目录 file_size 元数据可伪造不可信), 超限 raise 并清理已解出半成品 (先登记后写盘); installer 接入该常量 (失败时既有 finally 删 extract_tmp+target 兜底无残留); max=None 不检查向后兼容。zip bomb 超限拒绝+无残留/未超限正常/None 兼容 3 例。
> **Fix-87 MCP restricted 语义修正**: ToolPermission.check 对 mcp: 默认 restricted 但 _required_service 无映射 → restricted 等效 allow (语义矛盾)。修复 (方案 a): _required_service 对 mcp:* 返回 "mcp_clients" (MCP 接线时 assembly 注入 agent_services, 未接线缺失/为空 → restricted 门拒绝 LLM 直调); base.py check 注释同步。无 mcp_clients 拒绝/空 services 拒绝/注入后执行/tools_policy allow 覆盖 4 例。
> **Fix-88 插件工具命名空间**: mcp: 前缀防护只在 MCP 桥接层, compat/native 插件工具无前缀, 同名可覆盖内置工具 (仅 warning 非确定性)。修复: ToolRegistry.register 对插件来源 (source != builtin) 且名字无 ':' 的工具自动包装 `_NamespacedTool` (name=<plugin>:<tool>, 余者透传), 命名空间键与 source 追踪键一致 (tools_policy/EnableMatrix/deregister_by_source 统一); 已含 ':' 跳过避免二次前缀, builtin 不加。main._adapt_compat_plugins 拆 `_adapt_one_compat_plugin`/`_run_compat_adapt` (降 C901) 并逐插件 set_current_source (启动期 compat 桥接此前未设)。防覆盖内置/前缀/不二次前缀/execute 委托 6 例; 更新 tool_registry 7 例 + activation 4 例 source 断言为前缀名。
> **顺带批清**: ①subagent delegate_task `_wait_timeout` 补 `_MAX_WAIT_TIMEOUT=300` clamp (对齐 task.py); ②gateway 四库 (session/user_mapper/identity resolver/tenancy manager) `_ensure_schema` 补 `PRAGMA journal_mode=WAL + busy_timeout=5000` (对齐 metadata.py); ③`pending_messages` 死字段删除 (RuntimeContext+SessionContext 全仓无写入无消费, 仅 loop 无意义拷贝; 删字段+拷贝行+models.py 失效 import+4 处测试传参, 门控 pending_count 走 manager 局部参数不受影响); ④onebot 测试 aiocqhttp (可选 extra) 缺失时模块级 importorskip (此前 TestSend 走真实 _ensure_imports 致 4 例 ModuleNotFoundError)。
> 全量单测 **1740 通过 + 1 skip** (onebot)、integration **91 通过**、ruff/mypy (267 源文件) 全绿。**U0 完成, 进入 U1 事件溯源会话内核 (架构演进地基)**。
>
> ⚠️ **最近更新: 2026-08-17 —— 第二轮审查批 3 清偿完毕 (Fix-72~Fix-84, 全量 1834 测试通过)**。继批 1 (3 Critical + 回归) / 批 2 (协议契约) 后, 按域清偿全部 12 项 Medium:
> **竞态类**: Fix-72 LogBuffer 非 event loop 线程 append (to_thread 回调内打日志) 序号竞态/消费者列表迭代冲突/asyncio.Queue 跨线程投递 → threading.Lock + call_soon_threadsafe; Fix-73 AgentManager.create check-then-act 双创建覆盖实例 → per-agent 配置锁串行; Fix-74 consolidator 画像归纳 LLM await 期间并发更新被过期基线回滚 → 写回前重读最新 profile 合并; Fix-78 SessionManager 单一全局锁把所有会话连同 DB I/O 串成队列 → per-session_key 锁 + 缓存命中热路径无锁 + key 锁惰性回收; Fix-83 SubAgent restore_interrupted 先登记内存索引后改状态, 并发查询可见 "running 幻影" → 先落库改 cancelled 再入索引。
> **资源边界类**: Fix-75 WebChat `_pending_replies` 会话个数无界 (K7 只限了每会话队列长度) → max_sessions 上限 + 过期/最旧逐出 + poll 后删条目; Fix-76 feishu/wecom/qq_official 三个 webhook 适配器验签前全量读 body 无上限 (超大/chunked body 打爆内存) → 新增 `webhook_guard.read_body_limited` 流式限流 (默认 2MB, 可配); Fix-77 隔离插件 IPC recv 无超时 (子进程挂死 → 该插件所有 call 经 _lock 排队挂死) → wait_for 30s 超时按崩溃重启。
> **契约/状态机类**: Fix-79 Session 持久化 schema 缺 platform_session_id/user_ids → 补列 + 旧库 ALTER 迁移 + 写穿/hydrate (muted_until 是 monotonic 运行时值不持久化); Fix-80 webhook 事件名 dispatch 直发 EventBus 枚举值 (post_message/post_send), 与 CONTROL_PLANE_SPEC §5.1 目录 (message.*) 不一致 → 规范目录名派发 + 旧名订阅自动归一 (spec 同步补接线状态); Fix-81/82 强制话轮: 等锁期间被取消时 finally 无条件复位会破坏并发回合状态机 (turn_owns_state 限定) + AgentContext 未注入 conversation_runtime 致恒不可打断 + 正常完成不清陈旧 interrupt_state 污染下一回合; Fix-84 ArtifactStore 并发首写时 `_ensure_schema` 无锁竞态 (多连接并发切 WAL 撞写事务 → database is locked, 全量跑约 1/3 概率复现) → schema 初始化双重检查锁。
> 新增 20 例回归测试 (含 feishu 12 处测试 fake 补 stream() 接口适配限流读取)。**全量 1834 通过**, ruff/mypy 全绿。N1c 批 1-3 全部清偿, 剩余 ~40 项 Minor 另立批次。
>
> ⚠️ **最近更新: 2026-08-17 —— 第二轮全量代码审查修复完成 (Fix-55~Fix-71, 全量 1813 测试通过)**。N1b/N5b 清偿后按同规格再做一轮 5 路并行全量审查 (复核既有修复 + 查漏), 确认 3 项新 Critical + 5 项修复回归 + 一批 Medium, 分两批清偿:
> **批 1 (3 Critical + 回归, Fix-55~62)**: ① **Fix-55** webhook dispatch 在会话锁内同步 await (单个慢 endpoint 阻塞该会话全部消息链 ~32s) → 后台任务派发; ② **Fix-56** QQ 官方 send() 只看 HTTP 2xx 不看 body 错误字段 (平台级失败被静默吞掉, 与 OneBot 口径相反) → 非零错误码 fail-closed; ③ **Fix-57** 打断后 pending 消息丢失 (interrupted 分支直接 return 未回退消费游标) → `rewind_processed`; ④ Fix-58 MCP server agents_dir 未接线 (plugin_set_enabled 恒 False); ⑤ Fix-59 PUT plugins matrix 404 检查移入 config 锁; ⑥ Fix-60 stdio serve 异常未隔离会拖垮 TaskGroup; ⑦ Fix-61 静态凭证判定漏 parse_token_scopes 分支; ⑧ Fix-62 `is_safe_url` 同步 DNS 解析阻塞 event loop → to_thread + 去重复检查。
> **批 2 (协议契约 + 认证一致性 + 记忆/制品, Fix-63~71)**: Fix-63 MediaResolver 平台键与 OneBot adapter platform_name="qq" 不匹配; Fix-64 rerank 把 Cohere/Jina 响应字段假设成单数 "result" (协议错认, 官方为 "results"); Fix-65 reranker 非数字 score 排序崩溃 → float 强转回退; Fix-50/52 setup 已配静态凭证后 is_password_valid 仍 True + PBKDF2 校验滑动窗限速 (防在线爆破); Fix-66 PATCH agent 的 payload 可携带 revision 覆盖 (乐观锁 ABA) → 与 agent_id 同等剥离; Fix-67 consolidator episode 元数据 IN 查询分块 (500/批, 防 SQLite 变量上限); Fix-68 task/delegate_task 深度键从 ToolContext.services 读恒 0 (递归守卫形同虚设) → 改读 runtime 写入口径 AgentContext.services; Fix-69 ArtifactStore `INSERT OR REPLACE` 让同内容不同制品互改元数据/TTL (短 TTL 覆盖后共享文件被提前清扫) → `INSERT OR IGNORE` + 首次登记为准 + 写后回读 (并发竞态安全); Fix-70 handoff 无存活校验 (移交给已 stop/destroy 的 Agent 后, 会话被架空最长一个 TTL, 每条消息都丢弃) → 工具登记前拒绝 + router.route() 发现目标不可路由时清除残留归属自愈回落; Fix-71 Telegram entity offset 按 Python code point 切片 (emoji 在前时 mention 错位、@ 判定失效) → UTF-16 code unit 精确切片。
> 新增 12+ 例回归测试; **全量 1813 通过** (含此前计时抖动的 smoke_main_resident), ruff/mypy 全绿。元模式复现三次: "测试 fixture 与实现共享同一份错误协议假设" (wecom AES / QQ send / rerank 字段), 后续引入官方文档测试向量。剩余批 3 (11 Medium + ~40 Minor) 见 DEVELOPMENT_PLAN N1c。
>
> ⚠️ **最近更新: 2026-08-16 —— Phase 1 N2-2 browser CI 本地真跑通 (本沙箱可做项)**。本地装 pytest-playwright + chromium, 首次真跑 `tests/browser/` 两条黄金路径 (此前 CI 配置对了但本地从未真跑过, importorskip 跳过)。暴露并修复两处隐藏问题: ① **refreshUsage 产品 bug** —— 用量计量未启用 (usage_store 为 None) 时 `/usage/models/*` 路由不挂载, apiCall 404 返回 null, refreshUsage 此前 `if (summary === null) return` 直接退出不渲染任何行 → usage 表 tbody 永远空、页面无反馈 (既无数据也无空状态提示); 改为 null 时渲染 "(计量未启用)" 空状态行 (与 audit 空状态一致)。② **test_golden_path_agent_crud 测试 bug** —— `page.on("dialog")` 在 click 删除之后注册, playwright 默认 dismiss confirm dialog → 删除被取消、destroy_agent 审计不记录; 改为 click 前注册 + 删除后等 toast + logs 页等具体审计动作文本 (create/start/destroy_agent) 而非任意 td (避免匹配空状态行误判)。独立脚本验证后端 audit/usage 接口正常 (audit 完整流程返回 3 条记录)。**两条黄金路径本地真跑通 (2 passed)**。Phase 1 剩余项依赖外部环境/凭据 (line 259): N2-1 Docker 冒烟 (docker daemon)、N2-4 24h soak + LLM 兼容性矩阵 (真实 LLM key), 按"遇阻先跳过"留待环境就绪。
>
> ⚠️ **最近更新: 2026-08-16 —— Phase 0 代码清偿批次 C-G 全部完成 (N5b 清偿完毕)**。继 N1b/Fix-37~48 + 批次 A 后, 本轮按"解除阻塞先后"清偿 N5b 全部剩余批次:
> **批次E (记忆口径, 含真 bug)**: person_profiles 键分裂统一 episode.user_id=master_id (consolidator/注入器/manager 口径一致, S2 画像归纳默认部署即死已修)、`latest_episode_id_for_session` 租户包裹 SQL 报错修复 (R4 压缩链路恢复)、consolidator 软删同步 BM25/向量、去重桶 scope 加 user_id、`_sanitize_llm_induction` 防 prompt injection (整行正则删)、注入器注入 sparse/vector resolver、metadata latest/get/update_episode_summary 租户隔离。
> **批次F (LLM 参数 clamp)**: bash MAX_TIMEOUT_SECONDS=300、wait 上限 600s、task _MAX_BUDGET_TOKENS=32000/_MAX_WAIT_TIMEOUT=300。
> **批次D (MCP 生命周期)**: reload_config 加 `_disconnect_mcp_clients`、start 重连、`initialize`+`notifications/initialized` 握手 (5s 容错降级, 规范 server 受益非规范走降级)、stdio reader 脏输出 `continue` 不退出 (防该 server 此后恒超时)、connect 顺序先 `_connected=True` 让 reader 循环跑。
> **批次C (插件生态)**: **C1** 启动期 `call_on_load` 对全部 source-aware registry (tools/commands/prompt_builder/agent_hooks/event_bus) `set_current_source` (此前工具 source=builtin, `deregister_by_source` 失效 → 启动期插件工具永留死工具); **C2** 四表 (CommandRegistry/SystemPromptBuilder/AgentHooks/EventBus) 加来源追踪 + `deregister_by_source` + `set_current_source` (+ `get_by_source`/`deregister_plugin_sourced`/`items_with_source`), `activation._sync_one_instance` 对 commands/injectors 改按来源精确 deregister+re-register (替代全量 re-register 加法语义, 旧不同名残留), `routes_plugins` reload/uninstall 清全部共享表来源 (非仅 tools); **C3** 隔离 host `_on_crash` respawn 后标记 `_needs_reload` 让下次 call 重载 (`load_plugin` 缓存 path, 此前 respawn 空 worker 不 reload → 崩溃恢复名存实亡) + `_apply_rlimits` RLIMIT_CPU 可配 (此前 (1,1) 硬编码); **C4** `call` `asyncio.Lock` 串行化 IPC + `_ipc_roundtrip` 校验响应 `correlation_id` 匹配 (此前 FIFO recv 无锁, 并发响应错配); **C8** reload/uninstall 用 `loaded.path` 定位 (manifest.name≠目录名时不再 not_found/删错目录)。C5/C6/C9 已先行 (commit 3caff41/566ab91)。**C7 AstrBot import 沙箱留架构债** (隔离是 opt-in 设计取舍, 强制兼容层隔离需重构 adapt 进子进程, 写边层已就绪待后续)。
> **批次G (适配器零散)**: **G1** 飞书 p2p 按 `chat_type=="group"` 判定群聊 (此前 chat_id 非空即判群, p2p 误判); **G2** Discord `start` 缓存 `_bot_user_id` + `_to_isac_message` 按 `author.bot`/id 匹配丢弃自身消息 (REST polling 返回频道全部消息含 Bot 回复, 不过滤则自回应死循环); **G3** ChannelRegistry.start_all/stop_all 错误隔离 (单平台失败不阻断其余); **G4** uploads_store 注册生命周期 (`start_ttl_sweep` 周期清理 7 天过期入站媒体, 此前只注册 artifact_store → uploads 无限堆积); DELETE 不存在 agent 500→404 (经 `_require_agent` 统一)。**G5 list_tenants 已有内存缓存 / G6 resolve_secret 无扫描路径概念**, 取证为非 bug 跳过。
> 新增回归测试 ~40 例 (test_control_api_agents_destroy / test_feishu_adapter p2p+group / test_platform_adapters discord 自过滤 3 例 / test_channel_registry 错误隔离 4 例 / test_c2_source_tracking 四类 12 例 / test_plugin_isolation_c3c4 5 例 / test_plugin_manager_t6 name≠dir 2 例)。全量 **1794 测试通过** (unit 1704 + integration 90, smoke_main_resident 时序 flake 单跑通过非本轮引入)、ruff/mypy (266 源文件) 全绿。**Phase 0 代码清偿完成 (零已知 Critical/Major 缺陷), 下一阶段进入 Phase 1 工程验证 (Docker/browser CI/24h soak, 依赖环境)**。
>
> ⚠️ **最近更新: 2026-08-16 —— 全量代码审查 Fix 轮 (Fix-37~Fix-48): 7 Critical + 批次 A 安全一致性修复**。5 路并行全量审查 (isac/ 全部 260+ 源文件) 发现 7 Critical + 44 Major + 68 Minor, 主审逐条读码复核 Critical 全部确认后修复"立即"层: **Fix-37** 企微 AES 明文布局与官方 WXBizMsgCrypt 协议颠倒 (`wechat/adapter.py` 取 `plain[20+msg_len:]` 当 XML, 实为 corpid 尾部; 单测同错互相印证故全绿但真实回调必失败) → 按官方布局 `msg=plain[20:20+msg_len]` + 新增 receiveid==corpid 校验 + 测试编码方向同步修正 (wecom 渠道此前对真实环境完全不可用); **Fix-38** image_gen 下载 provider 响应 URL 复用带 Bearer api_key 的 client → api_key 外泄任意第三方 CDN 主机 → 独立无 Authorization 下载 client; **Fix-39** 入站媒体/插件安装器只校验初始 URL 后 `follow_redirects=True` (302→内网/云元数据 SSRF 绕过) 且无体积上限 (OOM) → 新增 `safe_install.safe_download_bytes` (重定向逐跳复跑 is_safe_url + 流式 50MB/100MB 上限), incoming_media/installer 统一接入; **Fix-40** 已配 api_token 但 setup_state 缺失时未认证 POST /setup 可设密码接管控制面 → SetupManager 增 static_credentials_configured (setup 不再必需 + complete_setup 拒绝 + 路由 403 SETUP_NOT_ALLOWED); **Fix-42** main MCP 接线未传 parsed_tokens → tokens[] 部署下 tools/call 认证整段跳过 → 接线补传; **Fix-43** MCP 无任何凭证时 tools/call fail-closed 拒绝 (此前零认证); **Fix-44** MCP native stdio `sys.stdin.buffer.readline()` 阻塞主事件循环 (启用即冻结 Bot) → asyncio.to_thread; **批次 A**: **Fix-45** /events/stream scope 解析不认会话 Cookie → tokens[] 下 WebUI SSE 全拒 → _resolve_caller_scopes 走 _resolve_token (Header 优先 Cookie 回退); **Fix-46** /logs/tail 无 scope 门禁 (窄 scope token 读全量日志) → 接 scope_dependency("*"); **Fix-47** CSRF 中间件拦带旧 Cookie 的重新登录 (POST /auth/session) → 豁免; **Fix-48** PUT /agents/{id}/plugins 无配置锁 (与 PATCH 并发丢更新) + `list(str)` 逐字符拆分 → acquire_config_lock + _as_str_list。新增 15 例回归测试 (test_wechat_adapter receiveid 拒绝 / test_safe_install safe_download_bytes 5 例 / test_image_gen key 不泄露 / test_mcp_server fail-closed+scope 2 例 / test_t3_backend setup 静态凭证 2 例 / test_control_api_events Cookie scope / test_t4 logs scope / test_control_api_auth_session 重登录)。全量 **1752 测试通过** (smoke_main_resident 时序 flake 单跑通过, 非本轮引入)、ruff/mypy 全绿。**剩余未修 (本轮审查发现, 按批次排期)**: 批次 C 插件生态专项 (source 追踪/全量 deregister/隔离崩溃重载/installer name 校验与回滚)、批次 D MCP 生命周期 (reload 泄漏/stop-start 重连/initialize 握手)、批次 E 记忆口径 (person_profiles 键分裂/租户 SQL/BM25 同步)、批次 F 参数 clamp、批次 G 适配器 (飞书 p2p/Discord 自过滤/Registry 错误隔离) 及 Minor 批量。
>
> ⚠️ **最近更新: 2026-08-16 —— 三态标记收敛 + 下一步行动计划 (N1-N5) 制定**。文档漂移修复: T3-backend 升 `[x]`; **P3/P4/P5 与 Q4/Q5/Q6 均已被 R 节点收敛, 由 `[~]` 升 `[x]`** 并补"结论"行 (P3 剩余"通用实体关系图抽取层"按 R4 决策转 Y1)。新增 `DEVELOPMENT_PLAN.md` **§三之三 下一步行动计划**: N1 文档收敛 (进行中) → N2 环境准入项清偿 (Docker 冒烟/browser CI/release checklist/24h soak) → N3 T5 真实 IM 凭据联调 (外部阻塞) → N4 前端轨道启动 (API 基线已冻结, 技术栈决策先行) → N5 剩余架构债并行线。后端代码工作已基本收尾 (全量 1739 测试通过、ruff/mypy 全绿), 剩余项几乎全部为环境/凭据依赖与前端轨道, 详见 DEVELOPMENT_PLAN §三之三与 `RELEASE_AUDIT.md` 第三节。
>
> 上一轮 2026-08-16 —— R7 取证复核 + hook 补测 + T7 代码部分完成。全量 **1733 单测通过** (+COMPRESS listener e2e 3 例 + ConfigMigrator 链式 2 例, 跳 browser 环境限制 + artifact_store 并发 flaky 单跑通过)、ruff/mypy 全绿 (266 文件)。**R7-⑤ REQUIREMENTS 十二条取证复核** → 新建 `docs/RELEASE_AUDIT.md` (8✅+4⚠️: 缺口均属 GA 后 V2/V3/V4/X3/X4 或环境准入非代码缺陷; 含 hook/injector 覆盖审计表)。**R7-⑥ hook/injector 真实触发测试补齐** → 新建 `tests/unit/test_compress_listener_e2e.py` (3 例: 经 `hooks.fire(COMPRESS)` 真实触发 assembly 注册的 `_on_compress` listener → 入队 → run_once 摘要落盘; MODULE_GUIDE §二第三道坎, 此前 COMPRESS 仅纯单元直调 enqueue_compression)。**T7 代码部分** → 补 `ConfigMigrator` 链式迁移测试 2 例 (链式跨版本 + 死端 warning) + 新建 `docs/QUICKSTART.md` 5 分钟跑通 (路径 A Docker 一键 / B 源码 / C 真实 LLM + 验证清单); Dockerfile/compose/export 早已存在 (I2)。详见 DEVELOPMENT_PLAN §四 R7/T7。新增三套集成测试 (现全缺 → 补齐): `tests/integration/test_p3_memory_retrieval.py` (8 例: 向量 KNN 召回 + 图谱 mentioned_in 邻居召回 + 治理 deleted 不被检索命中 + frozen 仍可检索 + embedder 降级 dense 短路 + graph 关闭不写边; 复用 `_KeywordEmbeddingProvider` 确定性 fake embedding)、`tests/integration/test_p4_identity_bind.py` (6 例: 两平台 qq+telegram bind 同一 person_id + 记忆按归一 master_id 聚合检索 + 归一身份隔离 + 低置信冲突写 identity_conflicts + resolve_conflict 标记解决 + 高置信不写冲突)、`tests/integration/test_p5_enterprise_isolation.py` (5 例: pipeline 层跨租户不可见 + PluginIsolationHost spawn→load→call→kill 真实插件 + _on_crash 崩溃重启达 max 放弃 + workflow 声明式 load_workflows_from_dir+persist + tool: action 经 build_default_action_handler 真实调 ToolRegistry.execute)。**待环境项 (按"遇到阻塞先跳过"留后)**: 真实启动冒烟 + Docker 健康检查 (需 docker daemon)、24h soak (需长时运行环境 + 真实 LLM key)、I 节点 browser CI 复核 100% (需浏览器环境, 本地无 browser 报 2 ERROR 为环境限制非代码缺陷)、release_checklist 七段全过 (需真实部署环境)、REQUIREMENTS 十二条逐条取证 (需人工逐条复核)。详见 DEVELOPMENT_PLAN §四 R7。
>
> 上一轮 2026-08-16 —— R4 记忆完整性补齐完成。全量 **1709 单测通过** (新增 R4 16 例: `test_memory_consolidator_r4` ①`_top_candidate_words` 高频词过滤/释义解析/LLM 隔离/无群聊跳过/LLM=None 跳过 + ②COMPRESS 入队+摘要落盘+dedup+无 episode 降级+LLM=None 跳过 + mid_term 注入器读 summary/无 summary 降级/无 metadata, 更新 `test_memory_injectors` 旧 mid_term 测为新契约, 跳 browser 环境限制 + smoke flaky 单跑通过)、ruff/mypy 全绿、smoke exit=0。**①行话学习写入回路** —— `MemoryConsolidator.run_once` 新增第 4 步 `_extract_jargon_step` (LLM 守卫内, 与画像归纳同级): 按 `group_id` 聚合群聊 episode → `_top_candidate_words` (内置 CJK 2-gram bigram 分词 + 停用词/单字/既有 jargon 过滤, 无 jieba 新依赖) 统计高频词 → `_define_one_jargon` 经 `self._llm.chat` 释义 (MEANING/CONTEXT 两行) → `metadata.upsert_jargon`; LLM 失败/无群聊/LLM=None 跳过, 异常隔离。**②中期记忆真实压缩 (方案 A)** —— `assembly` 经 `_register_compress_listener` 把 COMPRESS hook 回调注册进 per-Agent 私有 hooks: 回调仅 `consolidator.enqueue_compression(session_id, messages)` 入队 (不调 LLM, 守护 hook 禁直接调 LLM 规范); `run_once` 第 5 步 `_compress_step` 消费队列 → `_summarize_one_session` LLM 摘要 → `metadata.latest_episode_id_for_session` 定位 episode → `update_episode_summary` 落 `episodes.summary` (复用既存列 + episodes_fts_au 触发器自动同步 FTS); `MidTermMemoryInjector.build()` 改读本会话最近 episode 已落盘 summary 经 `RecallCue` 注入, 不再截断复述 `pending_messages[-5:]`; 新建 `CompressionPolicy`/`Summary`/`RecallCue` 三类承载逻辑。**③P3 通用实体关系图 —— 跳过留架构债**: 写边层 `GraphStore.add_edge` (通用三元组) 已就绪, 抽取层从零 (需 LLM + NER + 关系抽取 prompt 工程, ~150+ 行) 按"遇到阻塞先跳过"留 Y1 承接。新增 `MetadataStore.update_episode_summary`/`get_episode_summary`/`latest_episode_id_for_session` 三方法; `ConsolidationResult` 加 `jargon_extracted`/`compressed_summaries` 计数。**附带修复 R1 遗留**: `main.py:193` `_resolve_artifact_store` 调用处补 `await` (此前传协程对象致 R1-① artifact 解析静默失效, RuntimeWarning `coroutine never awaited`)。默认零行为变化 (LLM=None/无群聊/无 COMPRESS 触发时不变)。详见 DEVELOPMENT_PLAN §四 R4。
>
> 上一轮 2026-08-16 —— R1 多模态出入站闭环完成。全量 **1693 单测通过** (新增 R1 13 例: test_r1 caps/pricing/get_ref/完整id/入站下载/SSRF/record_*, 跳 browser)、ruff/mypy 全绿 (266 文件)、smoke exit=0。①`_send_reply` 扫回复 `artifact:<64位hex>` 经新增 `ArtifactStore.get_ref` (查表构造 ArtifactRef) + `MediaResolver.resolve_for_channel` 转 segment; `_format_artifact_refs` 去截断输出完整 id; `_resolve_artifact_store` 容错取 store。②新建 `isac/gateway/incoming_media.py` `download_inbound_media` 扫 segments url HTTP 下载 (httpx+SSRF) → `uploads_store.put` (root_dir=data/uploads) → 回填 media_uri; `process_message` 路由后调用; `_build_media_normalizer` 白名单含 data/uploads。③`_MediaToolBase.execute` 调 `_record_media_usage` 计 record_image_gen/stt/tts/video (传 provider/model); `EmbeddingManager`/`Reranker` 加 usage_recorder + record_embed/rerank; `_build_memory_stack` 透传。④新建 `data/pricing.jsonc` + `PricingCatalog.load`; record_* 传 provider/model 与价目表 key 对齐。⑤`AgentConfig.model_capabilities_allow` 字段 + `_register_media_tools` 条件注册 + `understand_image` hint。详见 DEVELOPMENT_PLAN §四 R1。
>
> 上一轮 2026-08-16 —— R6 企业化激活完成。全量 **1679 单测通过** (新增 R6 10 例: test_r6_tenants TenantManager 存储 CRUD/持久化/成员 + routes_tenants 端点 CRUD/成员/scope, 跳 browser 环境限制)、ruff/mypy 全绿 (265 文件)、smoke exit=0。①`routes_tenants` (`isac/control/api/routes_tenants.py`) CRUD 租户+成员 (`GET/POST /tenants`, `GET/DELETE /tenants/{id}`, `POST/DELETE /tenants/{id}/members`), `tenant:read/write` scope + 审计; 新建 `TenantManager` (`isac/runtime/tenancy/manager.py`, SQLite 持久化照 UserMapper/SessionManager 同构, best-effort 写穿+重启恢复+asyncio.Lock 串行), `tenancy.enabled` 时构造 (`main._build_tenant_manager`, `data/gateway/tenants.db`), `server._mount_tenant_router` 挂载 (无 manager 不挂载零行为变化); 数据面隔离已由 MetadataStore 层 `TenantIsolationGuard.enforce` 完成, AgentConfig/AgentManager 租户过滤界定为 O1 数据面纵深。②`loader` 子进程隔离**已完全满足零工作** (`_should_isolate`/`_is_isolated_native` manager.py:116-128 + `_load_isolated` 130-176 + `_on_crash` 崩溃自动重启 host.py:270-314, 已接生产 load 路径+有测试)。③Workflow Agent 工具入口**决策落地选 B** (文档化不做): `actions.py:57` `agent:` noop 补"经决策不实现"交叉引用消除悬空语义, actions.py docstring+main.py:1476 正式化依据 (engine 有 start 方法但 assembly 不接 workflow_engine, plumbing 代价与收益不匹配)。详见 DEVELOPMENT_PLAN §四 R6。
>
> 上一轮 2026-08-16 —— R2 控制面与 SubAgent 收尾完成。全量 **1669 单测通过** (新增 R2 11 例: test_r2 config/list-all/webhooks/envelope/evidence_refs + test_mcp_server 5 工具, 跳 browser 环境限制)、ruff/mypy 全绿 (263 文件)、smoke_webchat/smoke_main_resident exit=0。①`GET /agents/{id}/config` (`routes_agents.py:_get_agent_config`) 返回 asdict(config) 含真实 revision, WebUI `loadConfigForEdit` 改用替代硬编码 revision:1 (乐观锁 if_match 真实生效)。②`GET /subagent-runs` list-all 替代 app.js 硬编码 `GET /agents/_/subagent-runs`。③新建 `routes_webhooks.py` (CRUD + /automation/trigger, 复用 WebhookManager+SSRF), `main._setup_webhooks` 构造 WebhookManager + EventBus on_async(POST_MESSAGE/POST_SEND) 订阅 + AlertManager 注入 webhook_manager 激活告警推送, server `_mount_webhook_router` 挂载。④`mcp_server._call_tool` 补 5 工具 (channel_bind/unbind/agent_update_config/plugin_set_enabled/message_send) 抽 `_call_r2_tools` helper; `main._register_mcp_server` 生产启动点 (control.mcp_server.enabled 默认关闭零行为变化, spawn stdio task)。⑤`runner.py` 调 ContextEnvelopeBuilder.build 把 task.context.summary 拼进 LLM user message (此前 build 零调用)。⑥`runner._collect_evidence_refs` 从结果 content 扫 artifact:<id> 填 SubAgentResult.evidence_refs (此前恒空)。详见 DEVELOPMENT_PLAN §四 R2。
>
> 上一轮 2026-08-16 —— R5 持久化与密钥安全收尾完成。全量 **1659 单测通过** (新增 R5 8 例: SessionManager 持久化/重启恢复/并发/close + resolve_secret 各分支/resolve_secrets_in_config, 跳 browser 环境限制)、ruff/mypy 全绿 (262 文件)、真机冒烟 `scripts/smoke_session_persistence.py` exit=0 (建会话→SIGTERM 停→重启→同会话键发消息验证 session_id 不变 `sess_fbaa64ee` 恢复成功, 行数不增)。①`SessionManager` (`isac/gateway/session.py`) 照 `UserMapper` 同构加 `db_path` 参数: `SCHEMA_SQL` 建 `sessions` 表 + `_ensure_schema` (惰性建表) + `_load_from_db` (缓存未命中先查库 hydrate 既有会话, 重启复用 session_id 不新建) + `_persist` (best-effort 写穿, 失败仅记日志不阻塞消息流) + `_delete_from_db` (close/gc 同步删) + `asyncio.Lock` 串行 check-then-create (防并发双创建); `main` 传 `db_path=data/gateway/sessions.db`, 不传则纯内存向后兼容 (现有 14 处 `SessionManager(config)` 调用零行为变化)。②`SecretStore` 接入: `resolve_secret_async` (`security.py`) 用 `secret:<key>` 前缀约定解密配置中 api_key; `resolve_secrets_in_config` 在 `build_services`/`register_llm_provider` 之前就地解析 `llm.api_key` + `llm.multimodal[*].api_key` 使同步注册函数拿明文; env `ISAC_SECRET_KEY` 未配置时不构造 store → `secret:` 前缀值原样回退 (warning) 走原明文路径向后兼容; env `ISAC_LLM_API_KEY` 仍最高优先级; CLI `isac secret set/get/delete` (getpass 不回显); 控制面无 GET config 明文回显端点 (routes_config 仅 validate/diff), 审计 `secret:` 前缀本身不含明文天然安全。默认无 db_path/无 env/无 `secret:` 前缀零行为变化。详见 DEVELOPMENT_PLAN §四 R5。
>
> 上一轮 2026-08-16 —— T6 插件市场与热重载完成。全量 **1651 单测通过** (新增 T6 60 例: safe_install/tool_registry/activation/installer/manager_t6/routes_t6, 跳 browser 环境限制)、ruff/mypy 全绿 (262 文件)、真机冒烟 `scripts/smoke_plugin_marketplace.py` exit=0 (干净目录启动 → 列市场清单含 echo_tool → 上传安装 echo 插件 → loaded 含 → reload → 卸载 → loaded 不含)。新建 `PluginInstaller` (`isac/plugin/runtime/installer.py`, 对标 AstrBot `PluginUpdator`) 支持 market/git/url/upload 四源安装 (SSRF `is_safe_url` + zip slip `safe_extractall` + 失败回滚), 市场清单本地 `data/plugin_marketplace.jsonc` + 可配远程 `control.plugins.marketplace_url` (httpx 拉取失败降级仅本地); `PluginManager` 加 `install/reload/uninstall/list_failures/retry` + `_failures` 追踪; `ToolRegistry` 加 `deregister`/`deregister_by_source`/`deregister_plugin_sourced` + 来源追踪 (`_source`/`set_current_source`, register 加 source 向后兼容); 新建 `activation` 模块 (`activate_plugin` + `sync_plugin_tools_to_agents`) 遍历运行中 Agent deregister 旧工具 + register 新工具, 热重载运行中会话立即生效 (对标 AstrBot reload 全局重建, 适配 ISAC per-Agent registry); 控制面新增 `GET /plugins/marketplace` + `POST /plugins/install` + `POST /plugins/{name}/reload` + `DELETE /plugins/{name}` + `GET /plugins/failed` + `POST /plugins/{name}/retry` (写操作 `plugin:write` scope + 审计, `allow_install=false` 不注册写端点); CLI `isac plugin list/marketplace/install/reload/uninstall/failed/retry` 经 HTTP; upload 用 base64 body 不引 multipart 依赖; `main` 无条件设 `_plugins_dir` 供 reload/install/retry 定位; `assembly._merge_shared_plugin_tools` 改带 source 透传。injectors/commands 热重载为加法语义 (仅 tools 精确 deregister, 已知限制)。默认无 marketplace_url 无 install 调用零行为变化。详见 DEVELOPMENT_PLAN §四 T6。
>
> 上一轮 2026-08-16 —— R3 插件与 MCP 生态激活 (收敛 Q3) 完成。全量 **1590 单测通过** (新增 R3 7 例)、ruff/mypy 全绿、两真机 smoke (smoke_webchat / smoke_control_setup) exit=0 + R3 MCP 真机冒烟 (`scripts/dev_mcp_echo_server.py` 最小 stdio MCP server 配 `mcp.servers.echo` + Agent `mcp_servers=["echo"]` → isac 日志 `MCP server 已接入 server=echo tools=1`, list_tools 桥接真实生效)。R3 复用 `plugin_agent_hooks` 三阶段共享模式扩展到 tools/commands/injectors: `_fire_plugin_on_load` 建立进程级共享 `ToolRegistry`/`CommandRegistry`/`SystemPromptBuilder` 注入 `make_plugin_context` (替换原 None) → native 插件 `on_load` `register_*` 真实写入 + 新建 `AstrBotStarAdapter` (`isac/plugin/compatibility/astrbot/adapter.py`, 仿 `MaiBotPluginAdapter`) 经 `_adapt_compat_plugins` 桥接 AstrBot `@filter.llm_tool` / MaiBot `@register_action` 装饰器进共享表 → `assemble_agent` 经 `_merge_shared_plugin_tools`/`_merge_shared_plugin_commands` 合并进 per-Agent registry。MCPClient 生产接线: `config.jsonc` 顶层 `mcp.servers` 节 (DEFAULT_CONFIG 加默认空节) + `build_services` 注入 `services["mcp_servers"]` + `assemble_agent` 经 `_wire_mcp_clients` 按 `AgentConfig.mcp_servers` 构造+connect+list_tools 注册 `MCPToolBridge` + `AgentManager.stop`/`destroy`/`_shutdown_message_pipeline` 调 `disconnect`。CLI 工具 services 注入此前已完成。默认无插件无 mcp_servers 零行为变化。**第 5 项"兼容层迁进程隔离"未做** (架构受限: 兼容层无 manifest, Fix-31 已安全兜底, 留架构债)。下一步 T6 插件市场 或 R1/R2/R4/R5/R6 并行。详见 DEVELOPMENT_PLAN §四 R3。
>
> 上一轮 2026-08-16 —— 阶段 0 工程纠偏 + FE0 API 契约冻结 + FE1 分离基建 + T3-backend 控制面开箱后端支撑 完成。全量 **1582 测试通过**、ruff/mypy 全绿、两真机 smoke (smoke_webchat / smoke_control_setup) exit=0。阶段0: CI 分支修正 (dev 触发) + venv 重建 (shebang) + aiosqlite 连接未关闭警告归零 (24h soak 前置) + 清理残留 worktree/构建产物。FE0: openapi.json 契约基线归档 + 错误格式统一 (detail{code,message}) + 变更流程文档化。FE1: CORS 白名单 + Session SameSite 参数化 + WebUI 标 deprecated。T3-backend: control 默认开 (仅 127.0.0.1) + SetupManager 首登强制设密码 (428 gate + /setup API + PBKDF2) + CLI `isac password reset` + /api/v1/config/schema JSON Schema 端点。详见 DEVELOPMENT_PLAN §三之二 与 §四 FE/T3。
>
> 上一轮 2026-08-15 —— 前后端分离决策 + 文档整合; T 开箱可用轮 T1/T2/T4 已完成 (2026-08-04)。全量 **1568 测试通过**、ruff/mypy 全绿。T1 开箱能对话 (私聊无条件触发 + 未回复可观测 + 占位 key 检测)、T2 零配置启动 (默认配置内置 + 首启建 data 目录)、T4 错误可诊断 (中文可操作提示 + /health 聚合 + 实时日志台后端) 均附真机冒烟证据 (见对应 commit)。**T3 按前后端分离重定义** (后端先交付 setup/auth API, 见 DEVELOPMENT_PLAN §四 FE)。本轮文档整合: 2026-07-28/29 两份 Review 报告的遗留项已整合进 DEVELOPMENT_PLAN (架构债清单; 07-28 复审的 C-N1~C-N5 与全部 Required 项已由 Fix-22~Fix-36 修复), S 骨架轮 HANDOFF.md 已随轮次结束删除。
>
> 上一轮 2026-07-31 —— **首次真机部署冒烟, 推翻"MVP 已达成"结论**。此前所有轮次的验收都只跑单测 + 读代码/文档,**从未真机走一遍用户旅程**。本次按 README 拷 `config.sample.jsonc` 到干净目录启动后实测:**发消息永远收不到回复,且日志里没有任何错误** —— 根因 `gating/system.py:174` 把私聊的强制触发条件写成 `has_at or (is_private and has_mention)`,私聊被额外要求"必须提及机器人名",私聊"你好"仅得 40 分 < 阈值 80 → `门控评分 score=30.0 threshold=80` → 静默 WAIT。另实测发现:消息被吞后用户端与日志双向零反馈;`control.enabled: false` 导致**WebUI 开箱不可用**;必须手写 JSONC 才能启动(AstrBot 默认配置内置代码,零文件即可跑)。结论:**内部能力确实已接线, 但产品尚不可部署可用, 不构成 MVP**。已新增最高优先级 **T 开箱可用轮**(§四 T, 先于 R),并立**验收铁律: 任何节点声明完成必须附真机部署证据, 不接受"单测通过"作为可用性证明**。详见 DEVELOPMENT_PLAN §四 T。
>
> 上一轮 2026-07-29 (**全量代码复审校正进度**: 以代码为准重新核验 Q2-Q6 与 P 剩余项, 发现文档系统性**低估进度** —— Q2-Q6 多数为「实现完成待接线」而非「未开始」(**Q2 已于当日补齐接线并升级 `[x]`**: persona.description 接入 BaseIdentityInjector + 新增 MoodTracker 挂 FINAL_RESPONSE 真实驱动 decay/update)。Q3 EnableMatrix + 进程级 hooks 已接但 per-Agent PluginContext 恒 None、MCPClient 零接线、CLI 工具 services 未注入; Q4 6 个媒体工具已注册 assembly.py:312-317 但出站 _send_reply 不解析 artifact、record_* 计量零调用、PricingCatalog 空表; Q5 Extensions/SSE/Usage 已接但 GET config + SubAgent 表 agent_id + Webhook/MCP 启动点未接; Q6 用量证据保存 + 并发信号量 + delegate deny 已完成, 仅剩背景摘要传递与 evidence_refs 生成; O4 微信 wecom 模式实为已实现并注册 main.py:410, 仅 mp 公众号为骨架。测试实为 **1545 例/134 文件** (Q2 落地后), 旧记 1362 已订正。**另新增 R 发布收敛节点组** (§四 R): 三级发布门 v0.9 MVP ✅ 已达成 / v1.0 RC = R1-R5 / v1.0 GA = R6-R7; 并记录 4 个此前未记录的需求级缺口 (行话学习写入侧 / 中期记忆伪压缩 / Session 不持久化 / SecretStore 零调用)。详见下方"待实现能力"表与 DEVELOPMENT_PLAN §四 Q/R)。上一轮 2026-07-28 (**S1-S5+S7 飞书+QQ官方 激活**: S1 三个主动任务生产者填真实产出逻辑 + 注入 memory; S2 MemoryConsolidator run_once 三步 + 注入 llm; S4 身份归一控制面 routes_identity + resolve_conflict + main/server 注入; S3 图谱召回 mentioned_in 边 + _graph_search 真实召回 + Reranker provider 注入 + MemoryItem 边界; S5 Workflow action_handler + 声明式加载 + condition_evaluator; S7 飞书适配器 (AES-256-CBC 解密字节序核对自官方文档) + QQ 官方适配器 (Ed25519 验签字节序核对自官方文档, 三类消息事件规范化); 91 例新测试, 全量 1362 单测通过、ruff/mypy 全绿。详见 DEVELOPMENT_PLAN §四"S 骨架轮 / S1-S5+S7"。S6 视频 Provider 用户决定暂缓。上一轮 2026-07-27 **骨架轮 S1-S7**: 为 P3 图谱召回 / P4 身份归一 / P5 Workflow 控制面 / MemoryConsolidator / proactive-ext 生产者 / O4 飞书·微信·QQ 官方三平台 / O5 视频 Provider 一次性补齐**骨架 + 默认关闭接线锚点**,均 default-off、主链路零行为变化;1271 单测基线。骨架≠交付,真实激活按 P3/P4/P5 验收执行。上一轮 2026-07-26 对照 `REQUIREMENTS.md` 十二条需求做 10 域并行代码取证 + 真实启动实测,新增 **Q MVP 收尾** 节点组,其中 **Q1 记忆写入回路** 已完成)

## 节点总览

| 大节点 | 名称 | 进度 | 说明 |
|--------|------|------|------|
| A | 文档冻结 | 100% | A1-A5 完成 |
| B | 基础骨架 | 100% | 脚手架 + 核心契约 + 配置日志 + 入口 |
| C | 连接与路由 | 100% | OneBot + Gateway + Router + Registry |
| D | 单 Agent 核心 | 100% | D1-D9 完成 |
| E | 多 Agent 运行时 | 100% | E1-E4 完成;E5 经 K6 端到端验收 |
| F | 插件生态 | 100% | AstrBot / MaiBot / Native / 加载器 |
| G | 控制面与自动化 | 100% | Admin API / MCP / Webhook / 安全默认值 |
| H | 平台与工具扩展 | 100% | Telegram/Discord/WebChat + MCP Client + 实用工具 |
| I | 生产化与交付 | 85% | 部署/文档/数据工具/监控完成;WebUI v2 完成;浏览器测试 CI 已随 K8 接入,待复核升 100% |
| J | 模型能力、计量与管理面 | 100% | J1+J2+J3+J4 完成 (非桩实现+测试+运行验证+文档同步);2026-07-26 五维度代码评审发现的 J2/J3/J4 缺口 (媒体校验未接线、J4 执行循环未接线、Token Scope/SSE scope 过滤/CSRF 会话缺失等 20 项) 已逐项修复,详见下方"J2/J3/J4 补充修复"|
| K | 稳定化与可用版本闭环 | 100% | K1-K8 全部完成 (K8-2 Playwright CI + release_checklist 已落地) |
| L | 拟人化运行时落地 | 100% | **P1 已接线 (2026-07-27)**: debounce 合并/wait 三路唤醒/thinking 期打断+旧回复抑制/主动任务强制话轮/会话快照恢复 全部接入生产主链路 (conversation.enabled 开关, 默认关闭零行为变化); L1-L5 升级为 [x] |
| M | 路由与 Agent Mesh 深化 | 100% | **P2 已接线 (2026-07-27)**: observer 旁听/candidate 仲裁/notify·handoff·memory_query 全部接入生产 (Link 细粒度 permissions + handoff 归属转移 + memory_query 同步返回+scope 裁剪); M1/M2 升级为 [x] |
| N | 记忆深化 | **已完成 (2026-08-16 收敛)** | N2 治理完整接入生产; N1 MemoryItem 边界文档化; N3 身份归一经 P4 收敛 (控制面+集成测试); 图谱召回/Reranker/Consolidator 经 S2/S3 激活并由 P3/R4 收敛; 实体关系图抽取层转 Y1 (GA 后) |
| O | 企业化与平台扩展 | 主体完成, 剩 mp/O5 (GA 后 V2/V3) | O1/O2/O3 经 R6 收敛 (routes_tenants+TenantManager / 隔离核验满足 / Workflow action_handler+agent: 决策落地); S7 飞书+QQ 官方真实收发; wecom 企业微信已实现; 剩: 微信 mp 公众号 (V3)、O5 视频 Provider 端点 (V2, 用户选型暂缓)、Slack (V4) |
| P | 主链路接线与激活 | **全部完成 (2026-08-16 收敛)** | P0/P1/P2 完成 (2026-07-27); P3/P4/P5 于 2026-08-16 升 `[x]` —— P3 图谱召回+Reranker (S3) + 集成测试 test_p3 (R7), 剩余实体关系图抽取层转 Y1; P4 身份归一控制面 (S4) + 集成测试 test_p4 (R7); P5 由 R6 收敛 (routes_tenants + 隔离核验满足 + agent: 入口决策落地) + 集成测试 test_p5 (R7)。定义见 DEVELOPMENT_PLAN §四 P |
| Q | MVP 收尾(新增) | **全部完成 (Q3-Q6 于 2026-08-16 收敛)** | Q0/Q1/Q2 完成 (2026-07-27/29); **Q3 由 R3 收敛** (共享注册表+AstrBot/MaiBot 桥接+MCPClient 接线); **Q4 由 R1 收敛** (出入站闭环+6 个 record_* 计量+价目表); **Q5/Q6 由 R2 收敛** (真实 revision+list-all+webhooks+MCP 5 工具+envelope/evidence_refs)。均于 2026-08-16 升 `[x]`。定义见 DEVELOPMENT_PLAN §四 Q |
| T | **开箱可用 (最高优先级)** | T1/T2/T4 完成 + T3-backend 后端段完成 (2026-08-16); T3 前端段 F1/F2 待启动 | T1 开箱能对话 (门控私聊修复 + 未回复可观测 + 占位 key 检测)、T2 零配置启动、T4 错误可诊断 已完成并附真机冒烟证据;T3 按前后端分离重定义 (后端段 = FE/T3-backend);T5 真实 IM 验收 (需凭据)、T6 插件市场 ✅ 完成 (2026-08-16, 依赖 R3 已满足)、T7 分发运维未开始。定义见 DEVELOPMENT_PLAN §四 T |
| FE | **前后端分离 (2026-08-15 制定, 后端先行)** | FE0/FE1/T3-backend 完成 (2026-08-16); F1-F4 待启动 | FE0 API 契约冻结 → FE1 分离基建 (CORS/跨源认证/静态托管降级) → T3-backend 控制面开箱后端支撑;前端轨道 F1-F4 (独立项目) 在 API 基线冻结后启动。定义见 DEVELOPMENT_PLAN §四 FE |
| R | 功能广度 (降级到 T 之后) | R3/R5/R2/R6/R1/R4 ✅ 完成 (2026-08-16); R7 集成测试部分完成 (2026-08-16, 环境准入项待环境) | 补齐需求十二条仍缺的实现 + Q3-Q6/P3-P5 剩余接线。**2026-07-31 整组降级到 T 之后**(主干不可用时补功能广度无意义)。**R3 插件与 MCP 生态激活 (Q3) 已完成 (2026-08-16)**: 共享注册表 + AstrBot/MaiBot adapt 桥接 + MCPClient 生产接线 + CLI 工具 services 注入 (详见 §四 R3, 真机冒烟 `MCP server 已接入 server=echo tools=1`)。**R5 持久化与密钥安全已完成 (2026-08-16)**: SessionManager SQLite 写穿+重启恢复 (照 UserMapper 同构) + SecretStore `secret:` 前缀接入 + CLI `isac secret` (真机冒烟重启恢复 session_id exit=0, 详见 §四 R5)。**R2 控制面与 SubAgent收尾已完成 (2026-08-16)**: `GET /agents/{id}/config` 真实 revision + SubAgent list-all + routes_webhooks (WebhookManager+EventBus 订阅+AlertManager 注入) + MCP Server 5 工具/生产启动点 + ContextEnvelopeBuilder 真传背景摘要 + evidence_refs 生成 (详见 §四 R2)。**R6 企业化激活已完成 (2026-08-16)**: routes_tenants (CRUD 租户+成员 + tenant:read/write scope) + TenantManager (SQLite 持久化照 UserMapper 同构) + ②loader 子进程隔离已满足零工作 + ③workflow agent 入口决策落地选 B (文档化不做, 消除悬空) (详见 §四 R6)。**R1 多模态出入站闭环已完成 (2026-08-16)**: ①_send_reply 扫 artifact 经 get_ref+MediaResolver 转 segment + ②入站下载落盘 data/uploads 闭环 + ③6 个 record_* 计量 + ④pricing.jsonc 价目表 + ⑤model_capabilities_allow 工具可见性 (详见 §四 R1)。**R4 记忆完整性补齐已完成 (2026-08-16)**: ①行话学习写入回路 consolidator `_extract_jargon_step` 群聊高频词 LLM 释义落 `upsert_jargon` + ②中期记忆真实 COMPRESS 方案 A (hook 入队+consolidator 后台摘要落 `episodes.summary`+MidTermMemoryInjector 改读 summary 注入 RecallCue) + ③语义关系图跳过留架构债 (写边层已就绪待补 LLM 抽取层, 留 Y1) (详见 §四 R4)。**R7 集成测试补齐代码可做部分已完成 (2026-08-16)**: 新增 test_p3/p4/p5 三套集成测试 19 例 (向量+图谱+治理过滤召回 / 两平台 bind→记忆聚合 / 跨租户不可见+插件隔离+workflow 声明式执行), 全绿; 环境准入项 (真机/Docker/24h soak/browser CI/十二条逐条取证) 待环境 (详见 §四 R7)。定义见 DEVELOPMENT_PLAN §四 R |
| 可观测性 | trace 贯穿 + 分级日志 (横切) | 100% | trace_id/session_id/agent_id 贯穿全链路;level + per_module 分级;默认零输出零开销 |

## 可运行性状态

> ⚠️ **2026-07-31 订正**: 下述"可运行"指**进程能起来并驻留**,**不等于"用户能用"** —— 真机冒烟证明按 sample 配置部署后**发消息收不到回复**(见文首 T 轮说明)。"可部署可用"的口径以 §四 **T 开箱可用轮**的真机验收为准。

**已达到「可运行(进程驻留)」完成度**(2026-07-26 实测,不等于「MVP 可用」,见下方 2026-07-26 差距复核与文首 2026-07-31 真机冒烟):

- 主程序实测驻留(无 `data/config.jsonc` 时兜底默认值 + StubProvider 也能启动;18 秒驻留无异常栈),支持 SIGINT/SIGTERM 优雅关闭(Windows 下 Ctrl+C 尚不走优雅关闭路径,见 Q0)。
- 1568 单元/集成测试通过 (2026-08-15 实测);Ruff 通过;Mypy 全绿 (256 文件)。
- 集成测试就位:单 Agent 全链、多 Agent × 工具 × 记忆 × 控制面、启动驻留 smoke、J2 多模态全链 + Channel 投递、J4 SubAgent 全链 + Control API、J3 WebUI v2 SPA 十域。
- 真实 `OpenAICompatProvider`(httpx + SSE + Tool Call + 错误分类 + 连接池)可用;主链路默认非流式,流式路径(CR3-H4 已修合并逻辑)尚未在生产启用。
- Agent / 路由 / Link / 记忆可持久化恢复;SubAgent 任务可重启恢复 (running/queued → cancelled)。**订正**:此前"Session 可持久化恢复"表述不准确 —— `SessionManager`/`UserMapper` 实为纯内存实现(无落盘/无恢复),重启后会话状态与跨平台用户绑定丢失(对话内容因记忆子系统独立持久化不受影响);补齐计划见 Q1。
- J3 WebUI v2 SPA 十域全部真实内容: Dashboard/Agents/Channels/Providers/Usage/Extensions/Memory/Sessions/Logs/System; 配置编辑事务 (Schema 校验 + Diff 预览 + 二次确认 + ETag 乐观锁); SSE 实时事件流; Playwright 浏览器黄金路径测试 (未装时 skip, CI 接入待 K8-2)。

## 稳定化节点 (K) 明细

| 节点 | 状态 | 交付 |
|------|------|------|
| K1 应用生命周期 | ✅ | ApplicationRuntime + TaskGroup + register_lifecycle + 优雅关闭 |
| K2 真实 Provider | ✅ | OpenAICompatProvider 真实 HTTP/SSE/Tool Call/429·5xx 分类/连接池 |
| K3 存储生命周期 | ✅ | Schema init/migration + BM25 预热 + shared namespace ACL |
| K4 配置持久化恢复 | ✅ | 原子写 (tmp+fsync+os.replace) + Agent/Link 恢复 |
| K5 单 Agent E2E | ✅ | FakeChannel + FakeLLMProvider 全链集成测试 |
| K6 多 Agent E2E | ✅ | 多 Agent × 工具 × 记忆 × 控制面集成测试 (含原 E5) |
| K7 安全基线 | ✅ | SSRF 防护 + SecretStore(AES-256-GCM) + TTL + 有界队列 + kill-wait |
| K8 CI/发布准入 | ✅ | CI 四 job (check+build+docker+browser) + wheel/sdist smoke + Docker 30s health 循环 + Playwright CI 接入 + scripts/release_checklist.md 七段发布清单 |

## 待实现能力

**J2/J3/J4 补充修复 (2026-07-26)**:

对 J2/J3/J4 做五维度代码评审后发现 7 项 Critical + 8 项 Required 缺口 (均已直接
读代码确认, 非道听途说), 逐项 TDD 修复并独立提交:
- J2: `MediaNormalizer` 接入 `TranscribeAudioTool`/`VisionUnderstandTool` 生产路径 (此前授权这两个工具的 Agent 可读任意本地文件); 图片生成下载 URL 补 SSRF 校验。
- J4: 子 Agent 真实执行循环接入生产 (此前 `delegate_task` 永远停在 `queued`); `SubAgentPolicy` 空集改严格交集 (此前 fail-open); 递归深度限制; 取消超时不再静默; Journal 脱敏补 `summary`/`max_log_bytes`; `_authorize` 补跨 Agent 校验。
- J3: `PATCH /agents/{id}` If-Match 改读 HTTP Header (原来是 query 参数, 会被静默忽略) + `AgentManager` 按 agent_id 加配置锁修复并发竞态; `CONTROL_PLANE_SPEC.md` §6.1 描述的 Token Scope 模型 (`control.tokens[]`) 落地; SSE 事件按 scope 过滤 + 连接数上限; Provider 测试/制品删除端点补审计日志; `InterAgentLink` 格式校验 + WebUI 审计日志渲染改用 `textContent` (修复存储型 XSS); `POST /auth/session` 会话 Cookie + CSRF 双提交校验 (§8.2 第 5 条)。

**J3 已完成 (2026-07-25)**:

J3 WebUI v2 管理与观测已完整落地 (详见 DEVELOPMENT_PLAN.md J3 节"当前"):
- 后端 Control API 扩展 (routes_providers / routes_config / routes_sessions / routes_memory / routes_events SSE)
- AgentConfig 加 revision 字段 + PATCH If-Match 乐观锁
- WebUI v2 SPA shell 侧边栏 10 域导航
- Dashboard / Agents / Channels / Providers / Usage / Extensions / Memory / Sessions / Logs / System 十页真实内容
- 配置编辑事务 UI (Schema 校验 + Diff 预览 + 二次确认 + ETag 乐观锁)
- Playwright 浏览器黄金路径测试 (2 路径; 未装时 skip, CI 接入待 K8-2)

**剩余工作 (接线 + 未实现;定义详见 DEVELOPMENT_PLAN.md §四 P 节点)**:

*已实现待主链路接线 (`[~]`:核心逻辑 + 单测完成,默认关闭 / 生产路径无调用点)*:

| 能力 | 现状 | 接线节点 |
|------|------|---------|
| L2-L5 拟人化 | **已接线 (P1, 2026-07-27)**: debounce 合并/主动调度启停/打断闭环/恢复加载全部进生产主链路 | P1 ✅ |
| M1-M2 Mesh | **已接线 (P2, 2026-07-27)**: observer/candidate 路由 + broker 注入 + 4 A2A 工具真实可用 (Link permissions/handoff 归属转移/memory_query 同步返回) | P2 ✅ |
| N1 MemoryItem | 契约 + Adapter 实现;S3 落地边界文档化 —— 治理路径 (N2 export) 用 MemoryItem, 检索热路径 (`search()`/`_merge_results()`) 继续用轻量 MemoryHit (避免为尚无消费者的抽象层增加每请求开销) | 已明确边界 |
| N3 身份归一 | IdentityResolver 实现;**S4 激活 (2026-07-28)**: 控制面 routes_identity (bind/conflicts/resolve) + main/server 注入 + IdentityResolver.resolve_conflict;剩集成测试 + 真实凭据联调 | P4 (剩集成测试) |
| O1 多租户 | **已接线 (CR3-L2)**: `tenancy.enabled` 配置开启后 MetadataStore 读写带租户谓词/打标 + 记忆命名空间加前缀;默认关闭零行为变化 | 已完成 (跨租户测试见 test_tenant_isolation) |
| O2 插件隔离 | PluginIsolationHost 已支持子进程真实加载插件 (`load_plugin`, CR3-H2) + `on_load` 生命周期已接线;**默认加载路径仍在宿主进程内执行 (无隔离, 有护栏警告)**, 接管待做 | P5 |
| O3 Workflow | **S5 激活 (2026-07-28)**: action_handler (tool: 前缀 → ToolRegistry.execute) + 声明式加载 (`load_workflows_from_dir`) + condition_evaluator;控制面 routes_workflows 已挂载;剩 Agent 工具入口 (P5 决策项, 有意未做) | P5 (剩 Agent 工具入口) |
| 向量召回 | **已接线 (CR3-H3)**: `pipeline.search()` 稠密召回 + RRF 融合 + ACL 一致过滤;`memory.embedding` 配 api_key+model 即生效 (main 注入 EmbeddingProvider)。**S3 激活 (2026-07-28)**: 图谱召回 mentioned_in 边写入 + _graph_search 真实召回 (种子锚定 user_id/group_id 满足 ACL) + 第四路 RRF;Reranker provider 注入 (够 api_key+model 时 is_available=True, 仿 CR3-H3 embedding 注入写法) | P3 (通用实体关系图留后续增强) |
| 流式工具调用 | 按 index 累积分片 + stream_options.include_usage + 首 chunk 前失败回退 chat_with_retry (CR3-H4);主链路未启用 streaming | P0 |

*已激活 (2026-07-28 S1-S5+S7)*:

- **S1 主动任务生产者** — DateReminder/TopicFollowup/MemoryAssociation 三者 `__call__` 改 async + 填真实产出逻辑 (记忆日期实体/未闭合话题/记忆联想检索); `_build_task_producer` 注入 memory。16 例单测。
- **S2 MemoryConsolidator** — run_once 三步真实整合 (去重合并: 相似度≥0.92 软删旧者经 governor; 重要性+时间衰减剪枝; 画像归纳: llm 注入时调 chat 生成 profile_text); 各步异常隔离。10 例单测。
- **S3 图谱召回 + Reranker + MemoryItem 边界** — 见上表"向量召回"行。
- **S4 身份归一控制面** — 见上表"N3 身份归一"行。
- **S5 Workflow 控制面激活** — 见上表"O3 Workflow"行。
- **S7 飞书适配器** — Webhook 入站 (URL 校验 + 明文/加密两种模式, AES-256-CBC 解密 key=SHA256(encrypt_key)/IV=base64decode(encrypt)[:16]/PKCS7 unpad; im.message.receive_v1 事件规范化) + 出站 (tenant_access_token 缓存 + POST /im/v1/messages 按 receive_id_type 分群聊/私聊)。字节序核对自 open.feishu.cn 官方文档。14 例单测。
- **S7 QQ 官方适配器** — Ed25519 验签字节序核对自 bot.q.qq.com 官方文档 (seed=secret 重复双倍到 32 字节); op=13 验证握手签名 event_ts+plain_token; op=0 dispatch 事件验签 X-Signature-Ed25519 + X-Signature-Timestamp, msg=timestamp+raw_body; AT_MESSAGE_CREATE/GROUP_AT_MESSAGE_CREATE/C2C_MESSAGE_CREATE 三类事件规范化 + 出站 (access_token 缓存 + 群/私聊双端点 + 被动回复 msg_id)。19 例单测。

*2026-07-29 新发现的需求级缺口 (读侧就绪/写侧缺失, 此前各轮复核均未记录; 已收入 R4/R5)*:

| 缺口 | 证据 | 需求条款 | 收敛节点 |
|------|------|---------|---------|
| **行话学习写入侧零实现** | `JargonInjector` 已注册读侧 (`assembly.py:341`), 但 `upsert_jargon` 全仓无生产调用点 → 行话表恒空 | R4/R5 明确要求"行话学习" | R4 ✅ 已完成 (2026-08-16): consolidator `_extract_jargon_step` 群聊高频词 LLM 释义落 `upsert_jargon` |
| **中期记忆是伪压缩** | `MidTermMemoryInjector` 已注册 (`assembly.py:343`) 但仅截断复述 `pending_messages` 末 5 条; 与其自述"由 COMPRESS hook 触发 + CompressionPolicy + Summary + Recall Cue"不符, 未接 `COMPRESS` | R5 要求"中期记忆" | R4 ✅ 已完成 (2026-08-16): COMPRESS hook 入队 + consolidator 后台摘要落 `episodes.summary` + MidTermMemoryInjector 改读 summary 注入 |
| **Session 不可持久化恢复** | `SessionManager` 纯内存 (`session.py:30-35`), 重启丢会话状态 | R10 明确要求"Agent、Session、身份、路由、Link 和记忆可持久化恢复" | R5 |
| **SecretStore 零生产调用** | AES-256-GCM 实现存在但仅在注释被提及 (`progress.py:36`/`journal.py:23`), `api_key` 明文存 `data/config.jsonc` | R9"密钥只可设置或替换, 不可回显" | R5 |

*未开始 (`[ ]`)*:

- **S6 视频 Provider** — `generate` 仍抛 `NotImplementedError`; 用户决定暂缓端点选型 (Sora/Runway/Kling/自托管), 待确定后仿 image_gen 实现 (POST 生成 → 轮询/等待 → 结果写 ArtifactStore → 返回 ArtifactRef)。
- **微信适配器** — 用户决定本轮不做, 保持骨架 (start/stop no-op、send 返回 False)。
- **S5 Agent 工具入口** — 让 Agent 主动触发 workflow; 明确为 P5 决策项, 有意未做 (避免半接线死代码)。
- **I 节点复核** — WebUI 浏览器测试 CI 已随 K8 接入,复核 I 是否可由 85% 升 100%。

*已补齐*: N2 检索期软删除过滤已生效(CR2-Fix-12),N2 记忆治理已完整接入生产。

*订正(2026-07-26, 已于 2026-07-28 S3 修复)*: 此前"Reranker 已接入检索 pipeline"表述不准确。真实后端 `OpenAICompatRerankerProvider`(Cohere/Jina 双协议,`isac/provider/rerank/openai_compat.py`)确已实现,但生产 `main.py` 构造 `Reranker(memory_config.get("reranker", {}))` 时**未传入 provider**,`is_available()` 恒 `False`,`pipeline.search()` 的 rerank 步骤永不执行。**S3 (2026-07-28) 已修复**: `_build_memory_stack` 仿 CR3-H3 embedding 注入写法, 够 `reranker.api_key+model` 时构造 `OpenAICompatRerankerProvider` 传入 `Reranker(cfg, provider=...)`, `is_available()` 不再恒 False。

**CR3 修复轮 (2026-07-26, 对应 Review/ISAC_待修复项清单.md 的 14 项)**: H2 插件隔离护栏+`on_load` 接线+隔离宿主真实加载 / H3 向量召回接入 pipeline(RRF+ACL)+生产 EmbeddingProvider 注入 / H4 流式工具调用按 index 累积+include_usage+失败回退 / M2 bus notify 真实投递 / M5 Gating-Focus LRU cap 1000 / M6 调度器冷却不再饿死其他会话 / M7 Workflow 多入口+fan-in 入度语义 / L1 自动化创建 Agent 强制受限沙箱 / L2 租户隔离进数据面(默认关闭) / L3 软删同步 BM25+预热过滤 / L4 SSRF 请求期固定 IP / L5 治理审计 operator+agent_id 归因 / L6 非 ASCII Token 401+/metrics 可选认证 / L8 write_file 线程池+journal 原子 seq+MCP sse 显式拒绝。附带: 控制面 sessions/memory/events 路由完成生产挂载(此前 services 键缺失恒 None), `resource` 模块 Windows 平台守卫。

## 2026-07-27 MVP 增量代码评审修复轮 (MVP-Fix)

P0-P2 + Q0-Q1 达成 MVP 准入线后，对整个增量 diff (23 文件 / +1430 行) 做 5 维度并行审查 + 每条发现 2 票独立对抗性验证 (22 代理 / 405 次代码检索)：**17 项发现 → 13 项确认、4 项证伪**，全部修复并配 12 例回归测试 (`tests/integration/test_mvp_review_fixes.py`)。

高危 5 项：多步(工具)回合的打断被 `InterruptInjector` 吞掉 (改用单调 `interrupt_seq` 基线判定) / 突发消息重复回复 (drain 空即弃权 + 去重键改 `msg_id`，根因是 `dataclasses.replace` 使身份去重永不命中) / 门控只评估突发末条 (drain 提到门控前，`has_at` 取并集) / 后台记忆写入不被 drain (`drain_background_tasks` 接入关闭链) / **memory_query 空 scopes 泄露全部记忆**(改为 deny-by-default)。

中危 4 项：handoff 永久劫持路由 (加 TTL + 交还路径) / 强制话轮释放他人会话锁 (`acquired` 标志) / 互联消息被 debounce 拦截 (豁免) / UserMapper 并发身份分裂 (锁串行化)。

低危及顺带：快照过期清理 + 目录跟随 `control.agents_dir` (此前测试污染真实 `data/agents`) / `config.sample` embedding 维度矛盾 / 补齐 `InterAgentMessage.trace_id` / **记忆保真度**(合并回合改为写入完整 burst，冒烟发现)。

验证：1203 单测通过、ruff/mypy 全绿；真实启动冒烟确认 3 条突发消息恰好产生 1 条合并回复、记忆与画像正确落库。

## 2026-07-26 MVP 差距复核 (对照 REQUIREMENTS.md 逐条取证)

对照 `docs/REQUIREMENTS.md` 十二条原始需求,10 个领域并行验证(每条结论均落实到 文件:行号 证据,498 次代码检索 + 一次真实启动实测:无 `data/config.jsonc` 时兜底默认值也能启动、18 秒驻留无异常栈)。核心结论:**项目"能启动"但未达"MVP 可用"** —— 开箱只有 OneBot 一条可聊通道(WebChat/Telegram/Discord 已实现却零生产注册点)、**记忆写入回路完全缺失**(检索/注入/治理/持久化整条读链路就绪,但生产从未调用 `store_episode`,检索永远为空)、人格系统的情绪/表达风格/注意力漂移注入器是未注册的空桩、插件与 MCP 生态的数据面注册表在生产被硬编码为空、多模态语义工具从未注册进 ToolRegistry。

同时发现一批标 `[x]` **已交付**的节点(D8/E4/F1-F3/H1/H2/J1-J4/K1-K4/K7)存在与其"完成定义"(§二:非桩实现+单测+集成验证+**主链路接线**+文档+CI)矛盾的未接线子行为 —— 已在 `DEVELOPMENT_PLAN.md` 对应节点下补记"**2026-07-26 MVP 缺口复核**"说明并指向修复它的 Q 节点,不改动其余已验证部分的 `[x]` 标记(与 J2/J3/J4 既有的"补充修复"记录方式一致)。

为把这些**未被 P0-P5 任何节点覆盖**的必需缺口系统化,新增 **Q 节点组:MVP 收尾**(定义详见 `DEVELOPMENT_PLAN.md` §四 Q):

| 能力 | 现状 | 对应节点 |
|------|------|---------|
| **Q1 记忆写入回路与身份稳定化** | **已完成 (2026-07-27)**: 回复后后台写 episodic (整轮对话)+画像/关系每互动递增 (读写同键)+UserMapper SQLite 写穿持久化 (master_id 跨重启稳定);行话学习/画像 LLM 归纳留 MemoryConsolidator;Session 状态仍不持久化 (如实标注) | Q1 ✅ |
| Q0 开箱可触达与配置纠偏 | **已完成 (2026-07-27)**: 四平台注册分支+裸部署默认路由+样例死键修正+Dockerfile 冻结+Windows 优雅关闭+web_search deny+Provider 缓存失效+destroy 记忆清理+task 门修正;冒烟另修复出站平台会话键丢失 (WebChat 回复/进度帧落错队列) | Q0 ✅ |
| Q2 人格差异化实现 | **已完成 (2026-07-29)**: `config.persona.description`(Agent 覆盖全局)接入 `BaseIdentityInjector`(`assembly.py:254-259`, 未配置回落默认文案零行为变化);新增 `MoodTracker`(`isac/persona/mood_tracker.py`)挂 `FINAL_RESPONSE`, 每轮 `decay()` 自然衰减 + 按工具调用数(封顶 5)施加小幅 arousal 扰动(valence 不臆造情感判断);三注入器沿用既有真实逻辑。**复核修正**: arousal 信号源初版读 `response.tool_calls`, 但 `FINAL_RESPONSE` 触发时该值恒为空(`loop.py` else 分支的触发条件), 是死代码; 改读 `AgentContext.tool_calls_this_turn` 累加值, 补真实 `ISACAgentLoop` 端到端回归。新增 9 例单测, 全量回归(1473 单测 + 72 集成)无退化 | Q2 ✅ |
| Q3 插件与 MCP 生态数据面接线 | **部分接线 (2026-07-29 校正)**: `EnableMatrix` 已注入 `PluginManager` (`main.py:1227`) + 进程级 plugin hooks 已合并进 Agent (`assembly.py:265`);剩 ① per-Agent `PluginContext` 注册表恒 `None` (`main.py:1362`) → AstrBot/MaiBot 加载但 handler 不触发 (loader 不调 `adapt`) ② `MCPClient` 零生产接线, `mcp_servers` 无消费者 ③ `bash`/`read_file`/`write_file` 的 services 未注入 → 恒被拒 | Q3(新增,E4/F1-F4/H2 delta) |
| Q4 多模态工具注册与计量收尾 | **部分接线 (2026-07-29 校正)**: 6 个语义媒体工具已注册进 ToolRegistry (`assembly.py:312-317`, default deny);剩 ① 出站 `_send_reply` 不解析 `artifact_id` (`main.py:209`) → 生成媒体发不出 ② 入站媒体不落盘 `data/uploads/` ③ `record_*` 6 计量方法零生产调用 → 用量恒 0 ④ `PricingCatalog` 空表 (`main.py:770`) ⑤ 无 `model_capabilities_allow` 字段 | Q4(新增,J1/J2 delta) |
| Q5 WebUI 与控制面收尾 | **部分接线 (2026-07-29 校正)**: Extensions 页接 `/plugins/loaded`、SSE `EventSource('/events/stream')`、Usage 页结构已接;剩 ① `GET /agents/{id}/config`+真实 revision 缺失 (前端伪造 revision=1) ② SubAgent 任务表 agent_id 硬编码 `_` (`app.js:495`) 恒空 ③ Webhook/MCP Server 无生产启动点/路由挂载 | Q5(新增,J3/G2/G3 delta) |
| Q6 SubAgent 用量与安全补漏 | **大部分完成 (2026-07-29 校正)**: `result.usage`/`evidence_refs` 已存 run (`supervisor.py:193`) + 并发信号量 (`supervisor.py:54`, 默认 4) + `RESTRICTED` deny `delegate_task` (`defaults.py:35`);剩 ① 背景摘要未经 `ContextEnvelopeBuilder` 传子 Agent (runner 未调用) ② `evidence_refs` 生成缺失 (`runner.py:93` 恒空) | Q6(新增,J4 delta) |

Q0/Q1 不依赖 P0 消息并发化,建议与/先于 P 节点推进;P2(Mesh)、P3(记忆检索深化)的验收范围已相应扩充(Link 细粒度 ACL、Reranker 注入),不在 Q 中重复列出。MVP 准入线(P0-P2 + Q0-Q1)见 [ROADMAP.md](./ROADMAP.md) MVP 里程碑。

## 编号约定

- 大节点 A/B/C… 为里程碑;小节点如 D9、K1 为最小可交付单元。
- 完成定义 = 非桩实现 + 单元/集成测试 + 实际运行验证 + **主链路接线** + 文档同步 + Ruff/Mypy 通过。
- **scaffolding (框架已搭建)** = 契约 + 骨架 + 惰性默认关闭接线 + 骨架单测 + 主链路零行为变化;**不满足完成定义,不标 100%/`[x]`**。技术路线见 [ROADMAP.md](./ROADMAP.md),范式见 [MODULE_GUIDE.md](./MODULE_GUIDE.md)。
- **三态标记** = `[x]` 已交付(含主链路接线) / `[~]` 实现完成待接线(核心逻辑 + 单测完成,但未接入生产,接线项归 DEVELOPMENT_PLAN §四 P 节点) / `[ ]` 未开始。演进链:scaffolding → `[~]` → `[x]`。
