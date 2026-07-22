# Changelog

本文件记录 ISAC (Intelligent Social AI Companion) 所有发布版本与变更。
格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/), 版本遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

---

## [Unreleased]

后续待发布能力 (按 DEVELOPMENT_PLAN.md 节点推进):

- E5 多 Agent 集成测试 (待业务全完成后做联调测试)
- I6 集成测试 + 覆盖率提升至 80%+ 整体

---

## [1.0.0] - 2026-07-23

首个完整版本: 多 Agent AI 社交陪伴 Bot 框架, 覆盖 A-I 全部 9 大节点。

### Added

**A 文档冻结**
- 术语表 + 规范确认 (SPECIFICATION.md / ARCHITECTURE.md / DEVELOP.md / DEVELOPMENT_PLAN.md)
- 架构蓝图 v3.0 定稿 (多 Agent + 控制面/数据面分离 + Channel-Agent 解耦)
- 接口契约冻结 (core/types.py / events.py / exceptions.py)
- 5 个专项施工图: HUMANLIKE_RUNTIME / MEMORY_DESIGN / ROUTING_AND_AGENT_MESH / PLUGIN_COMPATIBILITY / CONTROL_PLANE_SPEC

**B 基础骨架**
- 项目脚手架 (pyproject.toml + uv + ruff + mypy + pytest CI)
- 核心契约 (types / events / exceptions / constants)
- 配置与日志系统 (utils/config + utils/logger + structlog 降级)
- 入口与调试脚本 (isac/main.py + scripts/)

**C 连接与路由**
- OneBot v11 适配器 (反向 WebSocket + aiocqhttp 惰性导入)
- Gateway 会话与用户系统 (EventBus 双层 + SessionManager + UserMapper + SessionLock)
- MessageRouter 路由规则 (显式绑定 > 触发词 > 默认 Agent > DROP)
- ChannelRegistry 统一启停

**D 单 Agent 核心**
- D1 门控系统 (GatingSystem + ReplyNecessityJudge 完整评分 + FocusMode + IdleBackoff + TurnScheduler 滑窗频率与存在感计数)
- D2 Prompt 组装 (SystemPromptBuilder + 注入器频率控制)
- D3 Agent Loop (pre_llm → LLM → post_llm → tool → final_response)
- D4 工具系统与权限 (13 个内置工具 + restricted 策略 + 路径白名单 + 命令白名单 + shell 元字符防护)
- D5 记忆存储 (MetadataStore SQLite + FTS5 + SparseBM25Index 真实 BM25)
- D6 检索流水线 (Embed→Dense+Sparse→RRF→Rerank, 恒降级为纯稀疏检索)
- D7 记忆注入器 (Heuristic 3min/60msg + PersonProfile + Jargon + MidTerm)
- D8 人格系统 (MoodEngine update/decay + BehaviorLearner FINAL_RESPONSE hook + PersonaManager 聚合)

**E 多 Agent 运行时**
- E1 AgentConfig 三层配置覆盖 (全局/Agent/环境变量)
- E2 AgentManager 生命周期 (create/start/stop/destroy/list/reload_config)
- E3 InterAgentBus + ACL (默认拒绝, 显式 Link)
- E4 启用矩阵 (EnableMatrix: Agent ∩ Channel ∩ 全局, plugin/tool/command/mcp 四类)

**F 插件生态**
- F1 AstrBot 兼容层 (Star + @filter.llm_tool + Context API 桥接 + sandbox import 拦截)
- F2 MaiBot 兼容层 (MaiBotPlugin + @register_action/@register_command + PluginAdapter 扫描装饰器)
- F3 原生 SDK v2 (ISACPlugin + PluginContext 真实落地 + InterAgent Hook + Admin Route 预留)
- F4 插件加载器与启用矩阵 (PluginLoader 三格式自动识别 + PluginManager 错误隔离 + 热重载)

**G 控制面与自动化**
- G1 Admin REST API (Bearer Token + AuditLog 双写 + AgentConfig/路由/Link/插件矩阵持久化 + FastAPI docs)
- G2 ISAC MCP Server (JSON-RPC 2.0 + stdio NDJSON + tools/call Bearer 认证 + 11 工具委托)
- G3 Webhooks (subscribe/unsubscribe/dispatch + 失败重试 3 次 + /automation/trigger)
- G4 控制面安全与审计 (RESTRICTED_TOOLS_POLICY 默认 deny bash/task + enforce_safe_host 防 0.0.0.0 + 审计日志查询)

**H 平台与工具扩展**
- H1 平台适配器 (Telegram Bot API long polling + Discord REST polling + WebChat 极简 HTTP)
- H2 MCP Client (stdio 子进程 + HTTP/SSE 双传输 + MCPToolBridge 桥接)
- H3 实用工具与子 Agent (TaskRunner 真实实现 + 限制 token 预算与递归深度)

**I 生产化与交付**
- I1 WebUI 管理面板 (Vanilla JS + 4 模块: Agent/路由/Link/审计)
- I2 Docker 部署 (多阶段构建 + docker-compose + 部署脚本)
- I3 文档完善 (docs/ 6 篇: usage/deployment/api/plugin_development/control_automation/README 导航)
- I4 数据工具 (AstrBot/MaiBot 迁移 + 备份/导入 zip)
- I5 监控告警 (MetricsCollector Counter/Gauge/Histogram + Prometheus 输出 + 规则驱动告警 + cooldown + 3 默认规则)

### Documentation

- README.md 项目总览
- ARCHITECTURE.md 架构蓝图 v3.0 + ADR-001~011
- SPECIFICATION.md 数据模型与接口契约
- DEVELOP.md 开发规范 (目录/导入/命名/测试)
- DEVELOPMENT_PLAN.md 节点制 SOW / TODO 清单 / 进度跟踪
- AGENTS.md Agent 协作指南
- docs/ 使用文档集群 (usage/deployment/api/plugin_development/control_automation)

### Tests

- 326 单元测试全部通过 (ruff All checks passed + mypy no issues)
- 覆盖核心模块 (core / memory / gating / persona / agent/tools 等) 80%+ 覆盖率
- 适配器类 (onebot/telegram/discord/webchat) 因需真实外部服务, 测试覆盖消息转换逻辑

### Known Limitations

- LLM 真实调用: OpenAICompatProvider.chat/chat_stream 仍是桩 (未集成 httpx 真实调用)
- 记忆真实向量检索: VectorStore 与 EmbeddingManager 仍是桩 (恒降级为纯稀疏检索)
- 记忆整合: MemoryConsolidator 后台任务未实现
- LLM 错误重试: chat_with_retry 区分错误类型 (RateLimitError 退避更久) 未实现
- 集成测试: 多 Agent 端到端联调 (E5) 待业务全完成后做
- 整体测试覆盖率 68% (核心模块 80%+; 适配器与控制面集成场景受外部服务限制)

---

## 历史版本

(本项目从 0.1.0 开始正式节点制开发, 此前无发布版本)
