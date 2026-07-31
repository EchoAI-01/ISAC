# ISAC 架构评审与下一阶段功能路线

> **评审人**: Doubao Seed Evolving
> **评审日期**: 2026-07-29
> **评审视角**: 架构师（对功能实现与未来开发负责）
> **评审基线**: 2026-07-28 S1-S5+S7 激活后代码状态；对照 `docs/ROADMAP.md`、`docs/REQUIREMENTS.md`、`docs/ARCHITECTURE.md` 与 `isac/` 全仓源码、单测 1362 条。

---

## 一、执行摘要

**当前阶段判定**：代码处于 **M-MVP 准入线达成、MVP+1 待启动** 的关键节点。

- ✅ **已闭环**：单 Agent 主链路（模型+工具+记忆+持久化）、多 Agent Mesh 协作、拟人化地基（debounce/wait/打断/主动）、控制面十域 API、9 个 Channel 适配器中 3 个真实收发（OneBot/Telegram/Discord/WebChat/飞书/QQ 官方）、记忆写入回路（episodic + 画像 + Consolidator）、图谱召回 + 身份归一 + Workflow action_handler。
- 🟡 **代码就位但主链路未激活**：Q2 三个人格注入器、Q3 Native SDK 注册点、Q4 多模态 Provider 挂点、MCP Server（11 tool 实现但零启动点）。
- ⬜ **完全未做**：Q5 WebUI 真实数据绑定、Q6 SubAgent 用量/证据/并发治理、O4 微信公众号/企业号真实收发、O5/S6 视频生成端点选型、若干 TODO 桩。
- ⚠️ **架构债**：`services: dict[str, Any]` 全仓弱类型传递、兼容层插件（AstrBot/MaiBot）仍在宿主进程 exec_module、SSE 事件 scope fail-open（已在前一轮发现，需确认已修）、默认 feature flag 关闭过多（开箱只得到一个"裸 WebChat 单 Agent"）。

**核心结论**：框架地基已经足够稳，**下一阶段的主要矛盾从"建能力"转向"激活能力 + 填最后一英里"**。不需要大改架构，重点是把 Q2–Q6 五个节点按优先级激活，并在激活过程中把几个小 TODO 和架构债顺手清掉。

---

## 二、架构分系统盘点

### 2.1 Channel / 适配器层

| 子项 | 状态 | 说明 |
|---|---|---|
| OneBot v11/v12 | ✅ 生产就绪 | 完整双向，H1 激活 |
| Telegram / Discord | ✅ 生产就绪 | HTTP 轮询 |
| WebChat 内置 | ✅ 生产就绪 | WebSocket，零外部依赖 |
| 飞书 (S7) | ✅ 生产就绪 | Webhook AES-256-CBC + tenant_access_token 缓存 |
| QQ 官方 (S7) | ✅ 生产就绪 | Ed25519 验签 + 三类事件 + access_token 缓存 |
| 微信企业号 | ⬜ 骨架 | `wechat/adapter.py` start/stop 空体，send 返回 False |
| 微信公众号 | ⬜ 骨架 | 同上，no-op |
| 模板适配器 | ⬜ 占位 | `template/adapter.py` 标注 TODO(O4) |

### 2.2 Provider / 模型与服务层

| 子项 | 状态 | 说明 |
|---|---|---|
| LLM (OpenAI 兼容) | ✅ 生产就绪 | HTTP + SSE + 工具调用 + 重试/回退/降级 |
| Embedding / Reranker | ✅ 生产就绪 | OpenAI 兼容；S3 已把 Reranker 注入生产检索链路 |
| Image Gen | ✅ 代码就位 | Provider 完整，但未注册成 Agent 工具（见 Q4） |
| STT / TTS | 🟡 基类就位 | `provider/stt_tts/base.py` 抽象基类，无具体实现 |
| Video Gen (O5/S6) | ⬜ 挂点就位 | `generate()` 抛 NotImplementedError；端点选型暂缓 |
| Provider 健康检查 | ⬜ 空实现 | `routes_providers.py:218/222` 两个 `pass` |

### 2.3 Memory / 记忆子系统

| 子项 | 状态 | 说明 |
|---|---|---|
| MetadataStore (SQLite+BM25+FTS5) | ✅ 生产就绪 | 带软删 |
| VectorStore (sqlite-vec) | ✅ 生产就绪 | 稠密召回 + RRF 融合，默认关（需 embedding 配置） |
| GraphStore | ✅ 生产就绪 | S3 激活 mentioned_in 边 + _graph_search 真实召回 |
| MemoryConsolidator (S2) | ✅ 生产就绪 | 去重(0.92)/剪枝(importance<0.2, 30d)/画像归纳 |
| IdentityResolver (S4) | ✅ 生产就绪 | bind/conflicts/resolve 控制面 |
| 结构化过滤条件 | ⬜ TODO | `memory/pipeline.py:91` `del filters, agent_id  # TODO` |

### 2.4 Agent / 单 Agent 核心

| 子项 | 状态 | 说明 |
|---|---|---|
| 主循环 (pre/post_llm, pre/post_tool, interrupt) | ✅ 生产就绪 | 流式/非流式、截断、慢工具事件、打断抑制 |
| PromptBuilder | ✅ 生产就绪 | Token 预算修剪尚有 TODO 但不阻塞 |
| 工具注册 / 权限 | ✅ 生产就绪 | allow/restricted/deny 三态 + Channel 覆盖 |
| Mood / ExpressionStyle / AttentionDrift 注入器 | 🟡 代码就位 | Q2：骨架完整，`runtime/assembly.py` 硬编码 `None`，生产路径未激活 |
| 上下文压缩 (`should_compress`) | ⬜ TODO | `core/types.py:209` 恒返回 False |

### 2.5 Plugin / 插件生态

| 子项 | 状态 | 说明 |
|---|---|---|
| Native SDK v2 | 🟡 API 就位 | `plugin/native/plugin.py` register_tool/command/injector 已实现，但 `assembly.py` 硬编码 None |
| 插件进程隔离 (PluginIsolationHost) | 🟡 仅 native isolated=true 走子进程 | 兼容层 AstrBot/MaiBot 仍在宿主 `exec_module`（见架构债） |
| AstrBot 兼容层 | 🟡 骨架 | 加载后不桥接 ToolRegistry |
| MaiBot 兼容层 | 🟡 骨架 | 同上 |
| MCP Server | 🟡 完整实现但零启动点 | `control/mcp_server.py` 11 个 tool，stdio JSON-RPC 2.0，main.py 无引用 |
| EnableMatrix 过滤 PluginManager | ⬜ 未接线 | plugins_allow/deny 对插件钩子不生效 |

### 2.6 Runtime / 编排

| 子项 | 状态 | 说明 |
|---|---|---|
| P0 并发化 / P1 拟人化 / P2 Mesh | ✅ 生产就绪 | handoff TTL、observer/candidate、打断序号 |
| P3 图谱召回 + Reranker | ✅ 激活 (S3) | |
| P4 身份归一控制面 | ✅ 激活 (S4) | |
| P5 Workflow action_handler | ✅ 激活 (S5) | tool: 路由 ToolRegistry.execute；condition_evaluator；声明式加载 |
| P5 agent:* 路由 | ⬜ 有意不做 | `workflow/actions.py:58` 留作后续 Agent 工具入口 |
| Proactive 主动任务生产者 | 🟡 代码就位 | DateReminder/TopicFollowup/MemoryAssociation/IdleReengage 已实现注入，但 `proactive.*_enabled` 全默认关 |

### 2.7 Control Plane / 控制面

| 子项 | 状态 | 说明 |
|---|---|---|
| Admin REST API（agents/routing/plugins/providers/config/sessions/memory/events/audit/identity/workflows） | ✅ 生产就绪 | Token/Scope + CSRF + 审计 + 全局异常兜底 |
| WebUI v2 SPA | 🟡 十域框架就位 | Dashboard/Config/Audit 真数据；插件页假数据、SubAgent 路径恒空、配置编辑 revision 失效（If-Match 改 query 后无效） |
| SSE `/events/stream` | ⚠️ 需复核 | 前一轮评审发现 fail-open 泄露 api_key 和聊天原文 (C-N1)，需确认修复已合入 |
| Webhook 入口 | ⬜ 未挂载 | 代码里有挂点但无生产启动点 |
| MCP Server 启动 | ⬜ 未接线 | 完整 stdio 实现，main.py 零引用 |

### 2.8 Observability / 可观测性

| 子项 | 状态 | 说明 |
|---|---|---|
| Trace ID 贯穿 + Prometheus 指标 | ✅ 生产就绪 | |
| 审计日志 (NDJSON) | ✅ 生产就绪 | 注意：同步 `open("a")` 写入（前一轮 R3-4 待异步化） |
| AlertManager | 🟡 已构造但 webhook_manager=None | 前一轮 R3-1 未接线 |
| 多模态计量 (6 个 record_*) | ⬜ 零调用 | Q4：image/video/stt/tts 用量记录方法全仓无引用 |

### 2.9 Core / 基础设施

| 子项 | 状态 | 说明 |
|---|---|---|
| SecretStore (AES-256-GCM) | 🟡 完整实现零调用 | 前一轮 R3-3：`save_agent_config` 仍明文写 api_key |
| magic-byte 媒体校验 | ⬜ TODO | `utils/media.py:135` PNG/JPG/WEBP/MP3/WAV/MP4 头部签名校验 |
| 优雅关闭 (SIGINT/SIGTERM) | ✅ 生产就绪 | |

---

## 三、待实现功能清单（按优先级）

> 排优先级的原则：**用户可感知价值 / 风险 / 工作量** 三维加权。能直接提升"开箱即用"感和"多 Agent 可辨性"的排最前。

### P0 — MVP+1 必做（2-3 天）

**Q2 人格差异化激活**
- 把 `MoodInjector` / `ExpressionStyleInjector` / `AttentionDriftInjector` 从 `assembly.py:391-395` 的硬编码 `None` 改为根据 `persona.enabled` 构造并注册进 PromptBuilder。
- 接通 MoodEngine → PersonaManager → 注入器的更新回路（回复后根据内容/情感打分更新 mood）。
- 验收：两个配了不同 persona 的 Agent 对同一句"你好"的回复肉眼可辨情绪/口吻差异。
- 工作量：~4h。骨架、i18n mood 文案基架已就位，主要是接线和写单测。

**Q5 三个硬伤修复**（不是重写 WebUI，只是把假数据换成真数据）
- 插件页：改为读 `PluginManager.list_plugins()` 真实数据。
- SubAgent 页：改为读 `subagent_supervisor.list_runs()`（注入不为 None 时）。
- 配置编辑 revision：把当前 If-Match query 参数改回 HTTP Header 或改用后端 revision 计数器 + 乐观锁。
- 工作量：~4h。

**C-N1 事件 SSE 安全复核**（如果前一轮已修就跳过，否则必修）
- 确认 `_event_visible()` 不再对无 event_type 的 payload fail-open；确认 `ON_START` 事件 payload 里的 api_key/token 已脱敏。
- 工作量：~0.5h（确认）/ ~2h（修复）。

### P1 — MVP+1 应当做（3-5 天）

**Q3 插件与 MCP 生态数据面接线**
- Native SDK：把 register_tool/command/injector 的注册表实例化并传给 NativePlugin，加载后把工具合并进 ToolRegistry。
- AstrBot/MaiBot 兼容层：从 plugin 的 handler/command 抽取元数据，桥接成 ToolRegistry 条目（名字加前缀避免冲突，如 `astrbot:<name>`）。
- PluginManager 传 EnableMatrix：让 plugins_allow/deny 真正生效到钩子调度。
- **MCP Server 启动点**：在 main.py 加一个 `--mcp-stdio` 启动模式（或按 `control.mcp.enabled` 在子进程启动），让 ISAC 能作为 MCP Server 被上游调用；同时考虑 MCP Client 能力（按配置连远端 MCP Server 反向拉工具）。
- 工作量：~8-12h。风险点是兼容层桥接要注意命名空间和权限模型。

**Q4 多模态工具注册与计量收尾**
- 把 image_gen / stt / tts / vision（多模态 LLM）包装成 Agent 工具注册进 ToolRegistry；video_gen 等端点定了再补。
- 接入点：`runtime/assembly.py` 里构造 ToolRegistry 后，检测对应 provider 是否配置，按需注册。
- 6 个 `record_*` 计量方法接通调用点；价目表（price_per_*）从 provider config 读。
- `utils/media.py` magic-byte 校验实现（135 行附近）—— 这是安全项，防止攻击者把恶意脚本改扩展名上传。
- 工作量：~6-8h。

**Q6 SubAgent 用量与安全补漏**
- supervisor 在 run 结束时把 token usage / evidence_refs 持久化（目前丢弃）。
- 加并发上限（按 agent_id 限流，默认 3）。
- 受限策略里补 `deny delegate_task` 作为可配置项（默认 allow，可全局或按 Agent 关闭委派能力）。
- 工作量：~4h。

### P2 — MVP+2 可做（1-2 周）

**O4 微信适配器真实收发**
- 公众号：接入微信服务器配置校验（signature）、接收普通消息/事件、被动回复。
- 企业号：接收消息 + 主动发送 access_token 缓存（与飞书/QQ 官方一致套路）。
- 注意：微信不支持 SSE/长连接，必须走 Webhook 回调 + 异步回复，复用现有 Webhook 入口即可。
- 工作量：~8-12h。

**P5 agent:* 路由（Workflow Agent 工具入口）**
- 让 Workflow 里的 `agent:<id>:<intent>` action 能真实调用指定 Agent（通过 bus 或 agent_manager）。
- 这一步会把 Workflow 从"工具编排"升级为"Agent 编排"，是 M-4 可商业化里程碑的最后一块。
- 工作量：~4-6h。需要定义跨 Agent 调用时的 session/context 传递契约。

**Feature flag 默认值调整 + onboarding 体验**
- `conversation.enabled` / `memory.consolidation.enabled` / `proactive.*_enabled` / `memory.embedding` 等开关在"有配置时自动启用"（如配了 embedding api_key 就默认开 embedding）。
- 目标：用户按注释填完 config.sample.jsonc 后，得到的不是裸 WebChat 单 Agent，而是"有记忆、有情绪、能主动说话"的完整 Bot。
- 工作量：~3h。但需要先把 Q2/Q3 激活完，否则没东西可自动开。

### P3 — 架构债与未来投资（持续清）

| 项 | 说明 | 建议时机 |
|---|---|---|
| `services: dict[str, Any]` 强类型化 | 改为 ServiceContainer Protocol / TypedDict，全仓 `services.get("x")` → `services.x`。机械替换，风险中等但 IDE/类型检查收益大 | MVP+2 末期，功能面稳定后做 |
| 兼容层插件子进程化 | AstrBot/MaiBot 插件目前 exec_module 在宿主，一个恶意/崩溃插件能拖垮主进程。应全部走 PluginIsolationHost | 与 Q3 接线同步做，避免二次迁移 |
| `memory/pipeline.py:91` 结构化过滤 | topics / 时间范围 / agent_id 过滤在检索链路中实现 | 做记忆检索质量调优时顺手做 |
| Provider 健康检查真实 ping | `routes_providers.py:218/222` 两个 pass 改为调用 `provider.test_connection()` 或发个最小 prompt | Q4 多模态接线时顺手做 |
| IO 异步化（前一轮 R3-4） | `audit.py` 同步 `open("a")`、`bus._trigger_persist` 同步 fsync、`routes_routing._persist_links` 同步写盘 | 任意空档期，~1h |
| SecretStore 接入（前一轮 R3-3） | `save_agent_config` 明文写 api_key → 用 SecretStore 加密 | Q5 配置编辑 revision 修复时顺手做 |
| Docker / K8s 部署工件 | Dockerfile + docker-compose + helm chart；与 Q0 "开箱可触达" 配套 | MVP+1 完成后启动 |
| Playwright 浏览器测试环境修复 | 2 个环境性 ERROR 是 chromium 未装，不是代码缺陷，但挡住了端到端回归 | 部署前补一次 |

### P4 — 待定 / 需决策

- **O5/S6 视频生成端点选型**：当前抛 NotImplementedError。需产品决策：接哪家（Sora / Veo / 可灵 / 即梦），再补实现。不影响 M-MVP。
- **STT/TTS Provider 选型**：基类有了但没有具体实现。可接 OpenAI Whisper / Azure TTS / 国内（豆包语音/讯飞）。
- **MCP Client 能力**：ISAC 作为 MCP Client 连外部 MCP Server 反向拉工具——这个功能和 Q3 插件生态有重叠，需要决策是"MCP Server 优先"还是"插件兼容优先"还是两条腿走路。

---

## 四、下一阶段路线建议

### 4.1 里程碑重组

现有 M-MVP 准入线已达成。建议新增：

| 里程碑 | 定义 | 包含节点 | 目标时间 |
|---|---|---|---|
| **M-MVP+1 可辨的 Agent** | 开箱得到一个有情绪、有口吻、能装插件、多模态可用的 Bot | Q2 + Q3(不含 MCP Client) + Q4 + Q5 + Q6 + C-N1 复核 | 1.5-2 周 |
| **M-MVP+2 全平台 + 可编排** | 微信可接 + Workflow 能跨 Agent + 默认 flag 智能启用 | O4 微信 + P5 agent:* + Feature flag 调整 + Docker 工件 | 2-3 周 |
| **M-4 可商业化** | 多租户真实接线 + 插件隔离 + 生产部署基线 | O1 routes_tenants + O2 loader 隔离 + 部署工件 + 集成/E2E 测试 | 1 个月 |

### 4.2 执行顺序建议

**第一周（按顺序）**：
1. C-N1 事件 SSE 安全复核（0.5-2h，安全不等人）。
2. Q2 人格注入器激活（4h，最小改动立刻可见）。
3. Q5 WebUI 三个硬伤（4h，改善管理体验）。
4. Q6 SubAgent 补漏（4h，治理可信）。
5. IO 异步化 + SecretStore 接入（前一轮 R3-3/R3-4，共 3h，顺手清债）。

**第二周**：
6. Q4 多模态工具注册 + 计量 + magic-byte（8h）。
7. Q3 Native SDK 接线 + AstrBot/MaiBot 桥接 + EnableMatrix（12h，同步把兼容层插件纳入子进程隔离）。
8. MCP Server 启动点 + stdio 模式（4h）。

**第三周及以后**：
9. O4 微信适配器真实收发。
10. P5 agent:* 路由。
11. Feature flag 默认值调优 + Docker 工件。
12. O5/S6 视频端点选型后补实现。

### 4.3 架构级风险提示

1. **"代码就位、硬编码 None"的反模式正在蔓延**：Q2/Q3 注入器/Native SDK/MCP Server/Proactive 生产者都属于这种"写了但没接上"的状态。后续新增功能务必遵循"写好即接线、默认能开即开"的原则，避免半成品越积越多。
2. **兼容层插件安全边界不够**：AstrBot/MaiBot 插件直接 exec_module 在宿主进程，等于放弃了 PluginIsolationHost 的隔离承诺。在 Q3 接线时必须同步迁移，否则将来出安全事件没法解释。
3. **services 字典是定时炸弹**：跨几十个文件传递 `dict[str, Any]`，重构时一旦改 key 名就是全仓 AttributeError。建议在 MVP+1 结束后立刻做 ServiceContainer 强类型化，越晚改越贵。
4. **测试金字塔失衡**：1362 单测但 0 个真正的端到端测试（Playwright 环境性 ERROR）。Q2-Q6 激活过程中每个节点必须配至少 1 个集成测试（启动完整 AgentManager 跑一轮消息），否则主链路接线失败发现不了。
5. **Feature flag 与文档漂移风险**：ROADMAP/PROGRESS/AGENTS 三个文档目前状态更新及时，但如果 Q2-Q6 激活后不及时同步，下个评审人看到的仍是"未开始"。每次激活一个节点必须同 PR 改文档。

---

## 五、结论

ISAC 已经从"建地基"阶段走到了"接开关"阶段。框架的架构分层（Control/Data 面分离、Channel/Provider/Plugin/Memory/Runtime/Agent 六大子系统、Mesh 协作模型）是健康的，没有需要推翻重来的部分。

**接下来 2-3 周的核心动作**是把已经写好但硬编码为 None / 默认关闭的能力（人格注入、插件注册、MCP Server、多模态工具、主动任务）一个一个激活并接入主链路，同时把微信适配器、WebUI 假数据、SubAgent 用量这几处"最后一英里"填完。架构层面不需要新增大模块，主要工作是接线 + 修 TODO + 清架构债。

建议先从 Q2 和 Q5 起步——这两个改动最小、收益最直观，做完之后立刻能"看出 ISAC 是个有情绪、有管理面板的产品"，为后续更大的接线工作建立信心和反馈环。

---

*评审: Doubao Seed Evolving · 2026-07-29*
