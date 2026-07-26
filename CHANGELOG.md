# Changelog

本文件记录 ISAC 各版本变更。格式遵循 [Keep a Changelog](https://keepachangelog.com/),
版本号遵循 [Semantic Versioning](https://semver.org/)。

## [Unreleased] — CR3 评审修复轮 (2026-07-26)

对应 `Review/ISAC_待修复项清单.md` 的 14 项待修复缺陷 (H2-H4 / M2 / M5-M7 / L1-L8),
外加评审阶段已写回的 5 项 (H1 越权 / M1 锁泄漏 / M3 Discord / M4 原子写 / README 文案)。

### Fixed

- **H3 向量召回**: `MemoryRetrievalPipeline.search()` 接入稠密 (向量) 召回 + RRF 融合;
  向量候选统一经 `get_episodes_by_ids` 过滤 (命名空间 + user/group ACL + 软删);
  `main.build_services` 按 `memory.embedding` 配置注入真实 EmbeddingProvider
  (此前生产恒降级, 写入白算 embedding)。
- **H4 流式工具调用**: `_parse_chunk` 按 index 累积分片 (id/name 首片、arguments 拼接),
  流结束统一装配完整 ToolCall; 并行调用不再丢弃; 流式请求默认带
  `stream_options.include_usage` (token 预算不再记 0); 首 chunk 前失败回退非流式
  `chat_with_retry` (重试/回退/降级)。
- **H2 插件隔离**: `resource` 模块平台守卫 (Windows 上模块可导入/测试可收集);
  `PluginIsolationHost` worker 从 echo 桩升级为可真实加载插件 (`load_plugin` +
  方法调用, 顶层代码在资源受限子进程执行); `PluginManager.call_on_load` 在主链路
  接线 (插件 on_load 生效, 可订阅生产 EventBus/注册 Admin Route); 加载路径与
  plugins/README.md 加"宿主内执行、无隔离、仅可信插件"护栏。
- **M2 跨 Agent notify**: `InterAgentBus.send` 对 notify 先真实投递再返回 None
  (此前投递前就 return, 目标收不到消息而工具报成功)。
- **M5 资源泄漏**: `GatingSystem._turn_schedulers/_idle_backoffs` 与
  `FocusMode._active_until` 加 LRU 上限 (cap 1000, 对齐 ConversationRuntimeRegistry)。
- **M6 调度饿死**: `ProactiveScheduler` 冷却中的任务不再退回队首反复重取, 改为
  原位跳过取下一个就绪任务 (`ProactiveTaskQueue.poll_ready`)。
- **M7 Workflow 引擎**: 启动全部入口节点 (此前只跑 entry[0]); fan-in 汇合节点按
  入度等全部父分支完成 (此前首个父分支到达即提前执行); conditional 跳过分支
  满足下游依赖, 全父跳过时级联 SKIPPED; RETRY 自环不计入流转边。
- **L1 自动化沙箱**: Admin API / MCP 创建 Agent 强制走 `make_restricted_agent_config`
  (bash/task deny + `plugins_deny=["*"]` + 仅安全命令), 调用方能力字段丢弃并告警;
  放宽能力走 PATCH 显式授予。
- **L2 多租户**: `TenantIsolationGuard` 接入 MetadataStore 数据面 —— episodes 加
  organization_id/tenant_id 列, 写入打标, 三条读路径 (FTS/按 ID/预热) 经 `enforce()`
  租户谓词过滤; `memory_factory` 命名空间加租户前缀; `tenancy.enabled` 默认关闭。
- **L3 BM25 墓碑**: 治理 delete/restore/correct 同步 SparseBM25Index
  (remove/重建); 预热查询排除 `deleted=1` 行。
- **L4 SSRF TOCTOU**: 新增 `pin_validated_url` 请求期"校验即固定" (http 域名替换为
  已校验 IP + Host 头, https 请求前复核), webhooks 与 image_gen 下载接入。
- **L5 审计归因**: 治理操作透传 operator (控制面 Token 指纹, 不落裸 Token) 并落
  `memory_audit` (补 agent_id 列)。
- **L6 零散安全**: `verify_token` 对非 ASCII Token 兜底 401 (此前 TypeError→500);
  `/metrics` 新增 `metrics_auth_enabled` 可选认证 (默认关闭保持 Prometheus 兼容)。
- **L8 零散正确性**: `write_file` 磁盘 I/O 卸载线程池; `SubAgentJournal.append`
  自动 seq 改单语句原子分配 (并发不再互相覆盖); MCP `transport="sse"` 显式报错
  不支持 + HTTP 响应补状态码检查。
- **接线补漏**: 控制面 sessions/memory/memory-admin/events 路由完成生产挂载
  (此前 `services` 缺键恒 None, 从未挂载)。
- **复核修正 (对本轮 diff 的对抗性审查发现)**: Workflow 引擎入度只统计"运行期
  可满足"的边 (悬空来源/非 RETRY 自环/DFS 回环边/不可达来源边全部排除, 收尾对
  残留 PENDING 告警) —— 否则这些边会让 stage 永久卡 PENDING 却报 SUCCEEDED;
  sessions/memory 读端点补 `deleted = 0` 过滤 (软删内容不得经控制面原文取回);
  VectorStore 按 namespace 分库 (多 Agent 下 KNN top-K 不再被其他命名空间挤占)。

### Changed

- README 状态表改为三态口径 (已接线 / 配置启用 / 待接线), rc 定位下修为
  "主链路 MVP + 待激活子系统"; PROGRESS/AGENTS 同步。
- config.sample.jsonc 补 `memory` (含 embedding 稠密召回) 与 `tenancy` 配置样例。

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
