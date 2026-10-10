# ISAC 技术路线图 (ROADMAP)

> 本文件是 ISAC 的**技术路线全景图**:按阶段串起已完成能力与待建能力,给出每个"进度 0"能力的目标形态、验收标准与依赖关系。
> 节点定义与验收细则以 [DEVELOPMENT_PLAN.md](./DEVELOPMENT_PLAN.md) §四为准,进度以 [PROGRESS.md](./PROGRESS.md) 为唯一事实源。本文件只描述**方向与阶段划分**,不重复维护进度。
>
> 最近更新: 2026-10-11(状态表按 docs/PROGRESS.md 重校准: 阶段 1-6 已完成收敛; 阶段 7-9 后端段基本完成, 当前关键路径 = N2 环境准入 / N3 真实 IM 验收 / N4 前端轨道, 见 DEVELOPMENT_PLAN §三之三; T 开箱可用轮 T1/T2/T4 自 2026-08-04 起)
>
> ⚠️ 本文件的阶段状态表为**摘要视图**, 与 PROGRESS.md 不一致时**以 PROGRESS.md 为准**。

## 一、阶段总览

ISAC 的能力按阶段推进。截至 2026-10-11: **阶段 1-6 的核心实现与主链路接线均已完成** —— 拟人化地基 (L) / 协作深化 (M) / 记忆深化 (N) / 企业化 (O) 由 P1/P2、S 骨架轮与 R 节点收敛;MVP 收尾 (Q0-Q6) 全部收敛升 `[x]`。阶段 7 (T 开箱可用)、阶段 8 (R 功能广度) 与阶段 9 (FE 前后端分离) 为当前主线: 后端代码工作已基本收尾, **当前关键路径 = N2 环境准入项清偿 → N3 真实 IM 凭据验收 → N4 前端轨道 (F1-F4)** (见 DEVELOPMENT_PLAN §三之三)。状态表以 docs/PROGRESS.md 为准。

| 阶段 | 主题 | 覆盖节点 | 状态 |
|------|------|---------|------|
| **阶段 -1** | 可运行闭环 | A-K (稳定化 K1-K8) | ✅ 已达可运行完成度(不等于 MVP 可用,见阶段 6) |
| **阶段 0** | 可观测性 + 文档体系 | 可观测性增强(横切) + 文档 | ✅ 已落地 |
| **阶段 1** | 拟人化地基 | L1-L5 | ✅ 已接线 (P1, 2026-07-27):debounce/wait/打断/主动任务/恢复全部进主链路 |
| **阶段 2** | 协作深化 | M1-M2 (路由 Mesh) | ✅ 已接线 (P2, 2026-07-27):observer/candidate + 4 A2A 工具真实可用 |
| **阶段 3** | 记忆深化 | N1-N3 (MemoryItem/治理/身份) | ✅ 完成 (2026-08-16 收敛):N2 治理完整接入生产;**S3 激活图谱召回 (mentioned_in 边 + Reranker provider 注入, 2026-07-28)**;**S4 激活身份归一控制面 (bind/conflicts/resolve + main/server 注入, 2026-07-28)**;N1 MemoryItem 边界文档化 (热路径继续用 MemoryHit);实体关系图抽取层转 GA 后 Y1 |
| **阶段 4** | 企业化与平台扩展 | O1-O5 (多租户/隔离/编排/平台/视频) | ✅ 主体完成 (2026-08-16 收敛):O1/O2/O3 经 R6 收敛 (routes_tenants+TenantManager / loader 隔离核验满足 / Workflow action_handler + agent: 入口决策落地);**S7 激活飞书 + QQ 官方 (2026-07-28)**;微信 wecom 已实现 (mp 公众号骨架);剩微信 mp 公众号 (V3)、O5 视频生成端点 (V2, 选型暂缓)、Slack (V4) 留 GA 后 |
| **阶段 5** | 主链路接线与激活 | P0-P5 | ✅ 全部完成 (2026-08-16 收敛):P0/P1/P2 完成 (2026-07-27);**P3/P4/P5 经 S3/S4/S5 激活 + R6/R7 收敛升 `[x]`**:图谱召回/身份归一控制面/Workflow action_handler + 声明式加载;P3 剩通用实体关系图转 GA 后 Y1 |
| **阶段 6** | MVP 收尾 | Q0-Q6 | ✅ 全部完成:Q0/Q1/Q2 完成 (2026-07-27/29);**Q3-Q6 经 R3/R1/R2 收敛, 2026-08-16 升 `[x]`** (插件生态 / 多模态计量 / WebUI 控制面 / SubAgent 用量) |
| **阶段 7** | **开箱可用 (最高优先级)** | T1-T7 | 🟡 T1/T2/T4 完成 (2026-08-04, 均附真机冒烟证据);**T6 插件市场 ✅ 完成 (2026-08-16)**;T3 按前后端分离重定义 (后端段见阶段 9);T5 真实 IM 验收待凭据 (N3);T7 分发运维代码可做部分完成 —— **Docker 冒烟/browser CI 2026-10-10 已过**, 24h soak/真人复现待环境 (N2) |
| **阶段 8** | 功能广度 (原阶段 7) | R1-R7 | ✅ R1-R6 完成 (2026-08-16):收敛 Q3-Q6/P3-P5 剩余 + 需求缺口 (行话学习/中期记忆/Session 持久化/密钥安全);R7 集成测试代码可做部分完成 (19 例 + RELEASE_AUDIT 取证), 环境准入项挂 N2 |
| **阶段 9** | **前后端分离 (后端先行)** | FE0/FE1/T3-backend + F1-F4 | 🟡 后端段完成 (2026-08-16):FE0 API 契约冻结 (OpenAPI 基线归档) + FE1 CORS/跨源认证/内置 WebUI 静态托管降级 + T3-backend 控制面开箱 (control 默认开 + 首登强制设密码 API + 配置 Schema 端点);前端独立项目 F1-F4 待启动 (N4) |

图例: ✅ 已完成(交付) · 🟡 核心实现完成待接线 / 进行中 · ⬜ 未开始(仅设计蓝图)

## 二、阶段依赖关系

```
阶段 -1 可运行闭环 (K1-K8)
        │
        ├── 阶段 0 可观测性 + 文档 ────────────┐ (横切,支撑其后所有阶段的排查)
        │                                      │
        └── 阶段 1 拟人化地基 (L1→L2→L3→L4→L5) │
                    │                          │
                    ├── 阶段 2 协作深化 (M1→M2)─┤ (M2 依赖 N 记忆)
                    │                          │
                    ├── 阶段 3 记忆深化 (N1→N2→N3)
                    │                          │
                    └── 阶段 4 企业化 (O1-O5)───┘ (O3 Workflow 依赖 L 运行时 + J4 SubAgent)
                                       │
        阶段 5 主链路接线与激活 (P0→P1;P2/P3→P4;P5) ── 把阶段 1-4 的 [~] 能力接入主链路
                                       │
        阶段 6 MVP 收尾 (Q0/Q1 不依赖阶段 5,可并行/优先;Q2-Q6 独立) ── 补齐阶段 5 未覆盖的 MVP 必需缺口
```

**关键路径 (2026-10-11)**: L1-L5 拟人化地基与阶段 2-6 均已实现并接线收敛 (P1/P2/S*/R*), 不再是瓶颈 —— wait/主动/打断/debounce 等拟人行为均已接入生产主链路 (`conversation.enabled` 开关)。阶段 7-9 的后端段 (T1/T2/T4/T6、T3-backend、FE0/FE1、R1-R6、R7 代码部分) 已完成; **当前关键路径 = N2 环境准入项清偿 (Docker 冒烟/browser CI 已过; release_checklist/24h soak 待环境) → N3 真实 IM 凭据联调 (T5) → N4 前端轨道 (F1-F4)**, 三者相对独立可并行推进, 定义见 DEVELOPMENT_PLAN §三之三。

## 三、"进度 0" 能力清单:目标形态与验收

下列能力此前"连框架都没有"(grep 零匹配或仅设计蓝图)。现 **L/M/N/O 14 子节点**均已交付:L1-L5 由 P1 接线、M1-M2 由 P2 接线、N1-N3 经 S2/S3/S4 与 P3/P4 收敛 (2026-08-16)、O1-O3 经 S5/R6 收敛;O4 飞书/QQ 官方/wecom 已实现 (剩微信 mp 公众号, GA 后 V3)、O5 只差视频生成真实端点 (选型暂缓, GA 后 V2)。每项给出**目标形态**(建成后长什么样)与**验收要点**;"状态"列为实测。

### 阶段 1 — 拟人化地基 (L)

| 能力 | 目标形态 | 验收要点 | 本轮状态 |
|------|---------|---------|---------|
| **L1 ConversationRuntime** | 每个 (agent_id, session_id) 一个运行时,持有消息缓存、状态机、等待/主动/打断状态 | 状态机转移正确;registry 按会话隔离且有 FIFO 上限;`enabled=False` 零行为变化 | ✅ 已交付 (P1 接线, 2026-07-27) |
| **L2 Wait 闭环** | `wait` 工具注册 `WaitState`,由消息/超时/主动任务结束并回填工具结果;连续消息 debounce 合并 | 三条结束路径都能唤醒;回填说明实际等待时长;静默窗口内消息合并为一次触发 | ✅ 已交付 (P1 接线, 2026-07-27) |
| **L3 主动任务调度** | `ProactiveTaskQueue` 按优先级+冷却驱动,唤醒会话发起强制话轮 | 主动发言必带 source/intent/reason;冷却/频率边界防刷屏;来源经鉴权 | ✅ 已交付 (P1 接线, 2026-07-27) |
| **L4 Planner 打断** | thinking 期间新消息可打断当前规划,抑制旧回复,下一轮 Prompt 提示"被打断" | 单轮打断次数受限;旧回复被抑制;打断提示注入 Prompt | ✅ 已交付 (P1 接线, 2026-07-27) |
| **L5 上下文恢复** | 重启后拟人状态可恢复到合理起点 (标为终止/复位,不续跑旧进度) | 未决 wait/打断标记/主动任务可持久化并恢复 | ✅ 已交付 (P1 接线, 2026-07-27) |

### 阶段 2 — 协作深化 (M)

| 能力 | 目标形态 | 验收要点 | 状态 |
|------|---------|---------|------|
| **M1 observer/candidate 路由** | Agent 可为旁听 (只入记忆不回复) 或候选 (多 Agent 竞争,仲裁选回复者) | 路由决策可解释、可审计;observer 记忆旁路正确 | ✅ 已交付 (P2 接线, 2026-07-27) |
| **M2 handoff/notify/memory_query** | Agent 间显式移交会话、发通知、跨 Agent 查记忆 | 全部经 InterAgentLink ACL 授权;动作可审计 | ✅ 已交付 (P2 接线, 2026-07-27) |

### 阶段 3 — 记忆深化 (N)

| 能力 | 目标形态 | 验收要点 | 状态 |
|------|---------|---------|------|
| **N1 统一 MemoryItem** | episodic/profile/jargon 统一到一个契约 (类型+载荷+元数据+命名空间) | 存储/检索/注入围绕它展开;迁移不破坏既有数据 | ✅ 已收敛 (MemoryItem 边界文档化, 热路径继续用 MemoryHit; R7 集成测试) |
| **N2 记忆治理** | 冻结/保护/纠错/删除记忆条目 | 操作经权限校验并审计;纠错保留可追溯历史 | ✅ 已完整接入生产 (冻结/保护/纠错/删除 + 权限校验/审计) |
| **N3 身份归一** | 跨平台同一用户归一到统一 identity | 归一规则可配置;冲突可人工裁决;记忆按归一身份聚合 | ✅ 已收敛 (S4 身份归一控制面 + P4 集成测试, 2026-08-16) |

### 阶段 4 — 企业化与平台扩展 (O)

| 能力 | 目标形态 | 验收要点 | 状态 |
|------|---------|---------|------|
| **O1 多租户/组织隔离** | Agent/记忆/配置/用量按 organization 隔离 | 跨租户不可见;控制面按租户鉴权 | ✅ 经 R6 收敛: routes_tenants + TenantManager (SQLite) + tenant:read/write scope;数据面纵深留后续设计 |
| **O2 插件进程级隔离** | 插件从进程内兼容层升级为进程级隔离 | 资源与故障不影响主进程;插件崩溃可恢复 | ✅ loader 子进程隔离已满足 (R6 核验: `_should_isolate`/`_load_isolated`/崩溃重启);兼容层进程化留架构债 (Z3) |
| **O3 Workflow 编排** | 声明式多步骤编排 (串/并/条件/重试),步骤可跨 Agent/工具 | 执行可观测、可恢复 | ✅ 经 R6 收敛:S5 action_handler (tool: 路由 ToolRegistry.execute) + 声明式加载 + condition_evaluator + routes_workflows 挂载;agent: 工具入口决策落地选 B (文档化不做) |
| **O4 平台扩展** | 新增微信/Slack/飞书等 Channel 适配器 | 复用 Channel 抽象;媒体/富文本按平台声明适配 | ✅ **飞书 + QQ 官方 + 企业微信 (wecom) 已实现** (S7, 2026-07-28;AES-256-CBC/Ed25519 字节序核对自官方文档;微信 mp 公众号骨架留 V3);不引入 lark-oapi/botpy SDK, 用 httpx+uvicorn+cryptography 既有依赖 |
| **O5 Video Provider** | 视频理解/生成 Provider 真实接入 | 经能力目录与 ModelRouter 选择;结果走 ArtifactStore | 🟡 只差视频生成真实端点 (注册挂点就位:S6 骨架 `kind="video_gen"` default-off;`generate` 仍抛 NotImplementedError,端点选型暂缓待二次确认, GA 后 V2) |

### 阶段 6 — MVP 收尾 (Q)

2026-07-26 对照 `REQUIREMENTS.md` 十二条需求逐条代码取证(10 域并行 + 真实启动实测)发现的、**未被阶段 5(P0-P5)覆盖**但 MVP 必需的缺口。节点定义见 [DEVELOPMENT_PLAN.md](./DEVELOPMENT_PLAN.md) §四 Q。

| 能力 | 目标形态 | 验收要点 | 状态 |
|------|---------|---------|------|
| **Q0 开箱可触达与配置纠偏** | 拷贝 `config.sample.jsonc` 即可用 WebChat 零外部依赖聊天;Telegram/Discord 配置即生效 | 三平台注册分支;裸部署有默认路由;样例配置无死键;Docker 构建可复现;Windows 优雅关闭 | ✅ 完成 (2026-07-27) |
| **Q1 记忆写入回路与身份稳定化** | 每轮对话结束写入 episodic 记忆;定期/每 N 轮归纳人物画像与关系深度;Session/UserMapper 持久化 | 聊天→重启→检索命中;画像随互动加深;person_id 跨重启稳定 | ✅ 完成 (2026-07-27) |
| **Q2 人格差异化实现** | 不同 Agent 的 persona/情绪/表达风格在回复中肉眼可辨 | persona 文本进 System Prompt;Mood/ExpressionStyle/AttentionDrift 注入器实现+注册+更新回路 | ✅ 完成 (2026-07-29):`persona.description` 接入 `BaseIdentityInjector` + `MoodTracker` 挂 FINAL_RESPONSE 驱动 decay/update;三注入器真实逻辑 |
| **Q3 插件与 MCP 生态数据面接线** | 插件/AstrBot/MaiBot/MCP 注册的工具真实进入 Agent 的 ToolRegistry 并被 LLM 调用 | 共享工具/命令/注入器注册表落地;PluginManager 传入 EnableMatrix;MCP Client 按配置连接 | ✅ 由 R3 收敛 (2026-08-16):共享注册表 + AstrBot/MaiBot 桥接 + MCPClient 生产接线 |
| **Q4 多模态工具注册与计量收尾** | 配置好 vision/STT/TTS/生图 Provider 后,Agent 能直接使用对应工具且用量可查 | 6 个媒体工具注册进 ToolRegistry;出入站媒体链路可用;多模态用量计量埋点;价目表加载 | ✅ 由 R1 收敛 (2026-08-16):出入站闭环 + 6 个 `record_*` 计量 + `pricing.jsonc` + `model_capabilities_allow` |
| **Q5 WebUI 与控制面收尾** | WebUI 十域无占位假数据;MCP Server/Webhook 可作为自动化入口 | 插件页/SubAgent 路径/配置编辑 revision 修复;消费 SSE;MCP Server 启动点;Webhook 路由挂载 | ✅ 由 R2 收敛 (2026-08-16):真实 revision + SubAgent list-all + routes_webhooks + MCP Server 5 工具/启动点 |
| **Q6 SubAgent 用量与安全补漏** | SubAgent 时间线的用量/证据真实可信;委派受控 | supervisor 保存 usage/evidence;并发上限;受限策略补 deny delegate_task | ✅ 由 R2 收敛 (2026-08-16):ContextEnvelope 背景摘要真传 + evidence_refs 生成 (+ 并发信号量/受限 deny 此前已完成) |

## 四、里程碑

| 里程碑 | 内容 | 准入条件 |
|--------|------|---------|
| **M-α 可运行** | 常驻 + 真实 Provider + 持久化恢复 + E2E + 安全基线 | K1-K8 代码落地(已达成) |
| **M-0 可观测** | trace 贯穿 + 分级日志 + 文档体系 | 阶段 0 落地(已达成) |
| **M-1 会像人一样对话** | wait/debounce/主动/打断闭环可用 | ✅ 已达成 (P1 接线, 2026-07-27):L1-L5 + P0/P1 接线并按完成定义验收 |
| **M-2 会协作** | 旁听/候选路由 + Agent 间协作动作 | ✅ 已达成 (P2 接线, 2026-07-27):M1-M2 + P2 接线验收 |
| **M-3 会记住** | 统一记忆 + 治理 + 跨平台身份 | ✅ 代码达成 (2026-08-16 收敛):**S2 激活 (2026-07-28)** MemoryConsolidator 真实去重/剪枝/画像归纳;**S3 激活 (2026-07-28)** 图谱召回 mentioned_in 边 + Reranker provider 注入;**S4 激活 (2026-07-28)** 身份归一控制面 routes_identity (bind/conflicts/resolve) + main/server 注入;N2 治理完整接入生产 + P3/P4 集成测试 (R7);剩 P3 通用实体关系图抽取层留 GA 后 Y1 |
| **M-4 可商业化** | 多租户 + 隔离 + 编排 + 多平台 | ✅ 代码达成 (2026-08-16 收敛):**R6 收敛 O1/O2/O3** (routes_tenants + TenantManager / loader 隔离核验满足 / Workflow S5 action_handler + 声明式加载 + agent: 决策落地);**S7 激活 (2026-07-28)** 飞书 + QQ 官方平台适配器;剩微信 mp 公众号 (V3)、O5 视频 Provider 端点 (V2, 选型暂缓)、Slack (V4) 留 GA 后 |
| **M-MVP 最小可用产品**(新增) | 开箱可聊(WebChat 零依赖,Q0)+ 越聊越熟(记忆写入闭环,Q1)+ 拟人化基线可用(等待/打断/主动,P0/P1)+ 双 Agent 协作(P2) | ✅ **准入线代码达成 (2026-07-27)**:P0-P2 + Q0-Q1 全部完成并集成测试通过 (MVP Review 已启动)。**2026-07-28 骨架轮 S1-S5+S7 激活**:主动任务生产者/MemoryConsolidator/图谱召回/身份归一控制面/Workflow action_handler/飞书+QQ官方平台 全部填真实业务逻辑;S6 视频 Provider 暂缓。人设可辨(Q2, **已于 2026-07-29 完成接线**)/插件与 MCP 生态(Q3)/多模态(Q4)/WebUI 无假数据(Q5)/SubAgent 用量真实(Q6)延后到 MVP+1。**2026-07-29 代码复审校正 + Q2 落地**:Q3-Q6 均已部分接线而非未开始 (Q3 EnableMatrix+hooks 已接待 per-Agent 桥接/MCP、Q4 6 工具已注册待出入站/计量、Q5 Extensions/SSE/Usage 已接待 config/Webhook、Q6 大部分完成),微信 wecom 亦已实现;详见 PROGRESS.md 与 DEVELOPMENT_PLAN §四 Q |
| ~~**M-MVP 判定为已达成**~~ | ~~P0-P2 + Q0-Q1 + Q2~~ | ❌ **2026-07-31 真机冒烟推翻** —— 内部能力确实已接线,但按 `config.sample.jsonc` 部署后**发消息收不到回复**(`gating/system.py:174` 私聊被额外要求 `has_mention`,私聊 40 分 < 阈值 80 → 静默 WAIT),WebUI 因 `control.enabled: false` 也不可用。**进程能驻留 ≠ 产品可用**,不构成 MVP |
| **M-T1 装上就能聊**(真 MVP) | 部署 → 发消息 → 收到回复, 这条最短路径无条件走通 | **T1 + T2**:门控私聊修复 + 消息不静默吞 + 无 key 明确提示 + 默认配置内置(零文件启动)。**✅ 代码达成 (2026-08-04)**, 真机冒烟证据见对应 commit |
| **M-T2 可部署可管理** | 打开浏览器就能管理, 出错知道去哪修 | ✅ **后端段达成 (2026-08-16)**:T4 后端段 (401/429 可操作中文提示 + `/health` + 实时日志台) + T3 后端段 (FE0/FE1/T3-backend: 控制面默认开 + setup/auth API + 首登强制设密码 + `/config/schema`);剩前端 F1/F2 落地 (N4) 即全达成 |
| **M-T3 可接入真实 IM** | 真实账号收发, 不只是单测 | 🔜 待 N2+N3:+ **T5**:OneBot/NapCat 真机跑通 + 各平台连接状态回显 + 飞书/QQ官方/企业微信按凭据逐个联调(此前从未真机验证)。需用户提供凭据与联调窗口 |
| **M-T4 生态可扩展** | 插件能装、能用、免重启 | ✅ 已达成 (R3 + T6, 2026-08-16):插件桥接激活(否则装了也不触发)+ 市场一键安装 + 热重载 + 失败插件可重试 |
| **M-GA v1.0 正式版** | `REQUIREMENTS.md` 十二条全覆盖 + 可分发可长跑, 定位由 Alpha 升为可用版本 | 🔜 **前置大部分完成**:T7 代码可做部分 (Docker 冒烟/browser CI 2026-10-10 已过; release_checklist/24h soak 待环境) + R1/R2/R4/R5/R6 (多模态 / 控制面与 SubAgent / 记忆完整性 / 持久化与密钥 / 企业化) + R7 (P3/P4/P5 集成测试 19 例 + hook 真实触发补测 + I 节点升 100% + 十二条取证) + U0-U9 架构演进全过 + A+ 复评达标 (2026-08-18)。**剩余:N2 环境准入 (release_checklist 七段 + 24h soak) + N3 至少一个平台真机通过 + N4-F2 前端十域迁移** (见 DEVELOPMENT_PLAN §三之三) |

**验收铁律(2026-07-31 新增)**：任何里程碑声明达成,**必须附真机部署证据**(命令 + 实际输出),不接受"单测通过"作为可用性证明。这条铁律的由来见 [DEVELOPMENT_PLAN.md](./DEVELOPMENT_PLAN.md) §四 T 与 [MODULE_GUIDE.md](./MODULE_GUIDE.md) §二"第三道坎"。

**GA 后可选(不阻塞正式版)**：S6 视频 Provider 端点(用户暂缓选型)、微信 mp 公众号、Slack 适配器、主链路启用流式回复(Provider 层已闭环, 属体验增强)。

## 五、原则

1. **地基优先**: 先把被大量能力依赖的底座 (ConversationRuntime、可观测性) 搭好,再往上长业务。
2. **默认关闭接线**: 新能力先以 `enabled=False` 惰性接入主链路,确保对既有行为零影响,再逐步开启。详见 [MODULE_GUIDE.md](./MODULE_GUIDE.md)。
3. **实现完成 ≠ 交付**: 核心逻辑 + 单测(scaffolding / `[~]`)与**主链路接线**分离;未接入生产主链路不标 `[x]`,接线待办统一收敛在 [DEVELOPMENT_PLAN.md](./DEVELOPMENT_PLAN.md) §四 P 节点。
4. **文档即蓝图**: 每个阶段开工前,对应节点的 目标/验收/产出/依赖 必须先在 DEVELOPMENT_PLAN.md 定义清楚。

## 六、相关文档

- 节点定义与验收: [DEVELOPMENT_PLAN.md](./DEVELOPMENT_PLAN.md) §四
- 进度事实源: [PROGRESS.md](./PROGRESS.md)
- 拟人化运行时施工图: [HUMANLIKE_RUNTIME.md](./HUMANLIKE_RUNTIME.md)
- 路由与 Mesh 施工图: [ROUTING_AND_AGENT_MESH.md](./ROUTING_AND_AGENT_MESH.md)
- 记忆施工图: [MEMORY_DESIGN.md](./MEMORY_DESIGN.md)
- 模块开发范式: [MODULE_GUIDE.md](./MODULE_GUIDE.md)
- 可观测性用法: [LOGGING.md](./LOGGING.md)
