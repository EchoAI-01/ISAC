# ISAC 骨架激活开发说明 (Handoff)

> 面向"按现有框架继续开发"的下一位开发者。本文档只讲**怎么把已搭好的骨架推进到交付**,
> 不重复架构设计(见 `ARCHITECTURE.md` / `SPECIFICATION.md`)。
> 对应本轮 **S 骨架轮 (2026-07-27)** 落地的骨架,节点定义见 `DEVELOPMENT_PLAN.md` §四。

---

## 0. 先读这一节(前置约定)

**当前状态 (2026-07-31 更新)**:**1545 单测通过 (134 文件)、ruff/mypy 全绿 —— 但 ⚠️ 真机部署后无法对话**。2026-07-31 首次真机冒烟推翻了"MVP 已达成":拷 `config.sample.jsonc` 启动后发消息永不回复(`gating/system.py:174` 私聊被额外要求 `has_mention` → 静默 WAIT),WebUI 因 `control.enabled: false` 不可用。**下一步开发按 `DEVELOPMENT_PLAN.md` §四 T 开箱可用轮执行,T1 是 P0 阻断项**;原 R 节点组(功能广度)已降级到 T 之后。**验收铁律: 任何节点完成必须附真机部署证据, 不接受"单测通过"作为可用性证明**。骨架轮 S1-S7 中 **S1-S5+S7 已激活** (真实业务逻辑 + 单测 + main/server 注入 + 主程序冒烟); **S6 视频 Provider 用户决定暂缓** (`generate` 仍抛 NotImplementedError, 待端点选型二次确认); **S7 微信 wecom 企业微信模式实为已实现并注册** (2026-07-29 代码复审确认: `adapter.py` start 启 uvicorn webhook + AES 验签 + send 真实发送, `main.py:410` enabled-gated 注册), 仅 mp 公众号模式仍骨架。`tests/browser/` 2 个 Playwright 用例因环境未装浏览器报错,与业务代码无关,本地可 `--ignore=tests/browser` 跳过。**2026-07-29 全量代码复审另发现 Q2-Q6 多为「部分接线」而非「未开始」** (Q2 三注入器已注册待 mood 回路+persona 文本、Q3 EnableMatrix+hooks 已接待 per-Agent 桥接/MCP/CLI、Q4 6 媒体工具已注册待出入站/计量、Q5 Extensions/SSE/Usage 已接待 config/Webhook、Q6 大部分完成仅剩背景摘要+evidence_refs), 详见 `PROGRESS.md` 与 `DEVELOPMENT_PLAN.md §四 Q`。

**激活进度一览 (2026-07-28)**:
- ✅ S1 主动任务生产者 (DateReminder/TopicFollowup/MemoryAssociation) — `__call__` async + 真实产出逻辑 + `_build_task_producer` 注入 memory (16 例单测)
- ✅ S2 MemoryConsolidator — `run_once` 三步真实整合 (去重/剪枝/画像归纳) + `_build_memory_consolidator` 注入 llm (10 例)
- ✅ S3 图谱召回 — `store_episode` 写 mentioned_in 边 + `_graph_search` 真实召回 (种子锚定 user_id/group_id 满足 ACL) + Reranker provider 注入 (够 api_key+model 时 is_available=True) + MemoryItem 落地边界文档化 (热路径继续用 MemoryHit) (12 例)
- ✅ S4 身份归一控制面 — `IdentityResolver.resolve_conflict` + `routes_identity.py` (bind/conflicts/resolve) + main/server 注入 (7 例)
- ✅ S5 Workflow 控制面 — `actions.py` (tool: 路由 ToolRegistry.execute) + `loader.py` (声明式加载) + `main._build_workflow_engine` helper 注入 (13 例); Agent 工具入口 (P5 决策项) 有意未做
- ⏸ S6 视频 Provider — 用户决定暂缓, `generate` 保持 NotImplementedError
- ✅ S7 飞书适配器 — Webhook 入站 (URL 校验 + 明文/加密两种模式, AES-256-CBC 解密字节序核对自 open.feishu.cn 官方文档) + 出站 (tenant_access_token 缓存) (14 例)
- ✅ S7 QQ 官方适配器 — Ed25519 验签字节序核对自 bot.q.qq.com 官方文档 (seed=secret 重复双倍到 32 字节) + 三类消息事件 (AT/GROUP_AT/C2C) 规范化 + 出站 (access_token 缓存) (19 例)
- ✅ S7 微信适配器 (wecom 企业微信) — 2026-07-29 复审确认已实现并注册 (webhook + AES 验签 + access_token + send); mp 公众号模式仍骨架

下一位开发者若要继续: S6 选端点 (Sora/Runway/Kling/自托管) 后仿 `image_gen` 实现 POST 生成 → 轮询/等待 → 结果写 ArtifactStore → 返回 ArtifactRef; 微信 mp 公众号模式按 `isac/channel/adapters/wechat/adapter.py` 顶部 docstring 机制备忘接入 (wecom 企业微信已实现); S5 Agent 工具入口属 P5 决策, 接入需评估是否新增 Tool + assembly 注册 + engine 注入到 agent services。

**三态标记**(见 `DEVELOPMENT_PLAN.md` §二):
- `[ ]` 未开始 / 仅骨架桩
- `[~]` 实现完成待接线(核心逻辑 + 单测,但未接生产主链路)
- `[x]` 已交付(**含主链路接线**,满足完成定义)
- 演进链:**骨架 → `[~]` → `[x]`**。你要做的就是把骨架逐个推到 `[x]`。

**完成定义**(§二,缺一不可):非桩实现 + 单元/集成测试 + 实际运行验证 + **主链路接线** + 文档同步 + ruff/mypy/CI 绿。**骨架≠交付**——骨架只满足前置的"契约 + 惰性默认关闭接线 + 骨架单测"。

**六要素范式**(见 `MODULE_GUIDE.md` §二):契约 → 骨架类 → 惰性默认关闭接线 → 骨架单测 → ruff/mypy 绿 → 文档同步。激活时保持同一范式,只是把骨架体填成真实逻辑。

**环境与验证命令**(uv 在 `/opt/homebrew/bin`):
```bash
export PATH="/opt/homebrew/bin:$PATH"
uv run ruff check isac tests
uv run mypy isac
uv run python -m pytest tests/unit tests/integration -q   # 跳过 tests/browser
```

**四条铁律**:
1. **default-off 不可破**:激活过程中,未显式配置 `enabled` 时行为必须与激活前完全一致。每个节点都有"零行为变化"回归测试兜底。
2. **复杂度**:ruff `C901` 上限 10。给 `process_message`/`main`/`assemble_agent` 这类大函数加分支前,先把逻辑抽成模块级 helper(参考本轮 `_build_task_producer`/`_resolve_identity`/`_build_memory_consolidator` 的抽法)。
3. **命名空间/ACL 一致**:任何新召回/写入路径都要经既有 ACL 过滤(记忆走 `get_episodes_by_ids` 的 agent 命名空间 + user/group + `deleted=0`;shared 命名空间强制 user/group)。
4. **git 纪律**:只提交自己改的文件,精确 `git add <file>`,不用 `git add -A/.`;不碰他人 `uv.lock`、`Review/*.md`、`.tmpfiles/`。

---

## 1. 通用激活流程(每个骨架 → 交付,固定 7 步)

1. 读节点定义(`DEVELOPMENT_PLAN.md` §四 对应节点 + "S 骨架轮")与本文档对应小节。
2. 定位**锚点**(下方每节给出文件 + 函数)与 `TODO(节点)` 标记。
3. 填真实逻辑,保持骨架的默认关闭分支不变(启用开关才走新逻辑)。
4. 写/扩测试:骨架测试验证 default-off 零产出,新增测试验证启用后的真实行为 + 失败降级。
5. 若要在大函数里加分支,先抽 helper 避免 C901。
6. 跑验证命令(ruff + mypy + pytest),必要时补集成测试(`tests/integration/`)。
7. 同步文档:把节点从 `[~]`/`[ ]` 升 `[x]`,更新 `DEVELOPMENT_PLAN.md` §四 "当前" + `PROGRESS.md` + `ROADMAP.md` 状态与测试数。

---

## 2. 逐节点激活指南

### S1 · 主动任务生产者(proactive-ext,归 L3/P1)

- **锚点**:`isac/runtime/conversation/producer.py` 的 `DateReminderProducer` / `TopicFollowupProducer` / `MemoryAssociationProducer`(三者 `__call__(now)` 现恒返回 `[]`);组合在 `isac/runtime/assembly.py::_build_task_producer`。
- **开启方式**:`conversation.proactive.date_reminder_enabled` / `topic_followup_enabled` / `memory_association_enabled`(默认 false)。开启后经 `CompositeTaskProducer` 汇入 `ProactiveScheduler`(L3 已接线,唤醒回调 → 强制话轮)。
- **待填**:各 `__call__` 的真实产出逻辑(见类内 `TODO(proactive-ext)`):
  - DateReminder:从记忆(person profile / episodic 日期实体)读重要日期,临近触发窗口产出 `intent="date_reminder"`;同一日期一个窗口只提醒一次(仿 `IdleReengageProducer._reengaged_marker` 去重)。
  - TopicFollowup:从会话历史/记忆识别未闭合话题,冷却窗口后产出 `intent="topic_followup"`。
  - MemoryAssociation:用近期上下文检索记忆,相似度超阈值且未近期提及时产出 `intent="memory_association"`。
- **产出的 ProactiveTask 必须带** `source`(在 `DEFAULT_ALLOWED_SOURCES` 内,如 `"memory"`)`/intent/reason`,否则被 `scheduler.authorize` 丢弃。
- **验收**:启用后对应场景真实产出主动任务且经冷却/鉴权触发;default-off 零产出(`test_proactive_producers_scaffolding.py` 已兜底);补集成测试(仿 `tests/integration/test_p1_humanlike_activation.py` 的主动任务用例)。

### S2 · MemoryConsolidator(记忆整合后台任务)

- **锚点**:`isac/memory/consolidator.py::MemoryConsolidator.run_once()`(现 no-op 返回全零 `ConsolidationResult`);构造在 `assembly._build_memory_consolidator`;生命周期由 `AgentManager` 的 start/stop/destroy/reload 四处驱动(已与 `proactive_scheduler` 同构接线)。
- **开启方式**:`memory.consolidation.enabled=true`(+ 可选 `interval_seconds`,默认 3600;注意 `__init__` 有 1.0s 安全下限)。
- **待填**(`run_once` 内 `TODO(consolidator)`):在命名空间内 ①相似 episode 去重/合并;②按重要性 + 时间衰减剪枝(软删走 N2 治理列,**不要硬删**);③归纳更新 PersonProfile 聚合(画像文本的 LLM 归纳放这里——`manager` 累积回路只做启发式,LLM 归纳一直留给本节点)。用注入的 `self._metadata`(MetadataStore)读写。
- **注意**:后台循环单次异常已被隔离(不拖垮循环);真实实现里 DB 操作要自己 try 兜底并计数。
- **验收**:启用后周期性整合、计数正确、软删条目不再被检索命中;default-off 不启动循环(`test_memory_consolidator_scaffolding.py` 兜底)。

### S3 · 图谱召回(归 P3)

- **锚点**:`isac/memory/pipeline.py::MemoryRetrievalPipeline._graph_search()`(现 default-off 恒 `[]`);`search()` 已调用它、`_merge_results()` 已接第四路 RRF;构造开关 `enable_graph_recall`,由 `main.memory_factory` 按 `memory.graph_recall.enabled` 注入。
- **待填**(`_graph_search` 内 `TODO(P3)`):①从 query 抽取实体/关键节点;②对每个节点 `self.graph.neighbors(self.namespace, node, relation)` 取邻居;③邻居节点经 metadata 反查映射回 episode `memory_id`,去重为 `(memory_id, weight)`。任一步失败降级返回 `[]`(仿 `_dense_search` 的防御结构)。**候选自动经 `get_episodes_by_ids` 过滤**(rows_by_id 检查丢弃无行数据的幽灵候选),ACL 安全已保证。
- **前置**:图谱要先有边——`GraphStore.add_edge` 目前全仓无调用点(图始终空)。写入侧(从对话/记忆抽取实体关系写边)也要一并补,否则召回恒空。
- **P3 其余两项**(不在 S3 骨架内,但属同一节点):`Reranker` provider 注入(`main.py` 构造 `Reranker(...)` 时传入 `OpenAICompatRerankerProvider`,否则 `is_available()` 恒 False);`MemoryItem`/`MemoryItemAdapter` 接入检索/注入链或明确落地边界。
- **验收**:配置后图谱召回真实生效并参与 RRF;被治理条目不命中;default-off 与三路结果完全一致(`test_graph_recall_scaffolding.py` 兜底)。

### S4 · 身份归一(归 P4)

- **锚点**:`isac/main.py::_resolve_identity(profile, identity_resolver, message)` + `_build_identity_resolver(global_config, user_mapper)`;在 `process_message` 里 `user_mapper.resolve` 之后调用。
- **开启方式**:`identity.enabled=true`(+ 可选 `heuristic_enabled`,默认 false 防误合并)。启用后 `IdentityResolver.resolve` 归一出 `person_id` 覆盖 `profile.user_id`,下游记忆按归一身份聚合。
- **IdentityResolver 本身已完整实现**(`isac/gateway/identity/resolver.py`:resolve/bind/merge/arbitrate_conflict + `person_identities`/`identity_conflicts` 表)。**待填的是生产接线的另一半**:
  - 谁来 `bind`(把平台账号绑定到 person,verified=1)——需要一个绑定入口(控制面 API 或命令),否则 `resolve` 只会走"委托 UserMapper 建新 person"的兜底,归一不生效。
  - 冲突裁决控制面:`arbitrate_conflict` 写 `identity_conflicts`(confidence<0.7),需要 `routes_identity_conflicts` 之类的人工裁决入口。
- **验收**:跨平台同一用户经 bind 后归一为同一 person、记忆聚合;低置信冲突写表可人工裁决;default-off 走 user_mapper 原路径(`test_identity_resolver_wiring.py` 兜底)。

### S5 · Workflow 控制面(归 P5/O3)

- **锚点**:`isac/control/api/routes_workflows.py`(`build_router`:list/get/start,`workflow_engine=None` 不挂载);`WorkflowEngine.list_workflows()`;`server.create_control_app` / `_mount_optional_routers` 已按注入的 `workflow_engine` 挂载;`main` 按 `control.workflow.enabled` 构造。
- **开启方式**:`control.workflow.enabled=true`(+ 可选 `base_dir`)。
- **WorkflowEngine 已完整实现**(`isac/runtime/workflow/engine.py`:串/并/条件/重试调度 + 持久化)。**待填**:
  - `set_action_handler` 生产注入:把 `Stage.action` 映射到真实动作(工具调用 / Agent 动作 / 子工作流)。当前无 handler 时 stage 视为 noop。
  - `set_condition_evaluator` 生产注入:`kind=conditional` 的 `condition` DSL 求值。
  - (可选)Agent 侧"工具入口":让 Agent 主动触发 workflow——需新增一个 Tool + 在 `assembly` 注册 + 注入 engine 到 agent services。这一项 S5 有意未做(避免半接线死代码),属 P5 决策项。
  - 工作流**注册来源**:目前只能代码 `engine.register(...)`;生产可能需要从声明式文件(如 `data/workflows/*.json`)加载 + 控制面创建端点。
- **验收**:声明式工作流可经控制面 list/get/start 且真实执行、可观测;default-off 不挂载路由(`test_routes_workflows_scaffolding.py` 兜底)。

### S6 · 视频生成 Provider(O5)

- **锚点**:`isac/provider/video_gen/openai_compat.py::OpenAICompatVideoGenProvider.generate()`(现抛 `NotImplementedError`);注册挂点已接 `main._build_multimodal_provider` 的 `kind="video_gen"` 分支(operations=`{"video_gen"}`,modalities text→video)。
- **开启方式**:`multimodal_providers[]` 增 `{kind:"video_gen", provider, api_key, base_url, model}`,即注册进 ModelCatalog/ModelRouter。默认无此项 → 不注册 → 零行为变化。
- **⚠️ 端点二次确认**:视频生成 API(Sora/Runway/Kling)多为受限预览、协议与轮询方式各异。**动手实现 `generate` 前必须先与需求方确认目标端点**。确认后仿 `image_gen`(`OpenAICompatImageGenProvider`)实现:POST 生成 → 轮询/等待 → 结果写 `ArtifactStore` → 返回 `ArtifactRef`,错误分类复用 `OpenAICompatProvider`。
- **注意**:构造参数顺序是 `(api_base, api_key, model, artifact_store)`,与 image_gen 的 `(api_key, base_url, ...)` 不同——`_build_multimodal_provider` 已用关键字传参,勿改回位置参数。
- **验收**:配置后经能力目录/Router 选中、结果走 ArtifactStore;注册不触发 generate(`test_main_multimodal_registration.py` 已覆盖注册 + NotImplementedError 闸门)。

### S7 · 平台适配器:飞书 / 微信 / QQ 官方(O4)

- **锚点**:`isac/channel/adapters/{feishu,wechat,qq_official}/adapter.py`(各实现 `PlatformAdapter` 四方法:`start`/`stop` no-op、`send` 返回 False,带平台机制备忘 + `TODO(O4)`);注册分支在 `main._register_channel_adapters`(enabled-gated 惰性导入)。
- **开启方式**:`channels.feishu.enabled` / `channels.wechat.enabled` / `channels.qq_official.enabled`。各 adapter 文件顶部 docstring 已写清入站/出站机制与 config 示例。
- **待填**(各 `start`/`send` 的 `TODO(O4)`):
  - **feishu**:入站事件订阅(长连接 lark-oapi WS 或 Webhook challenge/验签/解密)→ 规范化 `ISACMessage` → `self.on_message`;出站 `POST /open-apis/im/v1/messages`(tenant_access_token 缓存续期)。
  - **wechat**:**wecom 企业微信模式已实现** (回调服务端 Token 签名 + AESKey 解密入站 + `message/send` 出站, 见 `adapter.py`); 仅剩 mp 公众号模式待接 (个人微信违规不做)。
  - **qq_official**:QQ 官方机器人网关(WS 鉴权 + 心跳 + resume + intents)或 Webhook(Ed25519 验签)入站;OpenAPI 频道/群 messages 出站。
- **依赖**:惰性导入各平台 SDK,未安装时给友好 `ImportError`;新增可选依赖到 `pyproject.toml [project.optional-dependencies]`(仿 `onebot = [...]`)。
- **QQ 说明(重要,别重复造轮子)**:QQ 经 **OneBot v11 连 NapCat** 已是**完整实现**——`isac/channel/adapters/onebot/adapter.py`(`platform_name="qq"`,反向 WebSocket,`channels.onebot.enabled`)。`qq_official` 是**另一条**官方机器人 API 路径(`platform_name="qq_official"`,与 `qq` 并存不撞键),一般二选一启用。
- **验收**:各平台真实收发 + 富媒体按能力降级;default-off 不注册(`test_o4_platform_adapters_scaffolding.py` 兜底,含与 OneBot 并存不撞键)。
- **新增平台通用步骤**见 `DEVELOP.md` 3.3。

---

## 3. 全局注意事项

- **默认关闭如何验证**:每节点都有一条"default-off 零行为变化"测试。改动后先跑它,再跑启用路径的新测试。
- **复杂度红线**:`process_message`、`main`、`assemble_agent`、`_mount_optional_routers` 已接近 C901 上限。往里加逻辑前先抽 helper。
- **导入分层**(`DEVELOP.md` 1.2,单向):utils→provider→memory→persona→agent→gating→router→gateway→channel→commands→plugin→runtime→control→main。新代码不要反向依赖。
- **测试放置**:骨架/单元测试进 `tests/unit/`,端到端进 `tests/integration/`(仿 `test_p1_humanlike_activation.py` 等 P 节点集成测试)。
- **配置项**:本轮新增的开关(`memory.graph_recall` / `memory.consolidation` / `identity` / `control.workflow` / `channels.{feishu,wechat,qq_official}` / `multimodal_providers[].kind=video_gen`)默认全关。激活某节点时,建议同步把示例写进 `config.sample.jsonc` 并加注释。

---

## 4. 参考文档索引

- 节点定义 + "S 骨架轮":`docs/DEVELOPMENT_PLAN.md` §四(含 P0-P5、O1-O5、S1-S7)
- 进度事实源:`docs/PROGRESS.md`
- 技术路线 / 里程碑:`docs/ROADMAP.md`
- 脚手架范式(六要素 + "实现≠交付"教训):`docs/MODULE_GUIDE.md`
- 架构 / 契约:`docs/ARCHITECTURE.md`、`docs/SPECIFICATION.md`
- 开发约定(分层、新增适配器步骤):`docs/DEVELOP.md`
- 项目总览与当前定位:`AGENTS.md`
