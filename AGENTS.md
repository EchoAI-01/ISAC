# AGENTS.md — ISAC 项目协作指南

> 面向接手开发的 AI / 工程师的一页纸上下文。先读本文件,再按需深入 `docs/` 下的设计文档。
> 本文件保留在根目录以便 AI 编码工具自动加载;进度、规范、计划等详细内容集中在 `docs/`。

## 项目状态

**当前定位**: **T 开箱可用轮 T1/T2/T4 已完成 (2026-08-04), 转入前后端分离开发 (后端先行)**。**1568 单元/集成测试全绿、ruff/mypy 全绿 (2026-08-15 实测)**。背景链: 2026-07-31 首次真机冒烟推翻"MVP 已达成"(私聊被门控静默 WAIT、WebUI 开箱不可用、必须手写配置才能启动) → 新增 T 开箱可用轮 → **T1 开箱能对话** (门控私聊无条件触发 + 未回复可观测 + 占位 key 检测)、**T2 零配置启动** (默认配置内置 + 首启建 data 目录)、**T4 错误可诊断** (401/429 中文可操作提示 + `/health` 聚合 + `/logs/tail` 实时日志 SSE) 已完成并附真机冒烟证据。**T3 按前后端分离重定义**: 后端先交付控制面开箱 + setup/auth API (FE0 API 契约冻结 → FE1 CORS/跨源认证/静态托管降级 → T3-backend), 前端独立项目 (F1-F4) 在 API 基线冻结后启动, 决策见 `ARCHITECTURE.md` ADR-012。更早轮次 (A-K 基础体系 / P0-P2 主链路接线 / Q0-Q2 MVP 收尾 / S1-S7 骨架激活) 均已交付; 2026-07-28/29 两轮评审遗留项已整合进 `DEVELOPMENT_PLAN.md` (架构债清单), Review 报告与 S 轮 HANDOFF 已删除 (2026-08-15 文档整合)。

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

后端代码工作已基本收尾: 阶段 0 / FE0 / FE1 / T3-backend / T1/T2/T4 / T6 / R1-R6 全部完成, R7 代码部分完成 (P3/P4/P5 集成测试补齐 + RELEASE_AUDIT 取证 + QUICKSTART); N1b/N1c/N1d 三轮全量代码审查修复清偿完毕 (Fix-37~137, Critical/Major/Minor 代码级清零) + N1e 全局配置持久化与热重载落地; 全量 2098 测试通过、ruff/mypy 全绿、红线全绿 (2026-08-18 实测)。**剩余项几乎全部是环境/凭据依赖与前端轨道**, 下一步行动见 [docs/DEVELOPMENT_PLAN.md](./docs/DEVELOPMENT_PLAN.md) **§三之三 下一步行动计划 (N1-N5)**:

1. **N1 文档与标记收敛** ✅ 已完成 (2026-08-18) — 三态标记收敛 + T7/R7 剩余项逐一挂 RELEASE_AUDIT §三 + README/AGENTS 同步。
2. **N2 环境准入项清偿** — Docker 冒烟 + browser CI 复核 (I 节点 85%→100%) + release_checklist 七段 + **24h soak** (需 docker daemon/浏览器环境/真实 LLM key)。
3. **N3 T5 真实 IM 验收** (外部阻塞) — 凭据准备清单先行, OneBot 先行联调, 飞书/QQ 官方/wecom 逐个真机验证。
4. **N4 前端轨道启动** — API 基线已冻结 (FE0 openapi.json + FE1 CORS + T3-backend setup API + config schema 端点); 技术栈决策 → F1 登录/setup 向导 → F2 十域迁移 (完成后移除内置 WebUI) → F3 实时 → F4 插件市场 UI。
5. **N5 剩余架构债并行线** — services 强类型化 Z1 批 A+B 已完成 (50 键宽容属性 + 全局容器/per-Agent 面迁移, 棘轮 205→130; 批 C 剩 context.services 热路径与 control 路由面) / Z2 main.py 拆分已由 U2 收敛 / 同步 IO 异步化 / reload_config 差量更新。

**里程碑**: M-T1 ✅ → M-T2 后端段 ✅ (前端 F1/F2 落地即全达成) → M-T3 可接入 (N2+N3) → M-T4 可扩展 ✅ (R3+T6) → **M-GA** = N2 全过 + N3 至少一个平台真机通过 + F2 完成。GA 后进入 §四 GA 后开发计划 (V/X/Y/Z)。

**验收铁律**:任何节点声明完成必须附**真机部署证据**(命令 + 实际输出),不接受"单测通过"作为可用性证明。节点定义见 [docs/DEVELOPMENT_PLAN.md](./docs/DEVELOPMENT_PLAN.md) §三之三/§四,进度见 [docs/PROGRESS.md](./docs/PROGRESS.md)。

## 目录速查

见 [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) 六、目录结构;各目录职责边界见 [docs/DEVELOP.md](./docs/DEVELOP.md) 1.1。
