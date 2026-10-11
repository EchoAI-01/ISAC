# Changelog

本文件记录 ISAC 各版本变更。格式遵循 [Keep a Changelog](https://keepachangelog.com/),
版本号遵循 [Semantic Versioning](https://semver.org/)。

> **版本号策略 (2026-10-11 修订, 原 U9「GA 目标」定稿废止)**: 项目未达 MVP, 当前版本
> `0.0.1a1` = **Alpha-0.0.1**。版本节奏: `0.0.xaN` (Alpha, MVP 前) → `0.x.0` (MVP 后
> 功能迭代) → `1.0.0` (GA)。`pyproject.toml` / `isac/__init__.py:__version__` /
> `docs/api/openapi.json:info.version` 三处同源 (test_api_contract 契约测试锁定);
> 发布 tag `v<version>` 与三处一致 (release.yml verify 强校验), `aN/bN/rcN` 后缀
> 版本自动标 prerelease、镜像不打 latest。Alpha 期不承诺 API/配置兼容。

## [Unreleased]

### 后端收尾轮: N5 清偿 + 富媒体二波 + soak 工具 (2026-10-11, 全量 2378 通过)

后端剩余纯代码工作全部完成, 后端轨道收官:
**N5 同步 IO 异步化** 7 处 (Agent/全局配置/路由/links/插件解压的原子写与流式解压
全迁 to_thread; links 持久化回调事件循环内 fire-and-forget); **reload_config 差量更新**
(mcp_servers 未变时复用旧 MCPClient 连接, 避免秒级子进程重启; 复用失败回落全量重连);
**富媒体二波** —— 飞书入站 image (resources API + Bearer headers, 下载管线 headers 透传,
token 不落日志/事件流) + 飞书出站图片 (im/v1/images 上传) + Discord 入站附件 (CDN url
→ media segment) + Discord 出站 multipart + MediaResolver 登记两平台; **N2-4 soak 采样
工具** scripts/soak_sampler.py (负载发生 + RSS/FD/线程/事件表采样 + 泄漏判定, 等真实
LLM key 即跑 24h); **N3-1 凭据准备清单** docs/IM_CREDENTIALS_CHECKLIST.md (四平台逐项
+ 联调节奏)。新增回归测试 10 例; ruff/mypy/红线/catalog 全绿。

### D1-D6 缺陷修复轮 + N4 API 基线补齐 (2026-10-11, 全量 2368 通过)

基于 2026-10-11 全量架构评审修复 2026-10-10 审计登记的 5 项缺陷 + 复审新发现 1 项:
**D1** 入站去重键升 `(platform, session, msg_id)` 三维 (Telegram/Discord 的 msg_id 为
per-chat 序列, 两维键跨会话撞号误吞消息); **D2** tools_policy 非法档位 fail-open 堵断
(effective_policy 配置层覆盖值归一校验 + PATCH/validate 双端点配置期 fail-fast);
**D3** 压缩 GC 只删实际进入摘要的事件 (截断点后内容不再"不在摘要却被删");
**D4** 压缩摘要按替代区间起始位置插入历史窗口 (不再排在末尾被当最新发言);
**D5** 插件 reload/install 同步过 plugins_allow/deny 矩阵 (判定收口
core.policy 单源; 顺带修初始装配 injectors 无过滤与不带 source 注册两处同构面);
**D6** 压缩触发阈值改按内容事件计数 (工具密集会话不再恒空转全量 fetch)。
N4 前端开工前置: openapi 基线补 securitySchemes (bearerAuth+sessionAuth) 与 /ui/
挂载条目; `/config/schema` 模型从 3 键扩至全量 22 顶层键 (宽松建模, 零行为变化)。
新增回归测试 23 例; ruff/mypy/红线全绿。

### 加固轮 + 最小实例修复 + 全库文档收敛 (2026-08-19 ~ 10-11)

**2026-08-19 Review 后加固轮** (全量 2321 通过): 阶段 1 止血 (群聊锁粒度 Critical /
append-only 后门封堵 / shared ACL / 审批 scope / 插件来源追踪 + per-Agent 启用矩阵 /
发货面 pricing.jsonc 入仓); 阶段 2 (SubAgent 纳入 U5 权限管线 / U4 handoff 租约
fail-closed / Medium 批清 10 项 / 记忆 importance 规则显著度接线); 阶段 3 (入站幂等
去重 / 出站有界重试 + 死信环 / U1 会话压缩写侧 + 保留 GC / Telegram 入站媒体 /
429 Retry-After / CGNAT 封堵 / 成本闭环 provider 键统一 / 召回可解释性 recall_sources);
#25-#29 (U4 token↔tenant 绑定 + 删除级联 / 审计 actor 归因 / 策略合并语义 / MCP 重连
+ Channel 门控 / AstrBot import 重定向接线); Z1-C ServiceContainer 热路径迁移
(红线棘轮 130→35)。

**2026-10-10 最小实例运行修复** (全量 2346 通过): CI `build` job (uv venv 无 pip) 与
`docker` job (.dockerignore 行内注释致 README 被排除, docker build 从未通过) 修复,
**CI 5/5 全绿 (自 07-24 以来首次)**; 新增 `control.allow_external_host` 显式放行
(默认仍强制 loopback, 严格布尔 fail-closed; compose/CI 注入), 源码 + Docker compose
双向真机验证; `/health` 聚合 await 异步 AgentManager.list 修复 (此前 agents 统计恒 0)。

**2026-10-11 全库文档收敛**: 对照代码审计修复 88 项文档漂移 —— 状态文档
(README/AGENTS/CHANGELOG/PROGRESS/DEVELOPMENT_PLAN/RELEASE_AUDIT/release_checklist),
使用文档 8 篇 (usage/deployment/QUICKSTART/api/control_automation/MAINTENANCE/LOGGING/
plugin_development), 设计规范文档 9 篇 (ARCHITECTURE/SPECIFICATION/CONTROL_PLANE_SPEC/
HUMANLIKE_RUNTIME/MEMORY_DESIGN/ROUTING_AND_AGENT_MESH/PLUGIN_COMPATIBILITY/MODULE_GUIDE/
ROADMAP); Docker 冒烟 (N2-1) 与 browser CI 复核 (N2-2) 依据真机/CI 证据标记完成。

### CI/CD 流水线 (2026-10-11)

**CI 更新** (`ci.yml`, 原有 5-job 结构保留): 显式最小权限 `contents: read` + 同分支/PR
并发取消 (省 runner) + 全 job `timeout-minutes` + checkout v4→v5 + `setup-uv` 合并
python-version 输入 + `build` job 上传 wheel/sdist artifact (PR 页可下载) + `docker` job
改 buildx + gha 层缓存 (uv sync 依赖层跨 run 复用); K8/U8/U9 门禁与历史修复注释原样保留。
actionlint 校验通过。

**CD 新建** (`release.yml`): tag `v*` 驱动正式发布 + `workflow_dispatch` 演练模式
(GA 前不打 release tag, 演练保持链路随时可发布)。四段流水线: `verify` (CI 全量门禁
复验 —— 发布不信任历史 + 版本三处一致强校验, release_checklist §四机器化: tag/
pyproject/`__version__` 不一致即拒绝, 演练仅告警) → `build-wheel` (uv build + 安装
smoke + artifact) → `docker` (amd64 本地探活 → 多平台推 `ghcr.io/echoai-01/isac` →
按 digest 拉回再探活, 坏镜像绝不推/推送后端到端复验) → `release` (CHANGELOG `## [X.Y.Z]`
段落提取, 缺失回退 Unreleased; gh CLI 建 Release 附 wheel/sdist; rc/beta/alpha 自动
prerelease 不占 latest)。镜像 tag: `vX.Y.Z` → `X.Y.Z`/`X.Y`/`latest`, rc 版不占 latest。
小写化用 `tr` 而非 `${VAR,,}` (兼容本地 bash 3.2 复现)。

**配套**: `.github/dependabot.yml` (github-actions 生态月度升级 PR, 走 CI 门禁);
release_checklist 发版段/AGENTS/PROGRESS/deployment.md 同步 (deployment 新增 §1.4
ghcr 预构建镜像拉取)。

**版本号定调 Alpha-0.0.1 (2026-10-11)**: 项目未达 MVP, 版本从 `pyproject=1.0.0rc1` /
`isac.__version__=1.0.0` (原 U9「GA 目标」策略) 下调统一为 `0.0.1a1`; README 徽章、
`docs/api/openapi.json:info.version`、`uv.lock` 同步 (test_api_contract 5 例通过)。
release.yml 适配 alpha 语义: 镜像 tag 改 raw 直出 PEP 440 版本串 (node-semver 的
prerelease 格式 `0.0.1-a1` 与 PEP 440 `0.0.1a1` 不兼容, type=semver 对 aN 后缀不命中),
prerelease 判断改 PEP 440 后缀正则 `(a|b|rc)[0-9]+$` (原 `(rc|beta|alpha)` 字面匹配
漏 `a1` 形式)。

**模型快照刷新 workflow 恢复 (2026-10-11)**: 恢复 `model-capabilities.yml` (2026-10-10
删除时未同步处理 test_u7 新鲜度断言 —— 无刷新则约 60 天后 CI check job 恒红)。
相对原版修正: cron 每 6 小时→每周一 05:17 UTC (60 天窗口 8 周冗余, 不重试); 先
`--check` (本地零网络) 再在线生成; 补 concurrency/timeout/checkout v5; 生成器仅标准
库, `uv run --no-project` 直跑不装项目依赖 (本地实测 --check 通过, 8443 模型)。

### U 架构演进轮 (2026-08-17 ~ 08-18)

**U9 A+ 复评门禁**: 红线指标 CI 常驻 (scripts/check_redlines.py: main.py ≤120 行 /
模块 ≤500 行 / services 键 ≤36 / 硬编码门控词 ≤27 / services.get 残余 ≤205, 只减不增);
"定义了未接线"清零审计常驻 (UNWIRED_LEDGER 登记册); smoke_main_resident flake 根治
(固定 sleep → 就绪标记轮询); services 字符串键访问首批迁移 ServiceContainer;
复评报告归档 docs/U9_ARCHITECTURE_REVIEW.md。

**U2 装配层重构**: main.py 2046 → 82 行薄入口 (dispatch/wiring/bootstrap 三模块各
≤500 行 + 卫星模块层级归位); ServiceContainer (dict 子类 + 14 核心键类型化属性,
键错配类型层不可能); 红线测试常驻。

**U8 注入仲裁门 + 治理门禁**: SessionWriteGate (先预约后写入 / hold 窗口 /
fail-closed, Fix-81/82 根因收编) + AST 审计常驻; 工具/配置 catalog 生成 + CI --check
漂移检测; mock IM 事件流快照回放; evidence 目录规范化。

**U7 Agent 数据化**: prompt 文件化 (frontmatter 模型族变体, 改人格=改文件);
models.dev 能力快照 (6666 模型入库 + CI 每周刷新 + 新鲜度 drift 测试) +
record_health 生产接线 (fallback 链按能力与可达性过滤); category 路由
(delegate_task.category 四类画像经 ModelRouter 选模型链)。

**U3 门控策略化**: GatingProfile 配置收口 + GatingStrategy 四档 (off/keywords/
llm-judge/hybrid) + locales 双语词表 + drift test; llm-judge 走 fallback 链最便宜档
+ 频率上限 fail-safe。

**U6 插件隔离默认化**: 信任分级倒转 (原生插件默认隔离, hosted 需部署确认);
rlimits/ipc_timeout 部署接线; 兼容层文档化降级承诺 (Z3 收敛)。

**U5 工具权限管线 + HITL**: 四段管线 (waterfall → 单调 DenyGuard → 执行 → 事件表
审计留痕); ask 档 IM 审批卡片闭环 (同意/拒绝/超时 fail-closed); decision_reasons
词汇表 + drift test。

**U4 租户机制强制**: TenantBoundDB 机制强制层 (谓词唯一实现不可绕过); 四记忆表
租户列; QueryMemoryTool master_id 检索; 三处键统一。

**U1 事件溯源会话内核**: append-only 事件表 + 状态事件派生 + "Model-visible ⟺
Logged" + torn-tail repair + episodes 事件投影 + 迁移脚本 + 真机跨重启冒烟留档。

**U0 安全清偿**: Fix-85 治理面租户谓词 / Fix-86 解压体积上限 / Fix-87 MCP
restricted 语义 / Fix-88 插件工具命名空间; clamp/WAL/死字段批清。

### Phase 0/1 工程纠偏 + T 开箱可用轮 + R 需求完整性轮 (2026-08-04 ~ 08-16)

- **Phase0 批次 A-G**: 记忆口径租户隔离、LLM 参数 clamp、MCP 生命周期、适配器
  零散修复等 ~40 项; browser CI 本地真跑通。
- **T7**: 配置迁移测试 + compose 骨架 + 快速开始文档。
- **R7**: P3/P4/P5 集成测试 19 例 (向量+图谱+治理召回 / 身份绑定聚合 / 跨租户+
  插件隔离+workflow)。
- **R1-R6**: 多模态出入站闭环 / 控制面与 SubAgent 收尾 / 插件与 MCP 生态激活 /
  记忆完整性 (行话学习+MidTerm COMPRESS) / 持久化与密钥 / 企业化租户控制面。
- **T1-T6**: 开箱能对话 (私聊无条件触发+占位 key 检测) / 零配置启动 / 控制面开箱
  后端 / 错误可诊断 / 插件市场与热重载。
- **FE0/FE1**: API 契约冻结 (openapi.json 基线) + 分离基建 (CORS/SameSite)。

### CR3 评审修复轮 (2026-07-26)

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
