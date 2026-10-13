# AGENTS.md — ISAC 项目协作指南

> 面向接手开发的 AI / 工程师的一页纸上下文。先读本文件,再按需深入 `docs/` 下的设计文档。
> 本文件保留在根目录以便 AI 编码工具自动加载;进度、规范、计划等详细内容集中在 `docs/`。

## 项目状态

**当前定位**: **后端综合修复完成 (2026-10-13), 前端 F1-F2 已交付** —— A-K 基础体系 / P0-P2 主链路 / Q/S/T/R/U 全节点 / FE0-FE1+T3-backend / D1-D6 缺陷轮 / N4 API 基线补齐 / N5 清偿 / 富媒体二波 / soak 工具 / 凭据清单 全部交付; 2026-10-13 综合修复轮清偿 GitHub issues #6-#10 + review 缺陷 R1-R3 + 08-21 死路径遗留 L1-L5 (详见 docs/PROGRESS.md 与 CHANGELOG Unreleased), 全量 **2416 测试通过**、ruff/mypy (303 源文件)/红线/catalog 全绿。前端轨道: 脚手架 + F1 登录向导 + F2 十域迁移完成 (React 19 + Vite 8, 见 frontend/ 与 frontend/docs/PAGE_CONTRACT.md), 剩余 F3 实时深化 / F4 插件市场与写操作端到端联调。**提交人纯净性 (硬性规则 #9)**: 仓库全部提交统一署名 EchoAI-01; dependabot 已移除 (依赖升级手动), 分支保护拒绝 force push。环境/凭据依赖项待执行 (soak 执行 / 真机联调, 见 docs/IM_CREDENTIALS_CHECKLIST.md)。2026-07-31 真机冒烟推翻"MVP 已达成"的教训仍为验收铁律之源; T1/T2/T4 均有真机证据。

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
8. **提交署名固定** (2026-10-11 历史重写后立规): 本仓库全部提交统一署名 `EchoAI-01 <254134517+EchoAI-01@users.noreply.github.com>`。新克隆第一件事执行 `git config user.name "EchoAI-01" && git config user.email "254134517+EchoAI-01@users.noreply.github.com"` (仓库级)。2026-10-11 分支历史已整体重写 (统一 8 笔误署名提交, SHA 全变): 旧克隆必须 `git fetch origin && git reset --hard origin/main` 对齐 (有未推送提交先 `rebase --onto origin/main`), **禁止** 基于旧历史 merge 提交或 force push —— main/dev 均已开启分支保护拒绝 force push。
9. **提交人纯净性** (2026-10-13 仓库重建后立规): 仓库中不得出现账号以外的任何提交人/贡献者 (含 Chen/BOT/bot 署名)。执行面: ①全部提交署名 EchoAI-01 (含 CI 自动提交, 见 model-capabilities.yml); ②**禁用会产生提交/PR 的自动化**——dependabot.yml 已移除、仓库级 dependabot 安全更新与漏洞告警已关闭, 依赖升级一律手动; ③推送只用显式 refspec (`git push origin main` / `main:dev`), **禁止** `--all`/`--mirror` (防带出孤儿对象); ④合入外部 PR 前先核查作者身份 (fork 贡献者会进入贡献者图谱)。

## 剩余工作

**后端轨道已收官 + 2026-10-13 综合修复轮完成**: 阶段 0 / FE0 / FE1 / T3-backend / T1-T7 / R1-R7 / U0-U9 / D1-D6 缺陷轮 / N4 API 基线 / N5 架构债 (同步 IO 异步化 + reload_config 差量) / 富媒体二波 (飞书 image 出入站 + Discord 附件双向) / soak 采样工具 / 凭据清单 / issues #6-#10 + R1-R3 + L1-L5 死路径接线 (2026-10-13) 全部完成; 全量 **2416 测试通过**、ruff/mypy (303 源文件)/红线/catalog 全绿。**剩余项仅为环境/凭据依赖与前端深化**, 下一步行动见 [docs/DEVELOPMENT_PLAN.md](./docs/DEVELOPMENT_PLAN.md) **§三之三 下一步行动计划 (N1-N5)** 与 [docs/PROGRESS.md](./docs/PROGRESS.md):

1. **N1 文档与标记收敛** ✅ 已完成 (2026-08-18; 2026-10-11 全库二次收敛: 88 项漂移勘误, 见 docs/PROGRESS.md)。
2. **N2 环境准入项清偿** — **Docker 冒烟 ✅、browser CI 复核 ✅、CD 发布流水线 ✅、soak 采样工具 ✅ (2026-10-11 scripts/soak_sampler.py, 等真实 LLM key 即跑)**; 剩发版演练真跑 (release.yml workflow_dispatch, 发版时执行) + **24h soak 执行** (需真实 LLM key 与长时运行环境)。
3. **N3 T5 真实 IM 验收** (外部阻塞) — **凭据准备清单已交付 ([docs/IM_CREDENTIALS_CHECKLIST.md](./docs/IM_CREDENTIALS_CHECKLIST.md), 2026-10-11)**; OneBot 先行联调, 飞书/QQ 官方/wecom 逐个真机验证 (飞书联调顺带验证富媒体二波 image 链路)。
4. **N4 前端轨道** — **F1 登录向导 ✅ + F2 十域迁移 10/10 ✅ (2026-10-13, frontend/ isac-console: React 19 + Vite 8; tsc/eslint/vitest/build 全绿 + 浏览器真机冒烟十域全过)**; 剩 F3 实时深化 (useSse/EventStream 基础已有, Logs SSE 已活体验证) / F4 插件市场 UI / 写操作端到端联调 (见 PROGRESS 前端轮④清单)。
5. **N5 剩余架构债并行线** — **全部完成 (2026-10-11 后端收尾轮; 2026-10-13 补清 R1-R3)**: Z1 ServiceContainer 三面迁移 (棘轮 205→35) / Z2 main.py 拆分 (U2) / 同步 IO 异步化 7 处 / reload_config 差量更新 (mcp_servers 未变复用连接) / D1-D6 + R1 压缩死锁回归 + R2 富媒体出站防线 + R3 fail-closed 已修; L5-P2-6 三库租户列留设计批 (渠道↔租户绑定模型待拍板)。

**里程碑**: M-T1 ✅ → M-T2 后端段 ✅ (前端 F1/F2 落地即全达成) → M-T3 可接入 (N2 大部已过, 剩 soak 执行/发版段; N3 待凭据) → M-T4 可扩展 ✅ (R3+T6) → **M-GA** = N2 全过 + N3 至少一个平台真机通过 + F2 完成。GA 后进入 §四 GA 后开发计划 (V/X/Y/Z)。

**验收铁律**:任何节点声明完成必须附**真机部署证据**(命令 + 实际输出),不接受"单测通过"作为可用性证明。节点定义见 [docs/DEVELOPMENT_PLAN.md](./docs/DEVELOPMENT_PLAN.md) §三之三/§四,进度见 [docs/PROGRESS.md](./docs/PROGRESS.md)。

## 目录速查

见 [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) 六、目录结构;各目录职责边界见 [docs/DEVELOP.md](./docs/DEVELOP.md) 1.1。
