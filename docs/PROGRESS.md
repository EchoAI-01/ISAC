# ISAC 进度总表

> 本文件是各节点进度的**唯一事实源**。`DEVELOPMENT_PLAN.md` 描述节点定义与验收,`AGENTS.md` 只做一句话概述并链接此处;二者不再各自维护进度表。
>
> ⚠️ **最近更新: 2026-08-16 —— 全量代码审查 Fix 轮 (Fix-37~Fix-48): 7 Critical + 批次 A 安全一致性修复**。5 路并行全量审查 (isac/ 全部 260+ 源文件) 发现 7 Critical + 44 Major + 68 Minor, 主审逐条读码复核 Critical 全部确认后修复"立即"层: **Fix-37** 企微 AES 明文布局与官方 WXBizMsgCrypt 协议颠倒 (`wechat/adapter.py` 取 `plain[20+msg_len:]` 当 XML, 实为 corpid 尾部; 单测同错互相印证故全绿但真实回调必失败) → 按官方布局 `msg=plain[20:20+msg_len]` + 新增 receiveid==corpid 校验 + 测试编码方向同步修正 (wecom 渠道此前对真实环境完全不可用); **Fix-38** image_gen 下载 provider 响应 URL 复用带 Bearer api_key 的 client → api_key 外泄任意第三方 CDN 主机 → 独立无 Authorization 下载 client; **Fix-39** 入站媒体/插件安装器只校验初始 URL 后 `follow_redirects=True` (302→内网/云元数据 SSRF 绕过) 且无体积上限 (OOM) → 新增 `safe_install.safe_download_bytes` (重定向逐跳复跑 is_safe_url + 流式 50MB/100MB 上限), incoming_media/installer 统一接入; **Fix-40** 已配 api_token 但 setup_state 缺失时未认证 POST /setup 可设密码接管控制面 → SetupManager 增 static_credentials_configured (setup 不再必需 + complete_setup 拒绝 + 路由 403 SETUP_NOT_ALLOWED); **Fix-42** main MCP 接线未传 parsed_tokens → tokens[] 部署下 tools/call 认证整段跳过 → 接线补传; **Fix-43** MCP 无任何凭证时 tools/call fail-closed 拒绝 (此前零认证); **Fix-44** MCP native stdio `sys.stdin.buffer.readline()` 阻塞主事件循环 (启用即冻结 Bot) → asyncio.to_thread; **批次 A**: **Fix-45** /events/stream scope 解析不认会话 Cookie → tokens[] 下 WebUI SSE 全拒 → _resolve_caller_scopes 走 _resolve_token (Header 优先 Cookie 回退); **Fix-46** /logs/tail 无 scope 门禁 (窄 scope token 读全量日志) → 接 scope_dependency("*"); **Fix-47** CSRF 中间件拦带旧 Cookie 的重新登录 (POST /auth/session) → 豁免; **Fix-48** PUT /agents/{id}/plugins 无配置锁 (与 PATCH 并发丢更新) + `list(str)` 逐字符拆分 → acquire_config_lock + _as_str_list。新增 15 例回归测试 (test_wechat_adapter receiveid 拒绝 / test_safe_install safe_download_bytes 5 例 / test_image_gen key 不泄露 / test_mcp_server fail-closed+scope 2 例 / test_t3_backend setup 静态凭证 2 例 / test_control_api_events Cookie scope / test_t4 logs scope / test_control_api_auth_session 重登录)。全量 **1752 测试通过** (smoke_main_resident 时序 flake 单跑通过, 非本轮引入)、ruff/mypy 全绿。**剩余未修 (本轮审查发现, 按批次排期)**: 批次 C 插件生态专项 (source 追踪/全量 deregister/隔离崩溃重载/installer name 校验与回滚)、批次 D MCP 生命周期 (reload 泄漏/stop-start 重连/initialize 握手)、批次 E 记忆口径 (person_profiles 键分裂/租户 SQL/BM25 同步)、批次 F 参数 clamp、批次 G 适配器 (飞书 p2p/Discord 自过滤/Registry 错误隔离) 及 Minor 批量。
>
> ⚠️ **最近更新: 2026-08-16 —— 三态标记收敛 + 下一步行动计划 (N1-N5) 制定**。文档漂移修复: T3-backend 升 `[x]`; **P3/P4/P5 与 Q4/Q5/Q6 均已被 R 节点收敛, 由 `[~]` 升 `[x]`** 并补"结论"行 (P3 剩余"通用实体关系图抽取层"按 R4 决策转 Y1)。新增 `DEVELOPMENT_PLAN.md` **§三之三 下一步行动计划**: N1 文档收敛 (进行中) → N2 环境准入项清偿 (Docker 冒烟/browser CI/release checklist/24h soak) → N3 T5 真实 IM 凭据联调 (外部阻塞) → N4 前端轨道启动 (API 基线已冻结, 技术栈决策先行) → N5 剩余架构债并行线。后端代码工作已基本收尾 (全量 1739 测试通过、ruff/mypy 全绿), 剩余项几乎全部为环境/凭据依赖与前端轨道, 详见 DEVELOPMENT_PLAN §三之三与 `RELEASE_AUDIT.md` 第三节。
>
> 上一轮 2026-08-16 —— R7 取证复核 + hook 补测 + T7 代码部分完成。全量 **1733 单测通过** (+COMPRESS listener e2e 3 例 + ConfigMigrator 链式 2 例, 跳 browser 环境限制 + artifact_store 并发 flaky 单跑通过)、ruff/mypy 全绿 (266 文件)。**R7-⑤ REQUIREMENTS 十二条取证复核** → 新建 `docs/RELEASE_AUDIT.md` (8✅+4⚠️: 缺口均属 GA 后 V2/V3/V4/X3/X4 或环境准入非代码缺陷; 含 hook/injector 覆盖审计表)。**R7-⑥ hook/injector 真实触发测试补齐** → 新建 `tests/unit/test_compress_listener_e2e.py` (3 例: 经 `hooks.fire(COMPRESS)` 真实触发 assembly 注册的 `_on_compress` listener → 入队 → run_once 摘要落盘; MODULE_GUIDE §二第三道坎, 此前 COMPRESS 仅纯单元直调 enqueue_compression)。**T7 代码部分** → 补 `ConfigMigrator` 链式迁移测试 2 例 (链式跨版本 + 死端 warning) + 新建 `docs/QUICKSTART.md` 5 分钟跑通 (路径 A Docker 一键 / B 源码 / C 真实 LLM + 验证清单); Dockerfile/compose/export 早已存在 (I2)。详见 DEVELOPMENT_PLAN §四 R7/T7。新增三套集成测试 (现全缺 → 补齐): `tests/integration/test_p3_memory_retrieval.py` (8 例: 向量 KNN 召回 + 图谱 mentioned_in 邻居召回 + 治理 deleted 不被检索命中 + frozen 仍可检索 + embedder 降级 dense 短路 + graph 关闭不写边; 复用 `_KeywordEmbeddingProvider` 确定性 fake embedding)、`tests/integration/test_p4_identity_bind.py` (6 例: 两平台 qq+telegram bind 同一 person_id + 记忆按归一 master_id 聚合检索 + 归一身份隔离 + 低置信冲突写 identity_conflicts + resolve_conflict 标记解决 + 高置信不写冲突)、`tests/integration/test_p5_enterprise_isolation.py` (5 例: pipeline 层跨租户不可见 + PluginIsolationHost spawn→load→call→kill 真实插件 + _on_crash 崩溃重启达 max 放弃 + workflow 声明式 load_workflows_from_dir+persist + tool: action 经 build_default_action_handler 真实调 ToolRegistry.execute)。**待环境项 (按"遇到阻塞先跳过"留后)**: 真实启动冒烟 + Docker 健康检查 (需 docker daemon)、24h soak (需长时运行环境 + 真实 LLM key)、I 节点 browser CI 复核 100% (需浏览器环境, 本地无 browser 报 2 ERROR 为环境限制非代码缺陷)、release_checklist 七段全过 (需真实部署环境)、REQUIREMENTS 十二条逐条取证 (需人工逐条复核)。详见 DEVELOPMENT_PLAN §四 R7。
>
> 上一轮 2026-08-16 —— R4 记忆完整性补齐完成。全量 **1709 单测通过** (新增 R4 16 例: `test_memory_consolidator_r4` ①`_top_candidate_words` 高频词过滤/释义解析/LLM 隔离/无群聊跳过/LLM=None 跳过 + ②COMPRESS 入队+摘要落盘+dedup+无 episode 降级+LLM=None 跳过 + mid_term 注入器读 summary/无 summary 降级/无 metadata, 更新 `test_memory_injectors` 旧 mid_term 测为新契约, 跳 browser 环境限制 + smoke flaky 单跑通过)、ruff/mypy 全绿、smoke exit=0。**①行话学习写入回路** —— `MemoryConsolidator.run_once` 新增第 4 步 `_extract_jargon_step` (LLM 守卫内, 与画像归纳同级): 按 `group_id` 聚合群聊 episode → `_top_candidate_words` (内置 CJK 2-gram bigram 分词 + 停用词/单字/既有 jargon 过滤, 无 jieba 新依赖) 统计高频词 → `_define_one_jargon` 经 `self._llm.chat` 释义 (MEANING/CONTEXT 两行) → `metadata.upsert_jargon`; LLM 失败/无群聊/LLM=None 跳过, 异常隔离。**②中期记忆真实压缩 (方案 A)** —— `assembly` 经 `_register_compress_listener` 把 COMPRESS hook 回调注册进 per-Agent 私有 hooks: 回调仅 `consolidator.enqueue_compression(session_id, messages)` 入队 (不调 LLM, 守护 hook 禁直接调 LLM 规范); `run_once` 第 5 步 `_compress_step` 消费队列 → `_summarize_one_session` LLM 摘要 → `metadata.latest_episode_id_for_session` 定位 episode → `update_episode_summary` 落 `episodes.summary` (复用既存列 + episodes_fts_au 触发器自动同步 FTS); `MidTermMemoryInjector.build()` 改读本会话最近 episode 已落盘 summary 经 `RecallCue` 注入, 不再截断复述 `pending_messages[-5:]`; 新建 `CompressionPolicy`/`Summary`/`RecallCue` 三类承载逻辑。**③P3 通用实体关系图 —— 跳过留架构债**: 写边层 `GraphStore.add_edge` (通用三元组) 已就绪, 抽取层从零 (需 LLM + NER + 关系抽取 prompt 工程, ~150+ 行) 按"遇到阻塞先跳过"留 Y1 承接。新增 `MetadataStore.update_episode_summary`/`get_episode_summary`/`latest_episode_id_for_session` 三方法; `ConsolidationResult` 加 `jargon_extracted`/`compressed_summaries` 计数。**附带修复 R1 遗留**: `main.py:193` `_resolve_artifact_store` 调用处补 `await` (此前传协程对象致 R1-① artifact 解析静默失效, RuntimeWarning `coroutine never awaited`)。默认零行为变化 (LLM=None/无群聊/无 COMPRESS 触发时不变)。详见 DEVELOPMENT_PLAN §四 R4。
>
> 上一轮 2026-08-16 —— R1 多模态出入站闭环完成。全量 **1693 单测通过** (新增 R1 13 例: test_r1 caps/pricing/get_ref/完整id/入站下载/SSRF/record_*, 跳 browser)、ruff/mypy 全绿 (266 文件)、smoke exit=0。①`_send_reply` 扫回复 `artifact:<64位hex>` 经新增 `ArtifactStore.get_ref` (查表构造 ArtifactRef) + `MediaResolver.resolve_for_channel` 转 segment; `_format_artifact_refs` 去截断输出完整 id; `_resolve_artifact_store` 容错取 store。②新建 `isac/gateway/incoming_media.py` `download_inbound_media` 扫 segments url HTTP 下载 (httpx+SSRF) → `uploads_store.put` (root_dir=data/uploads) → 回填 media_uri; `process_message` 路由后调用; `_build_media_normalizer` 白名单含 data/uploads。③`_MediaToolBase.execute` 调 `_record_media_usage` 计 record_image_gen/stt/tts/video (传 provider/model); `EmbeddingManager`/`Reranker` 加 usage_recorder + record_embed/rerank; `_build_memory_stack` 透传。④新建 `data/pricing.jsonc` + `PricingCatalog.load`; record_* 传 provider/model 与价目表 key 对齐。⑤`AgentConfig.model_capabilities_allow` 字段 + `_register_media_tools` 条件注册 + `understand_image` hint。详见 DEVELOPMENT_PLAN §四 R1。
>
> 上一轮 2026-08-16 —— R6 企业化激活完成。全量 **1679 单测通过** (新增 R6 10 例: test_r6_tenants TenantManager 存储 CRUD/持久化/成员 + routes_tenants 端点 CRUD/成员/scope, 跳 browser 环境限制)、ruff/mypy 全绿 (265 文件)、smoke exit=0。①`routes_tenants` (`isac/control/api/routes_tenants.py`) CRUD 租户+成员 (`GET/POST /tenants`, `GET/DELETE /tenants/{id}`, `POST/DELETE /tenants/{id}/members`), `tenant:read/write` scope + 审计; 新建 `TenantManager` (`isac/runtime/tenancy/manager.py`, SQLite 持久化照 UserMapper/SessionManager 同构, best-effort 写穿+重启恢复+asyncio.Lock 串行), `tenancy.enabled` 时构造 (`main._build_tenant_manager`, `data/gateway/tenants.db`), `server._mount_tenant_router` 挂载 (无 manager 不挂载零行为变化); 数据面隔离已由 MetadataStore 层 `TenantIsolationGuard.enforce` 完成, AgentConfig/AgentManager 租户过滤界定为 O1 数据面纵深。②`loader` 子进程隔离**已完全满足零工作** (`_should_isolate`/`_is_isolated_native` manager.py:116-128 + `_load_isolated` 130-176 + `_on_crash` 崩溃自动重启 host.py:270-314, 已接生产 load 路径+有测试)。③Workflow Agent 工具入口**决策落地选 B** (文档化不做): `actions.py:57` `agent:` noop 补"经决策不实现"交叉引用消除悬空语义, actions.py docstring+main.py:1476 正式化依据 (engine 有 start 方法但 assembly 不接 workflow_engine, plumbing 代价与收益不匹配)。详见 DEVELOPMENT_PLAN §四 R6。
>
> 上一轮 2026-08-16 —— R2 控制面与 SubAgent 收尾完成。全量 **1669 单测通过** (新增 R2 11 例: test_r2 config/list-all/webhooks/envelope/evidence_refs + test_mcp_server 5 工具, 跳 browser 环境限制)、ruff/mypy 全绿 (263 文件)、smoke_webchat/smoke_main_resident exit=0。①`GET /agents/{id}/config` (`routes_agents.py:_get_agent_config`) 返回 asdict(config) 含真实 revision, WebUI `loadConfigForEdit` 改用替代硬编码 revision:1 (乐观锁 if_match 真实生效)。②`GET /subagent-runs` list-all 替代 app.js 硬编码 `GET /agents/_/subagent-runs`。③新建 `routes_webhooks.py` (CRUD + /automation/trigger, 复用 WebhookManager+SSRF), `main._setup_webhooks` 构造 WebhookManager + EventBus on_async(POST_MESSAGE/POST_SEND) 订阅 + AlertManager 注入 webhook_manager 激活告警推送, server `_mount_webhook_router` 挂载。④`mcp_server._call_tool` 补 5 工具 (channel_bind/unbind/agent_update_config/plugin_set_enabled/message_send) 抽 `_call_r2_tools` helper; `main._register_mcp_server` 生产启动点 (control.mcp_server.enabled 默认关闭零行为变化, spawn stdio task)。⑤`runner.py` 调 ContextEnvelopeBuilder.build 把 task.context.summary 拼进 LLM user message (此前 build 零调用)。⑥`runner._collect_evidence_refs` 从结果 content 扫 artifact:<id> 填 SubAgentResult.evidence_refs (此前恒空)。详见 DEVELOPMENT_PLAN §四 R2。
>
> 上一轮 2026-08-16 —— R5 持久化与密钥安全收尾完成。全量 **1659 单测通过** (新增 R5 8 例: SessionManager 持久化/重启恢复/并发/close + resolve_secret 各分支/resolve_secrets_in_config, 跳 browser 环境限制)、ruff/mypy 全绿 (262 文件)、真机冒烟 `scripts/smoke_session_persistence.py` exit=0 (建会话→SIGTERM 停→重启→同会话键发消息验证 session_id 不变 `sess_fbaa64ee` 恢复成功, 行数不增)。①`SessionManager` (`isac/gateway/session.py`) 照 `UserMapper` 同构加 `db_path` 参数: `SCHEMA_SQL` 建 `sessions` 表 + `_ensure_schema` (惰性建表) + `_load_from_db` (缓存未命中先查库 hydrate 既有会话, 重启复用 session_id 不新建) + `_persist` (best-effort 写穿, 失败仅记日志不阻塞消息流) + `_delete_from_db` (close/gc 同步删) + `asyncio.Lock` 串行 check-then-create (防并发双创建); `main` 传 `db_path=data/gateway/sessions.db`, 不传则纯内存向后兼容 (现有 14 处 `SessionManager(config)` 调用零行为变化)。②`SecretStore` 接入: `resolve_secret_async` (`security.py`) 用 `secret:<key>` 前缀约定解密配置中 api_key; `resolve_secrets_in_config` 在 `build_services`/`register_llm_provider` 之前就地解析 `llm.api_key` + `llm.multimodal[*].api_key` 使同步注册函数拿明文; env `ISAC_SECRET_KEY` 未配置时不构造 store → `secret:` 前缀值原样回退 (warning) 走原明文路径向后兼容; env `ISAC_LLM_API_KEY` 仍最高优先级; CLI `isac secret set/get/delete` (getpass 不回显); 控制面无 GET config 明文回显端点 (routes_config 仅 validate/diff), 审计 `secret:` 前缀本身不含明文天然安全。默认无 db_path/无 env/无 `secret:` 前缀零行为变化。详见 DEVELOPMENT_PLAN §四 R5。
>
> 上一轮 2026-08-16 —— T6 插件市场与热重载完成。全量 **1651 单测通过** (新增 T6 60 例: safe_install/tool_registry/activation/installer/manager_t6/routes_t6, 跳 browser 环境限制)、ruff/mypy 全绿 (262 文件)、真机冒烟 `scripts/smoke_plugin_marketplace.py` exit=0 (干净目录启动 → 列市场清单含 echo_tool → 上传安装 echo 插件 → loaded 含 → reload → 卸载 → loaded 不含)。新建 `PluginInstaller` (`isac/plugin/runtime/installer.py`, 对标 AstrBot `PluginUpdator`) 支持 market/git/url/upload 四源安装 (SSRF `is_safe_url` + zip slip `safe_extractall` + 失败回滚), 市场清单本地 `data/plugin_marketplace.jsonc` + 可配远程 `control.plugins.marketplace_url` (httpx 拉取失败降级仅本地); `PluginManager` 加 `install/reload/uninstall/list_failures/retry` + `_failures` 追踪; `ToolRegistry` 加 `deregister`/`deregister_by_source`/`deregister_plugin_sourced` + 来源追踪 (`_source`/`set_current_source`, register 加 source 向后兼容); 新建 `activation` 模块 (`activate_plugin` + `sync_plugin_tools_to_agents`) 遍历运行中 Agent deregister 旧工具 + register 新工具, 热重载运行中会话立即生效 (对标 AstrBot reload 全局重建, 适配 ISAC per-Agent registry); 控制面新增 `GET /plugins/marketplace` + `POST /plugins/install` + `POST /plugins/{name}/reload` + `DELETE /plugins/{name}` + `GET /plugins/failed` + `POST /plugins/{name}/retry` (写操作 `plugin:write` scope + 审计, `allow_install=false` 不注册写端点); CLI `isac plugin list/marketplace/install/reload/uninstall/failed/retry` 经 HTTP; upload 用 base64 body 不引 multipart 依赖; `main` 无条件设 `_plugins_dir` 供 reload/install/retry 定位; `assembly._merge_shared_plugin_tools` 改带 source 透传。injectors/commands 热重载为加法语义 (仅 tools 精确 deregister, 已知限制)。默认无 marketplace_url 无 install 调用零行为变化。详见 DEVELOPMENT_PLAN §四 T6。
>
> 上一轮 2026-08-16 —— R3 插件与 MCP 生态激活 (收敛 Q3) 完成。全量 **1590 单测通过** (新增 R3 7 例)、ruff/mypy 全绿、两真机 smoke (smoke_webchat / smoke_control_setup) exit=0 + R3 MCP 真机冒烟 (`scripts/dev_mcp_echo_server.py` 最小 stdio MCP server 配 `mcp.servers.echo` + Agent `mcp_servers=["echo"]` → isac 日志 `MCP server 已接入 server=echo tools=1`, list_tools 桥接真实生效)。R3 复用 `plugin_agent_hooks` 三阶段共享模式扩展到 tools/commands/injectors: `_fire_plugin_on_load` 建立进程级共享 `ToolRegistry`/`CommandRegistry`/`SystemPromptBuilder` 注入 `make_plugin_context` (替换原 None) → native 插件 `on_load` `register_*` 真实写入 + 新建 `AstrBotStarAdapter` (`isac/plugin/compatibility/astrbot/adapter.py`, 仿 `MaiBotPluginAdapter`) 经 `_adapt_compat_plugins` 桥接 AstrBot `@filter.llm_tool` / MaiBot `@register_action` 装饰器进共享表 → `assemble_agent` 经 `_merge_shared_plugin_tools`/`_merge_shared_plugin_commands` 合并进 per-Agent registry。MCPClient 生产接线: `config.jsonc` 顶层 `mcp.servers` 节 (DEFAULT_CONFIG 加默认空节) + `build_services` 注入 `services["mcp_servers"]` + `assemble_agent` 经 `_wire_mcp_clients` 按 `AgentConfig.mcp_servers` 构造+connect+list_tools 注册 `MCPToolBridge` + `AgentManager.stop`/`destroy`/`_shutdown_message_pipeline` 调 `disconnect`。CLI 工具 services 注入此前已完成。默认无插件无 mcp_servers 零行为变化。**第 5 项"兼容层迁进程隔离"未做** (架构受限: 兼容层无 manifest, Fix-31 已安全兜底, 留架构债)。下一步 T6 插件市场 或 R1/R2/R4/R5/R6 并行。详见 DEVELOPMENT_PLAN §四 R3。
>
> 上一轮 2026-08-16 —— 阶段 0 工程纠偏 + FE0 API 契约冻结 + FE1 分离基建 + T3-backend 控制面开箱后端支撑 完成。全量 **1582 测试通过**、ruff/mypy 全绿、两真机 smoke (smoke_webchat / smoke_control_setup) exit=0。阶段0: CI 分支修正 (dev 触发) + venv 重建 (shebang) + aiosqlite 连接未关闭警告归零 (24h soak 前置) + 清理残留 worktree/构建产物。FE0: openapi.json 契约基线归档 + 错误格式统一 (detail{code,message}) + 变更流程文档化。FE1: CORS 白名单 + Session SameSite 参数化 + WebUI 标 deprecated。T3-backend: control 默认开 (仅 127.0.0.1) + SetupManager 首登强制设密码 (428 gate + /setup API + PBKDF2) + CLI `isac password reset` + /api/v1/config/schema JSON Schema 端点。详见 DEVELOPMENT_PLAN §三之二 与 §四 FE/T3。
>
> 上一轮 2026-08-15 —— 前后端分离决策 + 文档整合; T 开箱可用轮 T1/T2/T4 已完成 (2026-08-04)。全量 **1568 测试通过**、ruff/mypy 全绿。T1 开箱能对话 (私聊无条件触发 + 未回复可观测 + 占位 key 检测)、T2 零配置启动 (默认配置内置 + 首启建 data 目录)、T4 错误可诊断 (中文可操作提示 + /health 聚合 + 实时日志台后端) 均附真机冒烟证据 (见对应 commit)。**T3 按前后端分离重定义** (后端先交付 setup/auth API, 见 DEVELOPMENT_PLAN §四 FE)。本轮文档整合: 2026-07-28/29 两份 Review 报告的遗留项已整合进 DEVELOPMENT_PLAN (架构债清单; 07-28 复审的 C-N1~C-N5 与全部 Required 项已由 Fix-22~Fix-36 修复), S 骨架轮 HANDOFF.md 已随轮次结束删除。
>
> 上一轮 2026-07-31 —— **首次真机部署冒烟, 推翻"MVP 已达成"结论**。此前所有轮次的验收都只跑单测 + 读代码/文档,**从未真机走一遍用户旅程**。本次按 README 拷 `config.sample.jsonc` 到干净目录启动后实测:**发消息永远收不到回复,且日志里没有任何错误** —— 根因 `gating/system.py:174` 把私聊的强制触发条件写成 `has_at or (is_private and has_mention)`,私聊被额外要求"必须提及机器人名",私聊"你好"仅得 40 分 < 阈值 80 → `门控评分 score=30.0 threshold=80` → 静默 WAIT。另实测发现:消息被吞后用户端与日志双向零反馈;`control.enabled: false` 导致**WebUI 开箱不可用**;必须手写 JSONC 才能启动(AstrBot 默认配置内置代码,零文件即可跑)。结论:**内部能力确实已接线, 但产品尚不可部署可用, 不构成 MVP**。已新增最高优先级 **T 开箱可用轮**(§四 T, 先于 R),并立**验收铁律: 任何节点声明完成必须附真机部署证据, 不接受"单测通过"作为可用性证明**。详见 DEVELOPMENT_PLAN §四 T。
>
> 上一轮 2026-07-29 (**全量代码复审校正进度**: 以代码为准重新核验 Q2-Q6 与 P 剩余项, 发现文档系统性**低估进度** —— Q2-Q6 多数为「实现完成待接线」而非「未开始」(**Q2 已于当日补齐接线并升级 `[x]`**: persona.description 接入 BaseIdentityInjector + 新增 MoodTracker 挂 FINAL_RESPONSE 真实驱动 decay/update)。Q3 EnableMatrix + 进程级 hooks 已接但 per-Agent PluginContext 恒 None、MCPClient 零接线、CLI 工具 services 未注入; Q4 6 个媒体工具已注册 assembly.py:312-317 但出站 _send_reply 不解析 artifact、record_* 计量零调用、PricingCatalog 空表; Q5 Extensions/SSE/Usage 已接但 GET config + SubAgent 表 agent_id + Webhook/MCP 启动点未接; Q6 用量证据保存 + 并发信号量 + delegate deny 已完成, 仅剩背景摘要传递与 evidence_refs 生成; O4 微信 wecom 模式实为已实现并注册 main.py:410, 仅 mp 公众号为骨架。测试实为 **1545 例/134 文件** (Q2 落地后), 旧记 1362 已订正。**另新增 R 发布收敛节点组** (§四 R): 三级发布门 v0.9 MVP ✅ 已达成 / v1.0 RC = R1-R5 / v1.0 GA = R6-R7; 并记录 4 个此前未记录的需求级缺口 (行话学习写入侧 / 中期记忆伪压缩 / Session 不持久化 / SecretStore 零调用)。详见下方"待实现能力"表与 DEVELOPMENT_PLAN §四 Q/R)。上一轮 2026-07-28 (**S1-S5+S7 飞书+QQ官方 激活**: S1 三个主动任务生产者填真实产出逻辑 + 注入 memory; S2 MemoryConsolidator run_once 三步 + 注入 llm; S4 身份归一控制面 routes_identity + resolve_conflict + main/server 注入; S3 图谱召回 mentioned_in 边 + _graph_search 真实召回 + Reranker provider 注入 + MemoryItem 边界; S5 Workflow action_handler + 声明式加载 + condition_evaluator; S7 飞书适配器 (AES-256-CBC 解密字节序核对自官方文档) + QQ 官方适配器 (Ed25519 验签字节序核对自官方文档, 三类消息事件规范化); 91 例新测试, 全量 1362 单测通过、ruff/mypy 全绿。详见 DEVELOPMENT_PLAN §四"S 骨架轮 / S1-S5+S7"。S6 视频 Provider 用户决定暂缓。上一轮 2026-07-27 **骨架轮 S1-S7**: 为 P3 图谱召回 / P4 身份归一 / P5 Workflow 控制面 / MemoryConsolidator / proactive-ext 生产者 / O4 飞书·微信·QQ 官方三平台 / O5 视频 Provider 一次性补齐**骨架 + 默认关闭接线锚点**,均 default-off、主链路零行为变化;1271 单测基线。骨架≠交付,真实激活按 P3/P4/P5 验收执行。上一轮 2026-07-26 对照 `REQUIREMENTS.md` 十二条需求做 10 域并行代码取证 + 真实启动实测,新增 **Q MVP 收尾** 节点组,其中 **Q1 记忆写入回路** 已完成)

## 节点总览

| 大节点 | 名称 | 进度 | 说明 |
|--------|------|------|------|
| A | 文档冻结 | 100% | A1-A5 完成 |
| B | 基础骨架 | 100% | 脚手架 + 核心契约 + 配置日志 + 入口 |
| C | 连接与路由 | 100% | OneBot + Gateway + Router + Registry |
| D | 单 Agent 核心 | 100% | D1-D9 完成 |
| E | 多 Agent 运行时 | 100% | E1-E4 完成;E5 经 K6 端到端验收 |
| F | 插件生态 | 100% | AstrBot / MaiBot / Native / 加载器 |
| G | 控制面与自动化 | 100% | Admin API / MCP / Webhook / 安全默认值 |
| H | 平台与工具扩展 | 100% | Telegram/Discord/WebChat + MCP Client + 实用工具 |
| I | 生产化与交付 | 85% | 部署/文档/数据工具/监控完成;WebUI v2 完成;浏览器测试 CI 已随 K8 接入,待复核升 100% |
| J | 模型能力、计量与管理面 | 100% | J1+J2+J3+J4 完成 (非桩实现+测试+运行验证+文档同步);2026-07-26 五维度代码评审发现的 J2/J3/J4 缺口 (媒体校验未接线、J4 执行循环未接线、Token Scope/SSE scope 过滤/CSRF 会话缺失等 20 项) 已逐项修复,详见下方"J2/J3/J4 补充修复"|
| K | 稳定化与可用版本闭环 | 100% | K1-K8 全部完成 (K8-2 Playwright CI + release_checklist 已落地) |
| L | 拟人化运行时落地 | 100% | **P1 已接线 (2026-07-27)**: debounce 合并/wait 三路唤醒/thinking 期打断+旧回复抑制/主动任务强制话轮/会话快照恢复 全部接入生产主链路 (conversation.enabled 开关, 默认关闭零行为变化); L1-L5 升级为 [x] |
| M | 路由与 Agent Mesh 深化 | 100% | **P2 已接线 (2026-07-27)**: observer 旁听/candidate 仲裁/notify·handoff·memory_query 全部接入生产 (Link 细粒度 permissions + handoff 归属转移 + memory_query 同步返回+scope 裁剪); M1/M2 升级为 [x] |
| N | 记忆深化 | **已完成 (2026-08-16 收敛)** | N2 治理完整接入生产; N1 MemoryItem 边界文档化; N3 身份归一经 P4 收敛 (控制面+集成测试); 图谱召回/Reranker/Consolidator 经 S2/S3 激活并由 P3/R4 收敛; 实体关系图抽取层转 Y1 (GA 后) |
| O | 企业化与平台扩展 | 主体完成, 剩 mp/O5 (GA 后 V2/V3) | O1/O2/O3 经 R6 收敛 (routes_tenants+TenantManager / 隔离核验满足 / Workflow action_handler+agent: 决策落地); S7 飞书+QQ 官方真实收发; wecom 企业微信已实现; 剩: 微信 mp 公众号 (V3)、O5 视频 Provider 端点 (V2, 用户选型暂缓)、Slack (V4) |
| P | 主链路接线与激活 | **全部完成 (2026-08-16 收敛)** | P0/P1/P2 完成 (2026-07-27); P3/P4/P5 于 2026-08-16 升 `[x]` —— P3 图谱召回+Reranker (S3) + 集成测试 test_p3 (R7), 剩余实体关系图抽取层转 Y1; P4 身份归一控制面 (S4) + 集成测试 test_p4 (R7); P5 由 R6 收敛 (routes_tenants + 隔离核验满足 + agent: 入口决策落地) + 集成测试 test_p5 (R7)。定义见 DEVELOPMENT_PLAN §四 P |
| Q | MVP 收尾(新增) | **全部完成 (Q3-Q6 于 2026-08-16 收敛)** | Q0/Q1/Q2 完成 (2026-07-27/29); **Q3 由 R3 收敛** (共享注册表+AstrBot/MaiBot 桥接+MCPClient 接线); **Q4 由 R1 收敛** (出入站闭环+6 个 record_* 计量+价目表); **Q5/Q6 由 R2 收敛** (真实 revision+list-all+webhooks+MCP 5 工具+envelope/evidence_refs)。均于 2026-08-16 升 `[x]`。定义见 DEVELOPMENT_PLAN §四 Q |
| T | **开箱可用 (最高优先级)** | T1/T2/T4 完成 + T3-backend 后端段完成 (2026-08-16); T3 前端段 F1/F2 待启动 | T1 开箱能对话 (门控私聊修复 + 未回复可观测 + 占位 key 检测)、T2 零配置启动、T4 错误可诊断 已完成并附真机冒烟证据;T3 按前后端分离重定义 (后端段 = FE/T3-backend);T5 真实 IM 验收 (需凭据)、T6 插件市场 ✅ 完成 (2026-08-16, 依赖 R3 已满足)、T7 分发运维未开始。定义见 DEVELOPMENT_PLAN §四 T |
| FE | **前后端分离 (2026-08-15 制定, 后端先行)** | FE0/FE1/T3-backend 完成 (2026-08-16); F1-F4 待启动 | FE0 API 契约冻结 → FE1 分离基建 (CORS/跨源认证/静态托管降级) → T3-backend 控制面开箱后端支撑;前端轨道 F1-F4 (独立项目) 在 API 基线冻结后启动。定义见 DEVELOPMENT_PLAN §四 FE |
| R | 功能广度 (降级到 T 之后) | R3/R5/R2/R6/R1/R4 ✅ 完成 (2026-08-16); R7 集成测试部分完成 (2026-08-16, 环境准入项待环境) | 补齐需求十二条仍缺的实现 + Q3-Q6/P3-P5 剩余接线。**2026-07-31 整组降级到 T 之后**(主干不可用时补功能广度无意义)。**R3 插件与 MCP 生态激活 (Q3) 已完成 (2026-08-16)**: 共享注册表 + AstrBot/MaiBot adapt 桥接 + MCPClient 生产接线 + CLI 工具 services 注入 (详见 §四 R3, 真机冒烟 `MCP server 已接入 server=echo tools=1`)。**R5 持久化与密钥安全已完成 (2026-08-16)**: SessionManager SQLite 写穿+重启恢复 (照 UserMapper 同构) + SecretStore `secret:` 前缀接入 + CLI `isac secret` (真机冒烟重启恢复 session_id exit=0, 详见 §四 R5)。**R2 控制面与 SubAgent收尾已完成 (2026-08-16)**: `GET /agents/{id}/config` 真实 revision + SubAgent list-all + routes_webhooks (WebhookManager+EventBus 订阅+AlertManager 注入) + MCP Server 5 工具/生产启动点 + ContextEnvelopeBuilder 真传背景摘要 + evidence_refs 生成 (详见 §四 R2)。**R6 企业化激活已完成 (2026-08-16)**: routes_tenants (CRUD 租户+成员 + tenant:read/write scope) + TenantManager (SQLite 持久化照 UserMapper 同构) + ②loader 子进程隔离已满足零工作 + ③workflow agent 入口决策落地选 B (文档化不做, 消除悬空) (详见 §四 R6)。**R1 多模态出入站闭环已完成 (2026-08-16)**: ①_send_reply 扫 artifact 经 get_ref+MediaResolver 转 segment + ②入站下载落盘 data/uploads 闭环 + ③6 个 record_* 计量 + ④pricing.jsonc 价目表 + ⑤model_capabilities_allow 工具可见性 (详见 §四 R1)。**R4 记忆完整性补齐已完成 (2026-08-16)**: ①行话学习写入回路 consolidator `_extract_jargon_step` 群聊高频词 LLM 释义落 `upsert_jargon` + ②中期记忆真实 COMPRESS 方案 A (hook 入队+consolidator 后台摘要落 `episodes.summary`+MidTermMemoryInjector 改读 summary 注入 RecallCue) + ③语义关系图跳过留架构债 (写边层已就绪待补 LLM 抽取层, 留 Y1) (详见 §四 R4)。**R7 集成测试补齐代码可做部分已完成 (2026-08-16)**: 新增 test_p3/p4/p5 三套集成测试 19 例 (向量+图谱+治理过滤召回 / 两平台 bind→记忆聚合 / 跨租户不可见+插件隔离+workflow 声明式执行), 全绿; 环境准入项 (真机/Docker/24h soak/browser CI/十二条逐条取证) 待环境 (详见 §四 R7)。定义见 DEVELOPMENT_PLAN §四 R |
| 可观测性 | trace 贯穿 + 分级日志 (横切) | 100% | trace_id/session_id/agent_id 贯穿全链路;level + per_module 分级;默认零输出零开销 |

## 可运行性状态

> ⚠️ **2026-07-31 订正**: 下述"可运行"指**进程能起来并驻留**,**不等于"用户能用"** —— 真机冒烟证明按 sample 配置部署后**发消息收不到回复**(见文首 T 轮说明)。"可部署可用"的口径以 §四 **T 开箱可用轮**的真机验收为准。

**已达到「可运行(进程驻留)」完成度**(2026-07-26 实测,不等于「MVP 可用」,见下方 2026-07-26 差距复核与文首 2026-07-31 真机冒烟):

- 主程序实测驻留(无 `data/config.jsonc` 时兜底默认值 + StubProvider 也能启动;18 秒驻留无异常栈),支持 SIGINT/SIGTERM 优雅关闭(Windows 下 Ctrl+C 尚不走优雅关闭路径,见 Q0)。
- 1568 单元/集成测试通过 (2026-08-15 实测);Ruff 通过;Mypy 全绿 (256 文件)。
- 集成测试就位:单 Agent 全链、多 Agent × 工具 × 记忆 × 控制面、启动驻留 smoke、J2 多模态全链 + Channel 投递、J4 SubAgent 全链 + Control API、J3 WebUI v2 SPA 十域。
- 真实 `OpenAICompatProvider`(httpx + SSE + Tool Call + 错误分类 + 连接池)可用;主链路默认非流式,流式路径(CR3-H4 已修合并逻辑)尚未在生产启用。
- Agent / 路由 / Link / 记忆可持久化恢复;SubAgent 任务可重启恢复 (running/queued → cancelled)。**订正**:此前"Session 可持久化恢复"表述不准确 —— `SessionManager`/`UserMapper` 实为纯内存实现(无落盘/无恢复),重启后会话状态与跨平台用户绑定丢失(对话内容因记忆子系统独立持久化不受影响);补齐计划见 Q1。
- J3 WebUI v2 SPA 十域全部真实内容: Dashboard/Agents/Channels/Providers/Usage/Extensions/Memory/Sessions/Logs/System; 配置编辑事务 (Schema 校验 + Diff 预览 + 二次确认 + ETag 乐观锁); SSE 实时事件流; Playwright 浏览器黄金路径测试 (未装时 skip, CI 接入待 K8-2)。

## 稳定化节点 (K) 明细

| 节点 | 状态 | 交付 |
|------|------|------|
| K1 应用生命周期 | ✅ | ApplicationRuntime + TaskGroup + register_lifecycle + 优雅关闭 |
| K2 真实 Provider | ✅ | OpenAICompatProvider 真实 HTTP/SSE/Tool Call/429·5xx 分类/连接池 |
| K3 存储生命周期 | ✅ | Schema init/migration + BM25 预热 + shared namespace ACL |
| K4 配置持久化恢复 | ✅ | 原子写 (tmp+fsync+os.replace) + Agent/Link 恢复 |
| K5 单 Agent E2E | ✅ | FakeChannel + FakeLLMProvider 全链集成测试 |
| K6 多 Agent E2E | ✅ | 多 Agent × 工具 × 记忆 × 控制面集成测试 (含原 E5) |
| K7 安全基线 | ✅ | SSRF 防护 + SecretStore(AES-256-GCM) + TTL + 有界队列 + kill-wait |
| K8 CI/发布准入 | ✅ | CI 四 job (check+build+docker+browser) + wheel/sdist smoke + Docker 30s health 循环 + Playwright CI 接入 + scripts/release_checklist.md 七段发布清单 |

## 待实现能力

**J2/J3/J4 补充修复 (2026-07-26)**:

对 J2/J3/J4 做五维度代码评审后发现 7 项 Critical + 8 项 Required 缺口 (均已直接
读代码确认, 非道听途说), 逐项 TDD 修复并独立提交:
- J2: `MediaNormalizer` 接入 `TranscribeAudioTool`/`VisionUnderstandTool` 生产路径 (此前授权这两个工具的 Agent 可读任意本地文件); 图片生成下载 URL 补 SSRF 校验。
- J4: 子 Agent 真实执行循环接入生产 (此前 `delegate_task` 永远停在 `queued`); `SubAgentPolicy` 空集改严格交集 (此前 fail-open); 递归深度限制; 取消超时不再静默; Journal 脱敏补 `summary`/`max_log_bytes`; `_authorize` 补跨 Agent 校验。
- J3: `PATCH /agents/{id}` If-Match 改读 HTTP Header (原来是 query 参数, 会被静默忽略) + `AgentManager` 按 agent_id 加配置锁修复并发竞态; `CONTROL_PLANE_SPEC.md` §6.1 描述的 Token Scope 模型 (`control.tokens[]`) 落地; SSE 事件按 scope 过滤 + 连接数上限; Provider 测试/制品删除端点补审计日志; `InterAgentLink` 格式校验 + WebUI 审计日志渲染改用 `textContent` (修复存储型 XSS); `POST /auth/session` 会话 Cookie + CSRF 双提交校验 (§8.2 第 5 条)。

**J3 已完成 (2026-07-25)**:

J3 WebUI v2 管理与观测已完整落地 (详见 DEVELOPMENT_PLAN.md J3 节"当前"):
- 后端 Control API 扩展 (routes_providers / routes_config / routes_sessions / routes_memory / routes_events SSE)
- AgentConfig 加 revision 字段 + PATCH If-Match 乐观锁
- WebUI v2 SPA shell 侧边栏 10 域导航
- Dashboard / Agents / Channels / Providers / Usage / Extensions / Memory / Sessions / Logs / System 十页真实内容
- 配置编辑事务 UI (Schema 校验 + Diff 预览 + 二次确认 + ETag 乐观锁)
- Playwright 浏览器黄金路径测试 (2 路径; 未装时 skip, CI 接入待 K8-2)

**剩余工作 (接线 + 未实现;定义详见 DEVELOPMENT_PLAN.md §四 P 节点)**:

*已实现待主链路接线 (`[~]`:核心逻辑 + 单测完成,默认关闭 / 生产路径无调用点)*:

| 能力 | 现状 | 接线节点 |
|------|------|---------|
| L2-L5 拟人化 | **已接线 (P1, 2026-07-27)**: debounce 合并/主动调度启停/打断闭环/恢复加载全部进生产主链路 | P1 ✅ |
| M1-M2 Mesh | **已接线 (P2, 2026-07-27)**: observer/candidate 路由 + broker 注入 + 4 A2A 工具真实可用 (Link permissions/handoff 归属转移/memory_query 同步返回) | P2 ✅ |
| N1 MemoryItem | 契约 + Adapter 实现;S3 落地边界文档化 —— 治理路径 (N2 export) 用 MemoryItem, 检索热路径 (`search()`/`_merge_results()`) 继续用轻量 MemoryHit (避免为尚无消费者的抽象层增加每请求开销) | 已明确边界 |
| N3 身份归一 | IdentityResolver 实现;**S4 激活 (2026-07-28)**: 控制面 routes_identity (bind/conflicts/resolve) + main/server 注入 + IdentityResolver.resolve_conflict;剩集成测试 + 真实凭据联调 | P4 (剩集成测试) |
| O1 多租户 | **已接线 (CR3-L2)**: `tenancy.enabled` 配置开启后 MetadataStore 读写带租户谓词/打标 + 记忆命名空间加前缀;默认关闭零行为变化 | 已完成 (跨租户测试见 test_tenant_isolation) |
| O2 插件隔离 | PluginIsolationHost 已支持子进程真实加载插件 (`load_plugin`, CR3-H2) + `on_load` 生命周期已接线;**默认加载路径仍在宿主进程内执行 (无隔离, 有护栏警告)**, 接管待做 | P5 |
| O3 Workflow | **S5 激活 (2026-07-28)**: action_handler (tool: 前缀 → ToolRegistry.execute) + 声明式加载 (`load_workflows_from_dir`) + condition_evaluator;控制面 routes_workflows 已挂载;剩 Agent 工具入口 (P5 决策项, 有意未做) | P5 (剩 Agent 工具入口) |
| 向量召回 | **已接线 (CR3-H3)**: `pipeline.search()` 稠密召回 + RRF 融合 + ACL 一致过滤;`memory.embedding` 配 api_key+model 即生效 (main 注入 EmbeddingProvider)。**S3 激活 (2026-07-28)**: 图谱召回 mentioned_in 边写入 + _graph_search 真实召回 (种子锚定 user_id/group_id 满足 ACL) + 第四路 RRF;Reranker provider 注入 (够 api_key+model 时 is_available=True, 仿 CR3-H3 embedding 注入写法) | P3 (通用实体关系图留后续增强) |
| 流式工具调用 | 按 index 累积分片 + stream_options.include_usage + 首 chunk 前失败回退 chat_with_retry (CR3-H4);主链路未启用 streaming | P0 |

*已激活 (2026-07-28 S1-S5+S7)*:

- **S1 主动任务生产者** — DateReminder/TopicFollowup/MemoryAssociation 三者 `__call__` 改 async + 填真实产出逻辑 (记忆日期实体/未闭合话题/记忆联想检索); `_build_task_producer` 注入 memory。16 例单测。
- **S2 MemoryConsolidator** — run_once 三步真实整合 (去重合并: 相似度≥0.92 软删旧者经 governor; 重要性+时间衰减剪枝; 画像归纳: llm 注入时调 chat 生成 profile_text); 各步异常隔离。10 例单测。
- **S3 图谱召回 + Reranker + MemoryItem 边界** — 见上表"向量召回"行。
- **S4 身份归一控制面** — 见上表"N3 身份归一"行。
- **S5 Workflow 控制面激活** — 见上表"O3 Workflow"行。
- **S7 飞书适配器** — Webhook 入站 (URL 校验 + 明文/加密两种模式, AES-256-CBC 解密 key=SHA256(encrypt_key)/IV=base64decode(encrypt)[:16]/PKCS7 unpad; im.message.receive_v1 事件规范化) + 出站 (tenant_access_token 缓存 + POST /im/v1/messages 按 receive_id_type 分群聊/私聊)。字节序核对自 open.feishu.cn 官方文档。14 例单测。
- **S7 QQ 官方适配器** — Ed25519 验签字节序核对自 bot.q.qq.com 官方文档 (seed=secret 重复双倍到 32 字节); op=13 验证握手签名 event_ts+plain_token; op=0 dispatch 事件验签 X-Signature-Ed25519 + X-Signature-Timestamp, msg=timestamp+raw_body; AT_MESSAGE_CREATE/GROUP_AT_MESSAGE_CREATE/C2C_MESSAGE_CREATE 三类事件规范化 + 出站 (access_token 缓存 + 群/私聊双端点 + 被动回复 msg_id)。19 例单测。

*2026-07-29 新发现的需求级缺口 (读侧就绪/写侧缺失, 此前各轮复核均未记录; 已收入 R4/R5)*:

| 缺口 | 证据 | 需求条款 | 收敛节点 |
|------|------|---------|---------|
| **行话学习写入侧零实现** | `JargonInjector` 已注册读侧 (`assembly.py:341`), 但 `upsert_jargon` 全仓无生产调用点 → 行话表恒空 | R4/R5 明确要求"行话学习" | R4 ✅ 已完成 (2026-08-16): consolidator `_extract_jargon_step` 群聊高频词 LLM 释义落 `upsert_jargon` |
| **中期记忆是伪压缩** | `MidTermMemoryInjector` 已注册 (`assembly.py:343`) 但仅截断复述 `pending_messages` 末 5 条; 与其自述"由 COMPRESS hook 触发 + CompressionPolicy + Summary + Recall Cue"不符, 未接 `COMPRESS` | R5 要求"中期记忆" | R4 ✅ 已完成 (2026-08-16): COMPRESS hook 入队 + consolidator 后台摘要落 `episodes.summary` + MidTermMemoryInjector 改读 summary 注入 |
| **Session 不可持久化恢复** | `SessionManager` 纯内存 (`session.py:30-35`), 重启丢会话状态 | R10 明确要求"Agent、Session、身份、路由、Link 和记忆可持久化恢复" | R5 |
| **SecretStore 零生产调用** | AES-256-GCM 实现存在但仅在注释被提及 (`progress.py:36`/`journal.py:23`), `api_key` 明文存 `data/config.jsonc` | R9"密钥只可设置或替换, 不可回显" | R5 |

*未开始 (`[ ]`)*:

- **S6 视频 Provider** — `generate` 仍抛 `NotImplementedError`; 用户决定暂缓端点选型 (Sora/Runway/Kling/自托管), 待确定后仿 image_gen 实现 (POST 生成 → 轮询/等待 → 结果写 ArtifactStore → 返回 ArtifactRef)。
- **微信适配器** — 用户决定本轮不做, 保持骨架 (start/stop no-op、send 返回 False)。
- **S5 Agent 工具入口** — 让 Agent 主动触发 workflow; 明确为 P5 决策项, 有意未做 (避免半接线死代码)。
- **I 节点复核** — WebUI 浏览器测试 CI 已随 K8 接入,复核 I 是否可由 85% 升 100%。

*已补齐*: N2 检索期软删除过滤已生效(CR2-Fix-12),N2 记忆治理已完整接入生产。

*订正(2026-07-26, 已于 2026-07-28 S3 修复)*: 此前"Reranker 已接入检索 pipeline"表述不准确。真实后端 `OpenAICompatRerankerProvider`(Cohere/Jina 双协议,`isac/provider/rerank/openai_compat.py`)确已实现,但生产 `main.py` 构造 `Reranker(memory_config.get("reranker", {}))` 时**未传入 provider**,`is_available()` 恒 `False`,`pipeline.search()` 的 rerank 步骤永不执行。**S3 (2026-07-28) 已修复**: `_build_memory_stack` 仿 CR3-H3 embedding 注入写法, 够 `reranker.api_key+model` 时构造 `OpenAICompatRerankerProvider` 传入 `Reranker(cfg, provider=...)`, `is_available()` 不再恒 False。

**CR3 修复轮 (2026-07-26, 对应 Review/ISAC_待修复项清单.md 的 14 项)**: H2 插件隔离护栏+`on_load` 接线+隔离宿主真实加载 / H3 向量召回接入 pipeline(RRF+ACL)+生产 EmbeddingProvider 注入 / H4 流式工具调用按 index 累积+include_usage+失败回退 / M2 bus notify 真实投递 / M5 Gating-Focus LRU cap 1000 / M6 调度器冷却不再饿死其他会话 / M7 Workflow 多入口+fan-in 入度语义 / L1 自动化创建 Agent 强制受限沙箱 / L2 租户隔离进数据面(默认关闭) / L3 软删同步 BM25+预热过滤 / L4 SSRF 请求期固定 IP / L5 治理审计 operator+agent_id 归因 / L6 非 ASCII Token 401+/metrics 可选认证 / L8 write_file 线程池+journal 原子 seq+MCP sse 显式拒绝。附带: 控制面 sessions/memory/events 路由完成生产挂载(此前 services 键缺失恒 None), `resource` 模块 Windows 平台守卫。

## 2026-07-27 MVP 增量代码评审修复轮 (MVP-Fix)

P0-P2 + Q0-Q1 达成 MVP 准入线后，对整个增量 diff (23 文件 / +1430 行) 做 5 维度并行审查 + 每条发现 2 票独立对抗性验证 (22 代理 / 405 次代码检索)：**17 项发现 → 13 项确认、4 项证伪**，全部修复并配 12 例回归测试 (`tests/integration/test_mvp_review_fixes.py`)。

高危 5 项：多步(工具)回合的打断被 `InterruptInjector` 吞掉 (改用单调 `interrupt_seq` 基线判定) / 突发消息重复回复 (drain 空即弃权 + 去重键改 `msg_id`，根因是 `dataclasses.replace` 使身份去重永不命中) / 门控只评估突发末条 (drain 提到门控前，`has_at` 取并集) / 后台记忆写入不被 drain (`drain_background_tasks` 接入关闭链) / **memory_query 空 scopes 泄露全部记忆**(改为 deny-by-default)。

中危 4 项：handoff 永久劫持路由 (加 TTL + 交还路径) / 强制话轮释放他人会话锁 (`acquired` 标志) / 互联消息被 debounce 拦截 (豁免) / UserMapper 并发身份分裂 (锁串行化)。

低危及顺带：快照过期清理 + 目录跟随 `control.agents_dir` (此前测试污染真实 `data/agents`) / `config.sample` embedding 维度矛盾 / 补齐 `InterAgentMessage.trace_id` / **记忆保真度**(合并回合改为写入完整 burst，冒烟发现)。

验证：1203 单测通过、ruff/mypy 全绿；真实启动冒烟确认 3 条突发消息恰好产生 1 条合并回复、记忆与画像正确落库。

## 2026-07-26 MVP 差距复核 (对照 REQUIREMENTS.md 逐条取证)

对照 `docs/REQUIREMENTS.md` 十二条原始需求,10 个领域并行验证(每条结论均落实到 文件:行号 证据,498 次代码检索 + 一次真实启动实测:无 `data/config.jsonc` 时兜底默认值也能启动、18 秒驻留无异常栈)。核心结论:**项目"能启动"但未达"MVP 可用"** —— 开箱只有 OneBot 一条可聊通道(WebChat/Telegram/Discord 已实现却零生产注册点)、**记忆写入回路完全缺失**(检索/注入/治理/持久化整条读链路就绪,但生产从未调用 `store_episode`,检索永远为空)、人格系统的情绪/表达风格/注意力漂移注入器是未注册的空桩、插件与 MCP 生态的数据面注册表在生产被硬编码为空、多模态语义工具从未注册进 ToolRegistry。

同时发现一批标 `[x]` **已交付**的节点(D8/E4/F1-F3/H1/H2/J1-J4/K1-K4/K7)存在与其"完成定义"(§二:非桩实现+单测+集成验证+**主链路接线**+文档+CI)矛盾的未接线子行为 —— 已在 `DEVELOPMENT_PLAN.md` 对应节点下补记"**2026-07-26 MVP 缺口复核**"说明并指向修复它的 Q 节点,不改动其余已验证部分的 `[x]` 标记(与 J2/J3/J4 既有的"补充修复"记录方式一致)。

为把这些**未被 P0-P5 任何节点覆盖**的必需缺口系统化,新增 **Q 节点组:MVP 收尾**(定义详见 `DEVELOPMENT_PLAN.md` §四 Q):

| 能力 | 现状 | 对应节点 |
|------|------|---------|
| **Q1 记忆写入回路与身份稳定化** | **已完成 (2026-07-27)**: 回复后后台写 episodic (整轮对话)+画像/关系每互动递增 (读写同键)+UserMapper SQLite 写穿持久化 (master_id 跨重启稳定);行话学习/画像 LLM 归纳留 MemoryConsolidator;Session 状态仍不持久化 (如实标注) | Q1 ✅ |
| Q0 开箱可触达与配置纠偏 | **已完成 (2026-07-27)**: 四平台注册分支+裸部署默认路由+样例死键修正+Dockerfile 冻结+Windows 优雅关闭+web_search deny+Provider 缓存失效+destroy 记忆清理+task 门修正;冒烟另修复出站平台会话键丢失 (WebChat 回复/进度帧落错队列) | Q0 ✅ |
| Q2 人格差异化实现 | **已完成 (2026-07-29)**: `config.persona.description`(Agent 覆盖全局)接入 `BaseIdentityInjector`(`assembly.py:254-259`, 未配置回落默认文案零行为变化);新增 `MoodTracker`(`isac/persona/mood_tracker.py`)挂 `FINAL_RESPONSE`, 每轮 `decay()` 自然衰减 + 按工具调用数(封顶 5)施加小幅 arousal 扰动(valence 不臆造情感判断);三注入器沿用既有真实逻辑。**复核修正**: arousal 信号源初版读 `response.tool_calls`, 但 `FINAL_RESPONSE` 触发时该值恒为空(`loop.py` else 分支的触发条件), 是死代码; 改读 `AgentContext.tool_calls_this_turn` 累加值, 补真实 `ISACAgentLoop` 端到端回归。新增 9 例单测, 全量回归(1473 单测 + 72 集成)无退化 | Q2 ✅ |
| Q3 插件与 MCP 生态数据面接线 | **部分接线 (2026-07-29 校正)**: `EnableMatrix` 已注入 `PluginManager` (`main.py:1227`) + 进程级 plugin hooks 已合并进 Agent (`assembly.py:265`);剩 ① per-Agent `PluginContext` 注册表恒 `None` (`main.py:1362`) → AstrBot/MaiBot 加载但 handler 不触发 (loader 不调 `adapt`) ② `MCPClient` 零生产接线, `mcp_servers` 无消费者 ③ `bash`/`read_file`/`write_file` 的 services 未注入 → 恒被拒 | Q3(新增,E4/F1-F4/H2 delta) |
| Q4 多模态工具注册与计量收尾 | **部分接线 (2026-07-29 校正)**: 6 个语义媒体工具已注册进 ToolRegistry (`assembly.py:312-317`, default deny);剩 ① 出站 `_send_reply` 不解析 `artifact_id` (`main.py:209`) → 生成媒体发不出 ② 入站媒体不落盘 `data/uploads/` ③ `record_*` 6 计量方法零生产调用 → 用量恒 0 ④ `PricingCatalog` 空表 (`main.py:770`) ⑤ 无 `model_capabilities_allow` 字段 | Q4(新增,J1/J2 delta) |
| Q5 WebUI 与控制面收尾 | **部分接线 (2026-07-29 校正)**: Extensions 页接 `/plugins/loaded`、SSE `EventSource('/events/stream')`、Usage 页结构已接;剩 ① `GET /agents/{id}/config`+真实 revision 缺失 (前端伪造 revision=1) ② SubAgent 任务表 agent_id 硬编码 `_` (`app.js:495`) 恒空 ③ Webhook/MCP Server 无生产启动点/路由挂载 | Q5(新增,J3/G2/G3 delta) |
| Q6 SubAgent 用量与安全补漏 | **大部分完成 (2026-07-29 校正)**: `result.usage`/`evidence_refs` 已存 run (`supervisor.py:193`) + 并发信号量 (`supervisor.py:54`, 默认 4) + `RESTRICTED` deny `delegate_task` (`defaults.py:35`);剩 ① 背景摘要未经 `ContextEnvelopeBuilder` 传子 Agent (runner 未调用) ② `evidence_refs` 生成缺失 (`runner.py:93` 恒空) | Q6(新增,J4 delta) |

Q0/Q1 不依赖 P0 消息并发化,建议与/先于 P 节点推进;P2(Mesh)、P3(记忆检索深化)的验收范围已相应扩充(Link 细粒度 ACL、Reranker 注入),不在 Q 中重复列出。MVP 准入线(P0-P2 + Q0-Q1)见 [ROADMAP.md](./ROADMAP.md) MVP 里程碑。

## 编号约定

- 大节点 A/B/C… 为里程碑;小节点如 D9、K1 为最小可交付单元。
- 完成定义 = 非桩实现 + 单元/集成测试 + 实际运行验证 + **主链路接线** + 文档同步 + Ruff/Mypy 通过。
- **scaffolding (框架已搭建)** = 契约 + 骨架 + 惰性默认关闭接线 + 骨架单测 + 主链路零行为变化;**不满足完成定义,不标 100%/`[x]`**。技术路线见 [ROADMAP.md](./ROADMAP.md),范式见 [MODULE_GUIDE.md](./MODULE_GUIDE.md)。
- **三态标记** = `[x]` 已交付(含主链路接线) / `[~]` 实现完成待接线(核心逻辑 + 单测完成,但未接入生产,接线项归 DEVELOPMENT_PLAN §四 P 节点) / `[ ]` 未开始。演进链:scaffolding → `[~]` → `[x]`。
