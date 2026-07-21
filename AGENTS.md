# AGENTS.md — ISAC 项目协作指南

> 面向开发 Agent 的项目上下文。先读本文档，再读根目录四份设计文档。

## 项目状态

**当前进度**: 框架骨架已搭建（架构 v3.0 全模块接口 + 部分基础实现），C1 OneBot 适配器已完成，处于 Phase 1 中期。

- 文档: [ARCHITECTURE.md](./ARCHITECTURE.md) v3.0（多 Agent）、[DEVELOP.md](./DEVELOP.md)、[SPECIFICATION.md](./SPECIFICATION.md)、[DEVELOPMENT_PLAN.md](./DEVELOPMENT_PLAN.md)
- 代码: 契约（数据模型/ABC/枚举/异常）已完成；业务逻辑以 `NotImplementedError("TODO(Day N): ...")` 标记

## 环境命令

```bash
uv sync --all-extras --dev   # 安装依赖（自动管理 Python 3.12+）
uv run pytest                # 运行测试
uv run ruff check .          # Lint (line-length 120)
uv run mypy isac/            # 类型检查
uv run python -m isac.main   # 启动（需要 data/config.jsonc + Provider 配置）
```

## 填充实现时的硬性规则

1. **TODO 标记**: 每个 `NotImplementedError` 带 `TODO(节点)`（如 `TODO(C1)` / `TODO(D5)`），对应 DEVELOPMENT_PLAN.md 的 SOW 节点，按依赖顺序实现。
2. **导入规则** (DEVELOP.md 1.2): `utils → provider → memory → persona → agent → gating → router → gateway → channel → commands → plugin → runtime → control → main`，单向无环；运行时实例注入替代跨层 import。
3. **契约不可改**: `core/types.py`、`core/events.py`、`core/exceptions.py`、各 ABC 的公开签名与 SPECIFICATION.md 一致；要改先改文档再改代码。
4. **多 Agent 规则** (DEVELOP.md 3.5): 禁止模块级单例保存 Agent 状态；记忆访问必须带 agent_id 命名空间；Channel 适配器不感知 Agent。
5. **错误处理** (SPECIFICATION.md 5.1): LLM 重试+回退、记忆失败降级、插件错误隔离、Injector 失败返回空串。
6. **编码规范** (DEVELOP.md 二): 类型注解齐全、async/await、structlog 结构化日志、docstring 中文。
7. **测试**: 核心模块 (agent/memory/gating) 覆盖率 ≥80%；单测在 `tests/unit/`，集成测试在 `tests/integration/`，fixtures 在 `tests/fixtures/`。
8. **文档同步**: 修改了文档中描述的结构/接口/流程，必须同步更新对应文档章节。

## 已实现 vs 待实现

| 状态 | 模块 |
|------|------|
| ✅ 已实现 | core/types·events·exceptions·constants/injector、EventBus、SessionManager/UserMapper(内存版)、SessionLockManager、MessageRouter+rules、GateDecision/IdleBackoff/FocusMode、AgentHooks、SystemPromptBuilder(频率控制)、ISACAgentLoop 主流程、ToolRegistry+ToolPermission、CommandRegistry、MemoryInjector 基类、PersonaManager(部分)、AgentManager、InterAgentBus(ACL)、ProviderManager(重试+回退)、ConfigMigrator、AstrBot 沙箱骨架、**OneBot 适配器**、Admin API 路由骨架、main.py 组装 |
| 🔲 待实现 | OpenAICompatProvider、SecretStore、记忆存储/检索全部、ReplyNecessityJudge、全部内置注入器逻辑、全部内置工具、Persona/Mood、插件三格式加载与兼容层、MCP Client/Server、Webhooks 推送、WebUI |

## 目录速查

见 ARCHITECTURE.md 六、目录结构。各目录职责边界见 DEVELOP.md 1.1。
