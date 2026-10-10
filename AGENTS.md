# AGENTS.md — ISAC 项目协作指南

> 面向接手开发的 AI / 工程师的一页纸上下文。先读本文件,再按需深入 `docs/` 下的设计文档。
> 本文件保留在根目录以便 AI 编码工具自动加载;进度、规范、计划等详细内容集中在 `docs/`。

## 项目状态

**当前定位**: **后端功能与架构演进完成, 最小实例运行双向真机验证 (2026-10-10)** —— A-K 基础体系 / P0-P2 主链路接线 / Q0-Q2 MVP 收尾 / S1-S7 骨架激活 / T1-T7 / R1-R6 / FE0-FE1+T3-backend / U0-U9 全部交付; N1b~N1e 三轮全量审查清偿 (Fix-37~137) + 2026-08-19 加固轮 (会话锁/幂等去重/压缩写侧/成本闭环/U4 绑定等) + 2026-10-10 最小实例修复 (CI build/docker 修复后 **CI 5/5 全绿**, 源码 + Docker compose 双向 /health 真机通过)。全量 **2346 测试通过**、ruff/mypy/红线全绿 (2026-10-10 实测)。2026-07-31 真机冒烟推翻"MVP 已达成"的教训仍为验收铁律之源; T1 开箱能对话 / T2 零配置启动 / T4 错误可诊断 均已修复并有真机证据。T3 按前后端分离重定义 (ADR-012): 后端段完成, 前端 F1-F4 独立项目待启动。

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

后端代码工作已收尾 (2026-08-16~10-10): 阶段 0 / FE0 / FE1 / T3-backend / T1/T2/T4 / T6 / R1-R6 / U0-U9 全部完成; N1b/N1c/N1d 三轮全量审查修复 (Fix-37~137) + N1e 全局配置持久化热重载 + 2026-08-19 加固轮 + 2026-10-10 最小实例修复; 全量 **2346 测试通过**、ruff/mypy (299 源文件)/红线全绿、CI check/browser/catalog-drift/build/docker 5/5 全绿 (2026-10-10 实测)。**剩余项为环境/凭据依赖与前端轨道**, 下一步行动见 [docs/DEVELOPMENT_PLAN.md](./docs/DEVELOPMENT_PLAN.md) **§三之三 下一步行动计划 (N1-N5)** 与 [docs/PROGRESS.md](./docs/PROGRESS.md):

1. **N1 文档与标记收敛** ✅ 已完成 (2026-08-18; 2026-10-11 全库二次收敛: 88 项漂移勘误, 见 docs/PROGRESS.md)。
2. **N2 环境准入项清偿** — **Docker 冒烟 ✅ (2026-10-10: compose healthy + 宿主 `/health` 200 + CI docker job 绿)、browser CI 复核 ✅ (CI 真跑 2 passed)**; 剩 release_checklist 发版段 (版本号/标签/回滚, 发版时执行) + **24h soak** (需真实 LLM key 与长时运行环境)。
3. **N3 T5 真实 IM 验收** (外部阻塞) — 凭据准备清单先行, OneBot 先行联调, 飞书/QQ 官方/wecom 逐个真机验证。
4. **N4 前端轨道启动** — API 基线已冻结 (FE0 openapi.json + FE1 CORS + T3-backend setup API + config schema 端点); 技术栈决策 → F1 登录/setup 向导 → F2 十域迁移 (完成后移除内置 WebUI) → F3 实时 → F4 插件市场 UI。开工前建议先补 API 基线缺口 (生产挂载路径未入基线/securitySchemes 缺失/config schema 仅 3 键, 见 2026-10-10 审计)。
5. **N5 剩余架构债并行线** — services 强类型化 Z1 批 A+B+C 已完成 (棘轮 205→35) / Z2 main.py 拆分已由 U2 收敛 / 剩同步 IO 异步化 (插件解压/配置写盘) 与 reload_config 差量更新 (观察项); 另有 2026-10-10 审计登记的代码缺陷批次 (入站去重键缺会话维度、tools_policy 非法档位 fail-open、压缩 GC 与摘要输入不一致、压缩摘要排序、插件 reload 绕过 plugins_allow/deny) 待修。

**里程碑**: M-T1 ✅ → M-T2 后端段 ✅ (前端 F1/F2 落地即全达成) → M-T3 可接入 (N2 大部已过, 剩 soak/发版段; N3 待凭据) → M-T4 可扩展 ✅ (R3+T6) → **M-GA** = N2 全过 + N3 至少一个平台真机通过 + F2 完成。GA 后进入 §四 GA 后开发计划 (V/X/Y/Z)。

**验收铁律**:任何节点声明完成必须附**真机部署证据**(命令 + 实际输出),不接受"单测通过"作为可用性证明。节点定义见 [docs/DEVELOPMENT_PLAN.md](./docs/DEVELOPMENT_PLAN.md) §三之三/§四,进度见 [docs/PROGRESS.md](./docs/PROGRESS.md)。

## 目录速查

见 [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) 六、目录结构;各目录职责边界见 [docs/DEVELOP.md](./docs/DEVELOP.md) 1.1。
