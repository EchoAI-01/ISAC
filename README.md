# ISAC — Intelligent Social AI Companion

> 融合 AstrBot / MaiBot / hermes-agent / openclaw / opencode 等项目之精华的 AI 社交陪伴 Bot 框架¹

> ¹ 设计溯源： AstrBot（多平台适配器/插件）、MaiBot（门控/专注模式）、opencode / grok-build（多 Agent 控制面）、hermes-agent / openclaw（Agent 工具与记忆模式）。详见 ARCHITECTURE.md 相关 ADR。

## 文档导航

| 文档 | 说明 |
|------|------|
| [ARCHITECTURE.md](./ARCHITECTURE.md) | **生产级架构设计** — 核心组件、消息流、目录结构、设计决策 |
| [DEVELOP.md](./DEVELOP.md) | **开发指南** — 编码规范、模块开发流程、测试规范、调试指南 |
| [SPECIFICATION.md](./SPECIFICATION.md) | **技术规范** — 数据模型、接口契约、配置规范、协议定义 |
| [DEVELOPMENT_PLAN.md](./DEVELOPMENT_PLAN.md) | **开发计划** — 按天分解的可执行计划、准备清单、决策点 |

## 核心设计哲学

1. **拟人即 Prompt** — 拟人能力通过 System Prompt 注入实现，不是代码变换
2. **单点集成** — 所有子系统通过 `SystemPromptBuilder` 和 `AgentHooks` 参与 Agent 循环
3. **门控先于 Agent** — 是否回复、何时回复先于 Agent 调用决定
4. **记忆是检索流水线** — 嵌入模型 + 双路径搜索 + 重排序
5. **事件驱动** — 消息处理通过 EventBus 双层事件解耦
6. **多 Agent 原生** — 单进程多 Agent 实例，配置/记忆/人格隔离，共享 IM 连接 + 路由
7. **Agent 互联显式化** — InterAgentBus + 显式 Link (ACL)，默认不互通
8. **控制面/数据面分离** — Admin API / MCP Server 支撑自动化与商业化
9. **兼容 AstrBot / MaiBot** — 复用存量插件生态，原生 SDK 承载独有能力
10. **简洁优先** — 不引入不必要的外部依赖，单机可运行

## 技术栈

- **语言**: Python 3.12+
- **包管理**: uv
- **记忆后端**: sqlite-vec + SQLite (FTS5)
- **嵌入模型**: fastembed / sentence-transformers / OpenAI Embedding API
- **重排序**: bge-reranker / Cohere Rerank / Jina Rerank
- **LLM**: OpenAI 兼容 API (支持自定义 base_url) / Anthropic / Google / ...
- **平台**: QQ (OneBot) / Telegram / Discord / WeChat / Slack / ... (18+ platforms)
- **插件生态**: AstrBot Star / MaiBot 兼容 + ISAC Native SDK v2
- **控制面**: Admin REST API / ISAC MCP Server / Webhooks
