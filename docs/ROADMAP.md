# ISAC 技术路线图 (ROADMAP)

> 本文件是 ISAC 的**技术路线全景图**:按阶段串起已完成能力与待建能力,给出每个"进度 0"能力的目标形态、验收标准与依赖关系。
> 节点定义与验收细则以 [DEVELOPMENT_PLAN.md](./DEVELOPMENT_PLAN.md) §四为准,进度以 [PROGRESS.md](./PROGRESS.md) 为唯一事实源。本文件只描述**方向与阶段划分**,不重复维护进度。
>
> 最近更新: 2026-07-28(S1-S5+S7 飞书+QQ官方激活完成, S6 视频 Provider 暂缓待端点选型)

## 一、阶段总览

ISAC 的能力分六个阶段推进。阶段 0/1 是"地基";阶段 1-4 各节点的**核心逻辑 + 单测已实现**,但多数**主链路未接线**(默认关闭、生产路径无调用点);为把这些能力接入同一主链路协同激活,新增 **阶段 5(P 节点)**。2026-07-26 对照 `REQUIREMENTS.md` 十二条需求逐条代码取证后,发现一批 MVP 必需但**未被 P0-P5 覆盖**的缺口(记忆写入回路、开箱可触达通道、人格差异化等),新增 **阶段 6(Q 节点)**;MVP 准入线见下方"四、里程碑"的 **M-MVP**。

| 阶段 | 主题 | 覆盖节点 | 状态 |
|------|------|---------|------|
| **阶段 -1** | 可运行闭环 | A-K (稳定化 K1-K8) | ✅ 已达可运行完成度(不等于 MVP 可用,见阶段 6) |
| **阶段 0** | 可观测性 + 文档体系 | 可观测性增强(横切) + 文档 | ✅ 已落地 |
| **阶段 1** | 拟人化地基 | L1-L5 | ✅ 已接线 (P1, 2026-07-27):debounce/wait/打断/主动任务/恢复全部进主链路 |
| **阶段 2** | 协作深化 | M1-M2 (路由 Mesh) | ✅ 已接线 (P2, 2026-07-27):observer/candidate + 4 A2A 工具真实可用 |
| **阶段 3** | 记忆深化 | N1-N3 (MemoryItem/治理/身份) | 🟡 N2 已接线;**S3 激活图谱召回 (mentioned_in 边 + Reranker provider 注入, 2026-07-28)**、**S4 激活身份归一控制面 (bind/conflicts/resolve + main/server 注入, 2026-07-28)**;N1 MemoryItem 边界文档化 (热路径继续用 MemoryHit) |
| **阶段 4** | 企业化与平台扩展 | O1-O5 (多租户/隔离/编排/平台/视频) | 🟡 O1 已接线;**S5 激活 Workflow 控制面 (action_handler + 声明式加载, 2026-07-28;剩 Agent 工具入口留 P5 决策)**;**S7 激活飞书 + QQ 官方 (Ed25519/AES 字节序核对自官方文档, 2026-07-28)**;微信保持骨架;O2/O3 剩 Agent 工具入口;O5 视频端点选型暂缓 (S6) |
| **阶段 5** | 主链路接线与激活 | P0-P5 | 🟡 P0/P1/P2 完成 (2026-07-27);**P3/P4/P5 子范围激活 (S3/S4/S5, 2026-07-28)**:图谱召回/身份归一控制面/Workflow action_handler + 声明式加载;剩 P3 通用实体关系图、P5 O1/O2 routes_tenants/loader 隔离模式、Agent 工具入口 |
| **阶段 6** | MVP 收尾 | Q0-Q6 | 🟡 Q0/Q1 完成 (2026-07-27);Q2-Q6 未开始 |

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

**关键路径**: 拟人化地基 L1 → L2(Wait 闭环)是最优先的后续开发,因为 wait/主动/打断/debounce 一切拟人行为都以 ConversationRuntime 为地基。阶段 2/3/4 之间相对独立,可按业务优先级并行排期。**当前关键路径已转移**:L1-L5 等核心实现已完成,下一步是 **阶段 5 P 节点**把 `[~]` 能力接入主链路 —— P0(消息并发化)→ P1(拟人化激活)最优先,P2-P5 可并行。**2026-07-26 新增关键路径分支**:**阶段 6 Q0(开箱可触达)与 Q1(记忆写入回路)不依赖 P0**,是"让产品能被摸到、越聊越熟"的最低门槛,建议与 P0 并行甚至优先于 P0 启动;Q2-Q6 各自独立,可按人力并行插入。

## 三、"进度 0" 能力清单:目标形态与验收

下列能力此前"连框架都没有"(grep 零匹配或仅设计蓝图)。现 **L/M/N/O 14 子节点**中 L2-L5/M1-M2/N1-N3/O1-O3 已完成**核心实现 + 单测**(标 `[~]`,主链路待接线 → §四 P 节点),O4/O5 未开始。每项给出**目标形态**(建成后长什么样)与**验收要点**;"本轮状态"列为实测。

### 阶段 1 — 拟人化地基 (L)

| 能力 | 目标形态 | 验收要点 | 本轮状态 |
|------|---------|---------|---------|
| **L1 ConversationRuntime** | 每个 (agent_id, session_id) 一个运行时,持有消息缓存、状态机、等待/主动/打断状态 | 状态机转移正确;registry 按会话隔离且有 FIFO 上限;`enabled=False` 零行为变化 | 🟡 核心 + 单测完成,主链路待接线(P 节点) |
| **L2 Wait 闭环** | `wait` 工具注册 `WaitState`,由消息/超时/主动任务结束并回填工具结果;连续消息 debounce 合并 | 三条结束路径都能唤醒;回填说明实际等待时长;静默窗口内消息合并为一次触发 | 🟡 核心 + 单测完成,主链路待接线(P 节点) |
| **L3 主动任务调度** | `ProactiveTaskQueue` 按优先级+冷却驱动,唤醒会话发起强制话轮 | 主动发言必带 source/intent/reason;冷却/频率边界防刷屏;来源经鉴权 | 🟡 核心 + 单测完成,主链路待接线(P 节点) |
| **L4 Planner 打断** | thinking 期间新消息可打断当前规划,抑制旧回复,下一轮 Prompt 提示"被打断" | 单轮打断次数受限;旧回复被抑制;打断提示注入 Prompt | 🟡 核心 + 单测完成,主链路待接线(P 节点) |
| **L5 上下文恢复** | 重启后拟人状态可恢复到合理起点 (标为终止/复位,不续跑旧进度) | 未决 wait/打断标记/主动任务可持久化并恢复 | 🟡 核心 + 单测完成,主链路待接线(P 节点) |

### 阶段 2 — 协作深化 (M)

| 能力 | 目标形态 | 验收要点 | 状态 |
|------|---------|---------|------|
| **M1 observer/candidate 路由** | Agent 可为旁听 (只入记忆不回复) 或候选 (多 Agent 竞争,仲裁选回复者) | 路由决策可解释、可审计;observer 记忆旁路正确 | 🟡 核心 + 单测完成,主链路待接线(P 节点) |
| **M2 handoff/notify/memory_query** | Agent 间显式移交会话、发通知、跨 Agent 查记忆 | 全部经 InterAgentLink ACL 授权;动作可审计 | 🟡 核心 + 单测完成,主链路待接线(P 节点) |

### 阶段 3 — 记忆深化 (N)

| 能力 | 目标形态 | 验收要点 | 状态 |
|------|---------|---------|------|
| **N1 统一 MemoryItem** | episodic/profile/jargon 统一到一个契约 (类型+载荷+元数据+命名空间) | 存储/检索/注入围绕它展开;迁移不破坏既有数据 | 🟡 核心 + 单测完成,主链路待接线(P 节点) |
| **N2 记忆治理** | 冻结/保护/纠错/删除记忆条目 | 操作经权限校验并审计;纠错保留可追溯历史 | 🟡 核心 + 单测完成,主链路待接线(P 节点) |
| **N3 身份归一** | 跨平台同一用户归一到统一 identity | 归一规则可配置;冲突可人工裁决;记忆按归一身份聚合 | 🟡 核心 + 单测完成,主链路待接线(P 节点) |

### 阶段 4 — 企业化与平台扩展 (O)

| 能力 | 目标形态 | 验收要点 | 状态 |
|------|---------|---------|------|
| **O1 多租户/组织隔离** | Agent/记忆/配置/用量按 organization 隔离 | 跨租户不可见;控制面按租户鉴权 | 🟡 核心 + 单测完成,主链路待接线(P 节点) |
| **O2 插件进程级隔离** | 插件从进程内兼容层升级为进程级隔离 | 资源与故障不影响主进程;插件崩溃可恢复 | 🟡 核心 + 单测完成,主链路待接线(P 节点) |
| **O3 Workflow 编排** | 声明式多步骤编排 (串/并/条件/重试),步骤可跨 Agent/工具 | 执行可观测、可恢复 | 🟡 **S5 激活 (2026-07-28)**:action_handler (tool: 路由 ToolRegistry.execute) + 声明式加载 + condition_evaluator;控制面 routes_workflows 已挂载;剩 Agent 工具入口 (P5 决策项) |
| **O4 平台扩展** | 新增微信/Slack/飞书等 Channel 适配器 | 复用 Channel 抽象;媒体/富文本按平台声明适配 | 🟡 **飞书 + QQ 官方激活 (S7, 2026-07-28)**:飞书 Webhook (AES-256-CBC 解密字节序核对自 open.feishu.cn 官方文档) + 出站 (tenant_access_token 缓存);QQ 官方 Ed25519 验签字节序核对自 bot.q.qq.com 官方文档 + 三类消息事件 (AT/GROUP_AT/C2C) + access_token 缓存;微信保持骨架;不引入 lark-oapi/botpy SDK, 用 httpx+uvicorn+cryptography 既有依赖 |
| **O5 Video Provider** | 视频理解/生成 Provider 真实接入 | 经能力目录与 ModelRouter 选择;结果走 ArtifactStore | 🟡 注册挂点就位(骨架轮 S6:`kind="video_gen"` default-off;`generate` 仍抛 NotImplementedError,端点暂缓选型待二次确认) |

### 阶段 6 — MVP 收尾 (Q)

2026-07-26 对照 `REQUIREMENTS.md` 十二条需求逐条代码取证(10 域并行 + 真实启动实测)发现的、**未被阶段 5(P0-P5)覆盖**但 MVP 必需的缺口。节点定义见 [DEVELOPMENT_PLAN.md](./DEVELOPMENT_PLAN.md) §四 Q。

| 能力 | 目标形态 | 验收要点 | 状态 |
|------|---------|---------|------|
| **Q0 开箱可触达与配置纠偏** | 拷贝 `config.sample.jsonc` 即可用 WebChat 零外部依赖聊天;Telegram/Discord 配置即生效 | 三平台注册分支;裸部署有默认路由;样例配置无死键;Docker 构建可复现;Windows 优雅关闭 | ✅ 完成 (2026-07-27) |
| **Q1 记忆写入回路与身份稳定化** | 每轮对话结束写入 episodic 记忆;定期/每 N 轮归纳人物画像与关系深度;Session/UserMapper 持久化 | 聊天→重启→检索命中;画像随互动加深;person_id 跨重启稳定 | ✅ 完成 (2026-07-27) |
| **Q2 人格差异化实现** | 不同 Agent 的 persona/情绪/表达风格在回复中肉眼可辨 | persona 文本进 System Prompt;Mood/ExpressionStyle/AttentionDrift 注入器实现+注册+更新回路 | ⬜ 未开始 |
| **Q3 插件与 MCP 生态数据面接线** | 插件/AstrBot/MaiBot/MCP 注册的工具真实进入 Agent 的 ToolRegistry 并被 LLM 调用 | 共享工具/命令/注入器注册表落地;PluginManager 传入 EnableMatrix;MCP Client 按配置连接 | ⬜ 未开始 |
| **Q4 多模态工具注册与计量收尾** | 配置好 vision/STT/TTS/生图 Provider 后,Agent 能直接使用对应工具且用量可查 | 6 个媒体工具注册进 ToolRegistry;出入站媒体链路可用;多模态用量计量埋点;价目表加载 | ⬜ 未开始 |
| **Q5 WebUI 与控制面收尾** | WebUI 十域无占位假数据;MCP Server/Webhook 可作为自动化入口 | 插件页/SubAgent 路径/配置编辑 revision 修复;消费 SSE;MCP Server 启动点;Webhook 路由挂载 | ⬜ 未开始 |
| **Q6 SubAgent 用量与安全补漏** | SubAgent 时间线的用量/证据真实可信;委派受控 | supervisor 保存 usage/evidence;并发上限;受限策略补 deny delegate_task | ⬜ 未开始 |

## 四、里程碑

| 里程碑 | 内容 | 准入条件 |
|--------|------|---------|
| **M-α 可运行** | 常驻 + 真实 Provider + 持久化恢复 + E2E + 安全基线 | K1-K8 代码落地(已达成) |
| **M-0 可观测** | trace 贯穿 + 分级日志 + 文档体系 | 阶段 0 落地(已达成) |
| **M-1 会像人一样对话** | wait/debounce/主动/打断闭环可用 | L1-L5 + P0/P1 接线并按完成定义验收 |
| **M-2 会协作** | 旁听/候选路由 + Agent 间协作动作 | M1-M2 + P2 接线验收 |
| **M-3 会记住** | 统一记忆 + 治理 + 跨平台身份 | **S3 激活 (2026-07-28)**:图谱召回 mentioned_in 边 + Reranker provider 注入;**S4 激活 (2026-07-28)**:身份归一控制面 routes_identity (bind/conflicts/resolve) + main/server 注入;**S2 激活 (2026-07-28)**:MemoryConsolidator 真实去重/剪枝/画像归纳;剩 P3 通用实体关系图、P4 集成测试 |
| **M-4 可商业化** | 多租户 + 隔离 + 编排 + 多平台 | **S5 激活 (2026-07-28)**:Workflow action_handler (tool: 路由) + 声明式加载;**S7 激活 (2026-07-28)**:飞书 + QQ 官方平台适配器;剩 O1 routes_tenants / O2 loader 隔离可选模式 / P5 Agent 工具入口;视频 Provider (O5/S6) 端点暂缓选型 |
| **M-MVP 最小可用产品**(新增) | 开箱可聊(WebChat 零依赖,Q0)+ 越聊越熟(记忆写入闭环,Q1)+ 拟人化基线可用(等待/打断/主动,P0/P1)+ 双 Agent 协作(P2) | ✅ **准入线代码达成 (2026-07-27)**:P0-P2 + Q0-Q1 全部完成并集成测试通过 (MVP Review 已启动)。**2026-07-28 骨架轮 S1-S5+S7 激活**:主动任务生产者/MemoryConsolidator/图谱召回/身份归一控制面/Workflow action_handler/飞书+QQ官方平台 全部填真实业务逻辑;S6 视频 Provider 暂缓。人设可辨(Q2)/插件与 MCP 生态(Q3)/多模态(Q4)/WebUI 无假数据(Q5)/SubAgent 用量真实(Q6)延后到 MVP+1,延后范围已在 AGENTS.md/PROGRESS.md 如实标注 |

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
