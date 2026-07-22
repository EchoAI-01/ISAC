# ISAC 路由与 Agent Mesh 设计

> 面向多 IM、多 Agent 共存、旁听 Agent、Agent 互联与会话转交的专项设计。
> 本文档补充 ARCHITECTURE.md 3.2 / 3.3 与 SPECIFICATION.md 1.7 / 1.8。

---

## 目录

- [一、设计目标](#一设计目标)
- [二、路由模型](#二路由模型)
- [三、旁听与候选 Agent](#三旁听与候选-agent)
- [四、路由优先级](#四路由优先级)
- [五、Agent Mesh](#五agent-mesh)
- [六、ACL 与上下文边界](#六acl-与上下文边界)
- [七、配置示例](#七配置示例)
- [八、验收标准](#八验收标准)

---

## 一、设计目标

ISAC 的路由层必须支持：

1. 一个 IM 连接服务多个 Agent。
2. 一个 Agent 绑定多个 IM 连接。
3. 默认 Agent 无触发词回复。
4. 专用 Agent 通过触发词、命令、绑定或自定义路由进入。
5. 旁听 Agent 可接收消息用于记忆或学习，但不抢默认回复。
6. Agent 间可通过显式 Link 互联、委托、通知或 handoff。
7. 控制面可热更新路由、绑定和 Agent Link。

---

## 二、路由模型

当前 `RoutingDecision.agent_id` 可表达单主 Agent。为支持旁听和候选 Agent，推荐扩展为：

```python
@dataclass
class RoutingDecision:
    """路由结果。"""

    primary_agent_id: str | None
    matched_by: str                         # binding | trigger_word | command | default | hook | drop
    content: str
    observer_agent_ids: list[str] = field(default_factory=list)
    candidate_agent_ids: list[str] = field(default_factory=list)
    reason: str = ""
```

### 2.1 Agent 角色

| 角色 | 是否回复 | 是否记忆 | 说明 |
|------|----------|----------|------|
| Primary Agent | 是 | 是 | 本轮主处理 Agent |
| Observer Agent | 否 | 可选 | 旁听消息，用于记忆/学习/状态更新 |
| Candidate Agent | 否 | 否 | 可被主 Agent handoff/ask 的候选 |
| Command Agent | 视命令 | 视命令 | 只处理管理或命令类消息 |

### 2.2 数据面处理

```
ISACMessage
  ↓
MessageRouter.route
  ↓
RoutingDecision
  ├─ primary_agent_id → AgentManager.handle_message
  ├─ observer_agent_ids → AgentManager.observe_message
  └─ candidate_agent_ids → 写入 AgentContext 可见候选
```

---

## 三、旁听与候选 Agent

### 3.1 旁听 Agent

旁听 Agent 用于解决“一群多 Agent 共存但不抢话”的问题。

典型场景：

- 默认陪伴 Agent 回复所有普通消息。
- 技术 Agent 旁听代码话题，必要时被默认 Agent 调用。
- 记忆 Agent 只记录，不发言。
- 管理 Agent 只处理 `/agent` 等命令。

旁听规则：

1. 旁听 Agent 默认不发送 IM 回复。
2. 旁听 Agent 是否写入记忆由其配置决定。
3. 旁听 Agent 可产生内部事件，但不能绕过 Router 主动发言。
4. 旁听 Agent 被主 Agent `ask_agent` 或 `handoff` 后，才进入主回复链路。

### 3.2 候选 Agent

候选 Agent 不接收消息，只作为本轮上下文中的可用协作者。

Prompt 注入示例：

```text
【可协作 Agent】
- tech_agent：擅长代码、架构、错误排查。可通过 ask_agent 调用。
- memory_agent：擅长检索历史背景。可通过 ask_agent 调用。
```

---

## 四、路由优先级

推荐优先级：

1. **Router Hook**：Native 插件或控制面注入的最高优先级自定义路由。
2. **Command Match**：`/agents`、`/focus`、`/use` 等命令。
3. **Explicit Binding**：platform + group_id/user_id → agent_id。
4. **Trigger Word**：AgentConfig.trigger_words。
5. **Mention Match**：@ 某个 Agent 或明确称呼。
6. **Default Agent**：platform 或 channel 默认 Agent。
7. **Observer Rules**：追加旁听 Agent。
8. **DROP**：无匹配。

```text
route(message)
  ↓
custom hooks
  ↓
command
  ↓
binding
  ↓
trigger_word
  ↓
mention
  ↓
default
  ↓
observers
```

### 4.1 触发词剥离

触发词只用于路由，不应污染 Agent 看到的用户原意。

```text
原消息：/tech 帮我看这个报错
路由：tech_agent
进入 Agent 的 content：帮我看这个报错
metadata.original_content：/tech 帮我看这个报错
```

---

## 五、Agent Mesh

### 5.1 消息类型

```python
@dataclass
class InterAgentMessage:
    from_agent: str
    to_agent: str
    type: str                         # request | response | notify | handoff | memory_query
    content: str
    context: dict = field(default_factory=dict)
    trace_id: str = ""
```

| 类型 | 说明 | 是否期待响应 |
|------|------|--------------|
| `request` | 提问或协助请求 | 是 |
| `notify` | 单向通知 | 否 |
| `handoff` | 会话转交 | 可选 |
| `memory_query` | 请求另一 Agent 可共享记忆 | 是 |
| `response` | 响应 request | 否 |

### 5.2 内置工具

| 工具 | 说明 |
|------|------|
| `ask_agent` | 向目标 Agent 提问，返回结果给当前 Agent |
| `notify_agent` | 通知目标 Agent，不等待回复 |
| `handoff_conversation` | 将当前会话转交给目标 Agent |
| `list_available_agents` | 列出当前 Agent 可协作对象 |

### 5.3 handoff 流程

```
Agent A 判断自己不适合继续
  ↓
handoff_conversation(target=B, reason, summary)
  ↓
InterAgentBus 检查 ACL
  ↓
Router 临时设置 primary_agent_id=B
  ↓
Agent B 接收 handoff 上下文
  ↓
Agent B 回复用户
```

---

## 六、ACL 与上下文边界

### 6.1 Link 权限

```python
@dataclass
class InterAgentLink:
    from_agent: str
    to_agent: str
    direction: str = "both"
    enabled: bool = True
    permissions: list[str] = field(default_factory=list)  # ask | notify | handoff | memory_query
    visible_memory_scopes: list[str] = field(default_factory=list)
    max_context_messages: int = 20
```

### 6.2 权限规则

1. 默认无 Link，Agent 之间不能互通。
2. `direction=oneway` 时只允许 from → to。
3. `handoff` 必须显式声明。
4. `memory_query` 只能访问 `visible_memory_scopes`。
5. Agent 间消息必须写入审计日志。
6. Agent 间上下文默认只传摘要，不传完整原始消息。

### 6.3 上下文裁剪

传给目标 Agent 的上下文应包含：

- 当前用户问题；
- 会话摘要；
- 最近 N 条必要消息；
- 主 Agent 的请求说明；
- 权限允许的记忆摘要。

不得默认传递：

- 全量历史消息；
- 其他 Agent 私有记忆；
- 不在 visible scopes 内的用户画像；
- 原始插件敏感输出。

---

## 七、配置示例

### 7.1 routing.jsonc

```jsonc
{
    "bindings": [
        {"platform": "qq", "group_id": "123456", "agent_id": "mai_default"}
    ],
    "default_agents": {
        "qq": "mai_default",
        "webchat": "mai_default"
    },
    "observers": [
        {
            "platform": "qq",
            "group_id": "123456",
            "agent_ids": ["tech_agent"],
            "mode": "memory_only",
            "keywords": ["代码", "报错", "部署", "架构"]
        }
    ]
}
```

### 7.2 links.jsonc

```jsonc
{
    "links": [
        {
            "from_agent": "mai_default",
            "to_agent": "tech_agent",
            "direction": "oneway",
            "enabled": true,
            "permissions": ["ask", "handoff"],
            "visible_memory_scopes": ["shared", "user_global"],
            "max_context_messages": 12
        },
        {
            "from_agent": "tech_agent",
            "to_agent": "mai_default",
            "direction": "oneway",
            "enabled": true,
            "permissions": ["notify"],
            "visible_memory_scopes": []
        }
    ]
}
```

---

## 八、验收标准

| 能力 | 验收 |
|------|------|
| 默认 Agent | 无触发词消息可进入 platform 默认 Agent |
| 触发词 Agent | 触发词命中后进入指定 Agent，且内容被剥离 |
| 旁听 Agent | Observer 接收消息但不发送 IM 回复 |
| 候选 Agent | 主 Agent Prompt 能看到可协作 Agent 列表 |
| ask_agent | 受 ACL 约束，能得到目标 Agent 返回 |
| handoff | 主回复权可转交目标 Agent |
| memory_query | 只能访问 visible_memory_scopes |
| 审计 | 每条 Agent 间消息有 trace_id 与审计记录 |

---

## 九、文档更新记录

| 日期 | 更新人 | 内容 |
|------|--------|------|
| 2026-07-22 | Architect | 新增路由与 Agent Mesh 专项设计，补充 primary/observer/candidate Agent、路由优先级、handoff 与 ACL 边界 |
