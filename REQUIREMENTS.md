# ISAC 需求清单

> 本文档汇总项目目标与用户需求。架构细节以专项文档为准，开发状态以 `DEVELOPMENT_PLAN.md` 为准。

## 1. 多 Agent 架构

- 同一系统运行多个独立 Agent。
- 每个 Agent 独立配置人格、模型、记忆 namespace、插件、工具、MCP 和权限。
- 支持 Agent 创建、启停、销毁、热更新及重启恢复。

## 2. 多 IM 与灵活路由

- 支持 OneBot/QQ、Telegram、Discord、WebChat，并可继续扩展平台。
- 一个 Agent 可连接多个 IM，一个 IM 可由多个 Agent 共享。
- 支持显式绑定、触发词、@提及、命令、默认 Agent 及 primary/observer/candidate 模式。
- Channel 与 Agent 解耦。

## 3. Agent 间协作

- 支持 ask、notify、handoff 和授权记忆查询。
- 使用 Link ACL 控制方向、消息类型、上下文和可见记忆范围。
- 默认拒绝未配置通信。

## 4. 拟人化交互

- 通过 ConversationRuntime 管理消息缓存、等待、打断、主动任务、回复节奏和上下文恢复。
- 支持人格、情绪、关系、表达风格、行为模式和行话学习。
- 工具执行期间可发送中间进度；最低保障是工具完成后按 Agent 人设汇报。

## 5. 长期记忆

- 支持事件记忆、人物画像、中期记忆、关系、行为模式和行话。
- 支持 Agent 私有 namespace 和受 ACL 约束的共享记忆。
- 无 Embedding/Reranker 时使用 FTS/BM25；有模型时支持向量、稀疏、图谱和 Rerank。
- 记忆可持久化、恢复、纠正、删除和治理。

## 6. 插件与工具生态

- 兼容 AstrBot 和 MaiBot 插件，提供 ISAC Native Plugin SDK。
- 支持内置工具、CLI、MCP 和受限子任务工具。
- 最终权限由全局、Agent、Channel 和任务策略取交集。
- Bash、文件、网络、插件和 MCP 必须具备安全与资源边界。

## 7. 统一模型体系

- 支持 LLM、视觉理解、STT、TTS、生图、视频理解和视频生成。
- 通过 ModelDescriptor、ModelCatalog 和 ModelRouter 统一注册、感知和选择。
- Agent 只看到获授权的语义能力，不依赖具体厂商模型名称。
- 媒体结果通过 ArtifactStore 管理并按 Channel 能力发送或降级。

## 8. Token、用量与成本

- 按 Provider、模型、Agent、会话、模态和物理请求记录用量。
- 区分输入、输出、缓存、推理、音频 Token，以及图片数量和音视频时长。
- 重试、失败、回退分别计量。
- 通过可追溯价格快照估算成本；未知价格不伪造费用。

## 9. WebUI 与控制面

- WebUI 管理 Agent、Channel、路由、Provider、模型、用量成本、插件、MCP、工具、记忆、会话、任务、日志、审计和系统设置。
- 配置修改支持 Schema 校验、diff、确认、乐观并发和审计。
- 密钥只可设置或替换，不可回显。
- 提供 REST API、MCP Server、Webhook 和自动化入口。

## 10. 稳定性与交付

- 应用必须持续驻留，并具备统一启动、健康检查和优雅关闭。
- 至少一个真实 Provider 完成流式、工具、用量和错误处理闭环。
- Agent、Session、身份、路由、Link 和记忆可持久化恢复。
- 建立单 Agent、多 Agent、控制面、Docker 和浏览器端到端测试。
- CI 覆盖 Ruff、Mypy、覆盖率、包构建、Docker、集成和浏览器测试。
- K1-K8 完成前项目定位为 Alpha。

## 11. 每个 Agent 的 SubAgent 能力

- 每个长期 Agent 都能把检索、工具、文件处理等事务性工作委派给临时 SubAgent，尤其用于避免情感陪伴主上下文被工具轨迹污染。
- SubAgent 使用独立消息历史、Prompt、预算和临时工作区；默认不继承情绪、关系、完整会话或长期记忆写权限。
- 主 Agent 默认只接收结构化结果、证据引用和用量摘要，不把完整执行轨迹注入主上下文。
- 每个子任务产生稳定 `task_id` 和持久化、追加式工作日志，记录状态、模型/工具调用、脱敏参数摘要、结果摘要、错误与证据；不记录模型原始 reasoning。
- 主 Agent 可列出任务、查询状态、分页读取日志和证据、取消任务；用户追问时优先复用既有日志，不重复执行仍有效的工作。
- SubAgent 权限只能是父 Agent 权限的收窄子集，并限制 Token、时间、工具、并发、递归、日志、工作区和制品保留期。
- SubAgent 默认不能直接回复用户、写长期记忆、创建永久 Agent 或无限派生；用户可见进度由主 Agent 的 ProgressReporter 统一发送。
- SubAgent 与 Agent Mesh 分离：前者是父 Agent 下的临时执行单元，后者是长期独立 Agent 间协作。

## 12. 总体目标

ISAC 应成为一个融合 AstrBot 多平台与插件生态、MaiBot 拟人化与长期记忆，并具备多 Agent 编排、隔离 SubAgent、统一模型能力、权限治理、自动化控制面和商业化基础的通用 Agent 框架。
