# ISAC 开发 SOW / 主 TODO

> 本文档是 ISAC 项目的 **工作说明书 (Statement of Work)** 与 **主 TODO 清单**。
> 不再按"第几天"排期，而是按 **节点 (A/B/C...) / 子节点 (1/2/3...)** 组织任务。
> 每个子节点完成后，需：1) 在本文档标记 `[x]`；2) 补充/更新相关文档；3) 向项目负责人汇报。

---

## 一、项目总则

1. **文件名称清晰易懂**：模块、文件、函数、类名须符合 `DEVELOP.md` 命名规范，做到"看名知意"。
2. **项目结构干净优雅**：目录职责单一，导入无环，新模块按 `DEVELOP.md` 1.1/1.2 放置。
3. **可接手能力强**：任何节点完成后，须留下"交接说明"——说明已实现内容、未实现边界、下一步入口。
4. **文档即蓝图**：整体思路、节点待办、项目构造、蓝图必须落成文档；修改实现时同步更新文档。
5. **代码可读性**：必须写中文 docstring；复杂逻辑加行内注释解释"为什么"；保持代码整洁。
6. **文档可读性**：避免模糊词与未定义名词；必须解释的专业术语集中放在 [术语表](#五术语表)。
7. **禁止"定义了未接线"**：安全相关的常量、机制、限制必须接线到生产或删除，不允许零引用声明（2026-08-17 立；反例：MAX_EXTRACTED_BYTES / install_sandbox / CompressionPolicy 三处）。
8. **同构面核对清单**：每个安全/防护修复交付前，必须核对同类入口是否全部覆盖同等防护（2026-08-17 立；反例：mcp: 前缀未推广到兼容层、SSRF pin 未推广到入站下载、租户谓词未推广到治理面）。

---

## 二、节点使用规则

- **大节点**：用 A/B/C... 编号，代表一个可验收的里程碑。
- **小节点**：用 A1/A2... 编号，代表可独立完成、可汇报的最小单元。
- **进度标记(三态)**:标记须如实反映"是否接入生产主链路",不得用 `[x]` 掩盖"实现了但没激活"。
  - `[x]` **已交付** — 满足下方"完成定义"(非桩实现 + 单测 + 集成/运行验证 + **主链路接线** + 文档 + `ruff`/`mypy`/CI)。
  - `[~]` **实现完成待接线** — 核心逻辑 + 单测完成,但未接入生产主链路(默认关闭 / 生产路径无调用点);**按"完成定义"尚不算完成**。其接线项统一收敛在 §四 **P 节点**,不散落于各节点备注。
  - `[ ]` **未开始** — 仅骨架桩(no-op / `NotImplementedError`)或尚不存在。
- **进度汇报**:每推进一个小节点,更新本文档标记并同步 [PROGRESS.md](./PROGRESS.md),简要汇报。
- **节点可调整**：如需新增/合并/拆分节点，先更新本文档与 `AGENTS.md`，再继续执行。
- **完成定义**：小节点完成 = 非桩代码实现 + 单元测试 + 对应集成/运行验证 + 错误与关闭路径验证 + 相关文档同步 + `ruff` / `mypy` / CI 门禁通过。仅有接口、占位实现、静态文件或 Mock 单测不得标记完成。

---

## 三、节点总览

各节点进度以 [PROGRESS.md](./PROGRESS.md) 为**唯一事实源**,本文档不再另存进度表,只描述节点定义、依赖与验收。

当前概况(详见 PROGRESS.md)：A-K 已达可运行完成度 —— A-C、F-H 完成;E 经 K6 端到端验收;I 主体完成(WebUI v2 已落地,浏览器测试 CI 随 K8 接入);J1-J4 完成;K1-K8 稳定化完成,进入发布候选。**L 拟人化 / M 路由 Mesh / N 记忆深化 / O 企业化** 四大节点的 14 子节点中,**L2-L5、M1-M2、N1-N3、O1-O3 核心逻辑 + 单测已实现,但主链路尚未接线**(标 `[~]`:默认关闭、生产路径无调用点,按 §二完成定义尚不算完成),O4/O5 未开始(`[ ]`);向量库 / 图谱 / Embedding / Reranker 检索后端已实现(向量/图谱召回待接入 pipeline)。为把这些 `[~]` 能力接入同一主链路协同工作,新增大节点 **P 主链路接线与激活**(P0-P5,定义见 §四)。当前 1271 单测通过、ruff/mypy 全绿、主链路零行为变化。**2026-07-27 骨架轮 (S1-S7)** 又为 P3 图谱召回 / P4 身份归一 / P5 Workflow 控制面 / MemoryConsolidator / O4 三平台(飞书·微信·QQ 官方)/ O5 视频 Provider 补齐**骨架 + 默认关闭接线锚点**(均 default-off、零行为变化,见各节点"当前"与文末"S 骨架轮")。

**2026-07-26 MVP 差距复核**：对照 `docs/REQUIREMENTS.md` 十二条原始需求做 10 域并行代码取证(498 次代码检索 + 一次真实启动实测),发现一批标 `[x]` **已交付**的节点(D8/E4/F1-F3/H1/H2/J1-J4/K1-K4/K7)存在与其"完成定义"矛盾的未接线子行为,已在对应节点下补记"**2026-07-26 MVP 缺口复核**"说明(不改动其余已验证部分的 `[x]`);并新增大节点 **Q MVP 收尾**,收纳未被 P0-P5 覆盖、但 MVP 必需的缺口(记忆写入回路等,定义见 §四 Q)。技术路线全景见 [ROADMAP.md](./ROADMAP.md);模块开发范式见 [MODULE_GUIDE.md](./MODULE_GUIDE.md)。

**2026-08-17 全景 Review 与架构演进决策**: 完成 18 项目全景 Review (16 存量项目增量核对 + 新增 deepseek-harness / oh-my-openagent 全量审查) 与 ISAC 深度 Review (报告归档于工作目录 `.tmpfiles/agent-review-2026-08-17/`, 含 `isac-deep.md` 461 行深度评估, 实测 pytest 1822/7/3、ruff/mypy 全绿): 认定 **4 项安全实洞**与 **8 项架构问题** (区别于"功能未完成"的进度问题, 定性原则见 §三之五)。项目负责人拍板**升级完再发版** (不留过渡形态): 新增大节点 **U 架构演进轮** (U0 安全清偿、U1-U8 八项架构升级、U9 A+ 复评门禁, 定义见 §四 U); 发布路径与四项已拍板决策见 **§三之五** (取代 §三之三/§三之四 的 M-GA 定义); 架构债 Z1/Z2 升级收敛至 U2, 兼容层隔离收敛至 U6。

## 三之二、下一步开发计划 (2026-08-15 整合: 前后端分离 · 后端先行)

**重大决策**: 项目转入**前后端分离**开发。后端 (本仓库) 演进为纯 API 服务 (REST + SSE 控制面 + 消息数据面), 前端独立成项目围绕 API 契约开发。**先开发后端**, 前端轨道 (F 节点) 在 API 基线冻结后启动。决策记录见 `ARCHITECTURE.md` ADR-012, 节点定义见 §四 FE。

**当前方位**: T 开箱可用轮 **T1/T2/T4 已完成 (2026-08-04)** —— 开箱能对话 (私聊无条件触发 + 未回复可观测 + 占位 key 检测)、零配置启动 (默认配置内置 + 首启建 data 目录)、错误可诊断 (中文可操作提示 + `/health` 聚合 + 实时日志台); **T3 未开始**并按前后端分离重定义 (后端先交付 setup/auth API, WebUI 页面归前端轨道); T5-T7 与 R 节点组未开始。1568 测试通过、ruff/mypy 全绿。**阶段 0 工程纠偏已完成 (2026-08-15)** (CI 分支/venv/aiosqlite/worktree/构建产物, 详见下方推进顺序第 1 项); **FE0 API 契约冻结已完成 (2026-08-16)** (openapi.json 基线归档 + 错误格式统一 + 变更流程文档化); **FE1 分离基建已完成 (2026-08-16)** (CORS 白名单 + Session SameSite 参数化 + WebUI 标 deprecated); **T3-backend 控制面开箱后端支撑已完成 (2026-08-16)** (control 默认开 + setup 首登强制设密码状态机 + CLI password reset + /config/schema JSON Schema 端点 + 真机验收 setup 流程走通), **R3 插件与 MCP 生态激活已完成 (2026-08-16)** (收敛 Q3: 共享注册表 + AstrBot/MaiBot adapt 桥接 + MCPClient 生产接线, 真机冒烟 `MCP server 已接入 server=echo tools=1`), **T6 插件市场与热重载已完成 (2026-08-16)** (PluginInstaller 四源安装 + SSRF/zip slip 防护 + ToolRegistry deregister/来源追踪 + activation 热重载同步运行中 Agent + 控制面端点 + CLI `isac plugin` + 本地/远程市场清单, 真机冒烟 `scripts/smoke_plugin_marketplace.py` 安装→reload→卸载 exit=0), **R5 持久化与密钥安全已完成 (2026-08-16)** (SessionManager SQLite 写穿+重启恢复 + SecretStore `secret:` 前缀接入 + CLI `isac secret`, 真机冒烟重启恢复 session_id exit=0), **R2 控制面与 SubAgent 收尾已完成 (2026-08-16)** (`GET /agents/{id}/config` 真实 revision + SubAgent list-all + routes_webhooks (WebhookManager+EventBus 订阅+AlertManager 注入) + MCP Server 5 工具/生产启动点 + ContextEnvelopeBuilder 真传背景摘要 + evidence_refs 生成), **R6 企业化激活已完成 (2026-08-16)** (routes_tenants + TenantManager SQLite + tenant:read/write scope + ②loader 隔离已满足零工作 + ③workflow agent 入口决策落地选 B), **R1 多模态出入站闭环已完成 (2026-08-16)** (①_send_reply 扫 artifact 经 get_ref+MediaResolver 转 segment + ②入站下载落盘 data/uploads 闭环 + ③6 个 record_* 计量 + ④pricing.jsonc 价目表 + ⑤model_capabilities_allow 工具可见性), **R4 记忆完整性补齐已完成 (2026-08-16)** (①行话学习写入回路 consolidator `_extract_jargon_step` 群聊高频词 LLM 释义落 `upsert_jargon` + ②中期记忆真实 COMPRESS 压缩 方案A: hook 入队+consolidator 后台摘要落 `episodes.summary`+MidTermMemoryInjector 改读 summary 注入 RecallCue + ③语义关系图跳过留架构债: 写边层已就绪待补 LLM 抽取层), **R7 集成测试补齐代码可做部分已完成 (2026-08-16)** (新增 test_p3/p4/p5 三套集成测试 19 例: 向量+图谱+治理过滤召回 / 两平台 bind→记忆聚合 / 跨租户不可见+插件隔离+workflow 声明式执行; 全绿)。环境准入项 (真机/Docker 健康检查/24h soak/browser CI/十二条逐条取证) 按需环境留后。前端轨道 F1-F4 (独立项目, 技术栈待决策) 暂不启动。**P 主链路接线 (历史阶段)** 已全部完成或被 T/R 收敛, 不再是独立工作线。

**后端推进顺序**(定义与验收见 §四对应节点):

1. **阶段 0 工程纠偏 ✅ 已完成 (2026-08-15)** — CI 触发分支修正 (`ci.yml` `[main, develop]` → `[main, dev]`, 此前推 dev 从不触发 CI, 致 `scripts/smoke_webchat.py` 的 C901 一直没被发现); 重建 venv (shebang 指向迁移前旧路径 `/Users/chen/ai/ISAC`, `uv venv`+`uv sync` 重建后修正); 修复 aiosqlite 连接未关闭 (`test_graph_store`/`test_vector_store`/`test_memory_pipeline`/`test_runtime_manager` 的 fixture/teardown 补关闭长连接, `Event loop is closed`/`deleted before being closed` 警告归零, 24h soak 前置); 清理残留 worktree (6 个停在 `7df5e67` 的旧快照 + 分支, dev 已含全部内容, 删除无丢失) 与构建产物 (htmlcov/.coverage/dist)。顺手拆分 `smoke_webchat.py::main` 降 C901。验证: ruff/mypy 全绿、1568 测试通过(0 aiosqlite 警告)、smoke 真机冒烟退出码 0。
2. **FE0/FE1 API 契约与分离基建** — OpenAPI 契约导出冻结; CORS 与跨源认证策略 (Session Cookie + CSRF 适配分离 origin, Bearer Token 保留双轨); 配置 Schema 暴露 (JSON Schema 端点, 前端表单驱动前提); 现内置 WebUI 静态托管标记 deprecated (迁移期保留); SSE 契约维持 (`/events/stream`、`/logs/tail`)。
3. **T3-backend 控制面开箱后端支撑** — `control.enabled` 默认 true (仅绑 127.0.0.1); 首登强制设密码 (setup 状态 + `password_change_requires` + CLI reset 兜底); 真机验收。
4. **T5 真实 IM 接入验收** — 需用户凭据; OneBot/NapCat 先行, 飞书/QQ 官方/企业微信逐个真机联调 (此前均只有单测, 从未真机验证); WebUI/控制面连接状态回显。
5. **R3 插件与 MCP 生态激活 ✅ 已完成 (2026-08-16, T6 前置)** — per-Agent PluginContext 真实共享注册表 + AstrBot/MaiBot `adapt` 桥接接线 (新建 `AstrBotStarAdapter`) + MCPClient 生产接线 (`mcp.servers` 配置节 + `_wire_mcp_clients` + stop/destroy/shutdown `disconnect`) + CLI 工具 services 注入; 真机冒烟 stdio MCP server 接入验证。兼容层插件迁进程隔离未做 (架构受限: 兼容层无 manifest, Fix-31 已安全兜底, 留架构债)。
6. **T6 插件市场与热重载 ✅ 已完成 (2026-08-16)** — `PluginInstaller` (market/git/url/upload + SSRF/zip slip 防护) + `ToolRegistry` deregister/来源追踪 + `activation` 模块 (热重载同步运行中 Agent) + 控制面 marketplace/install/reload/uninstall/failed/retry 端点 + CLI `isac plugin` + 市场清单 (本地+可配远程); 真机冒烟 exit=0。
7. **并行收尾 (相互独立, 可穿插)** — **R1 多模态闭环 ✅ 已完成 (2026-08-16)** (出站 artifact 扫描+MediaResolver 转 segment/入站下载落盘 data/uploads/6 个 record_* 计量/pricing.jsonc 价目表/model_capabilities_allow 工具可见性); **R2 控制面与 SubAgent ✅ 已完成 (2026-08-16)** (`GET /agents/{id}/config` + SubAgent list-all + routes_webhooks + MCP 5 工具/生产启动 + ContextEnvelopeBuilder 真传 + evidence_refs 生成); **R4 记忆完整性 ✅ 已完成 (2026-08-16)** (①行话学习写入回路 consolidator `_extract_jargon_step` 群聊高频词 LLM 释义落 `upsert_jargon` + ②中期记忆真实 COMPRESS 方案 A: hook 入队+consolidator 后台摘要落 `episodes.summary`+MidTermMemoryInjector 改读 summary 注入 + ③语义关系图跳过留架构债: 写边层 `GraphStore.add_edge` 已就绪待补 LLM 抽取层); **R5 持久化与密钥 ✅ 已完成 (2026-08-16)** (SessionManager SQLite 写穿+重启恢复 + SecretStore `secret:` 前缀接入 + CLI `isac secret` + 真机冒烟重启恢复 session_id exit=0)。
8. **R6 企业化激活 ✅ 已完成 (2026-08-16)** — routes_tenants (CRUD 租户+成员 + tenant:read/write scope) + TenantManager (SQLite 持久化) + ②loader 隔离已满足 (零工作) + ③workflow agent 入口决策落地选 B (文档化不做, 消除悬空); 真机 smoke exit=0。
9. **R7 发布准入 + T7 分发运维 (最后)** — P3/P4/P5 集成测试补齐 ✅ 已完成 (2026-08-16, 19 例);I 节点复核升 100%、REQUIREMENTS 十二条逐条取证、release_checklist 七段、docker compose 一键 + 配置自动迁移、**24h soak** (待环境) → v1.0 GA。

**前端轨道 (独立项目, FE0/FE1 + T3-backend 之后启动)**: F1 项目初始化 + 登录/setup 向导 → F2 十域页面迁移 (配置编辑事务改接真实 API, 顺带修复 Q5 遗留假数据) → F3 实时日志与 SSE → F4 插件市场 UI。定义见 §四 FE。

依赖顺序：阶段 0 → FE0/FE1 → T3-backend → T5;R3 → T6;R1/R2/R4/R5/R6 相互独立可并行;R7 必须最后。**验收铁律 (2026-07-31 立) 继续适用**: 任何节点声明完成必须附真机部署证据, 不接受"单测通过"作为可用性证明。每项按 §二"完成定义"验收, 完成后把 §四 对应标记升为 `[x]` 并同步 [PROGRESS.md](./PROGRESS.md)。

**GA 之后做什么**: 本节计划全部完成 (v1.0 GA) 后的预置蓝图见 §四 **"GA 后开发计划"** (V 功能广度兑现 / X 生态与商业化 / Y 智能演进 / Z 工程演进持续线), M-GA 验收通过后才激活排期, 不影响当前推进。

---

## 三之三、下一步行动计划 (2026-08-16 制定, 取代 §三之二 推进顺序的未完成部分)

**背景**: 后端代码工作已基本收尾 —— 阶段 0 / FE0 / FE1 / T3-backend / T1-T2/T4 / T6 / R1-R6 全部完成, R7 代码部分 (P3/P4/P5 集成测试 + hook 真实触发测试 + ConfigMigrator 测试 + QUICKSTART) 完成; 全量 1739 测试、ruff/mypy 全绿。**剩余项几乎全部是环境/凭据依赖与前端轨道**。本计划按"解除阻塞的先后"排列。**2026-08-16 补记**: 本轮全量代码审查 (见下方 N1b) 发现"接线层"仍有一批 Critical/Major 缺陷 —— "无纯后端代码缺口"的结论以 N1b/N5b 清偿完毕为准。

### N1 文档与标记收敛 (立即, ~0.5 轮) — **进行中**

- [x] 三态标记漂移修复: T3-backend `[ ]`→`[x]`; Q4/Q5/Q6/P3/P4/P5 已被 R 节点收敛, 由 `[~]` 升 `[x]` 并补"结论"行 (2026-08-16)。
- [ ] PROGRESS.md 节点总览表 N/O/Q 行同步收敛口径; T7 `[~]` 与 R7 `[~]` 的剩余项逐一挂到 `RELEASE_AUDIT.md` 第三节环境项。
- [ ] README 状态表与 AGENTS.md 剩余工作同步 (T6/R1-R6 完成态)。

### N1b 全量代码审查修复轮 (2026-08-16, Fix-37~Fix-48) — **"立即"层已完成, 专项批次见 N5b**

**方法**: 5 路并行全量审查 (isac/ 全部 260+ 源文件, 重点盯 T6/R1-R6 新增接线) → 主审对全部 Critical 逐条读码复核。发现 7 Critical + 44 Major + 68 Minor。

**已完成 (Critical 7 项 + 批次 A 安全一致性 4 项, 新增 15 例回归测试, 全量 1752 通过)**:

- [x] **Fix-37** 企微 AES 明文布局与官方 WXBizMsgCrypt 协议颠倒 (真实回调必失败, 单测同错互证故全绿) → 官方布局切片 + receiveid==corpid 校验。
- [x] **Fix-38** image_gen 下载第三方 CDN URL 泄露 Bearer api_key → 独立无 Authorization 下载 client。
- [x] **Fix-39** 入站媒体/插件安装器重定向 SSRF 绕过 + 无体积上限 → `safe_download_bytes` (逐跳复校验 + 流式上限)。
- [x] **Fix-40** 已配静态凭证时未认证 POST /setup 可接管控制面 → SetupManager static_credentials_configured 闸门。
- [x] **Fix-42** MCP 接线补传 parsed_tokens (tokens[] 部署认证跳过)。
- [x] **Fix-43** MCP 无凭证时 tools/call fail-closed。
- [x] **Fix-44** MCP stdio 阻塞 readline → asyncio.to_thread (启用即冻结 Bot)。
- [x] **Fix-45** /events/stream scope 解析支持会话 Cookie (WebUI SSE)。
- [x] **Fix-46** /logs/tail scope 门禁 ("*")。
- [x] **Fix-47** CSRF 豁免 POST /auth/session (带旧 Cookie 重新登录)。
- [x] **Fix-48** PUT plugins 配置锁 + 列表参数健壮化。

### N1c 第二轮全量代码审查修复轮 (2026-08-16/17, Fix-55~Fix-84) — **批 1 + 批 2 + 批 3 全部完成 (全量 1834 通过), 剩余 ~40 Minor 另立批次**

**方法**: 与 N1b 同规格 5 路并行全量审查, 目标"复核 N1b/N5b 修复质量 + 查漏"。确认 3 项新 Critical + 5 项修复回归 + 一批 Medium/Minor。

**批 1 已完成 (3 Critical + 回归, Fix-55~62)**:

- [x] **Fix-55** webhook dispatch 在会话锁内同步 await (单个慢 endpoint 阻塞该会话消息链 ~32s) → 后台任务派发。
- [x] **Fix-56** QQ 官方 send() 只看 HTTP 2xx 不看 body 错误字段 (平台级失败静默吞掉) → 非零错误码 fail-closed。
- [x] **Fix-57** 打断后 pending 消息丢失 (interrupted 分支未回退消费游标) → `rewind_processed`。
- [x] **Fix-58~62** MCP server agents_dir 未接线; PUT plugins matrix 404 移入 config 锁; stdio serve 异常隔离; 静态凭证判定补 token_scopes 分支; `is_safe_url` 同步 DNS 解析 to_thread 化。

**批 2 已完成 (协议契约 + 认证一致性 + 记忆/制品, Fix-63~71)**:

- [x] **Fix-63** MediaResolver 平台键与 OneBot adapter `platform_name="qq"` 不匹配。
- [x] **Fix-64** rerank 响应字段协议错认 (单数 "result" → 官方 "results", 单数保留为 fallback)。
- [x] **Fix-65** reranker 非数字 score 排序崩溃 → float 强转回退。
- [x] **Fix-50/52** setup 已配静态凭证后 `is_password_valid` 仍 True + PBKDF2 校验滑动窗限速。
- [x] **Fix-66** PATCH agent payload 可携带 revision 覆盖 (乐观锁 ABA) → 剥离。
- [x] **Fix-67** consolidator episode 元数据 IN 查询分块 (500/批)。
- [x] **Fix-68** task/delegate_task 深度键读错容器恒 0 (递归守卫失效) → 改读 AgentContext.services。
- [x] **Fix-69** ArtifactStore 同内容制品 `INSERT OR REPLACE` 互改元数据/TTL → `INSERT OR IGNORE` + 首次登记为准。
- [x] **Fix-70** handoff 无存活校验 (死 Agent 劫持会话至 TTL) → 工具登记前拒绝 + route() 自愈回落。
- [x] **Fix-71** Telegram entity offset 按 code point 切片错位 → UTF-16 code unit 切片。

**批 3 已完成 (Medium 12 项, Fix-72~84)**:

- [x] **Fix-72** LogBuffer 非 loop 线程 append 线程安全 (threading.Lock + call_soon_threadsafe)。
- [x] **Fix-73** AgentManager.create check-then-act 双创建 → per-agent 锁串行。
- [x] **Fix-74** consolidator 画像归纳写回前重读最新 profile (防过期基线回滚并发更新)。
- [x] **Fix-75** WebChat 待消费回复会话个数上限 (max_sessions + 逐出 + poll 删条目)。
- [x] **Fix-76** 三个 webhook 适配器验签前 body 限流 (`webhook_guard.read_body_limited`, 默认 2MB)。
- [x] **Fix-77** 隔离插件 IPC recv 超时 (默认 30s, 超时按崩溃重启)。
- [x] **Fix-78** SessionManager per-session_key 锁 (全局锁退化问题) + key 锁惰性回收。
- [x] **Fix-79** Session 持久化补 platform_session_id/user_ids 列 (含旧库 ALTER 迁移)。
- [x] **Fix-80** webhook 事件名对齐 CONTROL_PLANE_SPEC §5.1 目录 (旧名自动归一)。
- [x] **Fix-81** 强制话轮等锁期间被取消不再破坏并发回合状态机 (turn_owns_state)。
- [x] **Fix-82** 强制话轮注入 conversation_runtime (可被打断) + 正常完成清陈旧打断信号。
- [x] **Fix-83** SubAgent restore_interrupted 先落库改状态再登记内存索引。
- [x] **Fix-84** ArtifactStore schema 初始化双重检查锁 (并发首写 database is locked)。

**剩余 (~40 项 Minor)**: 另立批次, 优先级让位于 N2 环境准入与 N4 前端轨道。

### N2 环境准入项清偿 (T7/R7 收尾, ~2-3 轮, 依赖 docker daemon + 浏览器环境 + 真实 LLM key)

> 对应 `docs/RELEASE_AUDIT.md` 第三节。验收铁律适用: 每项附真实输出。

- [ ] **N2-1 Docker 健康检查冒烟**: `docker build` + `docker compose up` + `/health` 循环实测 (T7 验收 + release_checklist 第 3 段)。
- [ ] **N2-2 browser CI 复核**: 装 Playwright chromium 跑 `tests/browser/` 黄金路径, I 节点 85%→100% (release_checklist 第 4 段)。
- [ ] **N2-3 release_checklist 七段过一遍** (除真实 IM 凭据段): CI 全绿 + 本地全量 + 文档同步 + 版本号一致 + 发布标签 + 回滚预案 + 发布后监控预案。
- [ ] **N2-4 24h soak**: 真实 LLM key + 连续对话负载, 验证无内存/连接/任务泄漏 (验收铁律的最后一道)。

### N3 T5 真实 IM 接入验收 (外部阻塞: 需用户凭据 + 回调公网地址)

- [ ] **N3-1 凭据准备清单** (不依赖开发, 先交付给用户): OneBot/NapCat 测试 QQ 号; 飞书自建应用 (encrypt_key + verification_token); QQ 官方机器人 (app_id + secret); 企业微信 wecom (corpid/secret/agentid + 回调 URL)。
- [ ] **N3-2 逐平台真机联调**: OneBot 先行 (私聊 + 群聊 @ + 富媒体降级) → 飞书 → QQ 官方 → wecom; 每平台附收发实证。
- [ ] **N3-3 控制面连接状态回显** (Channel 实时状态经 `/health` 与 SSE 暴露)。

### N4 前端轨道启动 (独立项目, 后端 API 基线已冻结可直接开工)

> 前置已全部就绪: FE0 openapi.json 契约基线 + FE1 CORS/跨源认证 + T3-backend setup API + `/config/schema` JSON Schema 端点。

- [ ] **N4-1 技术栈决策** (开工第一决策): 框架与构建工具选型, 消费 `docs/api/openapi.json` 生成客户端。
- [ ] **F1** 项目初始化 + 登录页 + 首登强制设密码向导 (对接 `/setup` API + 428 gate)。
- [ ] **F2** 十域页面迁移 (配置编辑事务接真实 API + 乐观锁, 顺带清除 Q5 遗留假数据); 完成后移除后端 `control/webui/` 静态托管。
- [ ] **F3** 实时日志台 (`/logs/tail` SSE) + 事件流页面 (`/events/stream`)。
- [ ] **F4** 插件市场 UI (对接 T6 的 marketplace/install/reload/uninstall 端点)。

### N5 并行线: 剩余架构债与加固 (见缝插针)

- [ ] **Z1** `services` 弱类型 → ServiceContainer 强类型 (建议 N2 期间做, 功能面已稳定)。
- [ ] **Z2** `main.py` (1518 行) 拆 `isac/bootstrap/` 五模块。
- [ ] 同步 IO 异步化 (audit/bus persist/routes_routing 写盘)。
- [ ] `reload_config` 差量更新 (观察项, 不紧急)。

### N5b 全量审查剩余批次 (2026-08-16 审查发现的 Major/Minor, 各立专项)

> N1b 已清偿全部 Critical 与批次 A; 以下为剩余批次, 建议顺序 C → D → E → F/G。

- [x] **批次 C 插件生态专项** — 启动路径工具 source 追踪 (卸载/重载 deregister 对启动期插件失效); commands/injectors/hooks/EventBus 来源追踪 + deregister (只增不删); 隔离子进程崩溃后自动重载插件 + RLIMIT_CPU 可配 + 并发响应 correlation_id 匹配 + FD 泄漏; installer `name` 路径校验 (`^[A-Za-z0-9_-]+$` + resolve 子树检查)、update 原子交换回滚、解压体积上限; AstrBot import 沙箱接线 (官方语法插件当前加载失败); 插件名≠目录名生命周期映射; MCP 桥接工具名强制前缀 + 默认 restricted (防同名覆盖内置工具)。**注: C7 (AstrBot import 沙箱) 留架构债** —— 隔离是 opt-in 设计取舍, 非隔离插件顶层代码在宿主执行; 强制兼容层隔离需重构 adapt 进子进程, 写边层 (PluginIsolationHost) 已就绪待后续接入。
- [x] **批次 D MCP Client 生命周期** — reload_config 断开旧实例 MCP 连接 (子进程泄漏); stop→start 重连; connect 后 list_tools 失败路径清理; initialize/initialized 握手 + list_tools error 显式 (对真实 MCP server 当前恒 0 工具); stdio reader 脏输出 continue 不退出。
- [x] **批次 E 记忆口径一致性** — person_profiles 键分裂 (consolidator 平台 user_id vs manager/注入器 master_id, S2 画像归纳默认部署即死功能); 租户/自定义 namespace 注入器读不到 + person_profiles/jargon 表补租户列; `latest_episode_id_for_session` 租户包裹 SQL 报错 (R4 压缩链路失效, 已实测复现); consolidator 软删同步 BM25/向量; embedding 维度错配部分提交误报; 去重桶加 user_id; 归纳产物防持久化 prompt injection。
- [x] **批次 F LLM 可控参数 clamp** — wait/delegate/task 秒数、bash timeout、ask_agent 超时 + hop 深度、generate_image n、/mute 时长 + 命令用户级鉴权。
- [x] **批次 G 适配器与零散** — 飞书 p2p 私聊当群聊 (chat_type 未读); Discord/Telegram 自身消息过滤; ChannelRegistry.start_all/stop_all 错误隔离; uploads_store 生命周期注册 (TTL sweep); DELETE 不存在 agent 500→404; PUT routing/rules 400; TenantManager.list_tenants 缓存; resolve_secret 扫描路径对齐; 及 Minor 批量 (详见审查记录)。

### 里程碑路径

M-T2 可部署可管理 = N1 + N4-F1/F2 (前端落地即达成, 后端段已完成); **M-T3 可接入 = N2 + N3** (环境与凭据解除后); M-T4 可扩展已达成 (R3+T6); **M-GA v1.0 = N2 全过 + N3 至少一个平台真机通过 + N4-F2 完成** + release_checklist 七段全绿 **(2026-08-17 修订: 另需 U 节点组全过 + A+ 复评达标, 见 §三之五)**。GA 后进入 §四 GA 后开发计划 (V/X/Y/Z)。

---

## 三之四、产品可用全景计划 (2026-08-16 制定, 从"工程节点"升级为"产品可用"视角)

> **为什么新增本节**: §三之三 的 N1-N5 是**工程节点清单**, 回答"代码还缺什么"; 但历史教训 (2026-07-31 真机冒烟推翻"MVP 已达成") 证明**工程完成 ≠ 产品可用**。本节以**四类用户旅程**为线索定义"可用产品"的判定标准, 把 N1-N5 与其未覆盖的产品维度 (可部署性验证、可运维性、性能基线、兼容性矩阵、面向部署者/运维者的文档) 整合为 Phase 0-5 的全景计划。**关系**: N1-N5 是工程事实源与执行粒度, 本节是它们的产品化组织与缺口补充; 二者不重复维护进度, 进度仍以 [PROGRESS.md](./PROGRESS.md) 为唯一事实源。

### 一、"可用产品"判定标准 (v1.0 GA 的充分必要条件)

**v1.0 GA = 以下四条用户旅程全部真机走通并附证据** (验收铁律: 命令 + 实际输出, 不接受"单测通过"):

| 用户角色 | 核心旅程 | 成功标准 (真机可验) |
|---|---|---|
| **部署者** | 获得软件 → 部署 → 启动 → 说第一句话 | QUICKSTART 路径 A (Docker) / B (源码) 5 分钟跑通; 零手写配置可对话; 未配 LLM key 时给出"去哪配"的明确中文提示而非静默 |
| **管理者** | 打开浏览器 → 登录 → 配置 → 监控 → 排障 | 首登强制设密码 (无硬编码默认密码); 十域管理页无假数据; `/health` 聚合各子系统状态; 实时日志台可查; 配置修改经表单 + 乐观锁生效 |
| **终端用户** | 在 IM 里和 Bot 对话 | 私聊必回 (T1 已修); 群聊 @/提及触发; 越聊越熟 (记忆写入回路 Q1); 回复节奏拟人 (debounce/wait/打断); 富媒体按平台能力降级不丢 |
| **开发者** | 安装插件 / 接 MCP / 调 Admin API | 插件市场可装可用可热重载 (T6); MCP server 可接 (R3); API 契约冻结 (`docs/api/openapi.json`) 且向后兼容 |

### 二、全景缺口盘点 (八大维度)

按产品维度归位缺口, 而非仅按代码节点:

| 维度 | 现状 | 缺口 | 收敛位置 |
|---|---|---|---|
| **1. 功能完整性** | R1-R6 全部完成; REQUIREMENTS 十二条 8✅4⚠️ | 剩余 ⚠️ 项均属 GA 后 (V1-V4/X3/X4), 不阻塞 v1.0 | §四 GA 后计划 |
| **2. 正确性** | N1b 7 Critical + 批次 A; N5b 批次 C-G; N1c 第二轮审查批 1-3 (Fix-55~84: 3 新 Critical + 回归 + 协议契约 + 12 Medium) 全部清偿 | N1c 剩余 ~40 Minor 另立批次 | Phase 0 |
| **3. 开箱体验** | T1/T2/T3-backend/T4 已完成 (后端) | 前端 F1-F4 未启动 (登录向导/十域/实时/插件市场); 内置 `control/webui/` 静态托管待 F2 完成后移除 | Phase 3 |
| **4. 真实环境验证** | 从未在真实环境验证 | Docker 冒烟 (N2-1)、browser CI (N2-2)、24h soak (N2-4) 全部待环境; 真实 IM 联调 (N3) 待凭据 | Phase 1/2 |
| **5. 可部署性** | Dockerfile/compose/export 脚本已存在 | **未经真机构建验证** (N2-1); pip/uv 单包 3 步安装未验证; 配置版本迁移 (ConfigMigrator) 已有测试但缺真实升级链验证 | Phase 1/4 |
| **6. 可运维性** | `/health` + 日志台 + 用量计量 + 审计已有 | 缺: 备份/恢复/升级/降级流程真机演练; 监控告警端到端 (AlertManager→Webhook→送达) 验证; **面向运维者的 MAINTENANCE.md 运维手册缺失** | Phase 1/4 |
| **7. 安全性** | SSRF/Token/审计/SecretStore 已落地 | 缺: 安全自查清单 (secrets 扫描/依赖漏洞/权限最小化) 系统过一遍; 第三方审计留 X4 | Phase 4 |
| **8. 性能基线** | 无任何基线数据 | 并发会话上限、消息端到端延迟分布、24h 内存/连接/任务泄漏曲线全部未知 (随 N2-4 soak 产出) | Phase 1 |
| **9. LLM 兼容性** | 仅假设 OpenAI 兼容协议 | 主流端点 (DeepSeek/通义/Kimi/智谱/MiniMax) 未逐一验证 base_url/字段差异; 嵌入/重排端点同理 | Phase 1 |
| **10. 文档完备性** | 开发文档 (架构/规范/计划) 完备 | 缺面向**部署者/运维者**的用户文档: 部署详解、配置项参考、故障排查树、FAQ、各平台接入分步指南 | Phase 1/4 |

### 三、分阶段计划

> 每 Phase 列: 目标 / 工作项 (标注映射 N1-N5 或新增) / 准出标准 (真机证据) / 预估。验收铁律全程适用。

#### Phase 0 代码清偿 —— 把已知缺陷清零 (纯代码, 无外部依赖, **可立即启动**)

- **目标**: 消除全部已知 Critical/Major, 代码进入"零已知缺陷"状态。
- **工作项**:
  1. **N1 收尾** — README 状态表 + AGENTS.md 剩余工作同步 (T6/R1-R6 完成态)。
  2. **N5b 批次 E** (优先, 含真 bug) — 记忆口径一致性: person_profiles 键分裂 (consolidator 平台 user_id vs 注入器 master_id)、租户/自定义 namespace 注入器读不到、`latest_episode_id_for_session` 租户包裹 SQL 报错、consolidator 软删同步 BM25/向量、embedding 维度错配部分提交误报、去重桶加 user_id、归纳产物防 prompt injection。
  3. **N5b 批次 C** — 插件生态专项: source 追踪/deregister、隔离崩溃重载、installer name 路径校验、AstrBot import 沙箱、MCP 工具名前缀防覆盖。
  4. **N5b 批次 D** — MCP Client 生命周期: reload 断开旧连接、stop→start 重连、initialize 握手、stdio 脏输出。
  5. **N5b 批次 F** — LLM 可控参数 clamp: wait/delegate/task 秒数、bash timeout、/mute 时长鉴权。
  6. **N5b 批次 G** — 适配器与零散: 飞书 p2p 私聊误判、Discord/Telegram 自身消息过滤、DELETE 不存在 agent 500→404 等。
- **准出**: ruff/mypy/全量测试绿; 批次 E 真 bug 附复现→修复→回归测试证据; 新增缺陷回归测试。
- **预估**: 3-4 轮。**可全部在本沙箱完成**。

#### Phase 1 工程验证 —— 真实环境跑通 (环境准入, 对应 N2)

- **目标**: 证明"能装、能跑、能诊断、不泄漏", 产出性能基线。
- **工作项**:
  1. **N2-1 Docker 冒烟** — `docker build` + `compose up` + `/health` 循环; pip/uv 单包 3 步安装验证 (T7)。
  2. **N2-2 browser CI 复核** — pytest-playwright + chromium 跑 `tests/browser/` 黄金路径, I 节点 85%→100%。
  3. **N2-3 release_checklist 七段** (除真实 IM 段) — CI 全绿/本地全量/文档同步/版本号一致/发布标签/回滚预案/监控预案。
  4. **N2-4 24h soak** — 真实 LLM key + 连续对话负载, 产出并发/延迟/内存/连接/任务泄漏基线; 顺带覆盖性能基线 (维度 8)。
  5. **LLM 兼容性矩阵** (新增) — 逐一实测 DeepSeek/通义/Kimi/智谱/MiniMax 的 chat/embedding/rerank base_url 与字段差异, 记入文档; 不兼容处加适配或文档注明。
  6. **可运维性验证** (新增) — 备份→恢复→升级→降级全流程真机演练; AlertManager→Webhook→送达端到端; ConfigMigrator 真实升级链验证。
  7. **用户文档补齐** (新增) — `docs/deployment.md` 细化、`docs/MAINTENANCE.md` 新建 (排查树/备份/升级)、各平台接入分步指南、FAQ。
- **准出**: 每项附命令+实际输出; 性能基线数据落 `docs/`; Docker 与 soak 证据。
- **预估**: 2-3 轮。**依赖**: docker daemon、浏览器环境、真实 LLM key。**本沙箱可先做**: N2-2 (pytest-playwright 可装)、用户文档、LLM 兼容性矩阵 (需 key)。

#### Phase 2 真实接入 —— IM 凭据联调 (对应 N3, 外部阻塞)

- **目标**: 从"适配器有单测"升级为"真机能收发"。
- **工作项**:
  1. **N3-1 凭据准备清单** (先发用户): OneBot/NapCat 测试 QQ、飞书自建应用 (encrypt_key+verification_token)、QQ 官方 (app_id+secret)、wecom (corpid/secret/agentid + 回调公网地址)。
  2. **N3-2 逐平台真机联调** — OneBot 先行 (私聊+群聊@+富媒体降级) → 飞书 → QQ 官方 → wecom; 每平台附收发实证。
  3. **N3-3 控制面连接状态回显** — Channel 实时状态经 `/health` 与 SSE 暴露。
- **准出**: 每平台真人连续对话 N 轮无异常栈、无消息丢失的实证。
- **预估**: 1-2 轮 (不含凭据等待)。**阻塞项**: 用户凭据 + 回调公网地址。

#### Phase 3 前端交付 —— 前后端分离完成 (对应 N4)

- **目标**: 管理者旅程完整落地, 移除内置 WebUI 静态托管。
- **工作项**:
  1. **N4-1 技术栈决策** — 框架/构建工具选型, 消费 `docs/api/openapi.json` 生成客户端。
  2. **F1** 项目初始化 + 登录页 + 首登强制设密码向导 (对接 `/setup` API + 428 gate)。
  3. **F2** 十域页面迁移 (配置编辑事务接真实 API + 乐观锁); 完成后移除后端 `control/webui/`。
  4. **F3** 实时日志台 (`/logs/tail` SSE) + 事件流页 (`/events/stream`)。
  5. **F4** 插件市场 UI (对接 T6 marketplace/install/reload/uninstall)。
- **准出**: 独立前端项目跑通管理者全旅程; 内置 WebUI 移除后主链路无回归。
- **预估**: 3-5 轮。**依赖**: N4-1 技术栈决策 (用户输入); 后端 API 基线已冻结可直接开工。

#### Phase 4 发布准入 —— GA 门禁 (对应 R7 收尾 + 安全/文档收口)

- **目标**: 满足全部 GA 准入条件, 可正式发布 v1.0。
- **工作项**:
  1. **release_checklist 七段全过** (含真实 IM 段, 依赖 Phase 2)。
  2. **REQUIREMENTS 十二条逐条取证复核** (仿 RELEASE_AUDIT 方法, GA 前终审)。
  3. **安全自查清单** (新增) — secrets 扫描 (无硬编码 key)、依赖漏洞扫描 (`uv pip audit` / pip-audit)、权限最小化复核、CSRF/CORS/SSRF 配置复核。
  4. **文档终审** — QUICKSTART/部署/运维/FAQ/平台指南齐全且经"未接触项目的人"复现验证。
- **准出**: 七段清单全绿 + 十二条 8✅→全✅ (或明确记录 ⚠️ 项为 GA 后计划) + 安全自查通过。
- **预估**: 1 轮。**依赖**: Phase 0-3 全部完成。

#### Phase 5 GA 后演进 —— 衔接 §四 GA 后开发计划 (V/X/Y/Z)

GA 达成后进入 V (功能广度) / X (生态商业化) / Y (智能演进) / Z (工程持续线), 详见 §四 GA 后开发计划, 本节不重复。

### 四、里程碑 (产品可用口径)

| 里程碑 | 判定 | 依赖 Phase |
|---|---|---|
| **M-P0 代码零已知缺陷** | 全部 Critical/Major 清零, 回归测试绿 | Phase 0 |
| **M-P1 工程验证通过** | Docker/soak/browser CI 全过 + 性能基线产出 | Phase 1 |
| **M-P2 真实 IM 可用** | 至少一个平台真机收发通过 | Phase 2 |
| **M-P3 管理者旅程完整** | 前端十域 + 登录向导 + 实时可用 | Phase 3 |
| **M-GA v1.0 正式版** | release_checklist 七段全绿 + 十二条取证 + 安全自查 + **U 节点组全过 + A+ 复评 (§三之五)** | Phase 0-4 全过 + U 节点组 |

**GA 充分必要条件** (2026-08-17 修订, 以 §三之五 为准): N2 全过 (M-P1) + N3 至少一个平台真机通过 (M-P2) + N4-F2 完成 (M-P3) + Phase 0 代码清偿 (M-P0) + release_checklist 七段全绿 + 十二条取证 + 安全自查 (Phase 4) + **U0-U9 架构演进全过 + A+ 复评达标 (U9)**。

### 五、关键路径、依赖与风险

- **关键路径**: Phase 0 (本沙箱可做) → Phase 1 → Phase 2/3 可并行 → Phase 4。**Phase 2 (IM 凭据) 与 Phase 3 (前端) 相互独立**, 可并行推进; Phase 4 依赖全部前置。
- **外部依赖 (阻塞项, 需用户提供)**: ① IM 凭据 + 回调公网地址 (Phase 2); ② 真实 LLM key (Phase 1 soak + 兼容性矩阵); ③ docker daemon + 浏览器环境 (Phase 1); ④ 前端技术栈决策 (Phase 3 N4-1)。
- **风险**: ① 凭据/环境等待会拉长 Phase 2 时间线 —— 缓解: Phase 0/1 不依赖凭据的部分先行, 凭据清单提前发用户准备; ② LLM 端点兼容性可能暴露协议差异 —— 缓解: Phase 1 兼容性矩阵提前实测, 差异早发现早适配; ③ 24h soak 可能暴露泄漏 —— 缓解: 尽早启动, 失败项转 N5b 新批次清偿。

---

## 三之五、架构演进与发布总纲 (2026-08-17 制定; 发布路径取代 §三之三/§三之四 的既有 M-GA 定义)

**背景**: 2026-08-17 完成 18 项目全景 Review 与 ISAC 深度 Review (见 §三 概况)。结论: 后端代码面收尾质量高 (两轮对抗审查 43 项修复逐条核实无虚报, 1826 测试函数、mypy 全绿), 但存在 **4 项安全实洞**与 **8 项架构问题**。项目负责人已拍板: **架构升级全部完成并复评达标后才发布 v1.0**, 不留过渡形态, 不估工时, 只按验收标准推进, 质量目标为稳定性/健壮性/可维护性/可扩展性/可升级空间/模块化全部 A+ 水准。

### 已拍板决策 (2026-08-17)

| # | 决策 | 选择 | 说明 |
|---|------|------|------|
| 1 | 会话存储形态 | **事件溯源 (SQLite 事件表)** | "银行流水式": 只追加不涂改、可回溯、崩溃可精确重放恢复; 与既有 SQLite 栈一致, 不引入新依赖 (落点 U1) |
| 2 | 发版时点 | **升级完再发版** | U0-U9 全部验收 + A+ 复评通过才发 v1.0; 过渡性止血方案 (临时滑动窗口等) 全部取消, 一步做到最终形态 |
| 3 | 群聊门控 LLM judge 模型档位 | **fallback 链最便宜档** | "要不要回复"判断任务简单, 小模型够用且成本近零 (落点 U3) |
| 4 | 模型能力清单数据源 | **models.dev 开源数据** | 覆盖 2700+ 模型、每周 CI 刷新、零维护; 个别国产新模型晚收录时手动补录兜底 (落点 U7) |

### 架构问题 vs 进度问题 (定性原则)

- **架构问题** = 做法本身需要升级的结构性缺陷, 归 U 节点组清偿, 计入架构评分;
- **进度问题** = 功能未完成, 做完即可, 归既有节点, 不计入架构评分。包括: mp 公众号/视频 Provider/Slack/前端 F1-F4/Docker 冒烟/24h soak/真实 IM 凭据联调/CHANGELOG 补齐/发布卫生等;
- 原列的 COMPRESS 触发面窄、滑动窗口缺失等债务**依附 U1 解决** (事件溯源后二者均为派生策略), 不单独立项。

**8 项架构问题 → U 节点映射**:

| 架构问题 | 现状评分 | 收敛节点 |
|---|---|---|
| 装配层反模式 (main.py 1832 行上帝模块 + 25 键无类型 services 袋) | 总体分层 B+ | U2 |
| 门控硬编码 (中文关键词表 + 权重钉死 constants.py) | 配置与门控 C+ | U3 |
| 可变持久化 (episodes 可覆盖写、gateway 诸库无 WAL、非事件溯源) | 持久化层 B- | U1 |
| 租户半隔离 (治理面/画像/行话无租户列, 靠调用方自觉) | 记忆系统 B | U4 (前哨 U0 Fix-85) |
| 工具权限静态化 (无 ask 档、无单调 guard、restricted 语义走样) | MCP B+ | U5 (前哨 U0 Fix-87/88) |
| 插件隔离非默认 (供应链插件默认宿主内 exec) | 插件与隔离 B | U6 (前哨 U0 Fix-86) |
| 对话上下文无结构位 (loop 无历史派生槽位) | 主循环 A- | U1 (窗口=派生策略) |
| 注入无仲裁 (四路写会话靠锁兜底, Fix-81/82 已两次补丁) | 主循环 A- | U8 |

### 推进顺序 (只按验收推进, 不估工时)

```
U0 安全清偿 (阻塞一切) → U1 事件溯源内核 (地基) → U4 → U5;
U2/U3/U6/U7/U8 可穿插 → U9 A+ 复评门禁 (最后);
N2 环境准入 / N3 真机联调 / N4 前端 的环境与凭据等待期与 U 节点并行利用, 不互斥。
GA 门槛以 U 节点组与环境准入两者都完成为准。
```

### v1.0 GA 门槛 (修订版, 取代 §三之三/§三之四 的 M-GA 定义)

v1.0 GA = 以下全部满足:

1. **U0-U8 全部 `[x]`** (按 §二完成定义: 非桩实现 + 单测 + 集成/真机验证 + 主链路接线 + 文档 + ruff/mypy/CI);
2. **U9 A+ 复评通过**: 按 `isac-deep.md` 同款方法 (只读代码级审查 + 实测) 逐模块复评 —— 无 C 项、B 项 ≤2、其余 A-/A+ 以上; "定义了未接线"零残留;
3. 原 GA 条件全部维持: N2 全过 + N3 至少一平台真机 + N4-F2 完成 + release_checklist 七段全绿 + REQUIREMENTS 十二条取证 + 安全自查;
4. 验收铁律适用: 每项附真机部署证据。

### 新增工程纪律 (2026-08-17, 已并入 §一 总则第 7/8 条)

1. 禁止"定义了未接线"的安全常量/机制 (lint 规则常驻, U9 落地);
2. 同构面核对清单 (每个安全修复交付前核对同类入口);
3. 红线指标只减不增: main.py 行数、services 袋键数、硬编码门控词条目数纳入 CI 监控 (U2/U3 落地)。

### 本轮经验来源 (18 项目全景 Review → U 节点映射)

- **U1** ← deepseek-harness 会话内核四件套 (append-only 事件日志 + surface 派生模型可见面 + 带 sourceEventSeqs 溯源的 replace 压缩 + 未知事件默认拒绝重建) + "Model-visible ⟺ Logged" (入站队列即持久事件) + 副作用前 flush; pi 三存储规范 (entries/registers/ledger + 持久化程序计数器) 互证;
- **U3** ← MaiBot 决策-表达分离 + grok-build decision_reason 词汇治理 (23 规范值 + drift test);
- **U4** ← 反面教材: deepseek-harness 单信任域空白; 正面: ISAC 自有 TenantIsolationGuard 升级为机制强制;
- **U5** ← deepseek-harness 工具权限集中管线 (pre-execute allow/deny/ask + 单调 guard + fail-closed 审批 + 权限预设事件溯源) + grok-build 决策理由规范词汇 + RikkaHub 消息内审批卡片范式;
- **U6** ← MaiBot Supervisor 隔离模式; ISAC 自有 PluginIsolationHost 转正为默认路径;
- **U7** ← oh-my-openagent 数据化三件套 (prompt 文件按模型族变体 + models.dev 能力快照生成管线 + category 路由);
- **U8** ← oh-my-openagent prompt-async-gate (预约表 + hold 窗口 + 编译器 AST 审计禁绕过) + deepseek-harness 治理门禁 (生成目录 + --check 漂移检测 + 无 key 快照回放)。

---

## 四、详细节点

### A 文档冻结

**目标**：让任何新加入的开发者/Agent 在不问人的情况下，能读懂架构、接口、流程和当前进度。

- [x] **A1 术语表与规范确认**
  - **验收**：`ARCHITECTURE.md` / `DEVELOP.md` / `SPECIFICATION.md` / 本文档无冲突；所有核心术语（AgentInstance、MessageRouter、InterAgentBus、启用矩阵等）已定义。
  - **产出**：`SPECIFICATION.md` 1.x 数据模型、`ARCHITECTURE.md` 3.x 组件、`DEVELOP.md` 目录/导入规则。
  - **交接**：术语定义集中在 `SPECIFICATION.md` 与本文档"术语表"章节。

- [x] **A2 架构蓝图 v3.0 定稿**
  - **验收**：多 Agent 架构图、控制面/数据面分离、Channel-Agent 解耦、记忆命名空间、插件兼容策略已写入 `ARCHITECTURE.md`。
  - **产出**：`ARCHITECTURE.md` v3.0 + ADR-007~011。
  - **依赖**：A1。

- [x] **A3 接口契约冻结**
  - **验收**：`isac/core/types.py` / `events.py` / `exceptions.py` 与 `SPECIFICATION.md` 完全一致；ABC/Protocol 签名稳定。
  - **产出**：`isac/core/` 下全部契约文件通过单测。
  - **依赖**：A2。

- [x] **A4 SOW 与 AGENTS.md 维护流程**
  - **验收**：本文件与 `AGENTS.md` 的"当前进度"表每次节点完成后同步更新；新增节点有明确的依赖与验收标准。
  - **产出**：本文档 + `AGENTS.md` 进度表。
  - **依赖**：A1-A3；持续进行。
  - **当前**：2026-07-23 复审发现历史完成状态与真实运行能力不一致，已新增 K 稳定化节点并撤回 I2/I5/I6 完成状态；后续节点只有满足强化后的完成定义才可标记 `[x]`。

- [x] **A5 专项施工图补齐**
  - **验收**：拟人化运行时、记忆系统、路由与 Agent Mesh、插件兼容、控制面五个关键系统有独立专项文档；主文档引用清晰。
  - **产出**：`HUMANLIKE_RUNTIME.md`、`MEMORY_DESIGN.md`、`ROUTING_AND_AGENT_MESH.md`、`PLUGIN_COMPATIBILITY.md`、`CONTROL_PLANE_SPEC.md`。
  - **依赖**：A2、A3。
  - **交接**：实现对应模块前必须先阅读专项文档，主文档仅保留总览与核心接口。

---

### B 基础骨架

**目标**：搭好可运行、可测试的项目骨架，让上层模块有地方放、有规范可循。

- [x] **B1 项目脚手架**
  - **验收**：`uv sync --all-extras --dev` 成功；`.github/workflows/ci.yml` 可运行 `ruff` / `mypy` / `pytest`。
  - **产出**：`pyproject.toml`、`.gitignore`、`LICENSE`、`README.md`、`AGENTS.md`、`.github/workflows/ci.yml`、`data/.gitkeep`、`scripts/` 桩。
  - **交接**：依赖环境已就绪，后续 Agent 直接 `uv run` 即可。

- [x] **B2 核心契约实现**
  - **验收**：`isac/core/{types,events,exceptions,constants}.py` 全部实现并通过单测。
  - **产出**：数据模型、事件枚举、错误体系、常量。
  - **依赖**：B1。

- [x] **B3 配置与日志系统**
  - **验收**：`data/config.jsonc` 可加载（默认值 + 环境变量覆盖）；logger 在 structlog 不可用时降级为 stdlib。
  - **产出**：`utils/config.py`、`utils/logger.py`、`utils/security.py`（SecretStore 桩）、`utils/helpers.py`。
  - **依赖**：B2。

- [x] **B4 入口与调试脚本（仅初始化骨架）**
  - **验收**：`python -m isac` 可执行初始化（无 Channel 时不报错）；`scripts/migrate.py` / `export.py` 有入口。应用常驻、信号处理和优雅关闭由 K1 重新验收。
  - **产出**：`isac/__main__.py`、`isac/main.py`（组装骨架）、`scripts/*`。
  - **依赖**：B3。
  - **当前边界**：实测 `main()` 打印“启动完成”后立即返回，不能视为持续运行的服务。

---

### C 连接与路由

**目标**：让 IM 消息能进入系统，并按规则路由到正确的 Agent。

- [x] **C1 OneBot 适配器实现**
  - **验收**：能通过 NapCat 连接 QQ，收发消息；消息转换覆盖 text/at/image/reply；有重连机制。
  - **产出**：`channel/adapters/onebot/adapter.py`、`tests/unit/test_onebot_adapter.py`。
  - **依赖**：B1-B4。
  - **交接**：
    - 已实现反向 WebSocket 模式，配置 `channels.onebot.enabled=true` 即可启用。
    - aiocqhttp 改为惰性导入，未安装 onebot extra 时不会导致启动崩溃。
    - 消息转换支持 text/at/image/reply/face/record；发送支持 text/at/image/reply/emoji/voice。
    - 重连逻辑在 `_run_with_retry`，连接建立时重置计数。
    - 真机联调仍需 NapCat + 测试 QQ + 在 `data/config.jsonc` 填写 `channels.onebot` 与 `bot_id`。

- [x] **C2 Gateway 会话与用户系统**
  - **验收**：EventBus Intercept/Async 双层工作；SessionManager 能创建/查找会话；UserMapper 跨平台映射；SessionLockManager 串行处理。
  - **产出**：`gateway/{event_bus,session,user_mapper,lock,models}.py`。
  - **依赖**：B2。

- [x] **C3 MessageRouter 与路由规则**
  - **验收**：路由优先级（显式绑定 > 触发词 > 默认 Agent > DROP）通过单测；触发词可剥离；`data/routing.jsonc` 可热更新。
  - **产出**：`router/{router,rules,types}.py`。
  - **依赖**：C2。

- [x] **C4 Channel 注册表**
  - **验收**：ChannelRegistry 能注册多个适配器、统一启停。
  - **产出**：`channel/registry.py`。
  - **依赖**：C1 骨架（C1 业务实现后可联调）。

---

### D 单 Agent 核心

**目标**：单个 Agent 能决定是否回复、组装 Prompt、调用 LLM、使用工具、记忆用户。

- [x] **D1 门控系统**
  - **验收**：GatingSystem.evaluate 流程正确；ReplyNecessityJudge 评分模型与文档一致；FocusMode/IdleBackoff/TurnScheduler 工作。
  - **产出**：`gating/{system,reply_necessity,idle_backoff,turn_scheduler,turn_gates,types}.py`。
  - **依赖**：B2。
  - **当前**：GatingSystem/IdleBackoff/FocusMode 已实现；ReplyNecessityJudge 完整评分模型已实现（基础分+内容分+压力分-存在感惩罚 × 频率系数，权重集中在 `core/constants.py`）；TurnScheduler 滑动窗口频率与存在感计数已落地（按 `window_seconds` 时间戳 deque，self_ratio 线性映射到 [FREQ_MIN, FREQ_MAX]，附 `tests/unit/test_turn_scheduler.py`）；`runtime/manager.py` 已接线 `record_window_message` / `effective_frequency` / `recent_self_replies` / `recent_window_messages` / `record_reply` / `idle_backoff.record_reply`。D1 整体验收通过。

- [x] **D2 Prompt 组装系统**
  - **验收**：SystemPromptBuilder 按 priority 注入；注入器频率控制工作；失败 Injector 不影响整体。
  - **产出**：`agent/{injector,prompt_builder}.py` + `agent/injectors/` 目录。
  - **依赖**：B2。

- [x] **D3 Agent Loop 主流程**
  - **验收**：ISACAgentLoop.run 完整执行 pre_llm → LLM → post_llm → tool/pre_tool/post_tool → final_response；预算耗尽可停止。
  - **产出**：`agent/loop.py`、`agent/hooks.py`。
  - **依赖**：D2。
  - **当前**：已接入 ProviderManager.chat_with_retry；PRE_LLM 钩子顺序串联。

- [x] **D4 工具系统与权限**
  - **验收**：ToolRegistry 注册/执行/权限检查通过测试；所有内置工具（send_emoji/send_image/query_memory/ask_agent/switch_chat/wait/fetch_history/view_forward_message/bash/read_file/write_file/web_search/task）可用。
  - **产出**：`agent/tools/{base,registry}.py` + `agent/tools/social/` / `utility/` / `mcp/` 下全部工具。
  - **依赖**：D3。
  - **当前**：ToolRegistry + ToolPermission 已实现；restricted 策略落地 (未注入对应后端时直接拒绝, 避免把 NotImplementedError 暴露给 LLM)；13 个内置工具全部实现——social 类经 `channel_send` / `channel_history` / `channel_forward` / `session_topic` 服务注入, utility 类 (bash/read_file/write_file/web_search/task) 经对应 services key 注入, 全部带路径白名单/命令白名单/递归深度限制。附 `tests/unit/test_builtin_tools.py` (18 测试) + `tests/unit/test_tool_registry.py` (8 测试, 含 restricted 策略、路径越权、shell 元字符注入防护)。

- [x] **D5 记忆存储引擎** (MVP)
  - **验收**：MetadataStore Schema 初始化成功；VectorStore/SparseBM25Index/GraphStore 可读写；全表按 agent_id 过滤。
  - **产出**：`memory/storage/{metadata,vector,sparse,graph}.py`。
  - **依赖**：B3。
  - **当前**：MetadataStore 完整实现 (episodes + FTS5 + person_profiles + jargon_entries，全表带 agent_id 命名空间)；SparseBM25Index 真实 BM25 打分；VectorStore 与 GraphStore 仍是 `NotImplementedError` 桩，接口签名齐备、占位待真实向量/图后端落地。附 `tests/unit/test_memory_metadata_store.py`、`tests/unit/test_sparse_bm25_index.py`。

- [x] **D6 记忆检索流水线** (MVP)
  - **验收**：MemoryRetrievalPipeline.search 实现 Embed → Dense + Sparse → RRF → Rerank；EmbeddingManager 降级机制工作。
  - **产出**：`memory/{pipeline,embedder,reranker}.py`。
  - **依赖**：D5。
  - **当前**：检索链路打通，RRF 融合 (FTS5 + Sparse) + Reranker 跳过分支工作；EmbeddingManager 恒 `is_degraded=True`、VectorStore 暂存空、Reranker `is_available=False`，当前为纯稀疏检索模式。降级路径与命名空间隔离已测 (附 `tests/unit/test_memory_pipeline.py`)；真实向量检索与 Reranker 后端待 H/I 阶段补齐。

- [x] **D7 记忆注入器**
  - **验收**：HeuristicMemoryInjector 3min/60msg 频率工作；PersonProfile/Jargon/MidTerm 注入正确格式化。
  - **产出**：`memory/injector/{heuristic,person_profile,mid_term,jargon,base}.py`。
  - **依赖**：D6、D2。
  - **当前**：四个注入器全部实现并通过测试 (`tests/unit/test_memory_injectors.py`、`tests/unit/test_prompt_builder_memory_frequency.py`)；已接入 `runtime/assembly.py`；`HeuristicMemoryInjector` 频率控制 (`max_frequency_seconds` / `max_new_messages`) 由 `PromptInjector` 基类统一调度。

- [x] **D8 人格系统**
  - **验收**：PersonaManager 合并全局与 Agent 覆盖；MoodEngine 情绪更新/衰减；BehaviorLearner 注册 FINAL_RESPONSE hook。
  - **产出**：`persona/{manager,drift_profiles,style_profiles,mood,behavior_learner}.py`。
  - **依赖**：D2、D3。
  - **当前**：PersonaManager 合并全局/Agent 覆盖并聚合 MoodEngine + BehaviorLearner; MoodEngine 实现 update (valence/arousal 钳制 + 离散 label 映射) 与 decay (按 decay_rate 向中性衰减); BehaviorLearner 注册 FINAL_RESPONSE hook 从回复提取行为特征 (长度/emoji/话题) 写入 UserProfile.behavior_patterns, 带 max_patterns 滚动淘汰。已在 `runtime/assembly.py` 接线 `persona.register_hooks(hooks)`。附 `tests/unit/test_persona.py` (15 测试)。
  - **2026-07-26 MVP 缺口复核**：`AgentConfig.persona` 文本从未接入 `BaseIdentityInjector`(该注入器恒注入 locales 通用文案),两个 Agent 的人格差异在 Prompt 层不可见;`MoodInjector`/`ExpressionStyleInjector`/`AttentionDriftInjector` 是返回空串的桩且未注册进 `prompt_builder`(`assembly.py` 自认"待落地"),`MoodEngine.update/decay` 与 `PersonaManager.get_expression_style/get_drift_level` 全仓无生产调用点,既无注入也无更新回路;`BehaviorLearner` 写的 `behavior_patterns` 也无消费者。人格系统在读侧(合并/存储)完整,但对话可感知的差异化实际不存在。补齐见 **Q2**。

- [x] **D9 任务进度报告**
  - **验收**：Agent Loop 在工具完成/失败后产生 `ProgressEvent`；慢工具可在执行前报告；`ProgressReporter` 完成人格模板渲染、敏感信息过滤、2 秒默认频控、连续事件合并和每任务上限；WebChat 输出原生 `progress` 事件，普通 IM 降级为带 `message_kind=progress` 的文本；发送失败不阻断主任务；中断后不再发送旧任务进度。
  - **产出**：`runtime/progress.py`、Agent Loop/Runtime/Channel 接线、Persona 进度模板、配置项及单元/集成测试。
  - **依赖**：D3、D4、D8、C1。
  - **当前**：业务实现已落地，满足强化完成定义。`runtime/manager.py::handle_message()` 消费 `progress_reporter_factory` 按 session 复用 `ProgressReporter` 并绑定 `main.py` 构造的 Channel sender；`AgentContext.services` 携带每次处理独立生成的 `task_id`。Agent Loop 补齐 6 个契约阶段：`planned`（本轮首次出现工具调用时）、`tool_started`（哨兵任务在 `slow_tool_threshold_seconds` 后触发、工具完成即取消）、`tool_finished`/`tool_failed`（沿用既有提交点）、`completed`/`interrupted`（仅当本轮已报告过 `planned` 才收束，避免无工具调用的简单回复产生噪音）。`ProgressReporter._merge()` 在 `merge_window_seconds` 内合并同 task 同 stage 的相邻事件（拼接 `tool_name` 复用既有模板）；任务 `completed`/`interrupted` 后把 `task_id` 计入短期黑名单，丢弃迟到旧进度并清理按 task 累积的字典。`PersonaProgressRenderer` 的 `llm` 模式在注入 Provider 时受 3 秒超时约束改写文案，超时/异常/空响应均回退模板。`WebChatAdapter` 的 `poll_replies()` 按 `metadata.message_kind` 输出 `kind="message"|"progress"` 帧（progress 帧附 `task_id`/`progress_stage`）；普通 IM 复用现有 `adapter.send()`，sender 侧已附带 `message_kind=progress` metadata，adapter 本身无需改动。覆盖：`tests/unit/test_progress_reporter.py`、`tests/unit/test_runtime_manager.py`、`tests/unit/test_platform_adapters.py`、`tests/unit/test_runtime_assembly.py`、`tests/integration/test_single_agent_flow.py`。
  - **边界**：默认模板渲染不额外调用 LLM；可选 LLM 改写受预算、超时和降级策略约束。进度不包含 reasoning、原始工具参数或未清洗结果，也不计入普通回复频率和行为学习。

---

### E 多 Agent 运行时

**目标**：多个 Agent 实例独立运行，共享 Channel，按需互联。

- [x] **E1 AgentConfig 与配置分层**
  - **验收**：`data/agents/<id>/config.jsonc` 可加载；全局/Agent/环境变量三层覆盖正确。
  - **产出**：`runtime/config.py`。
  - **依赖**：B3。

- [x] **E2 AgentManager 生命周期**
  - **验收**：create/start/stop/destroy/list/reload_config 工作；无 `data/agents/` 时创建默认 Agent。
  - **产出**：`runtime/manager.py`、`runtime/instance.py`、`runtime/assembly.py`。
  - **依赖**：E1、D1-D4（需要可组装的子系统）。
  - **当前**：memory_factory 使用 NoOpMemoryPipeline，保证默认 Agent 可创建/启动。

- [x] **E3 InterAgentBus 与 ACL**
  - **验收**：Link ACL 默认拒绝；ask_agent 工具受 ACL 约束；handoff/notify 消息类型可识别。
  - **产出**：`runtime/bus.py`、`agent/tools/social/ask_agent.py`。
  - **依赖**：E2。

- [x] **E4 启用矩阵生效**
  - **验收**：AgentConfig.plugins_allow/deny、tools_policy、commands_allow、mcp_servers 在 Agent 运行时真正生效；Channel 级矩阵参与计算。
  - **产出**：`plugin/runtime/manager.py`、`commands/registry.py`、`agent/tools/registry.py` 联动逻辑。
  - **依赖**：E2、F4 骨架、D4。
  - **当前**：`core/policy.py` 新增 `EnableMatrix` 类实现有效权限计算 (Agent ∩ Channel ∩ 全局); `ToolRegistry` 接入 effective_policy (Channel deny/restricted 优先); `CommandRegistry` 启用矩阵注入 enable_checker; `runtime/assembly.py` 把 EnableMatrix 注入 ToolRegistry + 构造 CommandRegistry 注册 4 个内置命令; `runtime/manager.py` 在 handle_message 中接入命令拦截 (/cmd 跳过门控直接执行)。附 `tests/unit/test_enable_matrix.py` (14 测试覆盖 plugin/tool/command/mcp 四类矩阵决策)。
  - **2026-07-26 MVP 缺口复核**：tool/command 两臂矩阵在生产真实生效,但 **plugin 臂未接线** —— `PluginManager` 构造时未传入 `EnableMatrix`(`plugin/runtime/manager.py:105-107` 的 `is_enabled_for` 硬编码放行 `["*"], []`),`plugins_allow`/`plugins_deny` 对已加载插件的 hooks 完全不生效;**mcp 臂**(`is_mcp_enabled`)也全仓零生产调用点(因为 MCP Client 本身未接线,见 H2)。补齐见 **Q3**。

- [ ] **E5 多 Agent 集成测试（并入 K6 验收）**
  - **验收**：2+ Agent × 1 Channel + 触发词/默认 Agent 路由 + ask_agent 互联端到端通过，并验证重启恢复、权限与记忆隔离。
  - **产出**：`tests/integration/test_multi_agent.py`。
  - **依赖**：K1-K5、C1、E3、E4。

---

### F 插件生态

**目标**：兼容 AstrBot / MaiBot 存量插件，同时提供更强的原生 SDK。

- [x] **F1 AstrBot 兼容层**
  - **验收**：3 个简单 + 2 个复杂 AstrBot 插件可直接运行；Star/Context/EventType/FunctionTool 桥接工作。
  - **产出**：`plugin/compatibility/astrbot/{star,context,events,tools,sandbox}.py`。
  - **依赖**：B2、D3、D4。
  - **当前**：FunctionToolAdapter 桥接 @filter.llm_tool 函数 → ISAC Tool (同步/异步/异常隔离); ContextAdapter 映射 send_message/get_platform/get_provider/register_tool 到 ISAC services; Star 基类与 _FilterRegistry 实现 AstrBot 装饰器 (llm_tool/on_message/on_llm_request); events.py EventType 映射到 ISAC EventType/AgentHookPoint; sandbox.py meta_path 拦截 astrbot.* import 重定向。附 `tests/unit/test_astrbot_compat.py` (9 测试覆盖装饰器/桥接/Context 适配)。
  - **2026-07-26 MVP 缺口复核**：桥接组件本身(`FunctionToolAdapter`/`ContextAdapter`/`Star`/`_FilterRegistry`)已实现且有单测,但生产 `plugin/runtime/loader.py` 只识别格式并 `exec_module` 实例化,**从不调用这些桥接逻辑**做真正的注册;已加载的 AstrBot 插件是惰性实例,`@filter.llm_tool`/`@filter.on_message` 等装饰器标记的 handler 永不被生产事件触发,`sandbox.install_sandbox` 也无调用点。补齐见 **Q3**。

- [x] **F2 MaiBot 兼容层**
  - **验收**：2-3 个 MaiBot 插件可运行；Plugin/Action/Command 映射工作；锁定兼容版本。
  - **产出**：`plugin/compatibility/maibot/{plugin,actions,commands}.py`。
  - **依赖**：B2、D3、`commands/`。
  - **当前**：MaiBotPlugin 基类 + @register_action / @register_command 装饰器 (标记 _maibot_action / _maibot_command); MaiBotPluginAdapter 扫描装饰器并 adapt 到 ToolRegistry / CommandRegistry; bridge_action (MaiBotActionAdapter) 桥接 Action → ISAC Tool (同步/异步/异常隔离); bridge_command (MaiBotCommandAdapter) 桥接 Command → ISAC Command。附 `tests/unit/test_maibot_compat.py` (6 测试覆盖装饰器扫描/Action 桥接/Command 桥接)。
  - **2026-07-26 MVP 缺口复核**：与 F1 同源问题 —— `MaiBotPluginAdapter.adapt` 只被单测调用,生产 `loader.py` 加载 MaiBot 插件后不调用它;插件里 `@register_action`/`@register_command` 标记的能力在生产是死代码。`PLUGIN_COMPATIBILITY.md` §7.3 描述的 `enqueue_proactive_task` 映射也全仓无实现。补齐见 **Q3**。

- [x] **F3 原生 SDK v2**
  - **验收**：ISACPlugin 可注册 Commands/InterAgent Hooks/Admin Routes(预留)；Plugin Manifest 扩展字段生效。
  - **产出**：`plugin/native/{plugin,hooks,api}.py`。
  - **依赖**：B2、E3。
  - **当前**：PluginContext 实现 register_tool/injector/command 真实注册到 ToolRegistry/CommandRegistry/SystemPromptBuilder; register_inter_agent_hook 挂到 InterAgentBus; register_admin_route 收集到 services["admin_routes"] 待 G1 消费; on_event_intercept/on_event_async 订阅 EventBus。make_plugin_context 工厂在 PluginManager 加载时调用。附 `tests/unit/test_native_plugin.py` (9 测试)。
  - **2026-07-26 MVP 缺口复核**：`PluginContext` 的 `register_tool/register_command/register_injector` 实现真实存在,但生产 `main.py` 构造 `PluginContext` 时把 tools/commands/prompt_builder 三个注册表显式留 `None`(`main.py:750-755` 注释明示),`plugin/native/plugin.py` 里 `register_tool` 等方法在注册表为 `None` 时 `raise RuntimeError` —— 插件唯一能真正注册工具/命令/注入器的入口在生产环境不可用;`register_admin_route` 收集的路由也无人挂载到 control app。`CR3-H2` 已接线的是 `on_load` 生命周期调用本身,不含这三类注册表的生产绑定。补齐见 **Q3**(复用 `assembly.py:100-104` 已验证的 `plugin_agent_hooks` 共享注册表模式)。

- [x] **F4 插件加载器与启用矩阵**
  - **验收**：loader 自动识别三种格式；PluginManager 热重载、错误隔离、启用矩阵生效。
  - **产出**：`plugin/runtime/{manager,loader}.py`。
  - **依赖**：F1-F3。
  - **当前**：PluginLoader 实现 detect_format (manifest.jsonc/metadata.yaml/mai_plugin.yaml 三选一) + load (按格式找对应基类子类并实例化, 多签名兜底); PluginManager 实现 load_all (错误隔离, report 用目录名作 key 解耦) / unload (on_unload 调用) / call_on_load (Native 插件 on_load 传入 PluginContext) / is_enabled_for (EnableMatrix); LoadedPlugin 含 name/format/instance/manifest/path 元数据。附 `tests/unit/test_plugin_loader.py` (12 测试覆盖三种格式 detect/load + 错误隔离 + unload)。

---

### G 控制面与自动化

**目标**：提供 Admin API / MCP Server / Webhook，支撑商业化自动化。

- [x] **G1 Admin API 完整实现**
  - **验收**：Token 认证、审计日志、agents/routing/plugins/links 端点真正生效并持久化；FastAPI docs 可用。
  - **产出**：`control/api/{server,routes_agents,routes_routing,routes_plugins}.py`、`control/auth.py`、`control/audit.py`。
  - **依赖**：E2、E3、C3。
  - **当前**：control/auth.py verify_token 用 hmac.compare_digest 恒定时间比较; make_auth_dependency 构造 FastAPI Bearer 依赖; control/audit.py AuditLog 双写 (structlog + data/audit.ndjson) + 内存 deque + query 接口; routes_agents POST/PUT/DELETE 全部审计 + AgentConfig 持久化到 data/agents/<id>/config.jsonc; routes_routing PUT routing/rules 持久化 + POST/DELETE links 持久化到 data/links.jsonc; routes_plugins PUT plugins 矩阵持久化到 AgentConfig; server 注入 auth/audit + 暴露 /api/v1/audit 查询接口 + /health + /docs。附 `tests/unit/test_admin_api.py` (9 测试覆盖 Token 认证/Agent 生命周期审计/路由与 Link 持久化/插件矩阵持久化)。

- [x] **G2 ISAC MCP Server**
  - **验收**：可用任意 MCP 客户端完成 "创建 Agent → 绑定 Channel → 设置默认 Agent"。
  - **产出**：`control/mcp_server.py`。
  - **依赖**：G1。
  - **当前**：ISACMCPServer 实现 JSON-RPC 2.0 + stdio NDJSON 传输 (sys.stdin/stdout.buffer 简化模式); initialize / tools/list / tools/call / shutdown 方法分发; tools/call 受 Bearer Token 认证 (与 G1 Admin API 共用 verify_token); agent_create/agent_start/agent_stop/link_create/link_delete/route_set_default 6 个工具委托到 AgentManager/Router/Bus; MCPError 异常体系 + 标准 JSON-RPC 错误码 (-32601/-32602/-32603/-32700/-32001); notification (id 为 None) 不响应。附 `tests/unit/test_mcp_server.py` (11 测试覆盖 initialize/tools_list/Token 认证/tools 调用/notification/MCPError)。

- [x] **G3 Webhooks 与自动化触发器**
  - **验收**：message.received/agent.created 等事件可推送到订阅 URL；`/automation/trigger` 入口可用。
  - **产出**：`control/webhooks.py`。
  - **依赖**：G1。
  - **当前**：WebhookManager 实现 subscribe/unsubscribe/list_subscriptions/dispatch/trigger; dispatch 并发推送 (asyncio.gather), 失败重试 3 次 (指数退避); httpx 惰性导入 (生产) 或 http_client 注入 (测试 mock); trigger 作为 /automation/trigger 入口委托到 dispatch。附 `tests/unit/test_webhooks.py` (9 测试覆盖订阅/取消/推送/重试/部分失败/trigger)。

- [x] **G4 控制面安全与审计**
  - **验收**：默认 127.0.0.1；自动化创建 Agent 使用受限默认配置；审计日志可查询。
  - **产出**：`control/defaults.py` 审计中间件、日志查询接口。
  - **依赖**：G1。
  - **当前**：control/defaults.py 新增 RESTRICTED_TOOLS_POLICY (bash/task deny, read_file/write_file restricted) + RESTRICTED_COMMANDS_ALLOW (focus/mute/unmute); make_restricted_agent_config 工厂供自动化场景 (MCP/Webhook) 使用, 默认 plugins_deny=["*"] + mcp_servers=[]; is_safe_default_host/enforce_safe_host 防止误绑定 0.0.0.0/外网 IP; main.py _start_control_plane 接入 enforce_safe_host。审计日志查询接口已在 G1 落地 (/api/v1/audit endpoint)。附 `tests/unit/test_control_defaults.py` (16 测试覆盖受限策略表/构造工厂/extra 覆盖/未知字段忽略/安全地址判定)。

---

### H 平台与工具扩展

**目标**：支持更多 IM 平台，扩展工具能力。

- [x] **H1 更多平台适配器**
  - **验收**：Telegram / Discord / WebChat 适配器可收发消息。
  - **产出**：`channel/adapters/{telegram,discord,webchat}/`。
  - **依赖**：C1。
  - **当前**：TelegramAdapter 用 Bot HTTP API long polling + httpx 惰性导入; 私聊/群聊识别 + @mention entity 转 at segment; DiscordAdapter 用 REST polling (简化版, 生产推荐接入 discord.py 或 Gateway); WebChat 用 asyncio.start_server 极简 HTTP 实现 (/webchat/send + /webchat/poll), 不依赖外部 web 框架, 内存消息队列 + 过期清理。附 `tests/unit/test_platform_adapters.py` (13 测试覆盖三种适配器消息转换 + send + token 缺失兜底)。
  - **2026-07-26 MVP 缺口复核**：三个适配器本身"可收发消息"这一验收标准(单测层面)成立,但生产入口 `main.py` 只有 `channels.onebot` 一个注册分支,`TelegramAdapter`/`DiscordAdapter`/`WebChatAdapter` 全仓零生产实例化点(`config.sample.jsonc` 里 `channels.webchat.enabled=true` 是死配置);开箱部署事实上只有 OneBot(需外部 NapCat+QQ 号)一条可用通道,零外部依赖的 WebChat 摸不到。补齐见 **Q0**(main() 各加一个注册分支,~5 行 × 3)。

- [x] **H2 MCP Client**
  - **验收**：可连接外部 MCP Server；工具按 Agent mcp_servers 矩阵生效。
  - **产出**：`agent/tools/mcp/client.py`。
  - **依赖**：D4、E4。
  - **当前**：MCPClient 支持两种传输 (stdio 子进程 + HTTP/SSE); connect 启动子进程或 httpx.AsyncClient; list_tools 发现 MCP 工具并桥接为 MCPToolBridge (实现 ISAC Tool 接口); call_tool 转发 JSON-RPC tools/call + 错误处理 (jsonrpc error → is_error=True); disconnect 终止子进程 / 关闭 httpx + 取消 pending future。stdio 模式后台读 stdout NDJSON 并分发到 pending future。Agent 的 mcp_servers 启用矩阵在 E4 EnableMatrix 落地。附 `tests/unit/test_mcp_client.py` (9 测试覆盖 connect 各传输 + list_tools + call_tool 正常/错误/未连接 + MCPToolBridge 桥接)。
  - **2026-07-26 MVP 缺口复核**："Agent 的 mcp_servers 启用矩阵在 E4 EnableMatrix 落地"仅指判定逻辑(`is_mcp_enabled`)存在,`MCPClient` 本身**全仓无生产 import**——`AgentConfig.mcp_servers` 配置该字段对生产没有任何效果,`assembly.py` 从不构造/`connect`/把 `list_tools` 结果注册进 Agent 的 `ToolRegistry`。补齐见 **Q3**。

- [x] **H3 实用工具与子 Agent**
  - **验收**：bash/read_file/write_file/web_search/task 可用；受限策略（项目目录/递归深度）生效。
  - **产出**：`agent/tools/utility/*.py`。
  - **依赖**：D4。
  - **当前**：bash (命令白名单 + shell 元字符注入防护) / read_file (路径白名单 + 行范围 + 64KB 上限) / write_file (路径白名单 + 256KB 上限 + append) / web_search (经 services["web_search"] 注入后端) 全部在 D4 落地; task 工具在 D4 实现受限框架, 本节点补 TaskRunner 真实实现 (用 ISACAgentLoop 派生子任务, 限制 token 预算与递归深度)。附 `tests/unit/test_utility_integration.py` (11 测试覆盖 write→read 往返 / 路径越权 / append / bash 白名单 / 元字符防护 / web_search 缺后端与注入 / task_runner 调用与递归深度)。

---

### I 生产化与交付

**目标**：项目达到生产可用，可部署、可维护、可商业化。

- [x] **I1 WebUI 管理面板**
  - **验收**：FastAPI 静态托管的最小 WebUI 可管理 Agent/路由/Link 并查看审计；完整管理面能力由 J3 验收。
  - **产出**：`control/api/` 扩展 + WebUI 前端。
  - **依赖**：G1。
  - **当前**：采用 FastAPI 静态托管 + Vanilla JS (不依赖 Vue 构建工具链) 实现单页管理面板; control/webui/{index.html, app.js, __init__.py} 含 Agent 管理 (创建/启动/停止/删除)、路由规则更新、互联 Link 添加/删除、审计日志查询四个模块; server.py mount_webui 把 /ui 挂载到 FastAPI app。当前 Bearer Token 存在 localStorage 的实现仅作为 v1 开发态遗留，J3 必须迁移到 HttpOnly Session Cookie + CSRF，不得沿用到生产。附 `tests/unit/test_webui.py` (5 测试覆盖 index.html/app.js 静态返回 + 4 个模块齐全 + 端到端 API 工作流)。

- [ ] **I2 Docker 部署（K8 重新验收）**
  - **验收**：Dockerfile + docker-compose.yml 一键启动；含控制面端口。
  - **产出**：`Dockerfile`、`docker-compose.yml`、部署脚本。
  - **依赖**：I1（可选）。
  - **当前**：Dockerfile/Compose/部署脚本和文本级单测已存在，但主进程会立即退出，尚无真实 Docker build/start/health smoke test，因此撤回完成状态。K1 完成常驻生命周期、K8 完成容器实测后重新验收。

- [x] **I3 文档完善**
  - **验收**：使用文档、API 文档、部署文档、插件开发指南、控制面自动化指南齐全。
  - **产出**：`docs/` 或更新根目录 README/ARCH/DEVELOP/SPEC。
  - **依赖**：F、G 完成。
  - **当前**：新增 docs/ 目录含 6 篇文档: README.md (导航) + usage.md (使用文档 - 配置详解/运行/维护) + deployment.md (Docker 部署 - 镜像构建/数据卷/生产建议/nginx 反代) + api.md (Admin REST API 文档 - Agent/路由/Link/插件/审计/健康检查) + plugin_development.md (插件开发指南 - ISAC Native/AstrBot/MaiBot 三格式) + control_automation.md (控制面自动化 - REST/MCP/Webhooks 集成)。附 `tests/unit/test_docs.py` (22 测试覆盖文档存在 + 内容完整性 + 关键章节)。

- [x] **I4 数据工具**
  - **验收**：AstrBot/MaiBot → ISAC 迁移、备份/导出/导入可用。
  - **产出**：`scripts/migrate.py`、`scripts/export.py`。
  - **依赖**：D5-D7。
  - **当前**：scripts/migrate.py 实现 migrate_from_astrbot (LLM 配置从 cmd_config.json/llm_model.json 解析, 插件目录复制, 写出 ISAC config.jsonc) + migrate_from_maibot (config.toml 解析, 记忆目录备份, 创建默认 Agent 配置); 支持 --dry-run; scripts/export.py 实现 export_data (zip 打包, 默认排除 audit.ndjson + .venv + __pycache__) + import_data (解压恢复, 支持 --overwrite); 子命令模式 (export/import)。附 `tests/unit/test_data_tools.py` (11 测试覆盖 AstrBot LLM 迁移 + dry-run + 插件复制, MaiBot config.toml 解析 + 默认 Agent, export 含/排除日志, import 恢复 + skip/overwrite + 排除 venv/pycache)。

- [ ] **I5 监控告警（K1/K8 重新验收）**
  - **验收**：关键指标 Prometheus 采集；Webhook 告警；审计日志查看。
  - **产出**：监控中间件、告警配置。
  - **依赖**：G1、G4。
  - **当前**：MetricsCollector、AlertManager、默认规则与指标端点已有基础实现，但主进程结束时后台告警任务随事件循环取消，且缺少真实消息→指标→告警→Webhook 的端到端验证。K1/K8 完成后重新验收。

- [ ] **I6 可用版本验收与发布**
  - **验收**：核心模块覆盖率 ≥80%；集成测试通过；v1.0 发布。
  - **产出**：CHANGELOG、Git tag v1.0.0。
  - **依赖**：A-I5。
  - **当前**：2026-07-23 复审实测 378 个单元测试通过、Ruff 通过，但 Mypy 因 `aiocqhttp` 缺类型声明失败；`tests/integration/` 为空；主进程不驻留；真实 LLM Provider 不可用；Docker/WebUI 未做真实运行验收。因此撤回“v1.0 已完成/生产可用”结论，项目定位为 Alpha，待 K1-K8 全部通过后重新确定版本号与发布资格。

---

### J 模型能力、计量与管理面增强

**目标**：统一模型能力接入与选择，完整记录模型用量，并将运行状态和配置安全地暴露到 WebUI。

- [x] **J1 模型用量与成本计量**
  - **验收**：LLM/Embedding/Reranker/STT/TTS/ImageGen/Video 的每次物理请求均产生 `ModelUsageEvent`；重试、回退、失败和缓存 Token 可区分；支持按 Provider/模型/Agent/会话/模态/时间聚合；价格快照可追溯；未知价格不伪造成本；写入失败不阻塞主调用。
  - **产出**：`observability/usage/{models,recorder,storage,pricing}.py`、SQLite Schema、ProviderManager 接线、Usage REST API、指标与测试。
  - **依赖**：B2、G1、I5。
  - **当前**：已完成 (2026-07-25)。`TokenUsage`（`core/types.py`）补齐 `cache_read/cache_write/reasoning/audio_{input,output}_tokens` 明细字段；`OpenAICompatProvider` 从 `prompt_tokens_details`/`completion_tokens_details` 解析这些字段（非流式 + SSE 流式）。`PricingCatalog.estimate_cost()` 按分档单价计算缓存/音频 Token 成本（子集扣除，避免重复计价），未配置分档价时回退基础 input/output 价。`ProviderManager.chat_with_retry()`/`_call_and_record()` 贯穿 `agent_id`/`session_id`/`trace_id`（复用 D9 的 `task_id`）/`request_id`（每次物理尝试独立生成）/`fallback_from`；新增 `record_stream_result()` 补齐此前完全绕过计量的流式调用路径（`agent/loop.py::_call_llm_streaming()`，成功/失败都记录）。`UsageStore`：Schema 迁移（`_ensure_column` 补 5 个明细列）、`insert_many()` 批量提交替代逐事件 commit、`list_events()` 分页查询、`aggregate()` 真实多维聚合（`group_by` 走固定白名单防注入，`time_bucket` 按 hour/day 分桶，全空结果返回 `[]` 而非幻影汇总行）。`UsageRecorder` 新增 `start()`/`stop()`/`_flush_loop()` 周期性 flush（仿 `AlertManager._check_loop`），`main.py` 按 `observability.usage.flush_interval_seconds` 配置并保证 start/stop 顺序不丢最后一批事件。新增 `control/api/routes_usage.py` 提供 `GET /usage/models/{summary,events,timeseries}`，`create_control_app()` 仅在 `usage_store` 非 `None` 时挂载。测试：`tests/unit/test_usage_recorder.py`、`tests/unit/test_usage_storage.py`、`tests/unit/test_control_api_usage.py`、`tests/unit/test_provider_manager.py`、`tests/unit/test_openai_compat_provider.py`、`tests/unit/test_core_types.py`、`tests/integration/test_single_agent_flow.py`（全链路 process_message → ... → chat_with_retry → flush → aggregate 按 agent_id 查得用量）。Embedding/Reranker/STT/TTS/ImageGen/Video 的 `ModelUsageEvent` 埋点留给 J2（真实多模态调用路径落地时一起补，当前这些 Provider 仍是 J2 范畴的桩，没有可埋点的真实调用链路）。
  - **2026-07-26 MVP 缺口复核**：J2 完成后,`UsageRecorder` 已补 `record_image_gen/stt/tts/video/embed/rerank` 6 个方法(见 J2 当前),但生产**零调用点**——多模态工具(`agent/tools/media.py`)直连 Provider,不经过计量边界;`PricingCatalog` 在生产恒空快照(`main.py` 构造 `PricingCatalog()` 不加载任何价目表),`estimated_cost` 恒为 `None`。补齐见 **Q4**。

- [x] **J2 多模态 Provider 与能力选择**
  - **验收**：文本、视觉理解、STT、TTS、图片生成、视频理解/生成 Provider 使用统一注册与能力声明；Agent 只感知被授权能力；输入内容、用户意图、成本/延迟策略可选择模型；不可用时按能力回退或明确失败；生成结果经制品存储和 Channel 能力适配发送。
  - **产出**：Provider 能力目录、ModelRouter、多模态 Provider ABC/适配器、能力 Injector、媒体工具、ArtifactStore、权限与测试。
  - **依赖**：D2-D4、E1/E4、H1、J1。
  - **当前**：已完成 (2026-07-25)。通用多模态 Provider 框架落地: 所有 Provider (image_gen/stt/tts/embed/vision) 接受用户配置的 `api_base + api_key + model`, 可接任意 OpenAI 兼容端点; 测试用 httpx.MockTransport 不依赖真实 Key。
    - **ModelRouter 打分排序** (`isac/provider/router.py`): 过滤链 operation→modalities→authorization→cost_ceiling→latency_target→health; 综合分 `score = (4-cost_rank)*2.0 + (2-latency_rank)*1.0 + health*1.5 + pref*0.5`; `record_health()` 上报 provider 健康状态, `set_preference()` 用户偏好加权; `ModelSelection.reason` 输出各因子明细。
    - **ArtifactStore 本地 FS + TTL** (`isac/artifacts/store.py`): 路径 `data/artifacts/<sha256[:2]>/<sha256>.bin` (分桶避免单目录文件过多); SQLite 元数据 `meta.db` (artifact_id PK + expires_at 索引); `put` 写盘幂等 (sha256 决定性, 重复 put 不覆盖); `get` 探测过期则删文件+DB 行并返回 None; `sweep_expired()` 周期扫描; `start_ttl_sweep()/stop()` 生命周期对齐 ApplicationRuntime; `ArtifactRef` 新增 `expires_at` 字段, 默认 7 天 TTL 可配。
    - **MediaNormalizer** (`isac/utils/media.py`): MIME 推断 (mimetypes.guess_type) + 路径白名单 (默认 data/artifacts/, 可配置多个 allowed_dirs) + 大小上限 (image 25MB / audio 50MB / video 200MB / file 50MB) + expected_kind 校验 + URL 输入拒绝 (J2 不做入站 HTTP 下载) + magic-byte 头部签名校验 (2026-08-16 清偿架构债: png/jpeg/gif/mp3/wav/ogg/flac/mp4/webm 防扩展名伪造, 未登记 MIME 跳过)。
    - **多模态 Provider 真实实现**:
      * `OpenAICompatImageGenProvider` (`isac/provider/image_gen/openai_compat.py`): POST /images/generations, b64_json/url 两种响应格式都支持, 生成图片写入 ArtifactStore 返回 ArtifactRef 列表。
      * `OpenAICompatSTTProvider` + `OpenAICompatTTSProvider` (`isac/provider/stt_tts/openai_compat.py`): STT multipart 上传 /audio/transcriptions 返回 TranscriptionResult; TTS POST /audio/speech 返回音频 bytes 存 ArtifactStore 返回 ArtifactRef。
      * `OpenAICompatEmbeddingProvider` (`isac/provider/embed/openai_compat.py`): POST /embeddings, 解析 data[].embedding, 维度从首次响应推断缓存。
      * `OpenAICompatProvider.vision_chat` (`isac/provider/llm/openai_compat.py` 扩展): 把 MediaInput 图片转 base64 data URL, 构造 messages[0].content 为 list 格式 (text + image_url), 委托 chat() 走既有非流式 chat 路径。
      * `memory/{embedder,reranker}.py` 改为注入 Provider 实例 (向后兼容, 未注入时保持降级行为与 D6 一致)。
      * 错误分类复用 OpenAICompatProvider._map_http_error / _wrap_network_error (429 RateLimitError / 5xx retriable / 4xx non-retriable / 超时 retriable)。
    - **UsageRecorder 多模态计量** (`isac/observability/usage/recorder.py`): 新增 record_image_gen/record_stt/record_tts/record_video/record_embed/record_rerank 6 个方法, 仿 record_llm 结构, 贯穿 agent_id/session_id/trace_id/request_id/fallback_from; PricingCatalog.estimate_cost 扩展非文本 modality 按 input_units*input_price + output_units*output_price 计价 (text modality 走现有 token 分档公式)。
    - **媒体工具真实接线** (`isac/agent/tools/media.py`): _MediaToolBase.execute 走 router.select → provider_manager.multimodal_provider → Provider 调用 → ToolResult; 新增 VisionUnderstandTool (operation="vision", 调 vision_chat); GenerateVideoTool/UnderstandVideoTool 留桩 (Sora/Runway 真实 API 留 J3+, 用户二次确认端点后接入); DEFAULT_POLICY 加 understand_image: deny。
    - **Channel 媒体 segment** (`isac/channel/{model,media_resolver,adapters/onebot/adapter.py,adapters/webchat/adapter.py}`): MessageSegment docstring 加 audio/video/file; MediaResolver.resolve_for_channel() 把 ArtifactRef 转 MessageSegment (onebot: image/voice/video/file; webchat/telegram/discord 返回 None); OneBotAdapter._to_cq_segment 加 audio/video/file 分支 (file 用 getattr 探测扩展支持, 不支持时降级为文本占位); WebChatAdapter.send 把非 text segment 降级为 [<type>: <artifact_id[:8]>] 占位追加到 content。
    - **main.py 注册循环 + 配置模板** (`isac/main.py` + `data/config.sample.jsonc`): register_multimodal_providers() 按 multimodal_providers[] 实例化 Provider 注册到 ProviderManager._multimodal_providers + ModelCatalog; build_services 接入调用; data/config.sample.jsonc 含 5 个 kind 注释示例 + 自托管端点示例; .gitignore 加 !data/config.sample.jsonc 例外。
    - **视频生成 Provider**: J2 范围内不接真实 API (Sora/Runway/Kling 多为受限预览), 保留 VideoGenerationProvider ABC + 桩; 真实接入留 J3+ 节点开工前二次确认。
    - **Agent 能力授权字段**: `AgentConfig.model_capabilities_allow` 留 J4 (assembly.py:78-81 getattr 兜底保留)。
    - 覆盖测试: `tests/unit/test_artifact_store.py` (12) / `test_media_normalizer.py` (13) / `test_model_router.py` (10) / `test_usage_recorder_multimodal.py` (13) / `test_image_gen_provider.py` (9) / `test_stt_tts_provider.py` (13) / `test_embed_provider.py` (14) / `test_vision_chat.py` (7) / `test_media_tools_wired.py` (8) / `test_channel_media_resolver.py` (13) / `test_main_multimodal_registration.py` (8); 集成测试 `tests/integration/test_j2_multimodal_flow.py` (4) / `tests/integration/test_j2_channel_delivery.py` (4)。共 721 测试全绿。
  - **边界**: Agent 能力授权字段留 J4; 视频生成真实 API 留 J3+; Telegram/Discord 媒体 segment 留 J3; Channel 入站媒体解析 (用户上传图片/语音 → MediaInput) 留 J3; MediaNormalizer 白名单仅 data/artifacts/ (不启用 data/uploads/); 既有 send_image.py 旧工具保留不动, J3 决定迁移; _send_reply 改造 (扫描回复里的 artifact_id 引用 → MediaResolver 转 segment) 留 J3 WebUI v2 一起做。
  - **2026-07-26 MVP 缺口复核**：本节点标注"留 J3"的 `_send_reply`/入站媒体/Telegram·Discord segment 在 J3 完成后**仍未补齐**;更根本的是 `isac/runtime/assembly.py` 的 `ToolRegistry` 注册清单**不含任何 `media.py` 工具**(vision/STT/TTS/生图/视频理解/视频生成 6 个语义工具全仓仅测试引用),`AgentConfig` 也无 `model_capabilities_allow` 字段(此前留 J4,J4 完成后仍未补) —— Provider/Router/Catalog/ArtifactStore 全部就绪却是"配置了也没用"的状态,这是需求七 MVP 的核心缺口。补齐见 **Q4**。

- [x] **J3 WebUI v2 管理与观测**
  - **验收**：Dashboard、Agent、Channel/路由、Provider/模型、Token/成本、插件/MCP/工具、记忆、会话/任务进度、日志/审计、系统设置页面可用；配置写入支持 Schema 校验、差异预览、二次确认、版本冲突检测和审计；密钥只可替换不可回显。
  - **产出**：`control/webui/` 前端重构、Control API 扩展、实时事件通道、浏览器端测试与权限测试。
  - **依赖**：G1-G4、I1/I5、D9、J1-J2。
  - **当前**：已完成 (2026-07-25)。WebUI v2 SPA 十域全部真实内容落地:
    - **后端 Control API 扩展** (J3-1 至 J3-4): routes_providers (GET /providers /providers/models /artifacts + POST /providers/{id}/test + DELETE /artifacts/{id}) / routes_config (POST /config/validate /config/diff + PATCH /agents/{id} 支持 If-Match + revision 乐观锁 + 409 CONFIG_CONFLICT) / routes_sessions (GET /sessions /sessions/{id} /sessions/{id}/messages) / routes_memory (GET /memory/{agent_id}/episodes|profiles|jargon) / routes_events (GET /events/stream SSE + Last-Event-ID 断线恢复 + 心跳 + max_chunks 测试参数)。
    - **AgentConfig 加 revision 字段** (J3-2): save_agent_config 每次 +1; PATCH 端点用 If-Match 乐观锁。
    - **WebUI v2 SPA shell** (J3-5): 侧边栏 10 域导航 (Dashboard/Agents/Channels/Providers/Usage/Extensions/Memory/Sessions/Logs/System) + .page active 类切换 + navigate() 函数; Dashboard 页 stat-grid + 近期审计; Agents/Channels/Logs 页保留 v1 内容向后兼容。
    - **Providers/Usage/Extensions 三页** (J3-6): refreshProviders/refreshUsage/refreshExtensions 调用已就位 API。
    - **Memory/Sessions/System 三页** (J3-7): refreshMemory/refreshSessions/refreshSystem + 配置编辑事务 UI (loadConfigForEdit/validateConfig/diffConfig/patchConfig, 二次确认 + ETag 乐观锁)。
    - **Playwright 浏览器黄金路径测试** (J3-8): tests/browser/test_webui_golden_path.py 两条路径 (Agent CRUD + 审计 / 路由 + Link + 用量); 未安装 Playwright 时 importorskip 跳过, CI 在 K8-2 加 playwright install chromium。
    - **Bearer Token 模式**: 沿用 v1 从 DOM 读取 (不引入 HttpOnly Cookie + CSRF, 留作未来工作); sessionStorage 存 token (K7 已落地, 关闭标签即清除)。
    - 覆盖测试: tests/unit/test_webui.py (11 测试, 含 SPA 侧边栏 + 三批页面 + 配置编辑事务 UI) + tests/browser/test_webui_golden_path.py (2 黄金路径, Playwright 未装时 skip)。共 792 测试全绿。
  - **边界**: HttpOnly Cookie + CSRF 未引入 (沿用 v1 Bearer Token 从 DOM 读取); 多 scope 权限模型未引入 (扁平 Bearer Token); 插件表占位 (插件列表 API 待后续); WebUI 浏览器测试在 CI 中运行待 K8-2 加 Playwright step。
  - **2026-07-26 MVP 缺口复核**：HttpOnly Cookie + CSRF 与多 scope 权限模型已由后续的 Fix-17/Fix-12(见 CR2/CR3 修复记录)补上,本节点"边界"里这两条已解决,但另外几处遗留问题仍在:Extensions 插件表硬编码占位文案(实际后端 API `/agents/{id}/plugins` 已就绪,只是前端未接);SubAgent 任务表请求路径写死 `agent_id="_"`,恒空;配置编辑的 `loadConfigForEdit` 不读真实配置、伪造 `revision=1`,真实 revision>1 时 PATCH 必 409(乐观锁在 WebUI 侧形同虚设);后端 SSE(`/events/stream`)已挂载但前端无 `EventSource` 消费;Usage 页明细表按 `events?.events` 取值,与 API 裸数组返回不匹配,恒显示"(无事件)"。补齐见 **Q5**。

- [x] **J4 SubAgent Runtime 与可追溯任务日志**
  - **验收**：每个 Agent 可用 `delegate_task` 创建隔离子任务；子 Agent 使用独立 History/Prompt/Budget/Workspace 和父权限子集；主 Agent 默认只收到结构化结果、证据引用和用量摘要；可通过 task_id 列表、查询状态、分页读取脱敏日志、取消任务；日志持久化后重启仍可查询；不记录原始 reasoning；子 Agent 默认不能直接发消息、写长期记忆或无限派生。
  - **产出**：`runtime/subagent/{models,supervisor,context,journal,broker}.py`、delegate/list/status/log/cancel 工具、SQLite Journal、Control API/WebUI 时间线、恢复/取消/权限/隐私/预算测试。
  - **依赖**：K1-K5、D3-D4、D9、J1、K3-K4。
  - **当前**：已完成 (2026-07-25)。SubAgent Runtime 真实执行循环落地:
    - **SubAgentSupervisor 真实执行循环** (`isac/runtime/subagent/supervisor.py`): `submit()` 接受 `runner_factory` 注入, 用 `asyncio.create_task` 后台派生子 Agent 执行; 状态机 `queued→running→succeeded/failed/cancelled/timed_out`; 超时通过 `asyncio.wait_for` 控制; 取消通过 `asyncio.Task.cancel()` 传播; `_transition` helper 抽出状态转移 + journal 写入, 降低圈复杂度; 未注入 runner_factory 时保持骨架行为 (返回 queued, 不启动后台 task)。
    - **delegate_task 工具真实链路** (`isac/agent/tools/subagent.py`): 构造 SubAgentTask → supervisor.submit() → poll get_status 直到终态 → 返回 result.summary; 等待超时返回当前状态 (不取消, 后台 task 继续); `_format_terminal_result` 优先从 `run.result_summary` 取 (J4-2 新增字段)。
    - **H3 TaskRunner 迁移** (`isac/agent/tools/utility/task.py`): 删除 TODO(J4) 标记, 内部委托 supervisor.submit(); 保留 task + budget_tokens 接口向后兼容; 保留 task_depth 递归深度限制 (默认 3, 防无限派生); 无 supervisor 时回退到旧 task_runner 路径。
    - **SubAgentRun 新增 result_summary 字段**: succeeded 时存 runner 返回的 SubAgentResult.summary, 供工具直接读取, 不依赖 journal fetch。
    - **取消传播 + 重启恢复** (`supervisor.py`): `cancel()` 用 `asyncio.Task.cancel()` 传播到 runner (CancelledError); `restore_interrupted()` 从 Journal.restore() 读出持久化 run, 把 running/queued/waiting_tool 标记为 cancelled (中断后不恢复旧进度, 与 D9 思路一致); 已终态保留不改写; main.py 在 runtime.start() 后调 `_restore_subagent_interrupts(services)`。
    - **Journal schema 扩展** (`isac/runtime/subagent/journal.py`): subagent_runs 表加 result_summary 列; `_ensure_column()` 旧库迁移 (PRAGMA table_info 探测 + ALTER TABLE); append() 支持 seq 自动分配 (event.seq<=0 时由 DB 查 MAX(seq)+1 分配)。
    - **Control API routes_subagent** (`isac/control/api/routes_subagent.py`): `POST /agents/{id}/subagent-runs` 派生 / `GET /agents/{id}/subagent-runs` 列出 / `GET /subagent-runs/{task_id}` 查询状态 / `GET /subagent-runs/{task_id}/events` 分页读取事件 / `POST /subagent-runs/{task_id}/cancel` 取消 (幂等); Bearer Token 认证; 无 supervisor 时整个路由不挂载 (404); `create_control_app` 新增 subagent_supervisor 参数。
    - **DEFAULT_POLICY**: delegate_task 从 deny 改 restricted (需显式授权, 但不再默认禁用)。
    - 覆盖测试: `tests/unit/test_subagent_supervisor.py` (19) / `test_subagent_supervisor_exec.py` (7) / `test_delegate_task_wired.py` (10) / `test_subagent_restore.py` (5) / `test_control_api_subagent.py` (8); 集成测试 `tests/integration/test_j4_subagent_flow.py` (5)。共 751 测试全绿。
  - **边界**: SubAgentPolicy.intersect() 采用 fail-closed (AND/min/∩, 空集拒绝全部); AgentConfig.model_capabilities_allow 字段仍留 J4+ (assembly.py getattr 兜底); ContextEnvelope 不复制主会话可变上下文 (MoodState/RelationshipState/用户画像/私有记忆正文); 子 Agent 默认不能直接发消息、写长期记忆或无限派生 (allow_channel_send/allow_memory_write/allow_delegate 默认 False); list_subagent-runs 按 parent_agent_id 过滤 TODO (SubAgentRun 无该字段, 当前返回全部)。
  - **2026-07-26 MVP 缺口复核**：委派主链路(`delegate_task`→Supervisor→runner→独立 loop)本身是本仓接线最完整的域之一,但 `supervisor` 只保留 `result.summary`,把 `result.usage`/`evidence_refs` 丢弃(`run.tokens_used`/`tool_calls_used` 恒 0 —— Control API `/subagent-runs` 会把这两个恒 0 字段返回给客户端;WebUI 任务表当前未渲染用量列,补列后也无真实数据可显);`delegate_task` 收集的背景摘要从未真正传给子 Agent(`ContextEnvelopeBuilder` 死代码);`SubAgentPolicy` 无并发上限字段、`supervisor` 无信号量,可无限并发 `submit`;`control/defaults.py` 的 `RESTRICTED_TOOLS_POLICY` 只 `deny` 了 `task` 却漏了 `delegate_task`,自动化创建的受限 Agent 仍可派生子任务。补齐见 **Q6**。

---

### K 稳定化与可用版本闭环

**目标**：先打通“可持续运行、真实模型回复、持久化恢复、端到端可验证”的最小纵向链路，再继续 D9/J1-J3 等横向扩展。K1-K8 是当前最高优先级；完成前项目统一定位为 Alpha，不得宣称生产可用或完成 v1.0 验收。

- [x] **K1 应用常驻与统一资源生命周期**（P0）
  - **验收**：`python -m isac` 在无 Channel、仅 Control、启用 Channel 三种模式下均持续驻留；支持 SIGINT/SIGTERM；Channel、Control、Alert、Provider、Storage、Plugin、Webhook 后台任务统一 start/health/close；启动失败能回滚，后台任务异常不会静默丢失，关闭无 pending task/resource warning。
  - **产出**：`ApplicationRuntime` / `ServiceContainer`、统一 TaskGroup、信号处理、优雅关闭、生命周期单元与进程级 smoke test。
  - **依赖**：B4、C4、G1、I5。
  - **当前**：已完成(校正复选框,与 PROGRESS.md 稳定化节点明细表一致)。历史"已知问题"(`main()` 直接返回、后台任务被取消)已由 `ApplicationRuntime` 统一生命周期解决;2026-07-26 实测无 `data/config.jsonc` 时也能启动并驻留 18 秒无异常栈。
  - **2026-07-26 MVP 缺口复核**：Windows 控制台 Ctrl+C 不走优雅关闭 —— `add_signal_handler` 在 Windows 上注册失败(仅回退 `KeyboardInterrupt`),且 `main()` 的 `await runtime.serve_forever(); await runtime.shutdown()` 无 `try/finally` 包裹,`KeyboardInterrupt`/`CancelledError` 会直接穿透跳过 `shutdown()`;Linux/Docker(CI 实际运行环境)不受影响。补齐见 **Q0**。

- [x] **K2 真实 LLM Provider 纵向闭环**（P0）
  - **验收**：至少一个真实 Provider 支持非流式、SSE 流式、Tool Call、usage、超时、429/5xx/非法响应分类、重试与 fallback；配置真实 Provider 时不得回退为 Stub 冒充成功；Provider Client 可健康检查并在关闭时释放连接池。
  - **产出**：`OpenAICompatProvider` 或等价首个 Provider 的真实实现、HTTP 契约测试、Fake Server 集成测试、错误分类与关闭测试。
  - **依赖**：K1、D3、ProviderManager。
  - **当前**：已完成(校正复选框)。`OpenAICompatProvider` 真实闭环已实测(非流式/工具调用/错误分类/连接池);历史"阻塞"说明已解除。
  - **2026-07-26 MVP 缺口复核**：SSE 流式合并逻辑已修复(CR3-H4 按 index 累积),但主链路 `AgentContext.streaming` 默认 `False` 且全仓无生产赋 `True` 点,流式路径实际未在生产启用(非 MVP 阻塞项,已知记录)。

- [x] **K3 Storage Schema、记忆写入与恢复**（P0）
  - **验收**：启动时执行 Schema init/migration；Metadata/FTS/Sparse 按 namespace 初始化；消息或会话结束后真实写入 Episode；重启后可检索；shared namespace 强制 user/group/scope ACL；写入失败不阻塞回复但可观测；关闭时提交并释放连接。
  - **产出**：StorageLifecycle、schema_version/migration、MemoryEncoder 接线、Sparse 重建/恢复、跨用户隔离与重启测试。
  - **依赖**：K1、D5-D7。
  - **边界**：Vector/Graph/Reranker 可继续降级，但必须明确标记 experimental/stub，不能计入 MVP 完成度。
  - **当前**：Schema init/migration、跨用户隔离、重启恢复已完成(校正复选框)。
  - **2026-07-26 MVP 缺口复核**：本节点验收标准明确要求"消息或会话结束后真实写入 Episode",但生产 `_dispatch_message`/`process_message` 全程无任何 `store_episode`/画像/行话写入调用 —— 存储基建(Schema/FTS/Sparse/重启恢复)已就绪,唯独"写入"这一步从未接线,记忆检索因此恒为空。这是本次差距复核中最关键的发现,补齐见 **Q1(MVP 最高优先级)**。

- [x] **K4 Agent、Session、Identity、Routing 与 Link 持久化恢复**（P0）
  - **验收**：重启后恢复 AgentConfig/运行状态、Session、UserMapper 绑定、RoutingRules、InterAgentLink；Agent 独立 Provider 配置实际生效；配置写入使用原子替换和版本迁移；非法 ID/路径被拒绝。
  - **产出**：registry/session/identity 持久化、启动恢复编排、原子配置存储、路径安全与迁移测试。
  - **依赖**：K1、E1-E3、G1。
  - **当前**：AgentConfig/运行状态、RoutingRules、InterAgentLink 持久化恢复已完成(校正复选框)。
  - **2026-07-26 MVP 缺口复核**：`Session`(`gateway/session.py`)与 `UserMapper`(`gateway/user_mapper.py`,自述"[桩] 内存实现,待 SQLite 持久化")实际为纯内存,本节点验收要求的"重启后恢复 Session、UserMapper 绑定"未达成 —— 与本节点其余三项(Agent/RoutingRules/Link)相比是明确的未闭合子项;`PROGRESS.md` 此前"Session 可持久化恢复"表述已一并订正。补齐见 **Q1**。

- [x] **K5 单 Channel × 单 Agent 真实 E2E**（P0）
  - **验收**：进程启动 → Fake/测试 Channel 收消息 → EventBus intercept → Router 剥离触发词 → Session/Gating → 真实 HTTP Mock Provider → Tool Call → Channel 回复全链通过；覆盖打断、超时、错误和重启恢复。
  - **产出**：`tests/integration/test_single_agent_flow.py`、可复用 Fake Channel/Provider、进程级测试夹具。
  - **依赖**：K1-K4。
  - **当前**：已完成(校正复选框,与 PROGRESS.md 一致)。

- [x] **K6 多 Agent、工具、记忆与控制面 E2E**（P1）
  - **验收**：2+ Agent 共享 1 Channel；显式绑定/触发词/默认 Agent；InterAgentBus deliver + ACL；工具权限；记忆 namespace 隔离；Control 修改配置真实生效并在重启后保留。E5 并入本节点验收。
  - **产出**：`tests/integration/test_multi_agent.py`、Agent Mesh/权限/记忆/Control 集成测试。
  - **依赖**：K5、E3-E5、G1-G4。
  - **当前**：已完成(校正复选框,与 PROGRESS.md 一致)。

- [x] **K7 安全与长期运行基线**（P0/P1）
  - **验收**：Agent ID/路径穿越防护；Control 空 Token 仅显式开发模式；审计/JSON metrics 鉴权；WebUI 不持久化 Bearer Token；Webhook 与远程媒体防 SSRF；SecretStore 可用；插件明确为兼容层而非安全沙箱或提供进程级隔离；Bash/File/MCP 有字节、时间、进程、路径与 pending 上限；Session/Lock/队列有 TTL/LRU；Discord 分页不丢消息。
  - **产出**：安全回归测试、资源压力测试、威胁模型与生产安全配置。
  - **依赖**：K1、K4、G/H/F 相关模块。
  - **当前**：已完成(校正复选框,与 PROGRESS.md 一致)。
  - **2026-07-26 MVP 缺口复核**：`SecretStore`(AES-256-GCM)实现存在但生产零调用点,`api_key` 实际以明文存于 `data/config.jsonc`(env 覆盖已支持);MVP 建议先文档化 env 方案,`SecretStore` 接线留 MVP 之后,见 **Q5** 备注。

- [x] **K8 CI、Docker、浏览器与发布准入**（P1）
  - **验收**：CI 启用 branch coverage 与 `--cov-fail-under`；构建 wheel/sdist 并安装 smoke；Docker build/start/health/stop 实测；WebUI 用真实浏览器覆盖登录、Agent/路由/Link/审计黄金路径；Mypy 全绿或对 `aiocqhttp` 做局部明确 override；README/AGENTS/CHANGELOG/版本号与实际能力一致。
  - **产出**：CI 门禁、Docker smoke、Playwright/浏览器测试、发布检查表、版本状态校准。
  - **依赖**：K1-K7、I1-I6。
  - **当前**：已完成 (2026-07-26)。`.github/workflows/ci.yml` 四 job: check (ruff+mypy+pytest --cov-branch --cov-fail-under=75) + build (uv build + wheel install smoke `import isac`) + docker (build + 30s curl /health 循环 + cleanup) + browser (Playwright install chromium + tests/browser/ 黄金路径); 新建 `scripts/release_checklist.md` 七段发布准入清单 (CI 全绿 + 本地全量验证 + 文档同步 + 版本号一致 + 发布标签 + 回滚预案 + 发布后监控)。README/AGENTS/CHANGELOG/版本号校准留 K8-1 节点 (本节点不涉及文档内容校准, 只覆盖 CI 工程化)。

**强制开发顺序**：K1 → K2 → K3/K4 → K5 → K6/K7 → K8。K1-K5 完成前暂停 D9、J1-J4；K8 通过后才允许恢复 I6 发布验收。

---

### L 拟人化运行时落地

**目标**：把 `HUMANLIKE_RUNTIME.md` 描述的会话级拟人行为(消息合并、主动等待、主动任务、被打断、上下文恢复)从设计蓝图落成可运行代码。所有子节点默认由 `conversation.enabled` 开关控制,关闭时主链路零行为变化。

- [x] **L1 ConversationRuntime**(骨架完成,已由 L2-L5 充实;主链路接线见 P1)
  - **验收**：每个 (agent_id, session_id) 一个 `ConversationRuntime`;具备消息缓存、状态机 (idle/thinking/acting/waiting/stopped)、`WaitState`/`ForcedTurnState` 契约、per-session 注册表 (FIFO 上限) 与主动任务队列;`conversation.enabled=False` 时 `handle_message` 完全走原路径。
  - **产出**：`runtime/conversation/{__init__,models,runtime,registry,proactive}.py`、`assembly` 注入 `conversation_registry`、`manager.handle_message` 惰性接线、`tests/unit/test_conversation_runtime.py`。
  - **依赖**：B4、E1、D9。
  - **当前**：骨架完成 + L2-L5 已实现核心逻辑 (2026-07-26)。契约 + 状态机 + registry + 主动队列 + 惰性默认关闭接线就位,单测通过,ruff/mypy 全绿,主链路零行为变化。debounce 触发 / wait 回填 / 主动调度 / 打断闭环 / 上下文恢复 见 L2-L5(均已实现核心逻辑)。**接线待办 → 见 §四 P0/P1**:把 L1-L5 接入生产主链路。

- [x] **L2 Wait 闭环与 debounce 触发**(P1 已接线, 2026-07-27)
  - **验收**：`wait` 工具向 `ConversationRuntime.enter_wait` 注册 `WaitState`,由后续消息 / 超时 / 主动任务三条路径之一结束等待并向 AgentLoop 回填 wait 工具结果 (说明实际等待时长与结束原因);连续消息在 debounce 静默窗口内合并为一次触发,避免逐条打断。
  - **产出**：异步 debounce 触发循环、`resolve_wait` 三入口、wait 工具改造 (注册 WaitState)、超时定时器、单测与集成测试。
  - **依赖**：L1、D4 (wait 工具)、D9。
  - **当前**：已完成 (2026-07-26)。`ConversationRuntime.should_trigger` 真实 debounce 判定 (zero/positive); `enter_wait` (async) 创建 future + 启动超时定时器; `resolve_wait` 回填 `end_reason`/`actual_seconds` + 取消定时器 + 唤醒 wait 工具; `notify_new_message` 在 WAITING 时以 MESSAGE 原因结束等待。三条唤醒路径 (message/timeout/proactive) 单测覆盖 12 例; `WaitTool` enabled=True 时调 `enter_wait`+`await_wait`, enabled=False 保持原意图字符串 (零行为变化)。`assembly.py` 注入 `conversation_enabled` 标志。debounce 接入 manager 主链路 (连续消息合并) 留 §四 P1, 不影响 L2 骨架验收。
  - **接线待办 → 见 §四 P1**:debounce 连续消息合并接入 manager (依赖 P0 消息并发化)。

- [x] **L3 主动任务调度**(P1 已接线, 2026-07-27)
  - **验收**：`ProactiveTaskQueue` 由调度器按优先级 + 冷却 + 频率边界驱动;每个主动任务必须带 source/intent/reason (禁止无来源发言);触发时唤醒对应会话的 `ConversationRuntime` 发起一次强制话轮 (`ForcedTurnState`);来源经鉴权,防刷屏与滥用。
  - **产出**：主动调度循环、优先级/冷却策略、来源鉴权、强制话轮 Prompt 注入、单测与集成测试。
  - **依赖**：L1、L2、门控 (存在感/频率)。
  - **当前**：已完成 (2026-07-26)。`ProactiveTaskQueue` 改为 list 实现 priority 排序 (high>normal>low; 同优先 FIFO); `ProactiveScheduler` 加 `allowed_sources` 集合 (默认 plugin/memory/schedule/agent/api); `authorize` 拒绝不在集合内的 source; `to_forced_turn` 触发时更新 `_last_fired_at`; 新增 `async start/stop` 后台循环 (poll_interval_seconds 周期 poll → authorize → may_fire → wake_callback, 冷却中任务退回队列头部)。强制话轮 Prompt 注入 + manager 接线留 §四 P1, 不影响 L3 骨架验收。
  - **接线待办 → 见 §四 P1**:ProactiveScheduler 注入 assembly + 生命周期注册 start/stop + 强制话轮 Prompt 注入。13 例单测覆盖 priority/authorize/start/stop/冷却/空队列/重复 stop。

- [x] **L4 Planner 打断闭环**(P1 已接线, 2026-07-27)
  - **验收**：thinking 期间到达的新消息可请求打断当前规划;`AgentContext.interrupt_requested` 由 `ConversationRuntime.request_interrupt` 写入;限制单轮打断次数、抑制被打断的旧回复、下一轮 Prompt 注入"上一轮被新消息打断"提示。
  - **产出**：打断信号写入路径、打断次数限制、旧回复抑制、Prompt 提示注入、单测。
  - **依赖**：L1、L2、`agent/loop.py`。
  - **当前**：已完成 (2026-07-26)。`ConversationRuntime` 加 `interrupt_state` + `max_interrupts_per_turn` (默认 1, 保守); `request_interrupt(reason)` 单轮次数限制 + 置 `superseded=True` + `interrupt_count++`; `clear_interrupt` 进入下一轮前重置。新增 `agent/injectors/interrupt.py:InterruptInjector` 注入"上一轮被打断"内部参考 (含打断次数与原因), 注入后清空状态避免重复注入。AgentLoop 接线 (thinking 后读 `superseded`) 与 manager 并发处理消息 (thinking 期间收到新消息调 `request_interrupt`) 留 §四 P0+P1, 因这两者需要 manager 用 asyncio.create_task 并发处理消息的大改动, 超出 L4 骨架验收线。
  - **接线待办 → 见 §四 P0+P1**:manager 并发处理消息 (asyncio.create_task) + thinking 期新消息调 request_interrupt + loop 读 superseded 抑制旧回复 + InterruptInjector 注册 prompt_builder。9 例单测覆盖 request/clear/单轮上限/可配置/注入/清空/默认零行为变化。

- [x] **L5 上下文恢复**(P1 已接线, 2026-07-27)
  - **验收**：进程重启后,会话的拟人状态 (未决 wait、被打断标记、主动任务) 可从持久化恢复到合理起点 (与 D9/J4 "中断后不恢复旧进度" 思路一致,标为终止/复位而非续跑)。
  - **产出**：ConversationRuntime 状态持久化 schema、启动恢复编排、恢复测试。
  - **依赖**：L1-L4、K4 (持久化恢复框架)。
  - **当前**：已完成 (2026-07-26)。`ConversationStateStore` 原子写 JSON 落盘到 `data/agents/<id>/conversation/<session_id>.json` (复用 `utils.fs.atomic_write_json`, K4 模式); `load` 读回 → 计算 elapsed → 短(<5min)/中(<1h)/长(<24h) 窗口生成 `recovery_hint` → 复位 `state=idle` + `pending_wait=None` (中断后不续跑); > 24h 不恢复。新增 `agent/injectors/recovery.py:RecoveryInjector` 注入 `recovery_hint` 到第一轮 Prompt, 注入后清空 (避免重复注入)。10 例单测覆盖 save/load 往返 + 短/中/长/24h 窗口 + 未决 wait 复位 + 原子写文件存在 + RecoveryInjector 注入/清空/无快照空串。manager 启动时调 `store.load` 填充 snapshots + 接线 RecoveryInjector 到 prompt_builder 留 §四 P1 (不涉及主链路行为变化)。
  - **接线待办 → 见 §四 P1**:manager 启动时调 ConversationStateStore.load 恢复 + RecoveryInjector 注册 prompt_builder。

---

### M 路由与 Agent Mesh 深化

**目标**：把 `ROUTING_AND_AGENT_MESH.md` 描述的旁听/候选路由与 Agent 间协作动作从设计落成实现。

- [x] **M1 observer/candidate 路由**(P2 已接线, 2026-07-27)
  - **验收**：Agent 可配置为 observer (旁听,只入记忆不回复) 或 candidate (候选,多 Agent 竞争同一消息由仲裁选出回复者);路由决策可解释、可审计。
  - **产出**：路由角色模型、候选仲裁策略、observer 记忆旁路、单测与集成测试。
  - **依赖**：C (路由)、E (多 Agent)、门控。
  - **当前**：已完成 (2026-07-26)。`MeshRouter.to_mesh_decision` 按 agent_roles 字典 (agent_id → "primary"/"observer"/"candidate") 填充 observer_agent_ids/candidate_agent_ids (primary 不动); `arbitrate(decision, gating_scores=...)` 多候选按 gating_score 降序取最高, 但需**显著高于** primary (差值 > SWITCH_MARGIN=0.3) 才切换, 避免小噪声抖动; observer 不参与仲裁 (只观察); decision.reason 记录仲裁过程供审计。无角色配置时退化为单主路由 (零行为变化)。8 例单测覆盖 to_mesh_decision + arbitrate + observer 排除 + 候选切换/不切换 + 默认零行为变化。AgentConfig.mesh_role 字段 + manager.observe_message 接线留 §四 P2。
  - **接线待办 → 见 §四 P2**:AgentConfig 加 mesh_role + manager.observe_message 旁听/候选路由接线 + assembly 注入 MeshRouter。

- [x] **M2 handoff / notify / memory_query**(P2 已接线, 2026-07-27)
  - **验收**：Agent 间可显式移交会话 (handoff)、发通知 (notify)、跨 Agent 查询记忆 (memory_query);全部经 InterAgentLink ACL 授权;动作可审计。
  - **产出**：三类 Agent 间动作工具、ACL 校验、审计埋点、单测。
  - **依赖**：E3 (InterAgentBus/Link)、N (记忆)。
  - **当前**：已完成 (2026-07-26)。`MeshActionBroker.is_permitted` 无 policy 一律拒绝, 有 policy 时 action 在 permissions 中允许; `notify/handoff/memory_query` ACL 通过后经 `bus.send` 真实投递 (handoff 把 summary 进 context.summary, memory_query 把 visible_memory_scopes 进 context.filters.scopes 让接收方裁剪); `list_available` 从 bus.links 过滤可见对端 (双向 Link 双方可见, 单向 from→to, disabled 不计入); 无 bus 时所有动作拒绝 (零行为变化)。4 个 A2A 工具 (notify_agent/handoff_conversation/list_available_agents/memory_query_agent) 接入 broker; DEFAULT_POLICY 从 deny 改 restricted; ToolRegistry._required_service 加 mesh_action_broker 校验。11 例 broker 单测 + 骨架测试更新到新行为。
  - **接线待办 → 见 §四 P2**:assembly 注入 mesh_action_broker 到 services (否则 4 个 A2A 工具运行时报"未注入"错误) + 动作审计埋点。

---

### N 记忆深化

**目标**：把当前分散的记忆结构统一为 `MemoryItem` 模型,补齐记忆治理与身份归一。

- [~] **N1 统一 MemoryItem 模型**
  - **验收**：episodic/profile/jargon 等记忆统一到一个 `MemoryItem` 契约 (类型 + 载荷 + 元数据 + 命名空间),存储/检索/注入围绕它展开;迁移不破坏既有数据。
  - **产出**：`MemoryItem` 契约、存储层适配、迁移脚本、单测。
  - **依赖**：D5-D7、K3。
  - **当前**：已完成 (2026-07-26)。`MemoryItem.from_episode/to_episode` 补齐完整字段映射 (summary/topics/participants/emotion/session_id/group_id 进 metadata); 新增 `from_profile/to_profile` (name/traits/relationship_depth/interaction_count/first_seen/last_seen/embedding_hash); `from_jargon/to_jargon` (word/context/usage_count); `from_relationship/to_relationship` (familiarity/trust/last_interaction_at)。新增 `isac/memory/model/adapter.py:MemoryItemAdapter` 实现 `MemoryItem ↔ MemoryHit` 双向适配 (hit_type → memory_type, 未知类型默认 EPISODE 兜底)。既有 metadata.py 三表 schema 不动, 本模块只做读写适配层。10 例单测覆盖四种类型 from/to roundtrip + adapter 双向 + 未知列降级。
  - **接线待办 → 见 §四 P3**:MemoryItem/MemoryItemAdapter 接入 pipeline 检索/注入链 (当前 `pipeline.search()` 从不调用适配层,悬空)。

- [x] **N2 记忆治理 (freeze/protect/correct/delete)**
  - **验收**：支持冻结、保护、纠错、删除记忆条目;操作经权限校验并审计;纠错保留可追溯历史。
  - **产出**：记忆治理动作、权限与审计、单测。
  - **依赖**：N1、G (控制面)。
  - **当前**：已完成 (2026-07-26)。`MetadataStore.init_schema` 给 `episodes` 加 `frozen`/`protected`/`deleted`/`corrected_by` 治理列 (向后兼容老库, 默认 0/NULL); 新增 `memory_revisions` (corrected 历史保留) + `memory_audit` (审计日志) 表。`MemoryGovernor` 真实实现 6 类治理动作: freeze/protect 置标志位 + 审计; correct 写新版本 + memory_revisions 保留旧内容 + corrected_by 关系; delete 软删除 + protected 拒绝; restore 反向复位; export 组织为 `list[MemoryItem]` (治理状态进 metadata)。`routes_memory_admin.py` 真实接入 governor + 新增 `GET /memory/{id}/items` 列表端点。8 例单测覆盖 freeze/protect/correct/delete/restore/export + protected 拒绝 + 不存在条目返回 False。
  - **说明**:软删除 `deleted` 已在检索路径过滤生效(metadata FTS / by-id 检索加 `deleted = 0`,CR2-Fix-12);`frozen`(冻结)语义为"不再更新、仍可被检索",非缺口。N2 记忆治理已完整接入生产。

- [~] **N3 身份归一 (IdentityResolver)**
  - **验收**：跨平台 (不同 IM 的同一用户) 身份归一到统一 identity;记忆按归一后身份聚合;归一规则可配置、冲突可人工裁决。
  - **产出**：`IdentityResolver`、跨平台映射存储、冲突处理、单测。
  - **依赖**：C (Gateway/UserMapper)、N1。
  - **当前**：已完成 (2026-07-26)。`IdentityResolver` 新增 `person_identities` (verified/confidence/source) + `identity_conflicts` 表 (惰性建表, sqlite3 + aiosqlite 双轨)。`resolve` 先查 verified 命中, 未命中且 heuristic_enabled=True 时按 nickname 启发式匹配 (confidence≤0.5), 仍无则委托 UserMapper 创建新 person; `bind` 写 verified=1/confidence=1.0/source=manual + 同步 UserMapper.bind (若 master_id 已存在); `merge` 合并 aliases (去重) + platform_accounts (按 (platform, user_id) 去重), confidence 取较低, verified 取 AND; `arbitrate_conflict` 按 confidence 降序取最高, <0.7 写 identity_conflicts 供人工裁决。heuristic 默认 False (防误合并)。11 例单测覆盖 resolve/bind/merge/arbitrate + heuristic 开关 + 无 mapper 兜底 + 冲突写入。
  - **接线待办 → 见 §四 P4**(骨架轮 S4 已就位默认关闭锚点):gateway 入站 `main._resolve_identity` 在 `identity.enabled` 时接入 `IdentityResolver.resolve` 归一 `person_id` 并覆盖 `profile.user_id`(默认关闭走 user_mapper 原路径);剩 person_identities 生产写入 + 记忆聚合验证。

---

### O 企业化与平台扩展

**目标**：面向多租户、进程隔离、编排与更多平台的企业化能力。

- [~] **O1 多租户 / 组织隔离**
  - **验收**：Agent/记忆/配置/用量按 organization 隔离;跨租户不可见;控制面按租户鉴权。
  - **产出**：租户模型、数据隔离、租户级鉴权、单测。
  - **依赖**：G、K3-K4、J1。
  - **当前**：已完成 (2026-07-26)。`TenantIsolationGuard.namespace_for` enabled 时给命名空间加 `org:tenant:base` 前缀 (默认租户直通); `check_access` enabled 时跨租户不可见 (resource_org != tenant.org 且 != DEFAULT 拒绝); `assert_visible` 跨租户抛 PermissionError; `enforce(query, params, table, tenant)` 给 SQL 查询注入 `organization_id = ? AND tenant_id = ?` 谓词 (WHERE 已有时追加 AND, 无 WHERE 时加 WHERE, 用正则匹配 FROM <table> 定位)。默认 enabled=False (单租户 passthrough, 零行为变化)。16 例单测覆盖 namespace_for/check_access/enforce/assert_visible + 默认/非默认租户 + 无 WHERE 注入 + 跨租户拒绝。MetadataStore 加 tenant_id 列 + 控制面 routes_tenants 留 §四 P5。
  - **接线待办 → 见 §四 P5**:TenantIsolationGuard 接入 memory store/control/计量 + MetadataStore 加 tenant_id 列 + routes_tenants 控制面 (当前零调用点)。

- [~] **O2 插件进程级隔离**
  - **验收**：插件从当前"兼容层 (非安全沙箱)"升级为进程级隔离,资源与故障不影响主进程;插件崩溃可恢复。
  - **产出**：插件进程宿主、IPC 协议、资源限额、崩溃恢复、单测。
  - **依赖**：F (插件生态)、K7 (安全基线)。
  - **当前**：已完成 (2026-07-26)。`PluginIsolationHost.spawn` 用 `multiprocessing.Process` (fork on POSIX) 启动子进程 + `Pipe` 建立 IPC; 子进程入口 `_plugin_worker` 设资源限额 (`resource.setrlimit` RLIMIT_CPU=1s / RLIMIT_NOFILE=64 / RLIMIT_AS=256MB, 平台不支持时跳过); `call` 编码 IPCEnvelope → JSON → 管道发送 → asyncio.to_thread(recv) → 解码返回; 子进程崩溃 (BrokenPipeError/EOFError) 触发 `_on_crash` 自动重启 (最多 max_restart_attempts=3 次, 超过放弃); `kill` 优雅终止 (terminate + join 2s + kill 强杀); `is_alive` 属性。既有 `loader.py` 进程内兼容层不变 (仍默认)。6 例单测覆盖 spawn/call/kill roundtrip + 未 spawn 抛 + 重复 kill 幂等 + 崩溃重启计数 + 超限放弃 + 默认零行为变化。
  - **接线待办 → 见 §四 P5**:PluginIsolationHost 接入 loader 可选隔离模式 (当前 loader 仍进程内直接 import,未装配隔离)。

- [~] **O3 Workflow 编排**
  - **验收**：多步骤任务可用声明式 Workflow 编排 (串/并/条件/重试);步骤可跨 Agent/工具;执行可观测、可恢复。
  - **产出**：Workflow 引擎、步骤契约、执行器、可观测与恢复、单测。
  - **依赖**：J4 (SubAgent)、D9 (进度)、L (运行时)。
  - **当前**：已完成 (2026-07-26)。`WorkflowEngine.start` 按 transitions 调度 stages: 串行按 `TransitionKind.SEQUENTIAL` 递归执行, 并行用 `asyncio.gather` 同时跑多个 `PARALLEL` 目标, 条件 `CONDITIONAL` 按 `condition_evaluator` 返回决定执行或标 `SKIPPED`, 重试 `RETRY` 在 `_execute_stage` 内按 `max_retries=3` 重试; 状态机 `PENDING→RUNNING→SUCCEEDED/FAILED`; `step` 推进单个 PENDING stage; `resume` 把 RUNNING 标为 FAILED (中断后不续跑, 与 L5 一致); 持久化到 `data/workflows/<id>.json` (原子写)。`set_action_handler`/`set_condition_evaluator` 注入测试/生产回调; 无 handler 时 stage 视为 noop (零行为变化)。12 例单测覆盖串/并/条件/重试/step/resume/持久化/默认。
  - **接线待办 → 见 §四 P5**(骨架轮 S5 已就位控制面入口):`routes_workflows` 暴露 list/get/start REST 入口(default-off,`control.workflow.enabled` 启用);剩 action handler 生产注入 + Agent 工具入口。

- [~] **O4 平台扩展 (微信 / Slack / 飞书 …)**
  - **验收**：新增 IM 平台适配器,复用 Channel 抽象;媒体/富文本能力按平台声明适配。
  - **产出**：各平台 Channel 适配器、能力声明、投递适配、单测。
  - **依赖**：H (平台扩展)、C4 (Channel 抽象)。
  - **当前**：框架已搭建 + 三平台激活 (scaffolding 2026-07-26 模板 + 骨架轮 S7 + 2026-07-28/29 激活)。除 `template/` 通用模板外,新增 `feishu/`(`FeishuAdapter`)、`wechat/`(`WeChatAdapter`,公众号 mp / 企业微信 wecom)、`qq_official/`(`QQOfficialAdapter`,`platform_name="qq_official"` 与 OneBot 的 `qq` 并存不撞键)。**2026-07-28 激活**: feishu (AES-256-CBC 解密) + qq_official (Ed25519 验签) 真实 Webhook 收发。**2026-07-29 代码复审校正**: `wechat` **wecom 企业微信模式实为已实现并注册** (`adapter.py:90` start 启 uvicorn webhook + AES 验签, `:267` send 换 `access_token` 真实发送, `main.py:410` enabled-gated 注册), 仅 `mp` 公众号模式仍 no-op 骨架 —— 原"微信保持骨架/本轮不做"表述已滞后。`main._register_channel_adapters` 各平台 enabled-gated 惰性注册(默认不启用 → 零行为变化)。当前真实收发: OneBot/Telegram/Discord/WebChat + feishu + qq_official + wechat(wecom);仅骨架: wechat(mp)。剩余: Slack 适配器 + 各平台富媒体降级完善。附 `tests/unit/test_o4_platform_adapters_scaffolding.py` + `test_feishu_adapter.py` + `test_qq_official_adapter.py`。

- [ ] **O5 Video Provider**
  - **验收**：视频理解/生成 Provider 真实接入 (Sora/Runway/Kling 等),经能力目录与 ModelRouter 选择;结果走 ArtifactStore。
  - **产出**：Video Provider 实现、能力声明、计量埋点、单测。
  - **依赖**：J1-J2。
  - **当前**：框架已搭建 (scaffolding, 2026-07-26 + 2026-07-27 骨架轮 S6 注册挂点)。`isac/provider/video_gen/` (`OpenAICompatVideoGenProvider` 实现 `VideoGenerationProvider` ABC,`generate` 抛 `NotImplementedError`);已接入 `main._build_multimodal_provider` 的 `kind="video_gen"` 注册挂点 (operations={"video_gen"}, modalities text→video),配置 `multimodal_providers[]` 增 `{kind:"video_gen", ...}` 即注册进 ModelCatalog/ModelRouter,默认无该项 → 不注册 → 零行为变化。**真实 API 端点开工前需二次确认**(注册不触发 generate,仅 Agent 实际请求视频生成才暴露"未实现")。附 `tests/unit/test_main_multimodal_registration.py` 新增 3 例。

---

### P 主链路接线与激活

**目标**：把已实现但未接入生产的 L/M/N/O 能力(§四标 `[~]`)接入同一条消息处理主链路,让它们协同工作;所有子节点默认关闭、`enabled=False` 时零行为变化。**这是 `[~]` → `[x]` 的收尾节点组**——把原先散落在各节点"当前"备注的接线待办统一收敛于此,避免功能各自孤立、无法真正激活。

依赖顺序：P0 → P1;P2 与 P3 可并行;P4 依赖 P3;P5 独立。每个子节点完成后,把它激活的 `[~]` 节点在 §四 升级为 `[x]`。

- [x] **P0 消息处理并发化**(P1 前置基础)
  - **目标**：`manager` 从"单条即时同步处理"升级为 `asyncio.create_task` 并发处理,保留单会话串行、优雅关闭等待在途任务。这是 L2 debounce 合并、L4 thinking 期打断的共同前提(L4/L2 备注均指向它)。
  - **验收**：并发处理多会话不串话;同一会话消息串行;`shutdown` 等待在途任务不丢消息;集成测试。
  - **产出**：manager 并发调度、单会话锁/队列、在途任务生命周期登记、单测与集成测试。
  - **依赖**：K1(生命周期)、E(多 Agent 运行时)。
  - **当前**：已完成 (2026-07-27)。
    - `main.make_message_dispatcher` (模块级工厂, 可测): `handle_message` 派生 `asyncio.Task` 立即返回 —— 适配器收取循环不再被单条消息的 LLM 往返阻塞, Telegram/Discord/WebChat 轮询循环下跨会话真并行; 单会话串行保持 (锁键 platform:user:group, 同会话任务按到达顺序创建, asyncio FIFO 就绪队列 + 公平锁保证按序获取); 任务持强引用 (inflight 集合 + done 自清理), 异常任务内捕获记日志。
    - 优雅关闭: `drain_inflight` 带超时等待在途任务; channels 生命周期改到**最后注册** (LIFO 关闭最先执行: 停收取 → drain → 再关 journal/usage/providers 等下游; 此前 channels 最先注册 → 最后关闭, providers 连接池会在在途消息处理完之前被关掉)。
    - 集成测试 `tests/integration/test_p0_concurrent_dispatch.py` (3): 跨会话并发峰值≥2 / 同会话串行且回复有序 / drain 不丢在途消息。

- [x] **P1 拟人化激活**(依赖 P0 + L1-L5)
  - **目标**：把 L2-L5 已实现能力接入主链路 —— debounce 连续消息合并接入 manager(L2);ProactiveScheduler 注入 assembly + 生命周期注册 start/stop(L3);thinking 期新消息调 `request_interrupt`、loop 读 `superseded` 抑制旧回复、InterruptInjector 注册 prompt_builder(L4);启动时 `ConversationStateStore.load` 恢复 + RecoveryInjector 注册(L5);AgentConfig 增 `conversation` 配置段。
  - **验收**：`conversation.enabled=True` 时 wait/debounce/主动任务/打断/恢复端到端可用 + 集成测试;`enabled=False` 时主链路零行为变化。
  - **产出**：manager 接线、assembly 注入与注册、AgentConfig 配置段、集成测试。
  - **依赖**：P0、L2-L5。
  - **当前**：已完成 (2026-07-27)。L1-L5 全部升级为 `[x]`。关键设计: **拟人化信号必须在会话锁外发出** —— P0 dispatcher 在获取锁前调 `AgentManager.notify_incoming` (缓存消息 + WAITING 时 MESSAGE 唤醒 wait + THINKING 时 request_interrupt), 否则锁被正在 thinking 的上一条消息持有时信号永远到不了。
    - **L2 debounce**: `_dispatch_message` 在命令拦截后 sleep 静默窗口, 窗口内有更新消息则本条弃权, 由最新消息统一 `drain_new_messages` 合并 (带说话人前缀多行输入, 一次 LLM 调用); 门控积压数按未 drain 缓存计。
    - **L4 打断**: Loop 每轮 POST_LLM 后读 `services["conversation_runtime"].interrupt_state.superseded`, 命中即 `AgentResult(interrupted=True)` 抑制旧回复; manager 转 THINKING/IDLE 状态; 下一轮 InterruptInjector 注入"被打断"提示后清空。
    - **L3 主动任务**: assembly 按 `conversation.proactive` 配置构造 ProactiveScheduler; AgentManager start/stop/destroy/reload 驱动调度循环生命周期; 唤醒回调经会话锁执行强制话轮 (合成消息带 source/intent/reason), 回复经 `session.platform_session_id` 发回原 Channel; WAITING 会话只做 PROACTIVE 唤醒不另发话轮。
    - **L5 恢复**: 快照键改用**重启稳定**的会话键 (platform:group/user, 内部 sess_* 每次重启重生成导致旧键永不命中); 回复后随记忆写入任务落快照; assembly 组装时 `load_all` 批量恢复进 RecoveryInjector, 同会话第一轮注入"刚醒来"提示。
    - 配置: `AgentConfig.conversation` 覆盖段 (SPECIFICATION 1.7 同步) + `Session.platform_session_id` 字段 (SPECIFICATION 1.2 同步) + `config.sample.jsonc` conversation 节。
    - 集成测试 `tests/integration/test_p1_humanlike_activation.py` (5): debounce 合并单次 LLM 调用 / 打断抑制旧回复+提示注入 / 主动任务强制话轮真实送达 / 快照稳定键往返恢复 / wait 被新消息唤醒 (远早于超时)。`enabled=False` 零行为变化由既有 1178 测试兜底。

- [x] **P2 Mesh 激活**(依赖 M1/M2 + E3 bus)
  - **目标**：AgentConfig 增 `mesh_role`;`manager.observe_message` 实现旁听/候选路由(M1);assembly 注入 `MeshRouter`/`MeshActionBroker`,4 个 A2A 工具(notify/handoff/list/memory_query)获得 broker 后真正可用(M2);动作审计埋点。**(2026-07-26 差距复核扩充)** broker 注入只让 `list_available_agents` 真正可用——`notify`/`handoff`/`memory_query` 若要成为"真正可用"而非"能发一条消息",还需:①`InterAgentLink` 增 `permissions`/`visible_memory_scopes`/`max_context_messages` 配置面(`links.jsonc` 与控制面 API),按 (from_agent, to_agent) 解析出对应 `MeshLinkPolicy` 注入(而非当前假设的单值 `services["mesh_link_policy"]`);②`handoff_conversation` 需接收端识别 `HANDOFF` 类型消费 `context.summary` + Router/manager 侧临时切换 `primary_agent_id`,实现真正的会话所有权转移(当前只是发了一条普通消息);③`memory_query_agent` 需接收端按 `context.filters.scopes` 过滤检索记忆,并把结果经 `bus.send` 的 response 通道同步返回给查询方(当前 `_send` 忽略 `bus.send` 返回值,查询方永远拿不到结果)。
  - **验收**：observer 只入记忆不回复、candidate 多 Agent 仲裁选回复者、A2A 动作经 InterAgentLink ACL 真实投递且可审计;notify 触发目标 Agent 真实处理、handoff 后续消息路由到接收方、memory_query 返回按 scope 裁剪的真实检索结果;集成测试。
  - **产出**：AgentConfig `mesh_role`、observe_message 路由、assembly 注入、Link 细粒度策略配置面、handoff 会话所有权转移、memory_query 同步返回通道、审计埋点、集成测试。
  - **依赖**：M1、M2、E3(InterAgentBus/Link)。
  - **当前**：已完成 (2026-07-27)。M1/M2 升级为 `[x]`。
    - **M1 observer/candidate**: `AgentConfig.mesh_role` (""/observer/candidate); `process_message._apply_mesh_routing` 用 `MeshRouter` 生成 observer/candidate 分组 → observer 各自 `AgentManager.observe_message` (只 store_episode + 画像, 不回复) → candidate 与 primary 各自 `gating_score` (ReplyNecessityJudge 归一 0~1, 不调 LLM) → `arbitrate` 显著更高 (>SWITCH_MARGIN) 才切换回复者。无 Agent 配 mesh_role 时整段短路 (getattr 防御旧 manager 替身), 零行为变化。
    - **M2 Link 细粒度 ACL**: `InterAgentLink` 落地 SPECIFICATION 2.10 已定义的 `permissions`/`visible_memory_scopes`/`max_context_messages` (前 4 字段顺序不变, 向后兼容; permissions 默认空 = notify/handoff/memory_query deny-by-default, ask 仍由 can_talk 管); `MeshActionBroker.policy_for` 按 (from,to) 从 Link 解析策略, 取代生产无人注入的单值 `mesh_link_policy`; assembly 注入 `MeshActionBroker(bus)` 到每个 Agent services。
    - **handoff 真实会话所有权转移**: `MessageRouter` 加 handoff 覆盖 (platform:group/user → agent_id, 最高优先级, 内存态); `handoff_conversation` 工具投递摘要成功后经 `services["router"].set_handoff` 登记, 后续该会话消息 `matched_by=handoff` 路由给接手方; deliver 对 HANDOFF 类型标注"[会话交接]"。
    - **memory_query 同步返回 + scope 裁剪**: `broker.memory_query` 返回响应文本 (此前返回 bool 丢弃 response); `main._answer_memory_query` 接收端按 `scopes` (user:/group:) 走 pipeline.search 的 ACL 参数真实裁剪, 结果经 bus response 同步回查询方。
    - **互联消息跳过环境门控**: `INTERAGENT_PLATFORM` 常量 —— 已过 Link ACL 的显式协作动作 (ask/notify/handoff) 目标 Agent 处理时不再走回复必要性门控 (否则 notify/交接摘要可能被静默 WAIT 掉, ask 拿空响应); 互联投递共享单一 SessionManager (此前每次投递新建, 跨 Agent 会话永不复用)。
    - 动作审计: broker 4 类动作 (含拒绝) 结构化日志埋点 (trace 贯穿, 可与发起方消息串联)。
    - 集成测试 `tests/integration/test_p2_mesh_activation.py` (7): observer 旁听入记忆不回复 / candidate 评分切换 / 无角色零行为变化 / notify 真实投递 / notify 无权限拒绝 / handoff 归属转移 (后续消息路由接手方) / memory_query scope 裁剪同步返回。

- [x] **P3 记忆检索深化激活**(依赖 N1 + VectorStore/GraphStore/Embedding/Reranker)
  - **结论**：**已完成 (2026-08-16 收敛)** —— ①图谱召回接入 + ②Reranker provider 注入 + ③MemoryItem 落地边界均于 S3 轮 (2026-07-28) 激活;集成测试 `tests/integration/test_p3_memory_retrieval.py` (8 例) 于 R7 补齐;剩余"通用实体关系图抽取层"按 R4 决策转 **Y1 (GA 后)** 承接,写边层 `GraphStore.add_edge` 已就绪。
  - **目标**：`pipeline.search()` 接入向量 KNN(VectorStore)+ 图谱邻居(GraphStore)召回,与现有 FTS/BM25/Reranker 融合;`MemoryItem`/`MemoryItemAdapter` 接入检索/注入链或明确其落地边界(N1)。(注:检索期软删除 `deleted` 过滤已由 CR2-Fix-12 生效,向量召回+RRF 融合已由 CR3-H3 生效,均不在本节点剩余范围。)**(2026-07-26 差距复核扩充)** 本节点剩余范围收窄为:①图谱召回接入(`GraphStore` 边写入 + `neighbors` 结果并入 RRF,目前全仓无 `add_edge`/`neighbors` 调用点,图始终为空);②`Reranker` provider 注入 —— `main.py` 构造 `Reranker(memory_config.get("reranker", {}))` 时从未传入 provider,`is_available()` 恒 `False`,rerank 步骤永不执行,补齐仿 CR3-H3 embedding 的写法(按 `memory.reranker.{api_key,model,protocol}` 构造 `OpenAICompatRerankerProvider` 注入);③`MemoryItem`/`MemoryItemAdapter` 接入检索/注入链或明确落地边界。
  - **验收**：配置 embedding 时向量召回已生效(CR3-H3);配置 reranker 时 rerank 步骤真实执行;图谱召回生效;被治理条目不被检索命中;`MemoryItem` 成为检索/注入统一载体;集成测试。
  - **产出**：pipeline 图谱召回接线、Reranker provider 注入、MemoryItem 接入、集成测试。
  - **依赖**：N1、N2、J2(embed/rerank Provider)。
  - **当前**：**2026-07-28 S3 激活**:`store_episode` 成功后 + `enable_graph_recall=True` 时写 user/group → episode `mentioned_in` 边 (写边失败不影响 episode 已成功存储); `_graph_search` 实现: 种子锚定调用方 user_id/group_id (满足 ACL 铁律), `graph.neighbors` 取邻居剥 `episode:` 前缀还原 memory_id, 按 weight 降序去重截断; `_build_memory_stack` 注入 `OpenAICompatRerankerProvider` (够 `api_key+model` 时, 仿 CR3-H3 embedding 注入写法), `Reranker.is_available()` 不再恒 False; pipeline 模块 docstring 明确 MemoryItem 落地边界 (检索热路径继续用 MemoryHit, 治理路径用 MemoryItemAdapter)。新增 `test_graph_recall_s3.py` (12 例)。**剩余范围**: 通用实体关系图 (人物-人物/人物-话题等语义关系抽取, 本轮只交付 mentioned_in 提及图)、P3 集成测试。

- [x] **P4 身份归一激活**(依赖 N3 + N1 + P3)
  - **结论**：**已完成 (2026-08-16 收敛)** —— 控制面 bind/conflicts/resolve 于 S4 轮 (2026-07-28) 激活;集成测试 `tests/integration/test_p4_identity_bind.py` (6 例: 两平台 bind 同 person_id + 记忆按归一身份聚合 + 冲突裁决) 于 R7 补齐。
  - **目标**：gateway 入站主链路接入 `IdentityResolver.resolve`,把跨平台同一用户归一到统一 identity;记忆按归一身份聚合。
  - **验收**：不同 IM 的同一用户归一为同一 person、记忆按归一身份聚合、低置信冲突写入 `identity_conflicts` 供人工裁决;集成测试。
  - **产出**：gateway 接线、记忆聚合按归一身份、集成测试。
  - **依赖**：N3、N1、P3。
  - **当前**：**2026-07-28 S4 激活**:`IdentityResolver` 新增 `resolve_conflict` (人工裁决 conflict + 更新 person_id); 新建 `routes_identity.py` (bind / list conflicts / resolve conflict 三个 REST 入口, scope=identity:read/write, 无 resolver 注入时返回 None 不挂载); `server.create_control_app`/`_mount_optional_routers` 接收 `identity_resolver`; `main` 把 `services["identity_resolver"]` 注入并经 `_register_control_plane` 透传 (helper `_mount_identity_workflow_routers` 抽出避免 C901 超)。新增 `test_routes_identity.py` (7 例)。**剩余范围**: P4 集成测试 (两平台同一自然人 bind → 记忆聚合验证)。

- [x] **P5 企业化激活**(依赖 O1/O2/O3)
  - **结论**：**已完成 (R6, 2026-08-16 收敛)** —— Workflow action_handler + 声明式加载于 S5 激活;R6 补齐 routes_tenants + TenantManager、loader 子进程隔离经核验已满足、`agent:` 工具入口决策落地 (选 B 文档化不做);集成测试 `tests/integration/test_p5_enterprise_isolation.py` (5 例) 于 R7 补齐。
  - **目标**：`TenantIsolationGuard` 接入 memory store/control/用量计量 + MetadataStore 增 `tenant_id` 列 + `routes_tenants` 控制面(O1);`PluginIsolationHost` 接入 loader 作为可选隔离模式(O2);`WorkflowEngine` 暴露 control 路由/工具入口 + 生产注入 action handler(O3)。
  - **验收**：跨租户不可见且控制面按租户鉴权、插件进程隔离可选启用且崩溃可恢复、Workflow 可声明式执行且可观测;集成测试。
  - **产出**：租户接线 + tenant_id 列 + routes_tenants、loader 隔离模式、workflow 控制面入口、集成测试。
  - **依赖**：O1、O2、O3、G(控制面)。
  - **当前**：**2026-07-28 S5 激活 (O3 部分)**: 新建 `isac/runtime/workflow/actions.py` (生产 action_handler: `tool:<name>` 前缀经 agent_manager.get 取 ToolRegistry.execute + 最小 AgentContext 构造; 未知前缀记 warning noop 不触发重试; `agent:` 前缀 noop 留 P5 决策) + `isac/runtime/workflow/loader.py` (声明式加载: `load_workflows_from_dir` 扫描 `*.json` 解析为 Workflow + register, 单文件失败跳过不阻塞其余); `main._build_workflow_engine` helper 注入 handler/evaluator 并按 `definitions_dir` 加载; 新增 `test_workflow_s5.py` (13 例)。**剩余范围**: O1 routes_tenants 控制面、O2 loader 隔离可选模式、O3 Agent 工具入口 (P5 决策项, 有意未做)、P5 集成测试。

---

### MVP-Fix MVP 增量代码评审修复轮 (2026-07-27)

**背景**：P0-P2 + Q0-Q1 达成 MVP 准入线后，对整个增量 diff (23 文件 / +1430 行) 做了 5 维度并行审查 + 每条发现 2 票独立对抗性验证 (22 个代理，405 次代码检索)。17 项发现中 **13 项确认、4 项被证伪**。全部已修复并配回归测试 (`tests/integration/test_mvp_review_fixes.py`，12 例)。

- [x] **MVP-Fix 高危 (5)**
  - **打断在多步(工具)回合中失效**：`InterruptInjector.build()` 会消费并清空 `interrupt_state`，而它在每轮迭代开头的 prompt build 里运行 —— 工具执行期间到达的打断被下一轮 build 吞掉，POST_LLM 检查永远读不到 → 陈旧回复照发。修复：`ConversationRuntime` 增**单调递增** `interrupt_seq` (不被 clear 复位)，Loop 在回合开始快照基线，用"序号是否增长"判定；并把判定提前到 prompt build 之前 (省掉一次注定丢弃的 LLM 调用)。同时避免"接替的新回合误读上一回合的 superseded 标志而自杀"。
  - **突发消息重复回复**：debounce 弃权是纯时间判定，锁串行下突发中段消息 drain 全部并回复后，末条自身回合 drain 为空却退回用本条内容再回复一次。修复：`_drain_pending` 返回空即弃权。**根因**（审查只看到症状）：`notify_incoming` 缓存的是原消息对象，而 `process_message` 传下来的是 `dataclasses.replace(...)` 新对象，身份去重永不命中 → 每条消息被缓存两次；去重键改为 `msg_id`。
  - **门控只评估突发末条**：靠前消息的 @提及/内容分被丢弃，整个突发可能一条不回。修复：drain 提到门控之前，`has_at`/`has_mention` 取整批并集，`pending_count` 按真实批量计。
  - **后台记忆写入不被 drain**：消息任务产出回复即离开 dispatcher 的 inflight，其派生的记忆写入仍在跑，关闭链不等待 → 最后若干轮的 episodic/画像/快照在事件循环收尾取消任务时静默丢失。修复：`AgentManager.drain_background_tasks()` + 接入关闭链 (顺带停 ProactiveScheduler 的裸 create_task 循环)。
  - **memory_query 空 scopes 泄露全部记忆**(安全)：`visible_memory_scopes` 默认就是空，而空 scopes 走的是无 user/group 过滤的全量检索 —— 管理员只授予 `permissions=["memory_query"]` 忘配 scopes 时，对端可读取目标 Agent 的全部记忆(含他人私聊)。修复：**空 scopes 一律拒绝** (deny-by-default)，未知 scope 格式保守跳过。
- [x] **MVP-Fix 中危 (4)**
  - **handoff 永久劫持路由**：移交是最高优先级且全仓无 clear 调用点，一次移交无限期覆盖包括显式 @ 在内的所有路由信号。修复：TTL (默认 1h，到期自动回落) + 移交给自己 = 交还归属。
  - **强制话轮释放他人的会话锁**：`lock.locked()` 判定释放 —— 会话锁是共享对象，若在 `acquire()` 处被取消 (scheduler.stop 传播)，finally 会释放并发消息持有的同一把锁，单会话串行被破坏。修复：改用严格配对的 `acquired` 标志。
  - **互联消息被 debounce 拦截**：A2A 消息已过 Link ACL，却仍被静默窗口延迟/弃权 (与门控豁免同源问题)。修复：`INTERAGENT_PLATFORM` 豁免 debounce。
  - **UserMapper 身份分裂**：resolve 的 check-then-create 之间有 DB await，P0 并发化后同一用户首次在两个会话同时出现会创建两个 master_id。修复：`asyncio.Lock` 串行化临界区。
- [x] **MVP-Fix 低危 (3) 与顺带修正**
  - 会话快照只增不删 → `load_all` 顺带清理过期/损坏文件；快照目录跟随 `control.agents_dir` 配置 (此前硬编码写进真实 `data/agents`，测试互相污染)。
  - `config.sample.jsonc` 的 `embedding.dimension=1024` 与示例模型 `text-embedding-3-small`(1536) 自相矛盾 → 修正并注明常见模型维度。
  - `InterAgentMessage.trace_id` (SPECIFICATION 2.10 已定义、实现缺失) → 补齐，未显式传入时从日志上下文继承，响应沿用同一 trace。
  - **记忆保真度**(冒烟发现)：合并回合此前只把"触发那条"写进记忆，Agent 实际看到的是整个 burst → 改为写入合并后的完整输入。
- **被证伪 (4)**：ProactiveScheduler 孤儿循环的严重度描述、UserMapper 每消息连接开销、`_apply_mesh_routing` 的 session_id 副作用、SQLITE_BUSY 静默吞。前三项机制描述属实但后果不成立，第四项前提不成立。

---

### S 骨架轮 (2026-07-27)

**背景**：MVP 收尾后,按"把待开发功能一次搭全骨架"的要求,为 P3-P5 与 O4/O5/MemoryConsolidator/proactive-ext 一次性补齐**骨架 + 默认关闭接线锚点**。全部遵循 MODULE_GUIDE §二"六要素"范式:契约 + 骨架类 + 惰性默认关闭接线 + 骨架单测 + ruff/mypy 绿 + 文档同步;`enabled=False`/无注入时**主链路零行为变化**,`TODO(节点)` 标注真实实现待办。**这些节点仍为 `[~]`/`[ ]`,骨架≠交付**——真实激活按 §二完成定义 + P3/P4/P5 验收执行。新增 6 个骨架测试文件(40 例),全量 1271 单测通过。

- [x] **S1 主动任务其他生产者骨架**(proactive-ext,扩充 L3/P1)
  - `isac/runtime/conversation/producer.py` 新增 `DateReminderProducer`/`TopicFollowupProducer`/`MemoryAssociationProducer`(`__call__` 恒返回 [])+ `CompositeTaskProducer`(汇总多生产者、单个异常隔离);`assembly._build_task_producer` 按 `conversation.proactive.*_enabled` 组合(默认全关 → 仅 idle_reengage 或 None)。附 `test_proactive_producers_scaffolding.py` (6)。**2026-07-28 激活**: 三个 Producer `__call__` 改 async + 填真实产出逻辑 (DateReminder 从 `memory.search` 查日期关键词+正则解析+同年同日去重; TopicFollowup 末条用户消息含延后型短语/问号结尾+冷却窗口+同窗口去重; MemoryAssociation 拼接近消息为 query 检索+score 阈值+per-session hit.id 去重); `_build_task_producer` 加 memory 参数,`_setup_conversation_runtime` 透传。ACL 锚点 = 末条消息的 user_id/group_id (复用 `memory.search` 既有 ACL)。骨架单测改为 await 调用,新增 `test_proactive_producers_s1.py` (16 例)。
- [x] **S2 MemoryConsolidator 骨架 + 后台挂点**
  - `isac/memory/consolidator.py` 由纯 `NotImplementedError` 重写为骨架:`run_once` 为 no-op 返回全零 `ConsolidationResult`,`start/stop` 后台循环(仿 ProactiveScheduler);`assembly._build_memory_consolidator` 按 `memory.consolidation.enabled` 默认关闭构造,`AgentManager` start/stop/destroy/reload 四处驱动生命周期(与 proactive_scheduler 同构)。附 `test_memory_consolidator_scaffolding.py` (6)。**2026-07-28 激活**: `run_once` 实现三步真实整合 (各步独立隔离异常): ① 去重合并 (规范化内容分桶 + `difflib.SequenceMatcher` 相似度判定 + 经 `MemoryGovernor.delete` 软删较旧者, governor 拒绝 protected/frozen); ② 重要性+时间衰减剪枝 (created_at 早于阈值 + importance 低于阈值 → 软删); ③ 画像归纳 (仅 llm 注入时, 对近期活跃 person 用 LLM 生成 profile_text 写回 `upsert_person_profile`, LLM 失败隔离)。`_build_memory_consolidator` 加 llm 参数。新增 `test_memory_consolidator_s2.py` (10 例)。
- [x] **S3 图谱召回 `_graph_search` 骨架**(→ P3)
  - 见 §四 P3"当前"。`enable_graph_recall` 默认关闭,`_merge_results` 第四路 RRF 就位。**2026-07-28 激活**: `store_episode` 成功后 + `enable_graph_recall=True` 时写 user/group → episode `mentioned_in` 边 (写边失败不影响 episode 已成功存储); `_graph_search` 实现: 种子锚定调用方 user_id/group_id (满足 ACL 铁律), `graph.neighbors` 取邻居剥 `episode:` 前缀还原 memory_id, 按 weight 降序去重截断; `_build_memory_stack` 注入 `OpenAICompatRerankerProvider` (够 `api_key+model` 时, 仿 CR3-H3 embedding 注入写法), `Reranker.is_available()` 不再恒 False; pipeline docstring 明确 MemoryItem 落地边界 (检索热路径继续用 MemoryHit, 治理路径用 MemoryItemAdapter)。新增 `test_graph_recall_s3.py` (12 例) 覆盖写边 + 真实召回 + 去重 + 降级 + Reranker 注入。
- [x] **S4 身份归一主链路接线锚点**(→ P4)
  - 见 §四 P4"当前"。`_resolve_identity` + `_build_identity_resolver` 默认关闭。**2026-07-28 激活**: IdentityResolver 新增 `resolve_conflict` (人工裁决 conflict + 更新 person_id); 新建 `routes_identity.py` (bind / list conflicts / resolve conflict 三个 REST 入口, scope=identity:read/write, 无 resolver 注入时返回 None 不挂载); `server.create_control_app`/`_mount_optional_routers` 接收 `identity_resolver`; `main` 把 `services["identity_resolver"]` 注入并经 `_register_control_plane` 透传 (helper `_mount_identity_workflow_routers` 抽出避免 C901 超)。新增 `test_routes_identity.py` (7 例) 覆盖 bind 落 verified / list_conflicts / resolve_conflict 404 / resolve 标 resolved 后 list 不再返回。
- [x] **S5 Workflow 控制面入口骨架**(→ P5/O3)
  - 见 §四 P5"当前"。`routes_workflows`(list/get/start)+ `WorkflowEngine.list_workflows()` 访问器,`control.workflow.enabled` 默认关闭。**2026-07-28 激活**: 新建 `isac/runtime/workflow/actions.py` (生产 action_handler: `tool:<name>` 前缀经 agent_manager.get 取 ToolRegistry.execute + 最小 AgentContext 构造; 未知前缀记 warning noop 不触发重试; `agent:` 前缀 noop 留 P5 决策) + `isac/runtime/workflow/loader.py` (声明式加载: `load_workflows_from_dir` 扫描 `*.json` 解析为 Workflow + register, 单文件失败跳过不阻塞其余); `main._build_workflow_engine` helper 注入 handler/evaluator 并按 `definitions_dir` 加载; Agent 工具入口 (Agent 主动触发 workflow) 为 P5 决策项, 有意未做。新增 `test_workflow_s5.py` (13 例) 覆盖 action_handler 分发/重试/noop + condition_evaluator + 声明式加载 + 端到端 (声明式加载 → 控制面 start → 真实 tool: 执行 → succeeded)。
- [x] **S6 O5 视频 Provider 注册挂点**
  - 见 §四 O5"当前"。`kind="video_gen"` 接入 `_build_multimodal_provider`,default-off,`generate` 仍抛 `NotImplementedError`(端点二次确认闸门)。
- [x] **S7 O4 飞书/微信/QQ 官方三平台适配器骨架**
  - 见 §四 O4"当前"。三平台骨架 + enabled-gated 注册分支,QQ 官方(`qq_official`)与 OneBot(`qq`)并存不撞键。**2026-07-28 飞书激活**: 见上节。**2026-07-28 QQ 官方激活**: QQOfficialAdapter 真实实现 Webhook 入站 (Ed25519 验签: seed=secret 重复双倍到 32 字节作 Ed25519 seed, 字节序核对自 bot.q.qq.com 官方文档; op=13 验证握手签名 event_ts+plain_token 回响应; op=0 dispatch 事件验签 X-Signature-Ed25519 + X-Signature-Timestamp, msg=timestamp+raw_body; AT_MESSAGE_CREATE/GROUP_AT_MESSAGE_CREATE/C2C_MESSAGE_CREATE 三类事件规范化 member_openid/user_openid→user_id, channel_id/group_openid→group_id, data.id→msg_id 供被动回复) + 出站 (access_token 换取+缓存提前 60s 刷新; 群消息 POST /v2/groups/{group_openid}/messages, 私聊 POST /v2/users/{openid}/messages, Header Authorization: QQBot <token>, 被动回复带 msg_id)。不引入 botpy SDK, 用 httpx+uvicorn+cryptography 既有依赖。注意 0 在 Python 是 falsy (`0 or -1`=-1) 会误判 op=0, 用 `op_raw is None` 显式判定。新增 `test_qq_official_adapter.py` (19 例) 覆盖验证握手签名/验签/事件规范化/三类消息/send 群聊+私聊+token 缓存+失败降级/_derive_seed 派生算法。(注: 微信 wecom 企业微信模式后续已实现并注册, 见 §四 O4"当前"2026-07-29 校正; 仅 mp 公众号仍骨架。)

---

### Q MVP 收尾

**目标**：2026-07-26 对照 `docs/REQUIREMENTS.md` 十二条原始需求做 10 域并行代码取证(498 次代码检索 + 一次真实启动实测)后,发现一批 **MVP 必需、但未被 P0-P5 任何节点覆盖**的缺口 —— 既包括生产入口的"最后一厘米接线"(Channel 注册、工具注册),也包括此前未曾识别的**全新缺口**(记忆写入回路)。所有子节点默认不影响现有测试(新增代码路径,不改动既有默认关闭行为)。MVP 发布以 **P0-P2 + Q0-Q1** 完成为最低准入线(详见 [ROADMAP.md](./ROADMAP.md) M-MVP 里程碑)。

依赖顺序：Q0/Q1 不依赖任何 P 节点,可立即开工(Q1 最高优先级);Q2-Q6 相互独立、与 P 节点亦无强依赖,可按人力并行插入。

- [x] **Q0 开箱可触达与配置纠偏**(纯接线与纠偏,不依赖 P 节点)
  - **目标**：让"拷贝 `config.sample.jsonc` 并启动"就能获得至少一条零外部依赖的可聊通道,并修正一批会误导新用户的样例配置死键与生产健壮性缺口。
  - **验收**：`main()` 补齐 Telegram/Discord/WebChat 三个注册分支(镜像 OneBot 分支);裸部署(无 `data/routing.jsonc`)时已启用平台有默认路由,不再全部 DROP;`config.sample.jsonc` 修正 `control.auth_token`→`api_token`、`channels.onebot.ws_reverse_url`→`host/port`、`channels.webchat` 死配置、`alerting` 死键;Dockerfile 补 `COPY uv.lock` + `uv sync --frozen`(构建可复现);`docker-compose.yml` 按需补 OneBot 场景的 8080 端口映射说明;Windows `main()` 用 `try/finally` 包 `shutdown()` 且捕获 `KeyboardInterrupt`,Ctrl+C 走优雅关闭;`web_search` 默认策略由 `allow` 改 `deny`(无后端时不出现在 LLM schema 里);`ProviderManager._agent_providers` 在 `reload_config`/`destroy` 时失效缓存(PATCH 改 llm 立即热生效);`AgentManager.destroy(keep_memory=False)` 清理 `data/agents/<id>/memory`;`agent/tools/registry.py` 修正过期的 `task`→`task_runner` 映射(改查 `subagent_supervisor`,否则 SubAgent 委派被挡死)。
  - **产出**：`main.py` 三个 channel 注册分支、`config.sample.jsonc` 修正、`Dockerfile`/`docker-compose.yml` 修正、`main.py` 优雅关闭修正、`ProviderManager`/`AgentManager` 缓存失效修正、`registry.py` 映射修正、对应单测与一次多平台冒烟。
  - **依赖**：H1(适配器实现)、K1(生命周期)、K8(CI/Docker)。均已具备,本节点是纯接线与纠偏。
  - **当前**：已完成 (2026-07-27)。验收清单逐项落地:
    - `main._register_channel_adapters` 四平台按 `channels.*` 配置惰性注册 (未启用零 import);`main._ensure_default_routing` 裸部署 (bindings 与 default_agents 全空) 时为已注册平台登记默认 Agent (仅内存不落盘, 用户显式配置过任何路由即不动)。
    - `config.sample.jsonc` 四死键修正 (`api_token`/`host+port`/webchat 注释附 curl 示例/alerting 标注未接线);Dockerfile `COPY uv.lock` + `--frozen`;compose 附 8080/8090 端口映射注释;`main()` try/finally 优雅关闭;`web_search` 全局与 RESTRICTED 模板均改 deny;`ProviderManager.invalidate_agent_provider` + `AgentManager.reload_config/destroy` 接线 (含 aclose 释放连接池);`destroy(keep_memory=False)` 经 pipeline 的 namespace/MetadataStore 硬删三表 + `SparseBM25Index.clear` (shared 命名空间拒绝清理, 原 TODO 落地);registry `task` 门改为 `("subagent_supervisor", "task_runner")` 任一注入即放行 (restricted 门支持备选服务键)。
    - **冒烟发现并修复两个开箱不可聊的隐藏缺陷**: ① `_send_reply` 构造回复不带 session_id;② 更根本的 —— `SessionManager.get_or_create` 会把消息 session_id 改写为内部 `sess_*`, 平台侧会话键丢失, WebChat 回复与 D9 进度帧都落错队列 → `process_message` 现在在改写前捕获 `platform_session_id` 并透传 `_send_reply`/`_make_progress_sender`。
    - 真实启动冒烟通过: 拷 sample 起进程 → `POST /webchat/send` → 默认路由 → StubProvider 回复 → `GET /webchat/poll` 按客户端会话键取回。附 `tests/unit/test_q0_wiring.py` (14 测试)。

- [x] **Q1 记忆写入回路与身份稳定化**(MVP 最高优先级,不依赖 P0)
  - **目标**：补齐 K3 验收要求但从未接线的"消息/会话结束后真实写入 Episode"——这是记忆检索/注入/治理整条链路能真正发挥作用的前提,当前该链路读侧全通但生产端零写入,记忆恒为空。同时稳定化 person_id 与 Session。
  - **验收**：每轮对话回复后(或 `POST_MESSAGE` hook)真实调用 `store_episode`;每 N 轮或每次互动后更新人物画像(`upsert_person_profile`)与 `relationship_depth`/`interaction_count`;行话学习(可选,降级不阻塞 MVP);聊天 → 重启 → 记忆检索命中;`UserMapper` SQLite 持久化,`person_id` 跨重启稳定;`SessionManager` 状态持久化(可选,MVP 可接受会话状态重启丢失但需在文档准确标注,不得再宣称"可持久化恢复")。
  - **产出**：`_dispatch_message`/`process_message` 记忆写入接线、画像/关系更新回路、`UserMapper` 持久化、集成测试(聊天→重启→检索命中、画像随轮次加深)。
  - **依赖**：K3(存储基建)、D6-D7(检索/注入)、K4(持久化恢复框架)。
  - **当前**：已完成 (2026-07-27)。
    - **episodic 写入回路**: `AgentManager._dispatch_message` 回复后经 `_schedule_memory_write` 后台任务调 `instance.memory.store_episode` (存整轮对话"用户话+回复", importance 启发式 0.5); 后台化避免给回复路径加延迟 (配 embedding 时写入含一次向量化 API 调用); 任务强引用集合 + done 自清理; 失败降级只记日志 (SPECIFICATION 5.1)。
    - **画像/关系回路**: `_update_person_profile` 每次互动 `interaction_count+1`、`relationship_depth+0.01` (封顶 1.0)、name/first_seen/last_seen 维护; person_id 与读侧 (PersonProfileInjector/query_person_profile) 同口径 —— 优先 UserMapper master_id, agent 键用 instance.agent_id。画像文本 LLM 归纳留 MemoryConsolidator (MVP 后)。
    - **UserMapper SQLite 持久化**: 写穿模式 (user_bindings + user_profiles 两表, 含 behavior_patterns JSON), 内存缓存未命中先查 DB 恢复既有 master_id; 不传 db_path 保持纯内存 (测试零行为变化); main 接 `data/gateway/identity.db`。
    - **边界**: 行话学习未做 (可选项, 归 MemoryConsolidator); SessionManager 状态仍不持久化 (已在 PROGRESS 如实标注); `config.sample.jsonc` 的 `memory.enabled` 默认改 true (纯 SQLite 零外部依赖, "越聊越熟"开箱生效)。
    - 集成测试 `tests/integration/test_q1_memory_write_loop.py` (4): 聊→重启(新 pipeline 预热)→BM25 命中、画像随互动加深、UserMapper 重启同 master_id、纯内存模式零行为变化。

- [x] **Q2 人格差异化实现**(依赖 D8 人格系统 + D2 prompt_builder)
  - **目标**：让 `AgentConfig.persona` 配置的人格文本真正影响 System Prompt,并把 D8 已实现但未注册的情绪/表达风格/注意力漂移能力接入 Prompt 组装与更新回路,使不同 Agent 的人格差异在回复中可辨。
  - **验收**：`persona` 文本接入 `BaseIdentityInjector`(或新增专用注入器);`MoodInjector`/`ExpressionStyleInjector`/`AttentionDriftInjector` 实现真实文案(非空串)并注册进 `prompt_builder`;`MoodEngine.update/decay` 在 `POST_LLM`/`FINAL_RESPONSE` 或周期任务中真实被调用,情绪随对话变化;`PersonaManager.get_expression_style/get_drift_level` 有生产调用点。
  - **产出**：`BaseIdentityInjector` persona 接线、三个注入器实现+注册、情绪更新回路、集成测试(两个不同 persona 配置的 Agent 回复风格可辨)。
  - **依赖**：D8(PersonaManager/MoodEngine 已实现)、D2(prompt_builder)。
  - **当前**：**已完成 (2026-07-29 实现落地)**。①`config.persona.description`(Agent 级覆盖全局 `persona.description`, 契约见 `SPECIFICATION.md` 1.6/1.7 + `config.sample.jsonc`)接入 `BaseIdentityInjector`(`assembly.py:254-259`);未配置时回落原默认文案, 零行为变化。②新增 `MoodTracker`(`isac/persona/mood_tracker.py`), 经 `PersonaManager.register_hooks` 与 `BehaviorLearner` 同点挂 `FINAL_RESPONSE`:每轮先 `decay()` 自然衰减,再按本轮工具调用数(封顶 5 次, `AROUSAL_STEP_PER_TOOL_CALL=0.03`)对 `arousal` 施加小幅扰动 —— `valence` 不臆造对用户情绪的主观判断, 只交给 `decay` 回归中性,符合 `HUMANLIKE_RUNTIME.md` 6.2"缓慢变化不剧烈波动"。三注入器与 `PersonaManager` 访问器沿用既有接线(均为真实逻辑非空桩)。**2026-07-29 复核修正**:初版 arousal 扰动读 `response.tool_calls`,但 `FINAL_RESPONSE` 触发条件恰是 `response.tool_calls` 为空(`isac/agent/loop.py` 的 `else` 分支),该信号源恒为 0,是死代码;改为 `AgentContext.tool_calls_this_turn`(由 loop.py 在工具调用分支里累加)读取,并新增跑真实 `ISACAgentLoop` 的端到端测试防止同类回归。新增 `tests/unit/test_persona.py::TestMoodTracker`(5 例)+`test_register_hooks_attaches_mood_tracker`、`tests/unit/test_persona_injectors.py` 新增 3 例(persona 文本接线/回落默认/全局兜底);ruff/mypy 全绿, 全量回归(1473 单测 + 72 集成)无退化。

- [x] **Q3 插件与 MCP 生态数据面接线**(依赖 F1-F4/E4/H2,均已实现)
  - **目标**：让插件(Native/AstrBot/MaiBot)与 MCP Server 注册的工具/命令/注入器真正进入 Agent 的运行时注册表并被 LLM 调用,而不仅仅是"加载成功但惰性"。
  - **验收**：`main.py` 构造 `PluginContext` 时传入真实的进程级共享工具/命令/注入器注册表(复用已验证的 `assembly.py:100-104` `plugin_agent_hooks` 模式),`assemble_agent` 把共享注册表合并进每个 Agent 的 `ToolRegistry`/`CommandRegistry`/`SystemPromptBuilder`;`plugin/runtime/loader.py` 加载 AstrBot/MaiBot 插件后调用 `FunctionToolAdapter`/`MaiBotPluginAdapter.adapt` 完成真正桥接;`PluginManager` 构造时传入 `EnableMatrix`,`plugins_allow`/`plugins_deny` 对插件 hooks 真实生效;`AgentConfig.mcp_servers` 配置后,`assembly` 按需构造 `MCPClient`、`connect`、把 `list_tools` 结果注册进 `ToolRegistry`,Agent 停止/销毁时 `disconnect`;`tools.workspace_root`/`tools.bash_allowlist` 配置项接入 `build_services`,使 `bash`/`read_file`/`write_file` 三个 CLI 工具不再因 services 未注入而恒被拒绝。
  - **产出**：共享注册表机制、AstrBot/MaiBot 桥接接线、PluginManager EnableMatrix 注入、MCP Client 生产接线、CLI 工具 services 注入、集成测试(示例插件注册的工具被 LLM 真实调用)。
  - **依赖**：F1-F4(兼容层与加载器已实现)、E4(EnableMatrix 已实现)、H2(MCPClient 已实现)。
  - **当前**：**已完成 (2026-08-16, 由 R3 收敛)**。原三项剩余全部落地: ① per-Agent `PluginContext` 的 `_tools/_commands/_prompt_builder` 不再留 None —— `_fire_plugin_on_load` 建立进程级共享 `ToolRegistry`/`CommandRegistry`/`SystemPromptBuilder` 注入 `make_plugin_context`, native 插件 `register_*` 真实写入; 新建 `AstrBotStarAdapter` (`isac/plugin/compatibility/astrbot/adapter.py`) + `_adapt_compat_plugins` 把 AstrBot `@filter.llm_tool` / MaiBot `@register_action`/`@register_command` 桥接进共享表 (loader 不改: ToolRegistry per-Agent, adapt 在共享收集层); `assemble_agent` 经 `_merge_shared_plugin_tools`/`_merge_shared_plugin_commands` 合并共享表进 per-Agent registry。② `MCPClient` 生产接线: `build_services` 注入 `services["mcp_servers"]` (config.jsonc 顶层 `mcp.servers` 节), `assemble_agent` 经 `_wire_mcp_clients` 按 `AgentConfig.mcp_servers` 构造+connect+list_tools 注册 `MCPToolBridge`, `AgentManager.stop`/`destroy`/`_shutdown_message_pipeline` 调 `disconnect`。③ CLI 工具 services 注入此前已完成。EnableMatrix 注入 PluginManager (hooks 生效) + 共享 hooks 合并 (`assembly.py:269-273`) 保持。新增 7 例单测 + 真机冒烟 (`dev_mcp_echo_server.py` → `MCP server 已接入 server=echo tools=1`); ruff/mypy 全绿。AstrBot `@filter.on_message`/`@filter.on_llm_request` hook 桥接 (EventBus/AgentHooks 签名适配) 与兼容层进程隔离迁移 (需 manifest 机制) 留后续, 非本节点"工具激活"范围。

- [x] **Q4 多模态工具注册与计量收尾**(依赖 J1/J2,均已实现)
  - **结论**：**已完成 (R1, 2026-08-16 收敛)** —— 6 工具注册 (87a84fa) + R1 补齐出站 artifact 扫描、入站落盘 `data/uploads/`、6 个 `record_*` 计量接入、`data/pricing.jsonc` 价目表加载、`model_capabilities_allow` 字段;集成测试见 `test_r1_*`。
  - **目标**：打通 J2 已就绪的 Provider/Router/Catalog/ArtifactStore 与 Agent 侧的"最后一厘米"——6 个语义媒体工具注册进 ToolRegistry,出入站媒体链路可用,多模态用量真实可查。
  - **验收**：`assembly.py` 注册 vision/STT/TTS/生图/视频理解/视频生成 6 个 `media.py` 工具(视频两模态可保留桩,待 O5 二次确认端点);`AgentConfig` 增 `model_capabilities_allow` 字段并映射为工具可见性;`_send_reply` 扫描回复中的 `artifact_id` 引用,经 `MediaResolver.resolve_for_channel` 转换为对应 Channel 的 segment 发送;入站媒体(用户上传图片/语音)下载落盘到 `data/uploads/`,`MediaNormalizer` 白名单相应扩展,生成合法 `media_uri` 供工具使用;`_MediaToolBase`/`EmbeddingManager`/`Reranker` 调用点接入 `UsageRecorder` 的 6 个多模态 `record_*` 方法;`data/pricing.jsonc` 价目表加载机制落地,`ModelUsageEvent` 的 provider 字段与价目表 key 对齐(而非记 `type(provider).__name__`)。
  - **产出**：媒体工具注册、`model_capabilities_allow` 字段、出/入站媒体链路、多模态计量埋点、价目表加载、集成测试(配置生图/视觉 key 后发图/识图全链可用且计量有数)。
  - **依赖**：J1(用量框架)、J2(Provider/Router/Catalog/ArtifactStore)。
  - **当前**：**部分接线 (2026-07-29 代码复审校正, 原标"未开始"不准)**。6 个语义媒体工具 (`GenerateImageTool`/`GenerateVideoTool`/`TranscribeAudioTool`/`SynthesizeSpeechTool`/`VisionUnderstandTool`/`UnderstandVideoTool`) 已注册进 ToolRegistry (`assembly.py:312-317`, 默认 deny, 需 `tools_policy` 显式开启)。**剩余**: ① 出站 `_send_reply` 仅处理纯文本 (`main.py:209`), 不扫描 `artifact_id`、不经 `MediaResolver.resolve_for_channel` → LLM 生成的图/语音发不出去; ② 入站用户媒体不下载落盘 `data/uploads/`, `MediaNormalizer` 白名单未扩展; ③ `UsageRecorder` 的 6 个 `record_*` 多模态方法零生产调用 → 多模态用量恒 0; ④ `PricingCatalog()` 构造传空表 (`main.py:770`), `estimated_cost` 恒 `None`; ⑤ `AgentConfig` 无 `model_capabilities_allow` 字段 (现经 `getattr` 兜底空)。接线后升级 `[x]`。

- [x] **Q5 WebUI 与控制面收尾**(依赖 J3/G2/G3,均已实现)
  - **结论**：**已完成 (R2, 2026-08-16 收敛)** —— Extensions/SSE/Usage 页此前已接真实数据;R2 补齐 `GET /agents/{id}/config` 真实 revision、SubAgent 表 list-all、routes_webhooks + EventBus 订阅 + 告警推送激活、MCP Server 生产启动点 + 5 工具补齐。
  - **目标**：修掉 J3 WebUI 与 G2/G3 控制面里"看起来完成但实为占位"的断点,并给自动化场景补上生产启动点。
  - **验收**：Extensions 插件页改接真实 `/agents/{id}/plugins` API;SubAgent 任务表改正确 `agent_id` 参数(而非硬编码 `_`);新增 `GET /agents/{id}/config` 返回全量配置 + 真实 `revision`,WebUI `loadConfigForEdit` 改用它(乐观锁真实生效);WebUI 消费 `/events/stream` SSE(`EventSource`);Usage 明细表按实际 API 返回结构(裸数组)解析,不再读 `events?.events`;补 `routes_webhooks`(subscribe/unsubscribe/list + `/automation/trigger`)并在 `main.py` 构造 `WebhookManager` 订阅 `EventBus` 事件;`isac/control/mcp_server.py` 补生产启动点(独立进程或桥接到 Admin API)并补齐 5 个声明但未实现的工具;密钥管理策略文档化为"配置文件 + env 覆盖"(`ISAC_API_TOKEN` 已支持,Provider `api_key` 同理补 env 映射),`SecretStore` 接线留 MVP 之后。
  - **产出**：WebUI 断点修复、`GET /agents/{id}/config` 端点、SSE 前端消费、Webhook 路由与事件源接线、MCP Server 启动点、密钥管理文档、集成测试。
  - **依赖**：J3(WebUI v2)、G2(MCP Server)、G3(Webhooks)。
  - **当前**：**部分接线 (2026-07-29 代码复审校正, 原标"未开始"不准)**。Extensions 页已接真实 `/plugins/loaded` (`app.js:481`)、SSE `EventSource('/events/stream')` 已消费 (`app.js:292` + `routes_events.py` scope 过滤/断线恢复/连接上限)、Usage 明细表按正确结构解析。**剩余**: ① `GET /agents/{id}/config` 端点缺失 → 前端 `loadConfigForEdit` 伪造 `revision=1`, 乐观锁未真实生效; ② SubAgent 任务表调 `GET /agents/_/subagent-runs` (`app.js:495` 硬编码 `_`) → 恒空 (后端 `/{agent_id}/subagent-runs` 未被正确调用); ③ `WebhookManager`/`ISACMCPServer` 无生产启动点与路由挂载 (`main.py` 未实例化, `server.py` 未 include)。接线后升级 `[x]`。

- [x] **Q6 SubAgent 用量与安全补漏**(依赖 J4,已实现)
  - **结论**：**已完成 (R2, 2026-08-16 收敛)** —— usage/evidence 保留 + 并发信号量 + `delegate_task` restricted deny 此前已完成 (dbb58eb);R2 补齐背景摘要经 `ContextEnvelopeBuilder` 传子 Agent + `evidence_refs` 真实生成。
  - **目标**：让 J4 SubAgent 的用量/证据数据真实可信,并补上两个安全口子。
  - **验收**：`supervisor` 保存 `result.usage`/`evidence_refs` 到 `run.tokens_used`/`tool_calls_used`/journal(而非只留 `summary`);`delegate_task` 收集的背景摘要经 `ContextEnvelopeBuilder` 真正传给子 Agent;`SubAgentPolicy`/`supervisor` 加并发上限(信号量或计数器);`control/defaults.py` 的 `RESTRICTED_TOOLS_POLICY` 补 `deny` `delegate_task`。
  - **产出**：supervisor 用量/证据保存、summary 传递接线、并发信号量、受限策略修正、集成测试。
  - **依赖**：J4(SubAgent Runtime)。
  - **当前**：**大部分完成 (2026-07-29 代码复审校正, 原标"未开始"不准)**。`supervisor` 已把 `result.usage` 存入 `run.tokens_used`、`evidence_refs` 存入 `run.evidence_refs` (`supervisor.py:193-197`) + 并发上限 `asyncio.Semaphore` (`supervisor.py:54-60`, 默认 4) + `RESTRICTED_TOOLS_POLICY` 已 deny `delegate_task`/`task` (`defaults.py:35`, `runner.py:108` allow_delegate=False 时删除)。**剩余**: ① `delegate_task` 收集的背景摘要未经 `ContextEnvelopeBuilder.build()` 传子 Agent (`runner.py` 未调用, `task.objective` 直传, `context.summary` 丢弃); ② 子任务 `evidence_refs` 生成缺失 (`runner.py:93-99` 返回默认空列表)。补齐后升级 `[x]`。

---

### T 开箱可用轮 (2026-07-31 制定, **最高优先级, 先于 R**)

> **为什么新增这一组**: 2026-07-31 首次做**真机部署冒烟**(此前所有轮次的验收都只跑单测 + 读文档),结果推翻了 2026-07-29 "v0.9 MVP 已达成"的结论 —— **按 README 拷 `config.sample.jsonc` 启动后,发消息永远收不到回复,且日志里没有任何错误**。这类缺陷单测抓不到(单测里门控被显式配置或绕过),只有真机走一遍用户旅程才会暴露。
>
> **目标标准变更**: 从"模块完整度"(补内部接线)改为"**产品可用度**"—— 对标 AstrBot / MaiBot:**部署完就能运行**。功能广度(原 R1-R6)在主干可用之前没有意义:一个连私聊都不回的系统,补多模态毫无价值。

**2026-07-31 真机冒烟实证**(复现命令: 拷 `config.sample.jsonc` 到干净目录 `data/config.jsonc` → `python -m isac` → `POST /webchat/send` → `GET /webchat/poll`):

| # | 缺陷 | 证据 | 严重度 |
|---|------|------|--------|
| 1 | **开箱发消息永不回复** | 私聊"你好"→ `{"replies": []}`。日志: `门控评分 score=30.0 threshold=80` → `门控未触发 kind=wait`。根因 `gating/system.py:174` 强制触发条件写作 `has_at or (is_private and has_mention)` —— 私聊被额外要求"必须提及机器人名",而私聊本身就是对 Bot 说话;`reply_necessity` 只给 private 记 40 分 < 阈值 80 → 静默 WAIT | **P0 阻断** |
| 2 | **消息被吞且零反馈** | 用户端只得 `{"status":"ok"}` + 空 replies;服务端日志无 error/warning(连 LLM 都没调到)。用户无法判断是自己配错还是程序坏了 | **P0 阻断** |
| 3 | **WebUI 开箱不可用** | `config.sample.jsonc` 的 `control.enabled: false` → 无任何管理界面(AstrBot 的核心体验是开箱 WebUI + 首登向导) | P1 |
| 4 | **必须手写 JSONC 才能启动** | 无内置默认配置,必须拷 sample 并手改 `api_key: "sk-your-key"` 占位符;AstrBot 默认配置内置于 `core/config/default.py`,零文件即可跑 | P1 |

**对标基线**(AstrBot `/Users/chen/ai/AI Agent/AstrBot`、MaiBot `/Users/chen/ai/AI Agent/MaiBot` 代码取证):AstrBot **WebChat 适配器无条件实例化并启动**(`core/platform/manager.py:100-102`)、默认配置内置代码、首登强制设密码(`default.py:252-256` + `auth_service.py:115-125`)、无 key 照常启动且 WebUI 可用、插件市场一键装 + 热重载;MaiBot 有 `/health`(`webui/routes.py:128`)、401 映射中文提示、配置自动升级迁移。

**验收铁律(新增, 适用于 T 与其后所有节点)**：**任何节点声明完成,必须附真机部署证据**(命令 + 实际输出),不接受"单测通过"作为可用性证明。单测证明"函数逻辑对",真机才证明"用户能用"。参见 `MODULE_GUIDE.md` §二"第三道坎"。

- [x] **T1 开箱能对话**(P0 阻断)
  - **目标**：让"部署 → 发消息 → 收到回复"这条最短路径无条件走通。
  - **验收**：①`gating/system.py` 私聊无条件强制触发(`has_at or is_private`),不再额外要求 `has_mention`;群聊行为不变(仍需 @/提及/评分);②消息被门控 WAIT / 被 debounce 弃权 / 无可用 Provider 时**不得零反馈** —— 至少 WARNING 级日志说明原因,面向用户侧按人设给出可读提示或明确的"未回复原因"可查;③未配置有效 `api_key`(含 `sk-your-key` 占位符)时启动即 WARNING 提示"去哪配",调用失败映射为可操作提示而非静默;④**真机验收**:干净目录 + 默认配置启动 → 发"你好" → 收到回复。
  - **产出**：门控私聊修复、无回复原因可观测、Provider 缺失/占位 key 检测与提示、真机冒烟脚本(纳入 CI 或 `scripts/`)、回归测试(经真实 `manager.process_message` 驱动,不是直调 gating)。
  - **依赖**：无。
  - **当前**：**已完成 (2026-08-04)**。`gating/system.py:182` 强制触发改 `has_at or is_private`;`manager` drain_empty/gating_wait 两处静默 return 升级 info 带 reason 字段;`config_schema.is_placeholder_key()` 检测占位 key (sk-your/your-key/changeme/replace/example/placeholder/xxx/todo);占位/空 key → StubProvider + WARNING 引导,Stub 默认回复改引导文案;`scripts/smoke_webchat.py` 真机冒烟脚本落地 (干净目录启动 → 发"你好" → 收到回复)。

- [x] **T2 零配置启动**(对标 AstrBot 默认配置内置)
  - **目标**：不写任何配置文件也能启动并对话,`config.sample.jsonc` 降级为"可选覆盖参考"。
  - **验收**：默认配置内置代码(仿 AstrBot `core/config/default.py`,与 `config_schema.py` 共用一份 schema);首启自动创建 `data/` 及子目录;无 `data/config.jsonc` 时不再依赖 StubProvider 兜底的隐式行为,而是明确的"未配置模型 → 引导去配"路径;占位符 key 视为未配置。
  - **依赖**：T1。
  - **当前**：**已完成 (2026-08-04)**。`utils/config.py` `DEFAULT_CONFIG` 扩充为最小可启动形态 (webchat 默认开 loopback + llm 空 + control/memory 默认关, default-off 铁律);`load_config` 改 `deepcopy(DEFAULT_CONFIG)` (顺带修复浅拷贝污染全局默认值的既有 bug);`main._ensure_data_dirs()` 首启集中创建 data/ 及被引用子目录。真机零配置验证: 干净目录无 config.jsonc 启动 → webchat 默认开 → 发"你好"收到引导回复。**遗留决策项 (2026-08-15)**: 零配置模式 `memory.enabled` 默认 false → "越聊越熟"开箱不生效, 是否放开待 T3-backend 一并决策。

- [~] **T3 控制面开箱可用**(2026-08-15 按前后端分离重定义, 后端部分 = T3-backend / FE 节点; 后端段已完成, 前端段 F1/F2 待启动)
  - **目标**：装完打开浏览器就能管理,配置不用手写 JSONC。前后端分离后拆为两段: **后端**先交付控制面开箱与 setup/auth API (FE1 + T3-backend), **前端**向导与表单页面在独立项目实现 (F1/F2, 见 §四 FE)。
  - **验收 (后端)**：`control.enabled` 默认 true 且默认仅绑 `127.0.0.1`;首登强制设密码的后端支撑 (setup 状态机 + `password_change_required` 标志 + `/setup` API, 禁止硬编码默认密码, 对标 AstrBot `password_change_required` + `/setup`);CLI `isac password reset` 兜底;配置 Schema 暴露 (JSON Schema 端点) 使前端表单可驱动 Agent/Channel/Provider/路由等主要配置的创建与修改, 不需手工编辑文件;配置热更新生效。
  - **验收 (前端, F1/F2 节点)**：首登强制设密码向导页面;主要配置表单化 (schema 驱动)。
  - **依赖**：T1、G(控制面已实现)、J3(WebUI v2 已实现)、FE1。
  - **当前**：**T3-backend 后端段已完成 (2026-08-16)**, 前端段 F1/F2 (独立项目, 技术栈开工前决策) 待启动。①`control.enabled` 默认改 True + 仅绑 127.0.0.1 (DEFAULT_CONFIG + ControlConfig + enforce_safe_host; setup_enabled 默认 True 配套)。②**首登强制设密码状态机** `SetupManager` (`isac/control/setup.py`, PBKDF2-HMAC-SHA256 20 万次哈希, 禁止明文/硬编码默认密码, 状态文件 `data/control/setup_state.json` 原子写): 首登态 (无 api_token/tokens 且 setup_state 无密码) admin 端点 428 SETUP_REQUIRED, 仅 /setup /health 可用; `POST /api/v1/setup {password}` 设密码后作 Bearer 生效。③`auth.make_auth_dependency/make_token_only_dependency` 加 setup_manager 参数 (setup_manager=None 时行为不变向后兼容)。④**CLI `isac password reset`** 兜底 (`__main__.py` argparse 子命令, 删 setup_state 回首登态)。⑤**`GET /api/v1/config/schema`** JSON Schema 端点 (ISACConfig.model_json_schema, 前端表单驱动前提)。⑥`/health` 加 setup_required 标志。⑦**真机验收** `scripts/smoke_control_setup.py` (零配置启动 → /health setup_required=true → /api/v1/audit 428 → POST /setup 设密码 → Bearer 生效 200, exit=0)。`tests/unit/test_t3_backend.py` (8 例)。T4 日志台后端 (LogBuffer + `/logs/tail` SSE) 已先行完成, 页面消费等前端轨道 F3。

- [x] **T4 错误可诊断**
  - **目标**：出问题时用户知道"哪儿错了、去哪修",而不是看栈或看不到任何东西。
  - **验收**：LLM 401/402/429/连接失败映射为可操作中文提示,**且提示里引用的配置路径必须是当前真实路径**(MaiBot 的反面教材:提示指向已过时的 `/config/model_list.toml`);新增 `/health` 端点(对标 MaiBot `webui/routes.py:128`)返回各子系统状态;WebUI 实时日志台;消息在链路各环节被丢弃/延迟/等待均可观测。
  - **依赖**：T3(日志台挂 WebUI)。
  - **当前**：**已完成 (2026-08-04)**。T4-1 LLM 错误中文可操作提示 (`openai_compat._map_http_error` 区分 401/402·403/429/5xx/其他 4xx, 全部引用 `data/config.jsonc` 真实配置路径;`manager._degraded_reply_from_error` 按错误类型映射可操作降级文案);T4-2 `/health` 聚合 (`_aggregate_health`: agents running/total + llm stub/configured + channels 平台列表 + control, 关键子系统缺失 → status=degraded);T4-3 LogBuffer 单例 + `/api/v1/logs/tail` SSE 实时日志台。**备注**: 日志台的**页面消费**属前端轨道 (F3), 后端 SSE 契约已就位;T4 先行于 T3 完成, 依赖倒挂在 FE1 解决 (control 默认开后日志台即可用)。

- [ ] **T5 真实 IM 接入验收**(需用户提供凭据/环境)
  - **目标**：把"适配器有单测"升级为"真机能收发"。
  - **验收**：OneBot/NapCat 真实账号跑通(私聊回复 + 群聊 @ 触发 + 富媒体降级);WebUI 显示各平台连接状态实时回显;飞书 / QQ 官方 / 企业微信按用户提供的凭据逐个真机联调(此前只有字节序核对与单测,**从未真机验证**);真人连续对话 N 轮无异常栈、无消息丢失。
  - **依赖**：T1-T4、O4(适配器已实现)。
  - **当前**：未开始。
  - **备注**：需要外部账号与回调公网地址,**开工前需与用户确认可用凭据与联调窗口**。

- [x] **T6 插件市场与热重载**(生态可用性, 对标 AstrBot)
  - **目标**：插件"能装、能用、免重启",而不是"放进目录但不触发"。
  - **验收**：插件市场列表 + 一键安装(市场 / Git / URL / 上传)+ 热重载免重启 + 失败插件单独列出可重试(对标 AstrBot `api/plugins.py:578-593,502,534,565,820,1064`)。
  - **依赖**：**R3(插件桥接激活)必须先完成** —— 否则装了也不触发,是假功能。
  - **当前**：**已完成 (2026-08-16)**。新建 `PluginInstaller` (`isac/plugin/runtime/installer.py`, 对标 AstrBot `PluginUpdator`) 支持 market/git/url/upload 四源安装 (SSRF `is_safe_url` + zip slip `safe_extractall` + 失败回滚), 市场清单本地 `data/plugin_marketplace.jsonc` + 可配远程 `marketplace_url` (httpx 拉取, 失败降级仅本地); `PluginManager` 加 `install/reload/uninstall/list_failures/retry`; `ToolRegistry` 加 `deregister`/`deregister_by_source`/`deregister_plugin_sourced` + 来源追踪 (`_source`/`set_current_source`); 新建 `activation` 模块 (`activate_plugin` + `sync_plugin_tools_to_agents`) 遍历运行中 Agent deregister 旧工具 + register 新工具, 运行中会话立即生效 (对标 AstrBot reload 全局重建, 适配 ISAC per-Agent registry); 控制面新增 `GET /plugins/marketplace` + `POST /plugins/install` + `POST /plugins/{name}/reload` + `DELETE /plugins/{name}` + `GET /plugins/failed` + `POST /plugins/{name}/retry` (写操作 `plugin:write` scope + 审计, `allow_install=false` 不注册写端点); CLI `isac plugin list/marketplace/install/reload/uninstall/failed/retry` 经 HTTP; upload 用 base64 body 不引 multipart 依赖。injectors/commands 热重载为加法语义 (仅 tools 精确 deregister, 已知限制)。新增 60 单测 (safe_install/tool_registry/activation/installer/manager_t6/routes_t6), ruff/mypy 全绿; 真机冒烟 `scripts/smoke_plugin_marketplace.py` (干净目录启动 → 列市场清单 → 上传安装 echo 插件 → reload → 卸载, exit=0)。

- [~] **T7 分发、运维与长跑验证**
  - **目标**：让别人能照文档在自己机器上跑起来并长期运行。
  - **验收**：`docker compose up` 一键(单服务 + 仅暴露 WebUI 端口 + 一个 `data` 卷,对标 AstrBot `compose.yml`);`pip`/`uv` 单包安装 3 步命令可用;配置版本自动升级迁移(对标 MaiBot `config_upgrade_hooks.py`);备份/导出;**24h soak test** 验证无内存/连接/任务泄漏;`docs/` 快速开始 5 分钟跑通(由未接触过项目的人按文档复现)。
  - **依赖**：T1-T4。
  - **当前**：**代码可做部分已完成 (2026-08-16),环境验证待环境**。①`docker compose up` 一键 —— `Dockerfile` (多阶段 builder+runtime, uv --frozen, HEALTHCHECK curl /health) + `docker-compose.yml` (单服务 + 127.0.0.1:8765 端口 + isac_data 卷 + 环境变量映射) 早已存在 (I2 节点)。②`pip`/`uv` 单包安装 —— `uv sync --all-extras --dev` 3 步 (README 快速开始 + docs/QUICKSTART.md)。③配置版本自动升级迁移 —— `ConfigMigrator` (config.py:127, MIGRATIONS 链式 while 升级 + 0.0.0→1.0.0) 早已存在, **本轮补链式迁移测试 2 例** (test_chain_migration_across_multiple_versions 验证 while 链式跨版本 + test_broken_path_warns_and_stops_at_dead_end 验证死端 warning 不抛)。④备份/导出 —— `scripts/export.py` + `scripts/export_openapi.py` 早已存在。⑤docs 快速开始 5 分钟 —— **新建 `docs/QUICKSTART.md`** (路径 A Docker 一键 / B 源码 / C 接入真实 LLM + IM 接入 + 验证清单 + 常见问题)。**待环境项**: 24h soak (需长时运行环境 + 真实 LLM key, 验证无内存/连接/任务泄漏)、"由未接触项目的人按文档复现"真人验证 (需人工)。

---

### R 功能广度轮 (2026-07-29 制定, **2026-07-31 降级到 T 之后**)

**目标**：补齐 `REQUIREMENTS.md` 十二条里仍缺的实现 + 把 Q3-Q6 / P3-P5 的剩余接线做完。

> **优先级说明 (2026-07-31)**: R 节点组原本被排在最前,但真机冒烟证明主干尚不可用 —— 已整组降级到 **T 之后**。其中 **R3(插件与 MCP 桥接)是 T6 插件市场的前置**,建议紧随 T 之后先做。

**发布门重定义**(2026-07-31 修订, 准入清单见 [ROADMAP.md](./ROADMAP.md) 四、里程碑):

| 版本 | 准入 | 状态 |
|------|------|------|
| ~~v0.9 MVP (P0-P2+Q0-Q1+Q2)~~ | ~~已达成~~ | ❌ **2026-07-31 推翻** —— 内部能力确实已接线,但真机部署后**无法对话**,不构成"最小可用产品" |
| **v1.0 可对话** | T1 + T2 | 🔜 装上就能聊(真 MVP) |
| **v1.0 可管理** | + T3 + T4 | 🔜 WebUI 开箱 + 可诊断 |
| **v1.0 可接入** | + T5 | 🔜 真实 IM 跑通 |
| **v1.0 可扩展** | + R3 + T6 | 🔜 插件生态真实可用 |
| **v1.0 GA 正式版** | + T7 + R1/R2/R4/R5/R6 + R7 | 🔜 需求全覆盖 + 分发运维 + 发布准入 |

**节奏假设**:1 个"开发轮" ≈ 3-7 个子项 + 单测 + **真机验证** + 文档同步 ≈ 1 个工作日。**"装上能聊"约 1-2 轮;"可部署可管理"约 4-5 轮;GA 约 13-16 轮**(不含 T5 真实凭据联调与 T7 24h soak 的等待时间)。

依赖顺序：T1 → T2 → T3 → T4 → T5;R3 → T6;T7 依赖 T1-T4;R1/R2/R4/R5/R6 相互独立可并行插入;R7 必须最后。

- [x] **R1 多模态出入站闭环**(收敛 Q4;用户可见价值最高)
  - **目标**：让"生成的图/语音真的发得出去、用户发来的媒体真的用得上、多模态用量真的查得到"。
  - **验收**：`_send_reply` 扫描回复中 `artifact_id` 经 `MediaResolver.resolve_for_channel` 转 Channel segment 发送;入站媒体下载落盘 `data/uploads/` + `MediaNormalizer` 白名单扩展 + 生成合法 `media_uri`;`_MediaToolBase`/`EmbeddingManager`/`Reranker` 接入 `UsageRecorder` 6 个多模态 `record_*`;`data/pricing.jsonc` 价目表加载 + `ModelUsageEvent.provider` 与价目表 key 对齐;`AgentConfig` 增 `model_capabilities_allow` 字段并映射工具可见性。
  - **依赖**：J1/J2(已实现)、Q4 现状(6 工具已注册)。
  - **当前**：**已完成 (2026-08-16)**。①`_send_reply` (`main.py`) 扫回复文本 `artifact:<64位hex>` 经新增 `ArtifactStore.get_ref` (`store.py`, 查表构造 ArtifactRef 含 kind/mime/uri) + `MediaResolver.resolve_for_channel` 转 segment append `reply.segments`; `_format_artifact_refs` (`media.py`) 去掉 `[:12]` 截断输出完整 64 位 id; `_resolve_artifact_store` 从 agent_manager 取目标 Agent 的 artifact_store (容错 mock)。②新建 `isac/gateway/incoming_media.py` `download_inbound_media` 扫 `message.segments` 中 image/voice/audio/video/file 取 `data["url"]`, HTTP 下载 (httpx + SSRF `is_safe_url` 校验) → `uploads_store.put` (ArtifactStore root_dir=data/uploads) → 回填 `data["media_uri"]`; `process_message` 路由后调用; `_build_media_normalizer` 白名单含 data/uploads。③`_MediaToolBase.execute` (`media.py`) 调 provider 后经 `_record_media_usage` helper 计 record_image_gen/stt/tts/video (传 descriptor.provider_id/model_id); `EmbeddingManager`/`Reranker` 加 `usage_recorder` 参数 + `record_embed`/`record_rerank`; `_build_memory_stack` 透传 usage_recorder。④新建 `data/pricing.jsonc` (示例价目表, text/image/audio/video/embedding/rerank 条目) + `PricingCatalog.load` 类方法 (jsonc→PriceSnapshot, 文件不存在/解析失败返空 catalog); `main._build_usage_stack` 改 `PricingCatalog.load`; record_* 传 provider/model → 与价目表 key 对齐闭环。⑤`AgentConfig` 加 `model_capabilities_allow: list[str]` (默认 ["*"] 向后兼容); `_register_media_tools` (`assembly.py`) 按字段条件注册 6 工具; `ModelCapabilitiesInjector._CAPABILITY_HINTS` 补 `understand_image`。新增 13 单测 (test_r1: caps/pricing/get_ref/完整id/入站下载/SSRF/record_*); ruff/mypy 全绿 (266 文件); 全量 1693 passed; smoke exit=0。

- [x] **R2 控制面与 SubAgent 收尾**(收敛 Q5 + Q6)
  - **目标**：消除 WebUI/控制面剩余占位与 SubAgent 数据失真。
  - **验收**：新增 `GET /agents/{id}/config` 返回全量配置 + 真实 `revision`,WebUI `loadConfigForEdit` 改用它(乐观锁真实生效);SubAgent 任务表传真实 `agent_id`(修 `app.js` 硬编码 `_`);补 `routes_webhooks` + `main` 构造 `WebhookManager` 订阅 `EventBus`;`isac/control/mcp_server.py` 补生产启动点 + 补齐声明未实现的工具;`delegate_task` 背景摘要经 `ContextEnvelopeBuilder` 真传子 Agent;子任务 `evidence_refs` 真实生成。
  - **依赖**：J3/J4/G2/G3(均已实现)。
  - **当前**：**已完成 (2026-08-16)**。①`GET /agents/{id}/config` (`routes_agents.py` `_get_agent_config` 抽 helper 降复杂度) 返回 `asdict(instance.config)` 含真实 `revision`, WebUI `app.js:loadConfigForEdit` 改用它替代硬编码 `revision:1` (乐观锁 `?if_match=` 真实生效)。②SubAgent list-all: `GET /subagent-runs` (无 parent_agent_id 过滤) 替代 app.js `GET /agents/_/subagent-runs` 硬编码 `_`。③新建 `routes_webhooks.py` (CRUD + `/automation/trigger`, 复用 WebhookManager + SSRF), `main._setup_webhooks` 构造 WebhookManager + EventBus `on_async(POST_MESSAGE/POST_SEND)` 订阅 + AlertManager 注入 `webhook_manager` 激活告警推送, `server.py` `_mount_webhook_router` 挂载。④`mcp_server._call_tool` 补 5 工具 (channel_bind/unbind 操作 RoutingRules.bindings, agent_update_config 复用 `_do_patch_agent`, plugin_set_enabled 调整 plugins_allow/deny + 持久化, message_send 构造 ISACMessage+Session 调 handle_message_serialized) 抽 `_call_r2_tools` helper; `main._register_mcp_server` 生产启动点 (`control.mcp_server.enabled`, 默认关闭零行为变化, spawn stdio task)。⑤`runner.py` 调 `ContextEnvelopeBuilder().build(task)` 把 `task.context["summary"]` 拼进 LLM user message (此前 build() 零调用, summary 被忽略)。⑥`runner._collect_evidence_refs` 从结果 content 扫 `artifact:<id>` 引用填入 `SubAgentResult.evidence_refs` (此前恒空)。新增 11 单测 (test_r2 9 + test_mcp_server 2); ruff/mypy 全绿 (263 文件); 全量 1669 passed; smoke_webchat/smoke_main_resident exit=0。

- [x] **R3 插件与 MCP 生态激活**(收敛 Q3;工作量最大)
  - **目标**：让插件与 MCP 注册的工具/命令/注入器真正进入 Agent 运行时并被 LLM 调用。
  - **验收**：`main` 构造 per-Agent `PluginContext` 时传入真实共享注册表(替换 `main.py:1362` 的 `_tools=None/_commands=None`);`loader.py` 加载 AstrBot/MaiBot 插件后调 `FunctionToolAdapter`/`MaiBotPluginAdapter.adapt` 完成桥接,`@filter.llm_tool`/`@register_action` handler 真实触发;`assembly` 按 `AgentConfig.mcp_servers` 构造 `MCPClient` + `connect` + `list_tools` 注册进 `ToolRegistry`,停止/销毁时 `disconnect`;`tools.workspace_root`/`bash_allowlist` 接入 `build_services`,`bash`/`read_file`/`write_file` 不再恒被拒。
  - **依赖**：F1-F4/E4/H2(均已实现)。
  - **当前**：**已完成 (2026-08-16)**。复用 `plugin_agent_hooks` 三阶段共享模式扩展到 tools/commands/injectors: `_fire_plugin_on_load` 建立进程级共享 `ToolRegistry`/`CommandRegistry`/`SystemPromptBuilder` (`services["plugin_tools"]` 等) 注入 `make_plugin_context` (替换原 None), native 插件 `on_load` 的 `register_tool`/`register_command`/`register_injector` 真实写入; 新增 `_adapt_compat_plugins` 遍历已加载 AstrBot/MaiBot 插件调 `AstrBotStarAdapter.adapt` (新建 `isac/plugin/compatibility/astrbot/adapter.py`, 仿 `MaiBotPluginAdapter`) / `MaiBotPluginAdapter.adapt` 把 `@filter.llm_tool`/`@register_action` 标记桥接进共享表; `assemble_agent` 经 `_merge_shared_plugin_tools`/`_merge_shared_plugin_commands` 合并共享表进 per-Agent registry (同 hooks 合并模式)。MCPClient 接线: `build_services` 注入 `services["mcp_servers"]` (config.jsonc 顶层 `mcp.servers` 节, DEFAULT_CONFIG 加默认空节), `assemble_agent` 经 `_wire_mcp_clients` 按 `AgentConfig.mcp_servers` 查全局定义构造 `MCPClient` + `connect` + `list_tools` 注册 `MCPToolBridge` 进 per-Agent tools, client 存 `agent_services["mcp_clients"]` 供 `AgentManager.stop`/`destroy` 与 `_shutdown_message_pipeline` 调 `disconnect`。CLI 工具 services 注入此前已完成 (`main.py:755-797`)。默认无插件无 mcp_servers 零行为变化。新增 `test_astrbot_compat.py::TestAstrBotStarAdapter` (3 例) + `test_runtime_assembly.py` 共享合并/MCPClient 接线/零行为/disconnect (4 例); ruff/mypy 全绿; 真机冒烟: `scripts/dev_mcp_echo_server.py` (最小 stdio MCP server) 配 `mcp.servers.echo` + Agent `mcp_servers=["echo"]`, isac 启动日志 `MCP server 已接入 server=echo tools=1` (list_tools 桥接真实生效)。**第 5 项"兼容层插件迁进程隔离"未做**: `manager._load_isolated` 依赖 manifest.jsonc, AstrBot/MaiBot 兼容层无 manifest, Fix-31 已做安全兜底 (显式失败而非静默退回宿主进程); 真正支持需独立的兼容层 manifest 机制, 超出"激活"范围, 留架构债 (§架构债表)。

- [x] **R4 记忆完整性补齐**(收敛 P3 剩余 + 2026-07-29 新发现的需求缺口)
  - **目标**：补上 `REQUIREMENTS.md` 4/5 明确要求、但读侧就绪写侧缺失的两项记忆能力,并完成 P3 剩余。
  - **验收**：**①行话学习**(R5 要求) —— `JargonInjector` 已注册读侧(`assembly.py:341`)但 `upsert_jargon` 全仓零生产调用、行话表恒空;补群聊高频词/上下文的行话抽取写入回路(归 `MemoryConsolidator` 后台低频,`HUMANLIKE_RUNTIME.md` 6.3)。**②中期记忆真实压缩**(R5 要求) —— `MidTermMemoryInjector` 现仅截断复述 `pending_messages` 末 5 条,与其自述"由 COMPRESS hook 触发 + CompressionPolicy + Summary + Recall Cue"不符;改为真实接 `COMPRESS` hook 做摘要压缩并落中期记忆。**③P3 通用实体关系图** —— 现只有 `mentioned_in` 提及边,补人物-人物/人物-话题语义关系抽取写边。
  - **依赖**：N1/N2、S2(MemoryConsolidator 已激活)、S3(图谱召回已激活)。
  - **当前**：**已完成 (2026-08-16)**。**①行话学习写入回路** —— `MemoryConsolidator.run_once` 新增第 4 步 `_extract_jargon_step`(LLM 守卫内,与画像归纳同级):按 `group_id` 聚合群聊 episode → `_top_candidate_words`(内置 CJK 2-gram bigram 分词 + 停用词/单字/既有 jargon 过滤,无 jieba 新依赖)统计高频词 → `_define_one_jargon` 经 `self._llm.chat` 释义(MEANING/CONTEXT 两行)→ `metadata.upsert_jargon(namespace, word, meaning, context)`;LLM 失败/无群聊/LLM=None 时跳过,异常隔离。**②中期记忆真实压缩(方案 A)** —— `assembly` 经 `_register_compress_listener` 把 COMPRESS hook 回调注册进 per-Agent 私有 hooks:回调仅 `consolidator.enqueue_compression(session_id, messages)` 入队(不调 LLM,守护 hook 禁直接调 LLM 规范);`run_once` 第 5 步 `_compress_step` 消费队列 → `_summarize_one_session` LLM 摘要 → `metadata.latest_episode_id_for_session` 定位 episode → `update_episode_summary` 落 `episodes.summary` 列(复用既存列 + episodes_fts_au 触发器自动同步 FTS);`MidTermMemoryInjector.build()` 改读本会话最近 episode 已落盘 summary 经 `RecallCue` 注入,不再截断复述 `pending_messages[-5:]`;新建 `CompressionPolicy`/`Summary`/`RecallCue` 三类承载逻辑。**③P3 通用实体关系图 —— 跳过留架构债**:写边层 `GraphStore.add_edge`(通用三元组, relation 任意字符串)已就绪,抽取层从零(需 LLM + NER + 关系抽取 prompt 工程 + 解析归一,~150+ 行),按"遇到阻塞先跳过"指示文档化留后续(见架构债表)。新增 `MetadataStore.update_episode_summary`/`get_episode_summary`/`latest_episode_id_for_session` 三方法;`ConsolidationResult` 加 `jargon_extracted`/`compressed_summaries` 计数。测试 `test_memory_consolidator_r4.py`(16 例)+ 更新 `test_memory_injectors.py` 旧 mid_term 测为新契约。默认零行为变化(LLM=None/无群聊/无 COMPRESS 触发时不变),ruff/mypy 全绿。

- [x] **R5 持久化与密钥安全收尾**(补 `REQUIREMENTS.md` 9/10 缺口)
  - **目标**：让"重启不丢会话"与"密钥不落明文"达到需求要求。
  - **验收**：**①Session 持久化**(R10 明确要求"Agent、Session、身份、路由、Link 和记忆可持久化恢复") —— `SessionManager` 现为纯内存(`session.py:30-35`),补 SQLite 写穿 + 重启恢复,与 Q1 的 `UserMapper` 持久化同构。**②密钥安全**(R9"密钥只可设置或替换,不可回显") —— `SecretStore`(AES-256-GCM)现零生产调用点(仅注释提及),`api_key` 明文存 `data/config.jsonc`;接入 SecretStore 或落地"配置 + env 覆盖"并确保控制面/WebUI 不回显、审计不记明文。
  - **依赖**：K4(持久化框架)、K7(SecretStore 已实现)。
  - **当前**：**已完成 (2026-08-16)**。①`SessionManager` (`isac/gateway/session.py`) 照 `UserMapper` 同构加 `db_path` 参数: `SCHEMA_SQL` 建 `sessions` 表 + `_ensure_schema` (惰性建表) + `_load_from_db` (缓存未命中先查库 hydrate 既有会话, 重启复用 session_id 不新建) + `_persist` (best-effort 写穿, 失败仅记日志不阻塞消息流) + `_delete_from_db` (close/gc 同步删) + `asyncio.Lock` 串行 check-then-create (防并发双创建); `main` 传 `db_path=data/gateway/sessions.db`, 不传则纯内存向后兼容。②`SecretStore` 接入: `resolve_secret_async` (`security.py`) 用 `secret:<key>` 前缀约定解密配置中 api_key; `resolve_secrets_in_config` 在 `build_services`/`register_llm_provider` 之前就地解析 `llm.api_key` + `llm.multimodal[*].api_key` 使同步注册函数拿明文; env `ISAC_SECRET_KEY` 未配置时不构造 store → `secret:` 前缀值原样回退 (warning) 走原明文路径向后兼容; env `ISAC_LLM_API_KEY` 仍最高优先级 (非 `secret:` 前缀原样返回); CLI `isac secret set/get/delete` 管理加密密钥 (getpass 不回显); 控制面无 GET config 明文回显端点 (routes_config 仅 validate/diff), 审计 `secret:` 前缀本身不含明文天然安全。默认无 db_path/无 env/无 `secret:` 前缀零行为变化。新增 8 单测 (SessionManager 持久化/重启恢复/并发/close + resolve_secret 各分支/resolve_secrets_in_config); ruff/mypy 全绿 (262 文件); 真机冒烟 `scripts/smoke_session_persistence.py` (建会话→SIGTERM 停→重启→同会话键发消息验证 session_id 不变, exit=0)。

- [x] **R6 企业化激活**(收敛 P5 剩余)
  - **目标**：完成 O1/O2/O3 的最后一段控制面与隔离接线。
  - **验收**：`routes_tenants` 控制面落地 + 按租户鉴权(O1 数据面 `tenancy.enabled` 已接);`loader.py` 支持可选子进程隔离模式(按 manifest `isolated` 标记路由到已实现的 `PluginIsolationHost`),崩溃可恢复;Workflow Agent 工具入口决策落地(新增 Tool + `assembly` 注册 + engine 注入,或明确记录"不做"及理由,消除 `actions.py:57` 的 `agent:` noop 悬空)。
  - **依赖**：O1/O2/O3、G(控制面)。
  - **当前**：**已完成 (2026-08-16)**。①`routes_tenants` (`isac/control/api/routes_tenants.py`) CRUD 租户 + 成员管理 (`GET/POST /tenants`, `GET/DELETE /tenants/{id}`, `POST/DELETE /tenants/{id}/members`), `tenant:read/write` scope + 审计; 新建 `TenantManager` (`isac/runtime/tenancy/manager.py`, SQLite 持久化照 UserMapper/SessionManager 同构, best-effort 写穿 + 重启恢复 + asyncio.Lock 串行), `tenancy.enabled` 时构造 (`main._build_tenant_manager`, `data/gateway/tenants.db`), `server._mount_tenant_router` 挂载 (无 manager 不挂载, 零行为变化); 数据面隔离已由 MetadataStore 层 `TenantIsolationGuard.enforce` 完成, AgentConfig/AgentManager 租户过滤界定为 O1 数据面纵深 (R6 范围外)。②`loader` 子进程隔离**已完全满足, 零工作** (三要素: `_should_isolate`/`_is_isolated_native` 读 manifest `isolated` 路由 manager.py:116-128 + `_load_isolated` 构造 `PluginIsolationHost` manager.py:130-176 + `_on_crash` 崩溃自动重启 max_restart_attempts host.py:270-314, 已接生产 load 路径 + 有测试)。③Workflow Agent 工具入口**决策落地选 B (明确记录不做)**: `actions.py:57` `agent:` stage→agent noop 补"经决策不实现"交叉引用 (消除悬空语义, 非遗漏), actions.py docstring + main.py:1476 正式化决策依据 (engine 有 `start` agent-facing 方法但 assembly 不接收 workflow_engine, 接入需跨 build_services/assemble_agent 两层 plumbing 与收益不匹配; `agent:` stage 路由属 workflow→agent 方向, 依赖 agent intent 调用协议超 R6 范围)。新增 10 单测 (test_r6_tenants: TenantManager 存储 CRUD/持久化/成员 + routes_tenants 端点 CRUD/成员/scope); ruff/mypy 全绿 (265 文件); 全量 1679 passed; smoke exit=0。

- [~] **R7 集成测试补齐与发布准入**(GA 最后一道门,必须最后做)
  - **目标**：补齐缺失的集成测试,复核 I 节点,过发布清单。
  - **验收**：新增 `tests/integration/test_p3_*`(向量+图谱+治理过滤召回)、`test_p4_*`(两平台同一自然人 bind → 记忆聚合)、`test_p5_*`(跨租户不可见 + 插件隔离 + workflow 执行) —— 三者现全缺;R1-R6 各自的端到端集成测试就位;**每个 hook/injector 至少一条经真实触发者驱动的测试**(见 `MODULE_GUIDE.md` §二"第三道坎");I 节点复核由 85% 升 100%(浏览器测试 CI 已随 K8 接入);`scripts/release_checklist.md` 七段清单全过;真实启动冒烟 + Docker 健康检查;`REQUIREMENTS.md` 十二条逐条取证复核(仿 2026-07-26 方法)。
  - **依赖**：R1-R6 全部完成。
  - **当前**：**代码可做部分已完成 (2026-08-16),环境准入项待环境**。新增三套集成测试 (19 例, 全绿): `tests/integration/test_p3_memory_retrieval.py` (8 例: 向量 KNN 召回 + 图谱 mentioned_in 邻居召回 + 治理 deleted 不被检索命中 + frozen 仍可检索 + embedder 降级 dense 短路 + graph 关闭不写边, 复用 `_KeywordEmbeddingProvider` 确定性 fake embedding)、`tests/integration/test_p4_identity_bind.py` (6 例: 两平台 qq+telegram bind 同一 person_id + 记忆按归一 master_id 聚合检索 + 归一身份隔离 + 低置信冲突写 identity_conflicts + resolve_conflict 标记解决 + 高置信不写冲突)、`tests/integration/test_p5_enterprise_isolation.py` (5 例: pipeline 层跨租户不可见 + PluginIsolationHost spawn→load→call→kill 真实插件 + _on_crash 崩溃重启达 max 放弃 + workflow 声明式 load_workflows_from_dir+persist + tool: action 经 build_default_action_handler 真实调 ToolRegistry.execute)。**待环境项 (按"遇到阻塞先跳过"留后)**: 真实启动冒烟 + Docker 健康检查 (需 docker daemon)、24h soak (需长时运行环境 + 真实 LLM key)、I 节点 browser CI 复核 100% (需浏览器环境, 本地无 browser 报 2 ERROR 为环境限制非代码缺陷)、`scripts/release_checklist.md` 七段全过 (需真实部署环境)、`REQUIREMENTS.md` 十二条逐条取证 (需人工逐条复核)。全量 1728 单测通过 (+19 例, 跳 browser 环境限制)、ruff/mypy 全绿 (266 文件)。

**GA 后可选项(不阻塞正式版发布,用户已明确暂缓或判为增强)**：S6 视频 Provider 真实端点(待端点选型二次确认)、微信 mp 公众号模式(wecom 已实现)、Slack 适配器、主链路启用流式回复(Provider 层 `chat_stream` 已闭环且有测试,`loop` 流式路径存在但 `run_stream` 无生产调用点 —— 属体验增强而非需求缺口)。

---

### FE 前后端分离 (2026-08-15 制定, 后端先行)

**背景与决策**: 现 WebUI 是控制面静态托管的 SPA (`control/webui/`, Vanilla JS)。随管理面增长, 前后端耦合的代价上升 (前端产物随后端发布、页面演进受后端发版节奏制约、无法独立选型与迭代)。**2026-08-15 决策**: 转入前后端分离 —— 后端提供纯 REST + SSE API, 前端独立成项目围绕冻结的 API 契约开发。决策记录见 `ARCHITECTURE.md` ADR-012。**先开发后端**; 前端轨道 (F 节点) 在 FE0/FE1 + T3-backend 完成后启动。

- [x] **FE0 API 契约冻结**
  - **目标**：把既有控制面 API 冻结为前后端双方的正式契约。
  - **验收**：`/openapi.json` 导出并归档为契约基线 (同步 `docs/api.md`); 全部既有端点通过契约自检 (命名/错误格式符合 `CONTROL_PLANE_SPEC.md` §3.6 统一错误格式); 版本策略确认 (`/api/v1` 前缀保持, 破坏性变更须升版本); 契约变更流程文档化 (改 API 先改 `CONTROL_PLANE_SPEC.md`)。
  - **依赖**：无。
  - **当前**：已完成 (2026-08-16)。`scripts/export_openapi.py` 用最小 mock 注入 `create_control_app` 挂载全部可选路由, 导出 `docs/api/openapi.json` 契约基线 (45 路径, version=1.0.0)。运行时 `/openapi.json` 仍按 R15 默认关闭 (`docs_enabled=false`), 契约以归档文件为准。统一错误格式对齐实际形态 `{"detail":{"code","message"}}` (CONTROL_PLANE_SPEC §3.6 订正; 原 `{"error":{...,"retriable","trace_id"}}` 形态中 retriable/trace_id 标为可选扩展留待 GA); 顺手修 `routes_identity` 两处纯字符串 detail (违反契约)。FastAPI app version 由硬编码 `0.1.0` 改读 `isac.__version__`。`docs/api.md` 加"API 契约基线"章节 (版本策略 + 变更流程: 改 API 先改规范再跑导出脚本刷新基线)。`tests/unit/test_api_contract.py` (4 例) 自检: 基线可加载 + version 一致 + 关键端点在 + 运行时 paths 与归档基线一致 (防漂移)。

- [x] **FE1 分离基建 (CORS / 跨源认证 / 静态托管降级)**
  - **目标**：让独立部署的前端能安全地消费 API。
  - **验收**：CORS 策略落地 (开发态 origin 白名单可配, 生产推荐同源反代, 默认不放开); 跨源认证落地 (Session Cookie + CSRF 在分离 origin 下的 SameSite/credentials 策略, 自动化场景保留 Bearer Token 双轨); `control/webui/` 静态托管标记 deprecated (迁移期保留可用, F2 完成后移除); SSE 契约维持 (`/events/stream`、`/logs/tail`)。
  - **依赖**：FE0。
  - **当前**：已完成 (2026-08-16)。`CorsConfig` (origins 默认空 + allow_credentials) 加入 `ControlConfig` (`config_schema.py`); `server._configure_cors` helper: origins 非空时加 `CORSMiddleware` (allow_credentials + 全方法/头), 默认空不加零行为变化; `routes_auth.build_router` 加 `samesite` 参数, 分离 origin (origins 非空) 降 `SameSite=Lax` 跨源可带, 同源保持 `Strict`; 写操作 Bearer Token 双轨保留 (CSRF middleware 只对会话 Cookie 写请求生效)。`control/webui/__init__.py` docstring 标 DEPRECATED (迁移期保留, F2 后移除, 新功能去独立前端)。SSE 契约 (`/api/v1/events/stream`、`/api/v1/logs/tail`) 未动维持。`config.sample.jsonc` 加 `control.cors` 示例 (注释生产推荐同源反代)。`tests/unit/test_fe1_cors.py` (5 例): 默认不放开 / 配置 origin 预检放行 / 未列 origin 拒绝 / samesite strict 默认 / samesite lax 跨源。

- [x] **T3-backend 控制面开箱后端支撑** (T3 后端段)
  - **验收**：`control.enabled` 默认 true 且仅绑 `127.0.0.1`; 首登强制设密码后端支撑 (setup 状态机 + `password_change_required` + `/setup` API, 禁止硬编码默认密码); CLI `isac password reset` 兜底; 配置 Schema 暴露 (JSON Schema 端点, 前端表单驱动前提); 真机验收 (干净目录启动 → 控制面可达 → setup 流程走通)。
  - **依赖**：FE1。
  - **当前**：**已完成 (2026-08-16, 1c0e639)** —— `DEFAULT_CONFIG` control 默认开 (仅 127.0.0.1); `SetupManager` (PBKDF2 + 428 SETUP_REQUIRED gate + `/setup` API); CLI `isac password reset`; `/api/v1/config/schema` JSON Schema 端点; `scripts/smoke_control_setup.py` 真机验收 exit=0。

- [ ] **F1 前端项目初始化 + 登录/setup 向导** (前端轨道)
  - **验收**：独立项目/目录 (技术栈开工前决策); 消费 `/api/v1` + SSE; 登录页 + 首登强制设密码向导页; 与后端 T3-backend 联调通过。
  - **依赖**：FE1 + T3-backend。

- [ ] **F2 十域页面迁移** (前端轨道)
  - **验收**：Dashboard/Agents/Channels/Providers/Usage/Extensions/Memory/Sessions/Logs/System 十域在前端项目重实现; 配置编辑事务接真实 API (Schema 校验 + Diff + 二次确认 + 乐观锁, 消费 R2 的 `GET /agents/{id}/config` 真实 revision); 同步修复 Q5 遗留 (SubAgent 表真实 agent_id 等假数据); 完成后移除后端 `control/webui/` 静态托管。
  - **依赖**：F1、R2。

- [ ] **F3 实时体验** (前端轨道)
  - **验收**：实时日志台 (`/logs/tail` SSE) + 事件流页面化 (`/events/stream`)。
  - **依赖**：F2。

- [ ] **F4 插件市场 UI** (前端轨道)
  - **验收**：插件市场列表 + 一键安装 + 热重载操作 + 失败插件可重试的前端界面。
  - **依赖**：T6 (后端能力先行)。

---

### U 架构演进轮 (2026-08-17 制定, v1.0 GA 前置, 发布路径与决策见 §三之五)

**目标**: 把 2026-08-17 深度 Review 认定的 8 项架构问题清偿到 A+ 水准 (稳定性/健壮性/可维护性/可扩展性/可升级空间/模块化)。现状证据与工作目录报告见 `.tmpfiles/agent-review-2026-08-17/` (主报告 `isac-deep.md`)。

**依赖顺序**: U0 最先 (安全, 阻塞一切发布相关工作) → U1 (地基, U3/U5 部分项依赖) → U4 → U5; U2/U3/U6/U7/U8 可穿插; U9 最后 (复评门禁)。

**推进方式**: 不估工时, 按各节点验收标准推进; 验收铁律 (真机证据) 与三态标记适用; 每项完成同步 PROGRESS.md。

- [x] **U0 安全清偿 (P0, 阻塞一切发布相关工作)**
  - **目标**: 清偿深度 Review 新发现的 4 项安全实洞 (Fix-85~88), 均在多租户与插件生态两个核心卖点面上。
  - **验收**:
    ①**Fix-85 治理面租户谓词**: `MemoryGovernor` 全部 SQL 补租户作用域, `routes_memory_admin` 校验 agent 归属租户; `tests/integration/test_p5_enterprise_isolation.py` 扩展到治理面 —— 租户 A 凭据对租户 B 记忆 freeze/correct/delete 一律拒绝。(发现: `governance.py` SQL 不经租户谓词, 控制面传裸 agent_id。)
    ②**Fix-86 解压体积上限接线**: `MAX_EXTRACTED_BYTES` 接入解压循环 (流式累计计数, 超限中止 + 清理); zip bomb 构造测试被拒且无残留文件。(发现: `installer.py` 该常量全仓零引用。)
    ③**Fix-87 MCP restricted 语义修正**: restricted 服务门补 `mcp:*` 映射, 或改默认 allow 并同步文档与 `base.py` 注释 (二选一, 消除语义矛盾); restricted 档下 LLM 直调 mcp: 工具被拒的用例。
    ④**Fix-88 兼容层工具命名空间**: mcp: 前缀防护推广到 compat/native 插件工具 (`<plugin>:tool` 前缀), 同名工具在机制上不可能覆盖内置工具 (现有 warning 升级为确定性隔离)。
    另顺带批清: delegate_task `_wait_timeout` clamp、gateway 诸库 (sessions/identity/tenants) WAL + busy_timeout、`pending_messages` 死字段删除、onebot 测试 extra 缺失时 importorskip。
  - **产出**: 对应修复 + 每项回归测试 (按 Fix-N 体系编号归档 CODE_REVIEW_REPORT.md)。
  - **依赖**: 无。
  - **当前**: **已完成 (2026-08-17)**。Fix-85 治理面全部 episodes SQL 补 organization_id/tenant_id 谓词 (guard.enabled 且非默认租户时, 与 metadata enforce 语义一致) + test_p5 新增跨租户治理拒绝/默认租户直通 2 例; Fix-86 safe_extractall 增 max_extracted_bytes 流式累计实际写盘字节 (元数据可伪造, 以实际为准) 超限中止+清半成品, installer 接入 MAX_EXTRACTED_BYTES, zip bomb 3 例; Fix-87 _required_service 补 mcp:*→mcp_clients 映射 (接线时 assembly 注入, 未接线拒绝; 4 例); Fix-88 ToolRegistry.register 对插件来源工具自动 <plugin>: 前缀包装 (_NamespacedTool), 已含 ':' 跳过, 启动期 compat 桥接补 set_current_source (防覆盖内置 6 例)。顺带批清: subagent _wait_timeout clamp 300 / gateway 四库 WAL+busy_timeout / pending_messages 死字段删除 (基类+SessionContext+loop 拷贝+4 测试传参) / onebot importorskip。全量单测 1740 通过+1 skip, integration 91 通过, ruff/mypy 全绿。

- [ ] **U1 事件溯源会话内核 (架构演进地基)**
  - **目标**: 会话存储从可变表升级为事件溯源: append-only 会话事件表 + 状态全部从事件派生 (消息历史=折叠、滑动窗口=窗口派生策略、压缩=带 `source_seqs` 溯源的 replace 事件); 入站消息即持久事件 ("Model-visible ⟺ Logged" 的 IM 化, 天然解决异步消息/重启续跑/审计合规); 未知事件类型默认拒绝重建 (ignorable 白名单); torn-tail 容忍 + repair (孤儿工具调用合成 OUTCOME_UNKNOWN, 不猜结果); 工具执行前/LLM 请求前强制 flush (副作用前落盘)。
  - **验收**: 强制断电 (kill -9) 后事件重放恢复无损; 上下文压缩可查溯源凭证, 摘要不小于原文时拒绝提交; **滑动窗口历史开箱可用** (最近 N 轮, budget 感知截断, 窗口大小可配; memory 关闭时仍维持窗口内连续性 —— 这是底线场景); 真机演示"隔天回到同一群聊仍保持上下文"并留档; episodes 写入改事件投影 (检索面不变, 写入侧不可变化); 既有全量测试绿 + 新增事件溯源专项套件 (重放/压缩溯源/torn-tail/未知事件拒绝)。
  - **产出**: `session events` SQLite 事件表 (WAL + write-behind 批处理)、派生器 (全量/窗口/压缩后三种派生策略)、旧 sessions 数据迁移脚本、repair 工具、配置项、MEMORY_DESIGN.md / ARCHITECTURE.md 同步。
  - **依赖**: U0。
  - **当前**: 未开始。

- [ ] **U2 装配层重构 (收敛架构债清单 Z1+Z2)**
  - **目标**: main.py (1832 行, 08-17 实测) 拆为 bootstrap/dispatch/wiring/cli 四模块 (各 ≤500 行, main.py 变薄入口); `build_services` 25 键 services 袋 ServiceContainer Protocol 化 (先核心 10 键, 再清其余), 下游 123 处防御式 `services.get(...)` 清零; 合入 lint 红线 (main.py 行数冻结, 只减不增)。
  - **验收**: mypy strict 通过装配层; 键错配在类型层不可能; 既有全量测试绿; 单向导入链 (main.py:3-6 声明) 保持。
  - **依赖**: U0。
  - **当前**: 未开始。

- [ ] **U3 门控策略化 (配置 + i18n + LLM judge)**
  - **目标**: constants.py 硬编码的三组中文关键词表与评分权重迁入 config `gating` 节 + locales 双语包 (zh_CN 现有词表迁入, en_US 新配); GatingStrategy 可插拔四档 (off / keywords / llm-judge / hybrid), TurnGate 单一调用点; llm-judge 档用小模型判群聊发言相关性 (频率上限 + 成本估算入文档; 已拍板: fallback 链最便宜档); 词汇表 drift test (config 与 locales 键一致性 CI 检查)。
  - **验收**: 英文群聊场景门控 e2e 通过; 调整任何门控参数不改代码; zh_CN 默认配置下既有门控行为回归一致。
  - **依赖**: U0。
  - **当前**: 未开始。

- [ ] **U4 租户机制强制 (半墙 → 整墙)**
  - **目标**: 隔离从"调用方自觉"升级为"机制强制": TenantBound 连接包装层自动注入租户谓词 (替换逐处子查询, 调用方无法绕过); person_profiles/jargon_entries/memory_revisions/memory_audit 补 tenant_id 列 + 迁移脚本; QueryMemoryTool 改 master_id 检索 (修私聊工具召回系统性漏); 租户前缀/自定义 namespace 下 consolidator-manager-injector 三处键统一。
  - **验收**: 两租户共库全场景零串档 (检索/治理/画像/行话/工具召回集成测试); 审计确认无裸 SQL 绕过点; `tenancy.enabled=false` 时零行为变化。
  - **依赖**: U0 (Fix-85 是其前哨)。
  - **当前**: 未开始。

- [ ] **U5 工具权限管线 + HITL 卡片审批**
  - **目标**: 工具权限从静态 scope 表升级为四段管线: pre-execute (allow/deny/ask waterfall) → 单调 guard (拒绝不可翻回) → 执行 → post 审计留痕 (决策 + 决策者 + 理由, 经 U1 事件表); ask 档落 IM 审批卡片 (人点同意/拒绝, 超时 fail-closed); 决策理由词汇表 (规范值 + drift test); mcp:/compat/native 统一走命名空间注册管线 (Fix-88 机制化)。
  - **验收**: 真机演示 ask 审批完整闭环 (卡片同意/拒绝/超时三条路); guard 拒绝不可翻案测试; 决策留痕可查询; 既有 restricted/EnableMatrix 语义回归一致。
  - **依赖**: U0 (Fix-87/88 前哨)、U1 (留痕载体)。
  - **当前**: 未开始。

- [ ] **U6 插件隔离默认化 (信任分级倒转)**
  - **目标**: 市场/git/url/upload 安装的插件**默认隔离 host 运行** (trust 分级: manifest 声明 `trust: sandboxed|hosted`, hosted 需运营方显式确认); rlimits/ipc_timeout 从部署配置接线; 运行中 Agent 的插件 hooks 卸载后同步清除 (不留至重启)。兼容层 (AstrBot/MaiBot) 隔离迁移 (原 Z3) 在本节点给出处置决策: 复活 manifest 机制接入隔离, 或文档化降级承诺 + ARCHITECTURE.md 修订, 二选一消除"隔离承诺与实现落差"。
  - **验收**: 市场插件默认在隔离 host 运行的集成测试; rlimits 生效验证; 卸载后 hooks 零残留测试; 兼容层处置决策落文档。
  - **依赖**: U0 (Fix-86 前哨)。
  - **当前**: 未开始。

- [ ] **U7 Agent 数据化 + 模型能力快照 + category 路由**
  - **目标**: ①prompt 文件化: 人格/规则写 agents/*.md (frontmatter 声明变体键), SystemPromptBuilder 从文件装配, 改人格=改文件; ②模型能力快照管线: models.dev → 生成 JSON → CI 定期刷新 + 新鲜度测试 (已拍板数据源), fallback 链按能力与可达性过滤; ③category 路由: 委派任务按类型 (问答/创作/工具密集/闲聊) 选模型链, 并入现有数据驱动路由表。
  - **验收**: 新增一个模型族=加一个文件, 零代码改动; 能力快照漂移 CI 报警; category 路由委派测试; 既有 persona 行为回归一致。
  - **依赖**: U0。
  - **当前**: 未开始。

- [ ] **U8 注入仲裁门 + 治理门禁**
  - **目标**: ①SessionWriteGate: 记忆注入/handoff/插件注入/强制话轮统一预约表 (先预约后写入、hold 窗口、超时作废 fail-closed), Fix-81/82 补丁逻辑收编进门内; AST 审计 (ruff 自定义规则或 import-linter) 禁止门之外的会话写入路径; ②治理门禁: 工具 catalog / 配置 catalog 生成脚本 + CI --check 漂移检测; mock IM 事件流快照回放 (无真实凭据跑整条 bot 链路); ③evidence 目录规范化 (日期-slug/, 真机证据必留档)。
  - **验收**: 审计测试能当场捕获故意绕过的写入; catalog drift CI 生效; 快照回放测试跑通; 强制话轮/打断既有集成测试回归绿。
  - **依赖**: U0。
  - **当前**: 未开始。

- [ ] **U9 A+ 架构复评与发布门禁 (最后执行)**
  - **目标**: 按 `isac-deep.md` 同款方法 (只读代码级审查 + 实测 pytest/ruff/mypy) 对 U1-U8 改造后的架构逐模块复评; 清零全部"定义了未接线" (lint 规则常驻); 红线指标 (main.py 行数 / services 键数 / 硬编码门控词条目数) 纳入 CI 常驻监控; Minor 批清收尾 (smoke_main_resident flake 根治、CHANGELOG 补齐 07-26 之后全部变更、版本号策略定稿)。
  - **验收 (GA 门槛组成部分)**: 复评报告无 C 项、B 项 ≤2、其余 A-/A+; "零引用安全常量" lint 规则全仓通过; 复评报告归档 docs/。
  - **依赖**: U0-U8 全部 `[x]`。
  - **当前**: 未开始。

---

### 架构债清单 (2026-08-15 整合自 2026-07-28/29 两轮评审, 各轮顺手清)

> 两轮评审 (Review/ 报告, 已整合删除) 遗留的架构级债务统一登记于此; 对应修复时机见"建议时机"列, 不单独立轮。
> 2026-07-28 复审的 5 项 Critical (C-N1 SSE 泄露/C-N2 飞书绕过/C-N3 QQ 签名 oracle/C-N4 标签转义/C-N5 存储锁竞态) 与全部 Required 项已由 Fix-22~Fix-36 修复, 不在此列。

| 债务 | 说明 | 建议时机 |
|------|------|---------|
| `services: dict[str, Any]` 弱类型 | 跨几十个文件传递, 改 key 名即全仓 AttributeError; 改 ServiceContainer Protocol/TypedDict | **升级至 U2** (2026-08-17, 见 §四 U) |
| 兼容层插件宿主进程执行 | AstrBot/MaiBot 插件 `exec_module` 在宿主进程, 绕过 `PluginIsolationHost` 隔离承诺 | **升级至 U6** (2026-08-17, 处置决策在 U6 落地) |
| `main.py` (1832 行, 08-17 实测) / `manager.py` (1258 行) | 逼近 C901 红线且 main.py 逆向增长中 (1519→1832); 拆分方案见 U2 | **升级至 U2** (2026-08-17) |
| 2026-08-17 深度 Review 四项安全实洞 (治理面绕过租户谓词 / MAX_EXTRACTED_BYTES 零引用 / MCP restricted 等效 allow / 兼容层工具无前缀) | 均在多租户与插件生态核心卖点面 | **U0 立即清偿** (Fix-85~88) |
| 同步 IO | `audit.py` 同步 `open("a")`、`bus._trigger_persist` 同步 fsync、`routes_routing` 同步写盘 | 任意空档顺手清 |
| Provider 测试端点假连接 | `POST /providers/{id}/test` 不发真实连接即返回 ok, 且访问私有属性 | R1 顺手做真实 ping |
| ~~检索结构化过滤~~ | ✅ 已清偿 (2026-08-16): `pipeline.search(filters=)` 透传到 `search_fts`+`get_episodes_by_ids`, `_build_filter_clause` 支持 topics (json_each 匹配) + since/until 时间范围, None 向后兼容不加过滤 | — |
| ~~媒体 magic-byte 校验~~ | ✅ 已清偿 (2026-08-16): `_check_magic_bytes` 读头部签名校验 png/jpeg/gif/mp3/wav/ogg/flac/mp4/webm, 扩展名伪造拒, 未登记 MIME 跳过向后兼容 | — |
| 通用实体关系图抽取层 | R4-③ 跳过: 写边层 `GraphStore.add_edge`(通用三元组 relation 任意字符串)已就绪, 但抽取层从零(需 LLM + NER + 人物-人物/人物-话题关系抽取 prompt 工程 + 解析归一, ~150+ 行); 现 `mentioned_in` 提及图已满足 S3 召回, 语义关系图留 Y1 长期记忆深化承接 | Y1 (GA 后) |
| ~~429 退避区分~~ | ✅ 已清偿 (2026-08-16): `_retry_backoff(attempt, *, rate_limited=True)` RateLimitError 退避基数翻倍 (2,4 vs 普通 1,2), 给服务端配额恢复更多时间 | — |
| `reload_config` 差量更新 | 现整实例重建, 应差量更新 gating/persona/权限 | 观察, 不紧急 |

---

### 可观测性增强(横切,已落地)

**目标**：无报错也能追踪每步操作,快速定位问题。**非节点,横切能力**,随各模块持续演进。

- [x] **trace 贯穿 + 分级日志**(2026-07-26 落地)
  - **验收**：trace_id/session_id/agent_id 经 `contextvars` 贯穿路由→门控→Loop→工具→记忆→回复,无需逐处手传;日志可按 level 与按模块前缀分级;默认 `INFO` 时 debug 零输出、零性能影响;全程脱敏 (不打密钥/完整参数/未清洗结果)。
  - **产出**：`utils/logging_context.py` (`bind_log_context`)、`utils/logger.py` (level + per_module 分级)、`manager.handle_message` trace 绑定、`agent/loop.py`/`gating/system.py` 等关键链路 debug 日志、`docs/LOGGING.md`、`data/config.sample.jsonc` logging 段、单测。
  - **当前**：已落地。用法与排查树见 [LOGGING.md](./LOGGING.md)。

---

### GA 后开发计划 (2026-08-16 预置, M-GA 验收通过后激活, 不影响当前 T/R/FE 推进)

**定位**: 本节是"当前计划全部开发完成 (v1.0 GA) 之后做什么"的预置蓝图, 依据三处既有记录推演: ①§四 R 末尾的 **GA 后可选项** (S6 视频端点 / 微信 mp / Slack / 主链路流式); ②§四**架构债清单**的持续清偿; ③`REQUIREMENTS.md` 第 12 条总体目标中尚未展开的"商业化基础"与"通用 Agent 框架"外延。**激活前提**: M-GA 达成 (R7 + T7 验收通过); 本节节点在激活前一律视为 `[ ]` 预置, 不排期不占资源。验收铁律 (真机部署证据) 继续适用。

#### V 功能广度兑现轮 (v1.1–v1.2): 把 GA 后可选项做成产品能力

- [ ] **V1 主链路流式回复**
  - **目标**: Provider 层 `chat_stream` 已闭环、`loop` 流式路径存在但 `run_stream` 无生产调用点 —— 启用流式, 回复边生成边送达。
  - **验收**: `AgentContext.streaming=True` 生产路径接线; Channel 侧分片送达/编辑追加按平台能力适配 (WebChat 原生流式帧, IM 平台分片或编辑消息降级); 流式失败回退非流式 (已有 CR3-H4); 前端流式渲染契约进 FE (独立前端项目消费)。
  - **依赖**: M-GA; 前端流式渲染属前端轨道。
- [ ] **V2 视频生成 Provider (原 S6)**
  - **目标**: `OpenAICompatVideoGenProvider.generate` 落地真实端点。
  - **验收**: **开工前用户二次确认端点** (Sora/Runway/Kling/即梦/自托管); 仿 image_gen: POST 生成 → 轮询/等待 → ArtifactStore → ArtifactRef; 计量埋点 (record_video 已就绪)。
  - **依赖**: M-GA; 端点选型为用户决策闸门。
- [ ] **V3 微信公众号 (mp) 适配器**
  - **目标**: wecom 企业微信已实现, 补齐 mp 公众号模式。
  - **验收**: 服务器配置校验 (signature) + 消息/事件接收 + 被动回复 + access_token 缓存; 富媒体按能力降级。
  - **依赖**: M-GA。
- [ ] **V4 更多平台 (Slack 优先, Line/WhatsApp 可选)**
  - **验收**: 复用 Channel 抽象 + enabled-gated 注册 + 真机收发验证。
  - **依赖**: M-GA。
- [ ] **V5 语音交互链路**
  - **目标**: 从"语音消息转写工具"升级为连续语音对话 (陪伴场景核心体验)。
  - **验收**: 流式 STT/TTS Provider 选型落地 (现 stt_tts 为 OpenAI 兼容基类); 语音消息入站转写 → 回复 TTS 出站全链; 与 V1 流式协同降低首音延迟。
  - **依赖**: V1; 端点选型为用户决策。
- [ ] **V6 前端体验扩展** (独立前端项目)
  - **验收**: 移动端适配 / 界面 i18n / Dashboard 可视化增强 (用量趋势图、记忆图谱视图); 以冻结的 API 契约为准, 不改后端。
  - **依赖**: F1-F4 完成。

#### X 生态与商业化轮 (v1.2–v2.0): 从"能用的框架"到"有人用的生态"

- [ ] **X1 分发与托管体系** — 官方镜像与版本化发布节奏; 一键部署模板生态 (1Panel/宝塔/NAS 等); 官方文档站独立部署; 升级迁移自动化在 T7 基础上产品化。
- [ ] **X2 插件生态运营** — T6 插件市场之上: 市场托管与审核签名机制、插件开发文档与模板库、版本兼容声明; 与 AstrBot/MaiBot 存量插件的迁移工具产品化 (scripts/migrate.py 升级)。
- [ ] **X3 多租户商业化** — R6 routes_tenants 之上: 组织/配额/计费模型、用量成本按租户结算 (usage 计量已就绪)、租户级 WebUI 视图。
- [ ] **X4 安全与合规** — 第三方安全审计; 数据合规能力 (记忆治理 freeze/delete 扩展为"被遗忘权"导出与清除流程); 审计日志归档策略。
- [ ] **X5 Agent 即服务商业化接口** — 把"API/MCP 自动化创建与配置 Agent"从内部能力升级为对外产品: G1 Admin API + G2 MCP Server + R6 多租户底座之上补开放 API 配额/限流/计费挂接 (与 X3 协同) + 外部开发者文档与 SLA; 这是项目负责人框架愿景中预留的商业化能力。

#### Y 智能演进轮 (v2.0): 深化"像人"的核心差异

- [ ] **Y1 长期记忆深化** — R4 实体关系图之上: 人物-人物/人物-话题语义网络持续抽取; 记忆反思 (定期自省生成自我叙事与关系总结, 经 MemoryConsolidator 通道); 记忆可解释性 (用户可查"为什么记得这个")。
- [ ] **Y2 多 Agent 社会** — Mesh 从少数 Agent 协作扩展为大规模拓扑: 群聊中多角色并存、Agent 社区模拟、跨 Agent 记忆共享的 ACL 精细化。
- [ ] **Y3 自主成长** — BehaviorLearner 的行为特征累积升级为长期行为画像演化闭环 (风格随关系深度与互动历史渐变, 有界不漂移)。
- [ ] **Y4 学习效果评估与回滚** — 拟人化/记忆/行为学习的效果评估闭环 (学习前后对比评估 + 效果恶化自动回滚); 18 个调研项目全员缺失此能力 (hermes-agent evals 回归台仅部分缓解), 可成为 ISAC 的差异化卖点。

#### Z 工程演进 (持续线, 不设节点门, 见缝插针)

> 承接 §四架构债清单, 在 V/X/Y 各轮开发中顺手清偿; 清偿一项从架构债清单移除一项。

- [ ] **Z1 ServiceContainer 强类型化** — `services: dict[str, Any]` → Protocol/TypedDict (越晚改越贵, 建议 V 轮启动时做)。
- [ ] **Z2 main.py 拆分** — `isac/bootstrap/{services,channels,control_plane,lifecycle,links}.py` (2026-07-28 复审给出的划分方案)。
- [ ] **Z3 兼容层插件子进程化** — AstrBot/MaiBot 插件全部迁 PluginIsolationHost (R3 留下的架构受限项, 需先解决"兼容层无 manifest"问题)。
- [ ] **Z4 上游兼容测试矩阵** — AstrBot/MaiBot 真实插件样本的 CI 兼容回归 (现兼容层测试用仿写样本)。
- [ ] **Z5 多进程部署预研** — "执行外移、状态内留" (参考 openclaw Cloud Workers 模式: 执行可下放独立进程/一次性云机, 会话状态/推理/凭据留在网关); 前置 U1 事件溯源内核 (状态可从事件重建是执行外移的前提)。

**GA 后里程碑**: M-v1.1 (V1-V4 流式+视频+微信 mp+Slack) → M-v1.2 (V5-V6 语音+前端扩展 + X1-X2 分发+插件生态) → **M-v2.0** (X3-X5 商业化+合规 + Y1-Y4 智能演进)。Z 线贯穿始终。依赖要点: V5 依赖 V1; V2/V5 含用户选型闸门; X3 依赖 R6; X5 依赖 G1/G2 + X3; Y1 依赖 R4; Z5 依赖 U1。

---

## 五、术语表

| 术语 | 解释 |
|------|------|
| **节点** | 本文档中的任务单元。大节点 A/B/C... 是里程碑；小节点 A1/A2... 是可独立完成并汇报的最小单元。 |
| **`[x]` / `[~]` / `[ ]`** | 三态进度标记(见 §二)：`[x]` 已交付(含主链路接线+集成验证);`[~]` 实现完成待接线(核心逻辑+单测完成,但未接入生产主链路,接线项归 §四 P 节点);`[ ]` 未开始。 |
| **主链路接线 / 激活** | 把已实现的能力接入生产消息处理链路(manager / loop / assembly / pipeline / gateway 等)使其真正生效,而非仅有独立实现与单测。散落的接线待办统一收敛在 §四 **P 节点**。 |
| **SOW** | Statement of Work，工作说明书。本文档既是指令集，也是 TODO 清单。 |
| **启用矩阵** | Agent 与 Channel 对插件/工具/命令/MCP 的启用/禁用矩阵。有效权限 = Agent 允许 ∩ Channel 允许 ∩ 全局策略。 |
| **AgentInstance** | 运行中的 Agent，含独立的门控/PromptBuilder/记忆/人格/工具。 |
| **MessageRouter** | 消息路由器，决定 IM 消息归属哪个 Agent。 |
| **InterAgentBus** | Agent 间通信总线，必须显式配置 Link (ACL) 才能通信。 |
| **控制面** | 独立于消息处理的管理接口：Admin API / MCP Server / Webhooks。 |
| **数据面** | 消息处理主链路：Channel → Gateway → Router → Agent → 回复。 |
| **契约冻结** | 接口签名、数据模型、配置规范、协议定义稳定，不再随意改动。 |
| **专项施工图** | 对复杂系统的细化设计文档，如拟人化运行时、记忆、插件兼容、控制面等。 |
| **ConversationRuntime** | 某个 Agent 在某个会话中的拟人化运行时，管理消息缓存、等待、主动任务、打断与上下文恢复。 |
| **ProgressEvent** | Agent 任务阶段的结构化事实事件，由 ProgressReporter 统一频控、脱敏、人格化渲染和发送。 |
| **ModelUsageEvent** | 单次物理模型请求的标准计量事件，记录 Provider、模型、Agent、模态、实际用量和价格快照。 |
| **ModelDescriptor** | 模型能力声明，描述输入/输出模态、operation、限制、成本/延迟层级和安全标签。 |
| **ArtifactRef** | 多模态生成制品的受控引用，不把二进制内容直接写入消息历史、日志或记忆。 |
| **SubAgent** | 父 Agent 下的临时隔离执行单元，使用独立上下文与收窄权限，结果和脱敏日志通过 task_id 关联。 |
| **SubAgentJournal** | 追加式持久化子任务事件日志，记录状态、工具、证据、错误和用量，不记录模型原始 reasoning。 |
| **稳定化节点** | K1-K8；修复常驻、真实 Provider、持久化、E2E、安全和发布门禁的最高优先级工作。 |
| **可用版本准入** | K1-K8 全部完成且真实运行验收通过后，项目才可从 Alpha 提升为可用版本。 |
| **Observer Agent** | 旁听 Agent，只接收消息用于记忆/学习/候选协作，默认不发送 IM 回复。 |
| **WaitState** | Agent 主动等待状态，记录 wait 工具调用、起始时间、请求秒数与原因，由消息/超时/主动任务结束。 |
| **ProactiveTask** | 结构化主动任务，必须带 source/intent/reason/priority，禁止无来源随机发言。 |
| **ForcedTurnState** | 一次绕过普通回复频率的强制发言，来源为 timeout / proactive / handoff。 |
| **MemoryItem** | (N1 规划) 统一记忆条目模型，用类型 + 载荷 + 元数据 + 命名空间承载 episodic/profile/jargon 等各类记忆。 |
| **IdentityResolver** | (N3 规划) 跨平台身份归一器，把不同 IM 的同一用户映射到统一 identity，供记忆聚合。 |
| **scaffolding (框架已搭建)** | 契约 + 类骨架 + 惰性默认关闭接线 + 骨架单测就位，主链路零行为变化;业务实现待后续节点。不计入强化完成定义,不标 `[x]`。 |
| **MeshRoutingDecision** | (M1) 在 RoutingDecision 之上补充 observer/candidate 角色的路由结果;新增 sibling 契约,不改既有 RoutingDecision。 |
| **MeshActionBroker** | (M2) Agent 间协作动作 (notify/handoff/memory_query/list) 的 deny-by-default 代理,委托 InterAgentBus。 |
| **TenantContext** | (O1) 一次请求/一个 Agent 所属的租户上下文 (organization_id/tenant_id/limits),默认单租户。 |
| **Workflow** | (O3) 声明式多步骤编排 (Stage + Transition),支持串/并/条件/重试,由 WorkflowEngine 执行。 |
| **MVP** | Minimum Viable Product,满足 [ROADMAP.md](./ROADMAP.md) M-MVP 里程碑定义(P0-P2 + Q0-Q1 完成)的最小可用产品,是当前项目下一个明确的发布目标。 |
| **Q 节点(MVP 收尾)** | 2026-07-26 对照 `REQUIREMENTS.md` 逐条代码取证后新增的节点组,收纳未被 P0-P5 覆盖、但 MVP 必需的缺口(定义见 §四 Q)。 |
| **MVP 差距复核** | 2026-07-26 对照 `REQUIREMENTS.md` 十二条需求做的一次性审计事件(10 域并行代码取证 + 真实启动实测);其结论落为各节点下的"MVP 缺口复核"批注与 §四 Q 节点组。 |
| **MVP 缺口复核** | 本文档中标注在已交付(`[x]`)节点下的补充说明(是上述"MVP 差距复核"审计的逐节点产物),记录与该节点"完成定义"矛盾的未接线子行为,不改动该节点其余已验证部分的状态,指向修复它的 Q/P 节点。 |
| **U 节点组 (架构演进轮)** | 2026-08-17 设立的 v1.0 GA 前置节点组: U0 安全清偿、U1-U8 八项架构升级、U9 A+ 复评门禁; 定义见 §四 U, 发布路径与已拍板决策见 §三之五。 |
| **事件溯源** | (U1) 会话存储范式: 一切操作记为只追加事件, 消息历史/压缩/滑动窗口全部从事件"派生", 存储本身不可涂改; 参考 deepseek-harness 会话内核与 pi 三存储规范。 |
| **SessionWriteGate** | (U8) 会话写入单一闸门: 记忆注入/handoff/插件注入/强制话轮先预约后写入, 超时作废, AST 审计禁止绕过; 参考 oh-my-openagent prompt-async-gate。 |
| **GatingStrategy** | (U3) 可插拔门控策略: off/keywords/llm-judge/hybrid 四档, 词表与权重配置化 + i18n, 取代硬编码中文关键词表。 |
| **能力快照** | (U7) 模型能力清单生成管线: models.dev → 生成 JSON → CI 定期刷新 + 新鲜度测试; 模型路由按能力与可达性过滤。 |
| **category 路由** | (U7) 委派任务按类型 (问答/创作/工具密集/闲聊) 选模型链, 取代"每个 Agent 钉一个模型"。 |
| **同构面核对清单** | §一.8 工程纪律: 每个安全修复交付前核对同类入口是否全覆盖同等防护; 反例见 §一 总则。 |
