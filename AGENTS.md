# AGENTS.md — ISAC 项目协作指南

> 面向开发 Agent 的项目上下文。先读本文档，再读根目录四份设计文档。

## 项目状态

**当前进度**: Alpha — K1-K8 稳定化节点进行中 (K1-K7 已完成, K8 CI/Docker 准入进行中)。
框架骨架 + 真实 LLM Provider + 持久化恢复 + 安全基线 + 多 Agent E2E 已就位, 接近可用版本。

- 文档: [ARCHITECTURE.md](./ARCHITECTURE.md) v3.0（多 Agent）、[DEVELOP.md](./DEVELOP.md)、[SPECIFICATION.md](./SPECIFICATION.md)、[DEVELOPMENT_PLAN.md](./DEVELOPMENT_PLAN.md)，以及五份专项施工图：[HUMANLIKE_RUNTIME.md](./HUMANLIKE_RUNTIME.md)、[MEMORY_DESIGN.md](./MEMORY_DESIGN.md)、[ROUTING_AND_AGENT_MESH.md](./ROUTING_AND_AGENT_MESH.md)、[PLUGIN_COMPATIBILITY.md](./PLUGIN_COMPATIBILITY.md)、[CONTROL_PLANE_SPEC.md](./CONTROL_PLANE_SPEC.md)
- 代码: 契约 + 业务实现已完成; K1-K7 验收通过, K8 CI/Docker/浏览器测试门禁进行中

## 环境命令

```bash
uv sync --all-extras --dev   # 安装依赖（自动管理 Python 3.12+）
uv run pytest                # 运行测试 (K7 后含 467+ 用例)
uv run pytest --cov-branch --cov-fail-under=75  # K8 CI 门禁
uv run ruff check .          # Lint (line-length 120)
uv run mypy isac/            # 类型检查 (全绿)
uv build                    # K8 构建 wheel/sdist
uv run python -m isac       # 启动 (K1 后支持 SIGINT/SIGTERM 优雅关闭)
```

## 填充实现时的硬性规则

1. **TODO 标记**: 剩余 `NotImplementedError` 集中在 VectorStore/GraphStore experimental 桩 + 部分 commands 收尾; 大部分业务已实现。
2. **导入规则** (DEVELOP.md 1.2): `utils → provider → memory → persona → agent → gating → router → gateway → channel → commands → plugin → runtime → control → main`，单向无环；运行时实例注入替代跨层 import。
3. **契约不可改**: `core/types.py`、`core/events.py`、`core/exceptions.py`、各 ABC 的公开签名与 SPECIFICATION.md 一致；要改先改文档再改代码。
4. **多 Agent 规则** (DEVELOP.md 3.5): 禁止模块级单例保存 Agent 状态；记忆访问必须带 agent_id 命名空间；Channel 适配器不感知 Agent。
5. **错误处理** (SPECIFICATION.md 5.1): LLM 重试+回退、记忆失败降级、插件错误隔离、Injector 失败返回空串。
6. **编码规范** (DEVELOP.md 二): 类型注解齐全、async/await、structlog 结构化日志、docstring 中文。
7. **测试**: K7 后核心模块覆盖率 ≥75% + branch coverage; 单测在 `tests/unit/`，集成测试在 `tests/integration/` (K5 单 Agent + K6 多 Agent E2E)，fixtures 在 `tests/fixtures/` (FakeChannel + FakeLLMProvider)。
8. **文档同步**: 修改了文档中描述的结构/接口/流程，必须同步更新对应文档章节。

## 已实现 vs 待实现

| 状态 | 模块 |
|------|------|
| ✅ 已实现 | 全部 A-I 节点 + K1-K7 稳定化: ApplicationRuntime (TaskGroup + 优雅关闭)、OpenAICompatProvider (httpx + SSE + Tool Call + 429/5xx)、MetadataStore+FTS5+BM25、load_persisted_agents、原子配置写 (tmp+fsync+os.replace)、SecretStore AES-256-GCM、Webhook SSRF 防护、Session TTL+O(1) 索引、WebChat 队列有界、bash kill-wait、4 个内置命令接入状态机、PluginManager 接入 main |
| 🟡 K8 进行中 | CI cov-fail-under + branch coverage、wheel/sdist 构建 smoke、Docker build/health smoke、WebUI 浏览器测试 (Playwright)、README/AGENTS/CHANGELOG/版本号与实际能力一致 |
| 🔲 experimental | VectorStore (sqlite-vec 桩)、GraphStore (关系图桩)、MemoryConsolidator、MCP stdio 子进程高级生命周期优化、WebUI v2 (J3 设计已完成代码待实现)、多模态 Provider (J2)、模型用量计量 (J1)、任务进度报告 (D9) |

## 目录速查

见 ARCHITECTURE.md 六、目录结构。各目录职责边界见 DEVELOP.md 1.1。
