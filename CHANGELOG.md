# Changelog

本文件记录 ISAC 各版本变更。格式遵循 [Keep a Changelog](https://keepachangelog.com/),
版本号遵循 [Semantic Versioning](https://semver.org/)。

## [v1.0.0-rc.1] — 2026-07-26

首个 Release Candidate。A-O 全部大节点 + experimental 桩补齐就位, 1093 单测全绿,
ruff/mypy 全绿, 主程序实测驻留 + SIGTERM 优雅关闭。

### Added

- **L 拟人化运行时 (L1-L5)**: ConversationRuntime 会话级状态机 + DebounceWindow
  静默窗口合并 + WaitState 三条唤醒路径 (message/timeout/proactive) + actual_seconds
  回填 + ProactiveScheduler priority 队列 + allowed_sources 鉴权 + 后台循环 + InterruptState
  单轮次数限制 + InterruptInjector 注入"上一轮被打断"提示 + ConversationStateStore
  原子写 JSON + 短/中/长/24h 窗口判定 + RecoveryInjector 注入 recovery_hint。
- **M 路由与 Agent Mesh (M1-M2)**: MeshRouter observer/candidate 路由 + arbitrate
  按 gating_score 降序 + SWITCH_MARGIN=0.3 防抖 + MeshActionBroker ACL (deny-by-default)
  + notify/handoff/memory_query 经 InterAgentBus 真实投递 + visible_memory_scopes 裁剪
  + list_available 从 Link 表过滤 + 4 个 A2A 工具 restricted (notify_agent/handoff_
  conversation/list_available_agents/memory_query_agent) + ToolRegistry required_service
  校验 mesh_action_broker。
- **N 记忆深化 (N1-N3)**: MemoryItem 统一契约 (四类型 from/to: episode/profile/jargon/
  relationship) + MemoryItemAdapter 双向适配 (MemoryItem ↔ MemoryHit) + MemoryGovernor
  freeze/protect/correct/delete/restore/export 真实 SQL + memory_revisions 保留旧版本
  + memory_audit 审计日志 + IdentityResolver 跨平台归一 + person_identities/identity_
  conflicts 表 + heuristic 启发式匹配 (confidence≤0.5) + arbitrate_conflict 按
  confidence 排序 + 低置信写冲突表供人工裁决。
- **O 企业化 (O1-O3)**: TenantIsolationGuard namespace_for/check_access/enforce/
  assert_visible + SQL tenant_id 谓词注入 (WHERE 已有时追加 AND, 无 WHERE 时加 WHERE)
  + 跨租户 PermissionError + PluginIsolationHost multiprocessing.Process + Pipe IPC +
  resource.setrlimit (CPU/NOFILE/AS) + 崩溃自动重启 (max 3 次) + WorkflowEngine
  串/并/条件/重试调度 + 状态机 PENDING→RUNNING→SUCCEEDED/FAILED + step/resume +
  原子写持久化 (中断后标 FAILED 不续跑, 与 L5 一致)。
- **experimental 桩补齐**: VectorStore sqlite-vec vec0 虚拟表 (struct.pack 二进制) +
  GraphStore SQLite 三元组表 (namespace 隔离) + OpenAICompatRerankerProvider Cohere/
  Jina 双协议 (按 index 还原 scores 数组) + main.py register_multimodal_providers
  加 kind=="rerank" 分支 + config.sample.jsonc 补 rerank 示例。
- **K8-2 CI 工程化**: GitHub Actions 加 browser job (Playwright install chromium +
  tests/browser/ 黄金路径) + Docker smoke 已有 30s curl /health 循环 + wheel install
  smoke 已有 python -c "import isac" + 新建 scripts/release_checklist.md 七段发布准入
  清单 (CI 全绿 + 本地全量验证 + 文档同步 + 版本号一致 + 发布标签 + 回滚预案 + 发布后监控)。

### Changed

- README.md 项目状态从 Alpha 改为 Release Candidate v1.0.0-rc.1; 补 L/M/N/O 能力描述。
- AGENTS.md 剩余工作段更新 (L/M/N/O 全部 14 子节点业务实现完成, 仅 O4/O5 真实 API
  接入待用户二次确认)。
- docs/PROGRESS.md 节点总览表 L/M/N/O 行从"框架就位"改为具体进度 (L 100% / M 100% /
  N 100% / O 进行中 O1-O3 完成); K 行 100%。
- docs/DEVELOPMENT_PLAN.md L2-L5/M1-M2/N1-N3/O1-O3/K8 全部标 [x] + 补"已完成"段。
- docs/ROADMAP.md 阶段 1-3 状态从 🟡 改为 ✅ (阶段 4 进行中 O1-O3 完成)。

### Fixed

- 无 (本版本为首次 Release Candidate, 无既有缺陷修复)。

---

## 之前的里程碑 (摘要)

- **2026-07-25**: J4 SubAgent Runtime + J3 WebUI v2 SPA 十域 + J2 多模态 Provider +
  J1 Token 用量计量 完成。
- **2026-07-24**: K1-K7 稳定化 + D9 任务进度报告 完成。
- **2026-07-22**: A-H 基础骨架 + 连接路由 + 单 Agent 核心 + 多 Agent 运行时 + 插件生态
  + 控制面 + 平台扩展 完成。
