# AGENTS.md — ISAC 项目协作指南

> 面向接手开发的 AI / 工程师的一页纸上下文。先读本文件,再按需深入 `docs/` 下的设计文档。
> 本文件保留在根目录以便 AI 编码工具自动加载;进度、规范、计划等详细内容集中在 `docs/`。

## 项目状态

**当前定位**: 框架骨架 + 真实 LLM Provider + 持久化恢复(部分) + 安全基线已就绪, **1545 单测全绿 (134 文件)**; 2026-07-27 骨架轮 (S1-S7) 把 P3/P4/P5 与 O4/O5/MemoryConsolidator/proactive-ext 的**骨架 + 默认关闭接线锚点**搭齐 (default-off、零行为变化); **2026-07-28 S1-S5+S7 激活**: 主动任务生产者真实产出逻辑 + MemoryConsolidator 真实整合 + 图谱召回 mentioned_in 边 + 身份归一控制面 + Workflow action_handler + 飞书(AES-256-CBC 解密字节序核对自官方文档) + QQ 官方(Ed25519 验签字节序核对自官方文档) 适配器全部填真实业务逻辑。S6 视频 Provider 暂缓 (用户决定, 待端点选型确定后仿 image_gen 实现)。MVP 准入线 (P0-P2 + Q0-Q1) 的**内部接线**已达成,但 **2026-07-31 真机冒烟证明产品仍不可用**(见下方"剩余工作")。**2026-07-29 代码复审校正 + Q2 落地**: Q2-Q6 多为「部分接线」而非「未开始」,其中 **Q2 人格差异化当日已补齐接线并升级 `[x]`**(persona.description 接入 BaseIdentityInjector + 新增 MoodTracker 驱动 decay/update, 见 `isac/persona/mood_tracker.py`);剩 Q3 EnableMatrix+hooks 已接待 per-Agent 桥接/MCP/CLI、Q4 6 媒体工具已注册待出入站+计量、Q5 Extensions/SSE/Usage 已接待 config/SubAgent 表/Webhook、Q6 大部分完成仅剩背景摘要+evidence_refs; 微信 wecom 企业微信模式实为已实现并注册, 仅 mp 公众号骨架。S6 视频 Provider + S5 Agent 工具入口 (P5 决策) 待后续。MVP 收尾计划见 `docs/DEVELOPMENT_PLAN.md` Q 节点组与 `docs/ROADMAP.md` MVP 里程碑。

- 进度事实源: [docs/PROGRESS.md](./docs/PROGRESS.md)
- 文档导航: [docs/README.md](./docs/README.md)
- 需求清单: [docs/REQUIREMENTS.md](./docs/REQUIREMENTS.md)
- 变更记录: [CHANGELOG.md](./CHANGELOG.md)

## 核心文档

- 架构: [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md)(多 Agent v3.0 + ADR + 目录结构)
- 规范: [docs/SPECIFICATION.md](./docs/SPECIFICATION.md)(数据模型与接口契约,冻结)
- 开发: [docs/DEVELOP.md](./docs/DEVELOP.md)(目录/导入/命名/测试/安全规范)
- 模块指南: [docs/MODULE_GUIDE.md](./docs/MODULE_GUIDE.md)(scaffolding 框架先行范式,新增子系统必读)
- 计划: [docs/DEVELOPMENT_PLAN.md](./docs/DEVELOPMENT_PLAN.md)(节点 SOW/TODO/下一步,含 L/M/N/O)
- 路线: [docs/ROADMAP.md](./docs/ROADMAP.md)(阶段 0-4、里程碑、"进度 0" 能力目标形态)
- 运维: [docs/MAINTENANCE.md](./docs/MAINTENANCE.md)(排查树/备份/升级) · [docs/LOGGING.md](./docs/LOGGING.md)(日志分级/trace 贯穿)
- 专项施工图: [HUMANLIKE_RUNTIME](./docs/HUMANLIKE_RUNTIME.md) / [MEMORY_DESIGN](./docs/MEMORY_DESIGN.md) / [ROUTING_AND_AGENT_MESH](./docs/ROUTING_AND_AGENT_MESH.md) / [PLUGIN_COMPATIBILITY](./docs/PLUGIN_COMPATIBILITY.md) / [CONTROL_PLANE_SPEC](./docs/CONTROL_PLANE_SPEC.md)

## 环境命令

```bash
uv sync --all-extras --dev              # 安装依赖 (Python 3.12+)
uv run pytest                           # 运行测试 (用例数见 docs/PROGRESS.md)
uv run pytest --cov-branch --cov-fail-under=75   # CI 门禁
uv run ruff check .                     # Lint (line-length 120)
uv run mypy isac/                       # 类型检查 (全绿)
uv build                                # 构建 wheel/sdist
uv run python -m isac                   # 启动 (支持 SIGINT/SIGTERM 优雅关闭)
```

## 硬性规则

1. **契约不可改**: `core/types.py`、`core/events.py`、`core/exceptions.py` 及各 ABC 的公开签名与 `docs/SPECIFICATION.md` 一致;要改先改文档再改代码。
2. **导入规则** (DEVELOP 1.2): `utils → provider → memory → persona → agent → gating → router → gateway → channel → commands → plugin → runtime → control → main`,单向无环;跨层用运行时实例注入,不用 import。
3. **多 Agent 规则** (DEVELOP 3.5): 禁止模块级单例保存 Agent 状态;记忆访问必须带 agent_id 命名空间;Channel 适配器不感知 Agent。
4. **错误处理** (SPECIFICATION 5.1): LLM 重试+回退、记忆失败降级、插件错误隔离、Injector 失败返回空串。
5. **编码规范** (DEVELOP 二): 类型注解齐全、async/await、structlog 结构化日志、docstring 中文。
6. **测试**: 核心模块覆盖率 ≥75% + branch coverage;单测在 `tests/unit/`,集成测试在 `tests/integration/`,fixtures 在 `tests/fixtures/`。
7. **文档同步**: 改动了文档描述的结构/接口/流程,必须同步更新对应文档;进度只更新 `docs/PROGRESS.md`。

## 剩余工作

A-K 已达可运行完成度 (J1-J4 + K1-K8 交付)。CR3 修复轮 (2026-07-26, 见 PROGRESS.md) 已接线: **向量召回** (pipeline 稠密召回+RRF, `memory.embedding` 配置即生效)、**多租户 O1** (`tenancy.enabled` 数据面谓词, 默认关闭)、**插件 on_load 生命周期**、控制面 sessions/memory/events 路由挂载; 并修复 bus notify 假成功、Workflow 引擎 fan-in、流式工具调用、调度器饿死等正确性缺陷。**L2-L5 (P1 拟人化) / M1-M2 (P2 Mesh) 已接入生产主链路** (标 `[x]`,`conversation.enabled`/`mesh_role` 开关控制,默认关闭零行为变化);**N1-N3 部分接线** (N2 治理已生效含检索期软删除过滤, N1 边界文档化, N3 身份归一控制面 S4 已接);O2 插件默认加载路径仍无进程隔离 (隔离宿主机制已可用, 接管待做, 归 P5);图谱召回 S3 已接 `mentioned_in` 提及边 (通用实体关系语义图待后续)。

**2026-07-26 MVP 差距复核**(对照 `docs/REQUIREMENTS.md` 十二条需求逐条代码取证, 10 域并行验证 498 次代码检索 + 一次真实启动实测)进一步发现:一批标 `[x]` **已交付**的节点(D8/E4/F1-F3/H1/H2/J1-J4/K1-K4/K7)存在与其"完成定义"矛盾的**未接线子行为**(如 D8 人格系统的情绪/表达风格/注意力漂移注入器是未注册的空桩、F3 原生 SDK 的 register_tool/command/injector 在生产被硬编码为 `None`、H1 平台适配器仅 OneBot 被生产注册、J4 SubAgent 的用量/证据在 supervisor 层被丢弃),已逐条在对应节点下补记 **"2026-07-26 MVP 缺口复核"** 说明并指向修复它的 Q 节点;这些矛盾不影响该节点已实现的其余部分,但意味着"A-K 已达可运行完成度"不等于"MVP 各项能力真实可用"。

剩余工作分两条线,均定义于 [docs/DEVELOPMENT_PLAN.md](./docs/DEVELOPMENT_PLAN.md):
1. **P 主链路接线与激活**(§四 P 节点):P0 消息并发化 → P1 拟人化 → P2 Mesh(含 Link 细粒度 ACL) → P3 检索深化(图谱+Reranker) → P4 身份归一 → P5 企业化收尾。
2. **Q MVP 收尾**(§四 Q 节点,新增):补齐 P 节点未覆盖、但 MVP 必需的缺口 —— **Q1 记忆写入回路与身份稳定化**(最高优先级,检索链路全通但生产从未写入,未被任何 P 节点覆盖)、Q0 开箱可触达与配置纠偏、Q2 人格差异化实现、Q3 插件与 MCP 生态数据面接线、Q4 多模态工具注册与计量收尾、Q5 WebUI 与控制面收尾、Q6 SubAgent 用量与安全补漏。Q0/Q1 不依赖 P0,可与 P 节点并行甚至优先推进。

另有 **O4 平台扩展**(飞书 + QQ 官方已激活见 S7)、**O5 视频生成 Provider**(S6 用户决定暂缓, 待端点选型二次确认)、**MemoryConsolidator**(S2 已激活)、**I 节点复核** 独立于 P/Q, 可并行插入。**2026-07-27 骨架轮 (S1-S7)** 把 P3/P4/P5/O4/O5/MemoryConsolidator/proactive-ext 一次性补齐**骨架 + 默认关闭接线锚点**; **2026-07-28 S1-S5+S7 激活** 把骨架填成真实业务逻辑: S1 主动任务生产者真实产出 + memory 注入; S2 MemoryConsolidator run_once 三步真实整合 + llm 注入; S3 图谱召回 mentioned_in 边 + _graph_search 真实召回 + Reranker provider 注入 + MemoryItem 边界文档化; S4 身份归一控制面 routes_identity (bind/conflicts/resolve) + main/server 注入 + IdentityResolver.resolve_conflict; S5 Workflow action_handler (tool: 路由 ToolRegistry.execute) + 声明式加载 + condition_evaluator; S7 飞书 (AES-256-CBC 解密字节序核对自 open.feishu.cn 官方文档) + QQ 官方 (Ed25519 验签字节序核对自 bot.q.qq.com 官方文档) 适配器真实收发。⚠️ **2026-07-31 真机部署冒烟推翻了"MVP 已达成"**:此前各轮验收只跑单测 + 读代码,从未真机走用户旅程。实测按 `config.sample.jsonc` 部署后**发消息永远收不到回复且日志无任何错误**(根因 `gating/system.py:174` 私聊被额外要求 `has_mention`,私聊 40 分 < 阈值 80 → 静默 WAIT),`control.enabled: false` 使 **WebUI 开箱不可用**,且必须手写 JSONC 才能启动。**进程能驻留 ≠ 产品可用**。

剩余工作已重排为两组(定义见 `docs/DEVELOPMENT_PLAN.md` §四 T 与 §四 R):

1. **T 开箱可用轮(最高优先级)** —— 对标 AstrBot/MaiBot"部署完就能运行":**T1 开箱能对话(P0 阻断, 下一步立即做)** → T2 零配置启动(默认配置内置代码)→ T3 WebUI 开箱 + 首登强制设密码向导 → T4 错误可诊断(401/429 中文提示 + `/health` + 实时日志台)→ T5 真实 IM 接入验收(需用户凭据)→ T6 插件市场与热重载(依赖 R3)→ T7 分发运维 + 24h soak。
2. **R 功能广度轮(降级到 T 之后)** —— R1 多模态 · R2 控制面与 SubAgent · R3 插件与 MCP 桥接(**T6 前置**)· R4 记忆完整性 · R5 持久化与密钥 · R6 企业化 · R7 集成测试与发布准入。

**里程碑**:M-T1 装上就能聊(真 MVP, 约 1-2 轮)→ M-T2 可部署可管理(约 4-5 轮)→ M-T3 可接入真实 IM → M-T4 生态可扩展 → **M-GA 正式版(累计约 13-16 轮)**。GA 后可选: S6 视频 Provider 端点(暂缓)、微信 mp 公众号(wecom 已实现)、Slack、主链路流式。

**验收铁律**:任何节点声明完成必须附**真机部署证据**(命令 + 实际输出),不接受"单测通过"作为可用性证明。MVP 准入线(P0-P2 + Q0-Q1 完成)见 [docs/ROADMAP.md](./docs/ROADMAP.md) MVP 里程碑;节点定义见 [docs/DEVELOPMENT_PLAN.md](./docs/DEVELOPMENT_PLAN.md) §四,进度见 [docs/PROGRESS.md](./docs/PROGRESS.md)。

## 目录速查

见 [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) 六、目录结构;各目录职责边界见 [docs/DEVELOP.md](./docs/DEVELOP.md) 1.1。
