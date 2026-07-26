# AGENTS.md — ISAC 项目协作指南

> 面向接手开发的 AI / 工程师的一页纸上下文。先读本文件,再按需深入 `docs/` 下的设计文档。
> 本文件保留在根目录以便 AI 编码工具自动加载;进度、规范、计划等详细内容集中在 `docs/`。

## 项目状态

**当前定位**: Release Candidate v1.0.0-rc.1。框架骨架 + 真实 LLM Provider + 持久化恢复 + 安全基线 + 多 Agent 端到端 + 拟人化运行时 + 路由 Mesh + 记忆深化 + 企业化扩展全部就位, 1093 单测全绿。

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
uv run pytest                           # 运行测试 (467+ 用例)
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

A-K 已达可运行完成度 (J1-J4 + K1-K8 交付)。CR3 修复轮 (2026-07-26, 见 PROGRESS.md) 已接线: **向量召回** (pipeline 稠密召回+RRF, `memory.embedding` 配置即生效)、**多租户 O1** (`tenancy.enabled` 数据面谓词, 默认关闭)、**插件 on_load 生命周期**、控制面 sessions/memory/events 路由挂载; 并修复 bus notify 假成功、Workflow 引擎 fan-in、流式工具调用、调度器饿死等正确性缺陷。**L2-L5 / M1-M2 / N1-N3 核心逻辑 + 单测已实现,但主链路尚未接线** (标 `[~]`,默认关闭、生产路径无调用点);O2 插件默认加载路径仍无进程隔离 (隔离宿主机制已可用, 接管待做);图谱召回待接入。剩余工作:**P 主链路接线与激活** (P0 消息并发化 → P1 拟人化 → P2 Mesh → P3 检索深化(图谱) → P4 身份归一 → P5 企业化收尾)、**O4 平台扩展** (需二次确认平台: 飞书/微信/Slack)、**O5 视频生成 Provider** (需二次确认端点: Sora/Runway/Kling)、**MemoryConsolidator**、**I 节点复核**。定义见 [docs/DEVELOPMENT_PLAN.md](./docs/DEVELOPMENT_PLAN.md) §四 P 节点,进度见 [docs/PROGRESS.md](./docs/PROGRESS.md)。

## 目录速查

见 [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) 六、目录结构;各目录职责边界见 [docs/DEVELOP.md](./docs/DEVELOP.md) 1.1。
