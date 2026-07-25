# AGENTS.md — ISAC 项目协作指南

> 面向接手开发的 AI / 工程师的一页纸上下文。先读本文件,再按需深入 `docs/` 下的设计文档。
> 本文件保留在根目录以便 AI 编码工具自动加载;进度、规范、计划等详细内容集中在 `docs/`。

## 项目状态

**当前定位**: 可运行(Alpha→接近可用)。框架骨架 + 真实 LLM Provider + 持久化恢复 + 安全基线 + 多 Agent 端到端已就位。

- 进度事实源: [docs/PROGRESS.md](./docs/PROGRESS.md)
- 文档导航: [docs/README.md](./docs/README.md)
- 需求清单: [docs/REQUIREMENTS.md](./docs/REQUIREMENTS.md)

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

D9/J1/J2/J3/J4 能力框架已落地;可观测性增强 (trace 贯穿 + 分级日志) 已横切落地。拟人化/协作/记忆/企业化四大节点 **L/M/N/O 全部 14 子节点框架已搭建 (scaffolding)**——契约 + 骨架类 + 惰性默认关闭接线就位,主链路零行为变化,各节点 `TODO(节点)` 标注挂接点,业务实现待续。experimental 桩见 VectorStore/GraphStore/Reranker/MemoryConsolidator。详见 [docs/PROGRESS.md](./docs/PROGRESS.md) 与 [docs/ROADMAP.md](./docs/ROADMAP.md)。

## 目录速查

见 [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) 六、目录结构;各目录职责边界见 [docs/DEVELOP.md](./docs/DEVELOP.md) 1.1。
