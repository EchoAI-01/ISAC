# ISAC 拟人化运行时设计

> 面向 MaiBot 级“活人感”的会话级运行机制设计。
> 本文档补充 ARCHITECTURE.md 中 Gating / Persona / Prompt 注入未展开的行为层细节。

---

## 目录

- [一、设计目标](#一设计目标)
- [二、核心原则](#二核心原则)
- [三、ConversationRuntime](#三conversationruntime)
- [四、消息触发与调度](#四消息触发与调度)
- [五、Wait / Proactive / Interrupt](#五wait--proactive--interrupt)
- [六、关系、情绪与表达学习](#六关系情绪与表达学习)
- [七、上下文恢复](#七上下文恢复)
- [八、验收标准](#八验收标准)

---

## 一、设计目标

ISAC 的拟人化不是单一 Prompt，而是 **Prompt 表达层 + 会话运行时行为层 + 长期记忆关系层** 的组合。

目标：

1. Bot 不必每条消息都回复，而是根据社交场景选择回复、等待或沉默。
2. 同一 Agent 在不同会话中有独立节奏、关系、上下文和状态。
3. 新消息可打断正在规划的回复，避免“人已经换话题但 Bot 还在回旧话题”。
4. Agent 能主动发起聊天，但主动行为必须有来源、原因和频率边界。
5. 重启后能恢复短期上下文，表现为“刚醒来但还记得之前聊过什么”。
6. 表达风格、黑话、行为偏好通过学习模块渐进更新，不写死在 Prompt 中。

---

## 二、核心原则

| 原则 | 说明 |
|------|------|
| **拟人表达靠 Prompt** | 人格、语气、情绪、关系说明通过 SystemPromptBuilder 注入 |
| **拟人行为靠 Runtime** | 何时回复、等待多久、是否主动、是否打断由 ConversationRuntime 决定 |
| **会话状态独立** | 每个 `agent_id + session_id` 有独立 ConversationRuntime |
| **低频自然学习** | 表达/黑话/行为学习在后台进行，不阻塞回复链路 |
| **主动行为可解释** | 每次主动任务必须有来源、意图、原因和冷却控制 |
| **默认保守** | 群聊默认低频，私聊默认高频，@/明确提及强制触发 |

---

## 三、ConversationRuntime

**核心职责**：管理某个 Agent 在某个会话中的短期状态、消息缓存、触发节奏、等待状态和学习任务。

```python
@dataclass
class ConversationRuntime:
    """某个 Agent 在某个会话中的拟人化运行时。"""

    agent_id: str
    session_id: str
    state: str = "idle"                  # "idle" | "thinking" | "acting" | "waiting" | "stopped"

    message_cache: list[ISACMessage] = field(default_factory=list)
    last_processed_index: int = 0
    internal_turn_queue: asyncio.Queue[str] = field(default_factory=asyncio.Queue)

    last_message_received_at: float = 0.0
    last_external_message_received_at: float | None = None
    last_reply_at: float = 0.0

    pending_wait: WaitState | None = None
    forced_turn: ForcedTurnState | None = None
    relationship_state: RelationshipState | None = None
```

### 3.1 状态机

```
STOPPED
  │ start
  ▼
IDLE
  │ message / proactive / timeout
  ▼
THINKING
  │ tool_call
  ▼
ACTING
  │ wait_tool
  ▼
WAITING
  │ timeout / message / proactive
  ▼
THINKING
  │ final_response / no_reply
  ▼
IDLE
```

### 3.2 Runtime 归属

| 状态 | 归属 | 持久化 |
|------|------|--------|
| `message_cache` | ConversationRuntime | 否，重启后从消息库恢复 |
| `relationship_state` | Memory / Persona | 是 |
| `pending_wait` | ConversationRuntime | 否 |
| `forced_turn` | ConversationRuntime | 否 |
| 表达/黑话学习结果 | Memory / Persona | 是 |

---

## 四、消息触发与调度

消息进入后不应立即调用 LLM，而是先进入 ConversationRuntime 的缓存和调度器。

```
ISACMessage
  ↓
ConversationRuntime.register_message
  ↓
message_cache append
  ↓
TurnScheduler 判断是否满足触发条件
  ↓
等待静默窗口 debounce
  ↓
GatingSystem.evaluate
  ↓
ISACAgentLoop.run
```

### 4.1 触发来源

| 来源 | 说明 | 是否绕过普通频率 |
|------|------|------------------|
| `message` | 普通新消息 | 否 |
| `mention` | @ 或明确提及 Agent | 是 |
| `private` | 私聊消息 | 通常是 |
| `proactive` | 主动任务 | 是 |
| `timeout` | wait 到期 | 是 |
| `handoff` | 其他 Agent 转交 | 是 |

### 4.2 静默窗口

静默窗口用于避免用户连续发送多条消息时 Bot 过早回复。

```jsonc
{
    "gating": {
        "message_debounce_seconds": 1.2,
        "private_message_debounce_seconds": 0.5,
        "group_message_debounce_seconds": 1.5
    }
}
```

### 4.3 回复频率

回复频率由会话类型、关系深度、FocusMode、Agent 配置共同决定。

```text
effective_frequency =
  base_frequency
  × relationship_factor
  × focus_factor
  × temporary_adjustment
```

| 场景 | 默认建议 |
|------|----------|
| 私聊 | 1.0 |
| 群聊普通消息 | 0.15 ~ 0.35 |
| 群聊 @ | 1.0 |
| FocusMode | 1.0 |
| 陌生人 | 适当降低主动性 |
| 熟人/高互动用户 | 适当提高回复概率 |

---

## 五、Wait / Proactive / Interrupt

### 5.1 Wait 工具

`wait` 是拟人化的重要工具，表示 Agent 选择暂时不说话，等待后续消息或超时再继续。

```python
@dataclass
class WaitState:
    tool_call_id: str
    started_at: float
    requested_seconds: float | None
    reason: str = ""
```

规则：

1. 连续 wait 次数必须有限制。
2. wait 状态被新消息、主动任务或超时打断。
3. wait 完成后应向 AgentLoop 回填工具结果，说明实际等待时长。

### 5.2 主动任务

主动任务必须结构化，不允许无来源地随机说话。

```python
@dataclass
class ProactiveTask:
    task_id: str
    agent_id: str
    session_id: str
    source: str                   # "plugin" | "memory" | "schedule" | "agent" | "api"
    intent: str
    reason: str
    priority: str = "normal"
    created_at: float = 0.0
    metadata: dict = field(default_factory=dict)
```

主动任务来源：

- 记忆提醒：用户之前说过某件事需要跟进。
- 插件触发：插件请求 Agent 主动处理一轮聊天。
- 定时任务：生日、日程、每日问候等。
- Agent 互联：其他 Agent 委托。
- 控制面：API/MCP 自动化触发。

### 5.3 Planner Interrupt

当 Agent 正在 thinking，而新消息到来时，ConversationRuntime 可设置 `interrupt_requested`。

规则：

1. 同一轮规划最多打断一次。
2. 连续打断次数有上限。
3. 被打断的响应不发送给用户。
4. 下一轮 Prompt 中应包含“上一轮被新消息打断”的内部提示。

### 5.4 任务进度与中间态

长任务不能只在结束时发送最终回复。`ISACAgentLoop` 在任务状态变化时产生结构化 `ProgressEvent`，由 `ProgressReporter` 决定是否汇报、按 Agent 人设渲染可见文本，并经原 Channel 发送。

```text
AgentLoop / ToolRegistry
  │ ProgressEvent（事实，不含人设文本）
  ▼
ProgressReporter
  ├─ ProgressPolicy：可见性、频控、合并、敏感信息过滤
  ├─ PersonaRenderer：把事实渲染为 Agent 口吻
  └─ ChannelSender：按原会话发送 progress 消息
```

状态流：

```text
PLANNED
  │ 预计耗时超过阈值时可见
  ▼
TOOL_STARTED
  │ 工具返回
  ├───────────────┐
  ▼               ▼
TOOL_FINISHED   TOOL_FAILED
  │ 下一工具 / 最终生成
  ▼
COMPLETED / INTERRUPTED
```

最低保障是每次工具调用完成后产生 `tool_finished` 或 `tool_failed` 事件。工具开始前的“正在查询……”只在预计耗时超过阈值、工具明确声明 `progress_safe=true` 且策略允许时发送；快速连续工具应合并为一条进度，避免刷屏。

人格化遵循“事实与表达分离”：

1. 工具名、阶段、成功/失败和安全摘要由系统提供，Persona 只能改变称呼、语气和措辞，不得改变事实。
2. 默认使用 Persona 模板渲染，不为每条进度额外调用 LLM；仅在显式开启、预算充足且有超时保护时允许轻量模型改写。
3. 进度文本不得包含 reasoning、密钥、访问令牌、原始工具参数、文件完整路径或未清洗的工具结果。
4. `silent`、敏感工具及后台维护任务默认只记录内部事件，不发送用户可见进度。
5. 同一会话默认最短发送间隔为 2 秒；间隔内事件保留最新事实并合并摘要。
6. 进度发送失败只记录日志，不中断工具执行和最终回复。
7. 新消息打断任务时，未发送的进度丢弃；已发送进度可用一条 `interrupted` 收束，但不能发送旧任务的最终结果。
8. 最终回复独立于进度消息；进度消息不得替代完整结果，也不参与行为学习和普通回复频率统计。

平台降级规则：WebChat 等支持结构化事件的平台发送原生 `progress` 帧；普通 IM 以 `ISACMessage` 文本发送，并设置 `metadata.message_kind="progress"`，以便历史、学习、统计和 WebUI 区分进度与正式回复。

### 5.5 陪伴型 Agent 的 SubAgent 委派

情感陪伴主 Agent 的核心职责是保持关系、语气与对话连续性。搜索、文件分析、批量工具和长耗时研究等事务性轨迹不应默认进入主会话上下文，应优先委派给隔离 SubAgent。

建议委派：

- 需要两次及以上工具调用的检索或分析；
- 可能产生大量网页、日志、代码或结构化数据；
- 预计超过交互延迟阈值；
- 需要高风险工具、临时工作区或不同模型能力；
- 任务细节与当前情感对话无关，注入后会稀释人格和关系上下文。

不建议委派：

- 简短澄清、共情、闲聊和人格表达；
- 单次低延迟、低输出工具即可完成的操作；
- 必须依赖细腻关系状态且无法安全摘要的判断。

上下文隔离规则：

1. 主 Agent 生成 `ContextEnvelope`，只包含用户目标、必要事实摘要、输出要求和授权引用。
2. 默认不传 MoodState、RelationshipState、全量聊天历史、人物画像正文或陪伴人格 Prompt。
3. 子 Agent 完成后只回注 `SubAgentResult`；完整工具轨迹保留在 Journal 中。
4. 主 Agent 可在用户追问或结果异常时按 task_id 查询日志和证据，再用自身人格重新组织回答。
5. 子 Agent 结果是内部参考，不得逐字复述内部日志，也不得把错误堆栈直接发给用户。
6. 用户可见进度由主 Agent 的 ProgressReporter 统一发送；子 Agent 不得绕过主 Agent 与用户建立独立陪伴关系。

---

## 六、关系、情绪与表达学习

### 6.1 RelationshipState

```python
@dataclass
class RelationshipState:
    agent_id: str
    person_id: str
    session_id: str
    relationship_depth: float = 0.0
    familiarity: float = 0.0
    trust: float = 0.0
    last_interaction_at: int = 0
    interaction_count: int = 0
```

用途：

- 调整称呼方式。
- 调整回复频率。
- 调整主动行为边界。
- 为 PersonProfileInjector 提供关系描述。

### 6.2 MoodState

```python
@dataclass
class MoodState:
    agent_id: str
    session_id: str
    mood: str = "neutral"
    intensity: float = 0.0
    updated_at: int = 0
```

情绪必须缓慢变化和自然衰减，不应每条消息剧烈波动。

### 6.3 学习模块

| 模块 | 输入 | 输出 | 触发时机 |
|------|------|------|----------|
| ExpressionLearner | 用户与 Agent 的可见文本 | 表达偏好 | 后台低频 |
| JargonLearner | 群聊高频词/上下文 | 行话条目 | 后台低频 |
| BehaviorLearner | Agent 回复与用户反馈 | 行为偏好 | FINAL_RESPONSE 后 |
| ReplyEffectTracker | 回复后续用户反应 | 回复效果评分 | 回复后观察窗口 |

---

## 七、上下文恢复

重启后，ConversationRuntime 应从消息库恢复最近上下文，而不是完全失忆。

```
启动 Agent
  ↓
加载最近 N 条消息
  ↓
过滤 clear marker / 通知消息
  ↓
构造上下文恢复 reference message
  ↓
进入 IDLE，等待新消息
```

恢复提示示例：

```text
这是启动时恢复的历史上下文提醒，不代表当前用户刚刚发来新消息。
距离上次关机前最后一条可恢复聊天记录已经过去 2 小时 15 分钟。
你像短暂离线后重新上线，仍记得上次关机前的聊天内容。
```

规则：

1. 短间隔重启：自然接上话题。
2. 中等间隔：表现为刚上线但记得前情。
3. 长间隔：可以表现出“睡了一会儿/刚回来”。
4. 恢复上下文是内部参考，不应逐字告诉用户。

---

## 八、验收标准

| 能力 | 验收 |
|------|------|
| ConversationRuntime | `agent_id + session_id` 独立维护消息缓存和状态 |
| 静默窗口 | 连续消息不会触发多次即时回复 |
| wait | Agent 可进入等待并由 timeout/message/proactive 恢复 |
| interrupt | 新消息能打断正在运行的规划，旧回复不发送 |
| progress | 每次工具完成后产生结构化事件；Reporter 可按人设汇报，支持频控、合并、脱敏和普通 IM 降级 |
| SubAgent isolation | 事务性任务使用独立上下文；主 Agent 只回注结构化结果，并能按 task_id 查询日志与证据 |
| proactive | 插件/API/记忆可创建主动任务并唤醒会话 |
| context restore | 重启后恢复最近上下文并注入内部参考 |
| relationship | 关系深度影响回复频率和称呼风格 |
| learning | 表达/黑话/行为学习异步执行，不阻塞主链路 |

---

## 九、文档更新记录

| 日期 | 更新人 | 内容 |
|------|--------|------|
| 2026-07-24 | Architect | 新增陪伴型 Agent 的 SubAgent 委派与上下文隔离：委派判断、最小 ContextEnvelope、结果回注和按需日志查询 |
| 2026-07-23 | Architect | 新增任务进度与中间态设计：ProgressEvent、ProgressReporter、Persona 渲染、频控合并、脱敏与平台降级 |
| 2026-07-22 | Architect | 新增拟人化运行时专项设计，补充 ConversationRuntime、wait、proactive、interrupt、上下文恢复与学习模块 |
