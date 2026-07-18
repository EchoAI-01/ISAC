# ISAC 开发路线图

> 实施计划、里程碑、优先级定义
> 
> **工时说明**: 预估工时为纯开发时间，实际交付需乘以 **1.3~1.5** 的缓冲系数
> （含调试、联调、Code Review、文档更新）

---

## 里程碑总览

```
Phase 1 (Foundation)          Phase 2 (Core)              Phase 3 (Ecosystem)         Phase 4 (Polish)
├─ 项目脚手架                  ├─ Agent Loop               ├─ 更多平台适配器            ├─ WebUI
├─ Channel 抽象                ├─ Prompt Builder           ├─ AstrBot 插件兼容 (P0/P1) ├─ 监控告警
├─ Gateway + EventBus         ├─ Gating System            ├─ 原生插件 SDK             ├─ 性能优化
├─ Provider 抽象               ├─ Memory Pipeline          ├─ MCP 集成                ├─ 部署工具
├─ 基础测试框架                ├─ 内置社交工具              ├─ Skills 系统              ├─ 文档完善
└─ CI/CD                       ├─ 人格配置                  ├─ 子 Agent 委派            └─ 发布 v1.0
                               └─ 嵌入 + 重排序
```

---

## Phase 1: Foundation (基础框架)

> 目标：可运行的最小框架，能接收消息并回复

| # | 任务 | 优先级 | 预估 | 产出 |
|---|------|--------|------|------|
| 1.1 | 项目脚手架 (pyproject.toml, ruff, pytest) | P0 | 0.5d | 可运行的 `uv sync && pytest` |
| 1.2 | `core/types.py` + `core/events.py` 核心类型 | P0 | 0.5d | 数据模型、事件枚举 |
| 1.3 | `channel/base.py` PlatformAdapter ABC | P0 | 1d | 适配器接口 |
| 1.4 | `channel/model.py` ISACMessage | P0 | 0.5d | 统一消息模型 |
| 1.5 | `channel/adapters/onebot/` OneBot 适配器 | P0 | 2d | QQ 连接 (第一个平台) |
| 1.6 | `gateway/event_bus.py` EventBus | P0 | 1.5d | 双层事件总线 |
| 1.7 | `gateway/session.py` SessionManager | P0 | 1.5d | SQLite 会话管理 |
| 1.8 | `provider/base.py` + `provider/llm/openai.py` | P0 | 1d | LLM 调用 |
| 1.9 | `utils/logger.py` structlog | P0 | 0.5d | 结构化日志 |
| 1.10 | `main.py` 应用入口 | P0 | 1d | 可启动的最小系统 |
| 1.11 | 基础测试 + CI (GitHub Actions) | P0 | 1d | pytest + ruff CI |

**Phase 1 交付标准**: `uv run python -m isac.main` 启动后，通过 QQ 发消息，Bot 能用 OpenAI 回复。

---

## Phase 2: Core (核心能力)

> 目标：实现完整的 Agent Loop + Memory + Gating

| # | 任务 | 优先级 | 预估 | 产出 |
|---|------|--------|------|------|
| 2.1 | `agent/loop.py` ISACAgentLoop | P0 | 2d | Agent 循环 (带 hooks) |
| 2.2 | `agent/hooks.py` AgentHooks | P0 | 1d | 钩子注册/触发 |
| 2.3 | `agent/prompt_builder.py` SystemPromptBuilder | P0 | 1.5d | Prompt 组装器 |
| 2.4 | `agent/injector.py` PromptInjector 基类 | P0 | 0.5d | 注入器协议 |
| 2.5 | `gating/` 门控系统 (reply_necessity + turn + backoff) | P0 | 2d | 完整的门控决策 |
| 2.6 | `memory/pipeline.py` MemoryRetrievalPipeline | P0 | 2d | 嵌入 + 搜索 + 重排序 |
| 2.7 | `memory/storage/` 存储引擎 | P0 | 2d | sqlite-vec + SQLite |
| 2.8 | `memory/embedder.py` EmbeddingManager | P0 | 1d | fastembed + API 适配 |
| 2.9 | `memory/injector/heuristic.py` | P0 | 1.5d | 启发式记忆注入 |
| 2.10 | `memory/injector/person_profile.py` | P0 | 1d | 人物画像注入 |
| 2.11 | `memory/injector/mid_term.py` | P0 | 1.5d | 中期记忆 |
| 2.12 | `memory/injector/jargon.py` | P0 | 1d | 行话匹配 |
| 2.13 | `agent/tools/social/` 社交工具 (8个) | P0 | 2d | send_emoji, query_memory 等 |
| 2.14 | `persona/` 人格配置 (drift + style + mood) | P0 | 1.5d | 注意力漂移 + 表达风格 |
| 2.15 | 核心集成测试 | P0 | 1.5d | 完整消息流测试 |

**Phase 2 交付标准**: Bot 能够：
- 记住用户（跨会话识别）
- 拟人化回复（注意力漂移、风格一致）
- 在群里知道什么时候该说话
- 主动发起对话（空窗补偿）
- 使用社交工具（emoji、图片）

---

## Phase 3: Ecosystem (生态建设)

> 目标：插件兼容 + 多平台 + 扩展能力

| # | 任务 | 优先级 | 预估 | 产出 |
|---|------|--------|------|------|
| 3.1 | `plugin/compatibility/star.py` AstrBot Star 基类 | P0 | 1d | Star 兼容 |
| 3.2 | `plugin/compatibility/events.py` EventType 映射 | P0 | 1d | 事件映射 |
| 3.3 | `plugin/compatibility/context.py` Context API | P0 | 2d | Context 模拟 |
| 3.4 | `plugin/compatibility/tools.py` FunctionTool 桥接 | P0 | 1d | 工具桥接 |
| 3.5 | `plugin/compatibility/sandbox.py` Import 拦截 | P1 | 1.5d | 沙箱 |
| 3.6 | `plugin/runtime/` 插件运行时 | P0 | 2d | 加载/依赖/热重载 |
| 3.7 | `plugin/native/` ISAC 原生 SDK | P1 | 2d | 原生插件 API |
| 3.8 | `channel/adapters/` 更多平台 (telegram/discord/wechat) | P1 | 各 2d | 每平台一个适配器 |
| 3.9 | `agent/tools/mcp/` MCP 工具集成 | P1 | 2d | MCP Client |
| 3.10 | `agent/tools/utility/` 实用工具 | P1 | 2d | bash, read_file, web_search |
| 3.11 | `agent/tools/task.py` 子 Agent 委派 | P1 | 2d | 子 Agent 编排 |
| 3.12 | `provider/llm/` 更多 LLM 提供商 | P1 | 各 1d | Anthropic, Google, etc. |

**Phase 3 交付标准**: 
- AstrBot 插件（至少 5 个常见插件）无需修改直接运行
- 支持 QQ + Telegram + Discord 三个平台
- 支持 MCP 工具

---

## Phase 4: Polish (打磨优化)

> 目标：生产可用

| # | 任务 | 优先级 | 预估 | 产出 |
|---|------|--------|------|------|
| 4.1 | WebUI 管理面板 (FastAPI + Vue) | P1 | 5d | 配置管理、监控 |
| 4.2 | 监控告警 (Prometheus / 简单 Webhook) | P2 | 2d | 关键指标监控 |
| 4.3 | 性能优化 (并发、缓存、延迟) | P1 | 3d | 性能提升 |
| 4.4 | 部署工具 (Docker, docker-compose, 脚本) | P0 | 1d | 一键部署 |
| 4.5 | 文档完善 (使用文档、API 文档、部署文档) | P1 | 3d | 完整文档 |
| 4.6 | 数据迁移工具 | P2 | 1d | AstrBot → ISAC 迁移 |
| 4.7 | 数据备份工具 | P2 | 1d | 记忆导出/导入/备份 |
| 4.8 | 发布 v1.0 | - | - | 正式版本 |

---

## 任务依赖关系

```
Phase 1 (必须按顺序):
  1.1 → 1.2 → 1.3 → 1.4 → 1.5 → 1.6 → 1.7 → 1.8 → 1.9 → 1.10 → 1.11

Phase 2 (核心模块，部分可并行):
  2.1 (AgentLoop) 依赖: 2.2 (Hooks), 2.3 (PromptBuilder), 2.4 (Injector)
  2.6 (MemoryPipeline) 依赖: 2.7 (Storage), 2.8 (Embedder)
  2.9-2.12 (MemoryInjectors) 依赖: 2.6 (Pipeline), 2.3 (PromptBuilder)
  2.13 (SocialTools) 依赖: 2.1 (AgentLoop)
  2.14 (Persona) 依赖: 2.3 (PromptBuilder)

Phase 3 (生态，可并行):
  3.1-3.5 (AstrBot兼容) 依赖: 2.1 (AgentLoop), 2.3 (PromptBuilder)
  3.6 (PluginRuntime) 依赖: 3.1-3.2
  3.7 (NativeSDK) 依赖: 2.1, 2.3
  3.8 (PlatformAdapters) 依赖: 1.3 (Channel Base)
  3.9 (MCP) 依赖: 2.1 (AgentLoop)

Phase 4 (打磨):
  4.1 (WebUI) 依赖: Phase 2 完成
  4.4 (Docker) 依赖: Phase 2 完成
  4.5 (Docs) 依赖: Phase 3 完成
```

---

## 关键路径 (Critical Path)

```
1.2 → 1.3 → 1.4 → 1.5 → 1.6 → 1.7 → 1.8 → 1.10
      ↓
2.2 → 2.3 → 2.4 → 2.1
                  ↓
2.6 → 2.7 → 2.8 → 2.9 → 2.10 → 2.11 → 2.12
      ↓
2.13 → 2.14 → 2.15
      ↓
3.1 → 3.2 → 3.3 → 3.6
      ↓
4.4 → 4.5
```

---

## 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| AstrBot 插件 API 变动 | 兼容层失效 | 跟踪 AstrBot 版本，做版本适配 |
| 嵌入模型性能差 | 记忆检索不准确 | 支持多模型切换，提供降级到纯稀疏搜索 |
| LLM 成本过高 | Token 消耗大 | 门控过滤 + Prompt 注入频率控制 + 压缩策略 |
| 多平台消息模型不一致 | 适配器复杂 | 统一的 ISACMessage + 平台特定 metadata |
| 插件生态迁移困难 | 用户流失 | 提供迁移工具 + 详细迁移指南 |
