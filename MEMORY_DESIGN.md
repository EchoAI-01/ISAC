# ISAC 记忆系统设计

> 面向跨会话身份连续性、长期关系、检索增强与无嵌入降级能力的专项设计。
> 本文档补充 ARCHITECTURE.md 3.6 与 SPECIFICATION.md 1.3 / 1.4 / 2.4。

---

## 目录

- [一、设计目标](#一设计目标)
- [二、记忆分层](#二记忆分层)
- [三、身份归一](#三身份归一)
- [四、写入流水线](#四写入流水线)
- [五、检索流水线](#五检索流水线)
- [六、记忆注入](#六记忆注入)
- [七、记忆治理](#七记忆治理)
- [八、存储 Schema 补充](#八存储-schema-补充)
- [九、验收标准](#九验收标准)

---

## 一、设计目标

ISAC 记忆系统要解决四个核心问题：

1. **认得人**：同一用户换平台、换群、换会话后仍可映射到同一 `person_id`。
2. **记得事**：长期保存事件、事实、偏好、关系、行话、Agent 自我经历。
3. **想得起**：支持关键词、向量、图谱、多路召回与重排序。
4. **可治理**：支持删除、修正、冻结、保护、审计和解释召回原因。

记忆必须支持三种运行模式：

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| `keyword` | SQLite FTS5 + 时间衰减 + 重要性排序，不依赖 embedding/rerank | 低成本、本地、离线部署 |
| `hybrid` | FTS5 + Vector + RRF，可选 rerank | 默认推荐 |
| `vector` | 向量检索为主，FTS 兜底 | 语义搜索优先场景 |

---

## 二、记忆分层

| 层级 | 内容 | 生命周期 |
|------|------|----------|
| Working Memory | 当前 turn 临时状态 | 单轮 |
| Short-term Memory | 当前会话最近上下文 | 会话级，可从消息库恢复 |
| Episodic Memory | 发生过的事件、对话摘要 | 长期 |
| Semantic Memory | 稳定事实和知识 | 长期 |
| User Profile Memory | 用户画像、偏好、身份 | 长期 |
| Relationship Memory | Agent 与用户/群的关系 | 长期，缓慢变化 |
| Jargon Memory | 群聊黑话、常用词 | 长期，可衰减 |
| Agent Self Memory | Agent 自己经历过的事 | Agent 私有或共享 |
| Shared World Memory | 多 Agent 共享事实 | 显式共享 |

### 2.1 记忆作用域

```text
agent_private      # 某 Agent 独有
agent_group        # 某几个 Agent 共享
user_global        # 跨 IM 用户画像
conversation       # 单会话
channel_group      # 群聊/频道
organization       # 商业化租户级
system_global      # 全局公共知识
```

---

## 三、身份归一

### 3.1 IdentityResolver

```text
platform + connection_id + platform_user_id
        ↓
PlatformIdentity
        ↓
IdentityResolver
        ↓
global person_id
        ↓
UserProfile / RelationshipMemory / Memory filters
```

```python
@dataclass
class PlatformIdentity:
    """平台身份。"""

    platform: str
    connection_id: str
    platform_user_id: str
    display_name: str = ""
    group_aliases: dict[str, str] = field(default_factory=dict)
    first_seen: int = 0
    last_seen: int = 0


@dataclass
class PersonIdentity:
    """跨平台统一身份。"""

    person_id: str
    aliases: list[str] = field(default_factory=list)
    platform_accounts: list[PlatformIdentity] = field(default_factory=list)
    verified: bool = False
    confidence: float = 0.0
    created_at: int = 0
    updated_at: int = 0
```

### 3.2 合并规则

| 来源 | 是否自动合并 | 说明 |
|------|--------------|------|
| 用户手动绑定 | 是 | 置信度 1.0，verified=true |
| 管理员控制面绑定 | 是 | 置信度 1.0，记录审计 |
| 相同平台 user_id | 是 | 同 connection 下天然一致 |
| 昵称/行为相似 | 否 | 仅作为候选，不自动合并 |
| 插件提供身份映射 | 视权限 | 必须经过权限与审计 |

---

## 四、写入流水线

长期记忆不能每条消息直接写入，应经过提取、判断、去重和整合。

```
Raw Messages
  ↓
Message Buffer
  ↓
Importance Judge
  ↓
Extractor / Summarizer
  ↓
Deduplication
  ↓
MemoryItem Store
  ↓
Profile / Relationship / Jargon Update
  ↓
Background Consolidation
```

### 4.1 MemoryItem

```python
@dataclass
class MemoryItem:
    """统一记忆条目。"""

    id: str
    agent_id: str
    scope: str
    subject_id: str                    # person_id / session_id / group_id / agent_id
    content: str
    memory_type: str                   # episode | fact | profile | relationship | jargon | preference | self
    source_message_ids: list[str] = field(default_factory=list)
    confidence: float = 0.8
    importance: float = 0.5
    created_at: int = 0
    updated_at: int = 0
    expires_at: int | None = None
    frozen: bool = False
    protected: bool = False
    metadata: dict = field(default_factory=dict)
```

### 4.2 写入类型

| 类型 | 示例 | 写入来源 |
|------|------|----------|
| `episode` | “昨天在群里讨论过插件兼容方案” | 会话摘要 |
| `fact` | “用户正在做 ISAC 项目” | 信息抽取 |
| `profile` | “用户偏好简洁中文回答” | 用户画像更新 |
| `relationship` | “与 Agent 熟悉度提升” | 互动统计 |
| `jargon` | “群里把某模块称为施工图” | 高频词挖掘 |
| `preference` | “用户喜欢先看架构再写代码” | 明确偏好 |
| `self` | “Agent 曾被要求补齐文档” | Agent 自我经历 |

### 4.3 去重策略

1. 同一 `subject_id + memory_type` 下相似内容不重复写入。
2. 新事实与旧事实冲突时，不直接覆盖；创建候选修正任务。
3. 高置信度手动记忆优先于自动提取记忆。
4. frozen/protected 记忆不被自动覆盖或删除。

---

## 五、检索流水线

### 5.1 keyword 模式

无 embedding/rerank 时必须可用。

```
Query
  ↓
SQLite FTS5
  ↓
Scope Filter
  ↓
Time / Importance / Relationship Scoring
  ↓
Top-K
```

排序公式：

```text
score =
  fts_score * 0.45
+ recency_score * 0.20
+ importance * 0.20
+ relationship_score * 0.15
```

### 5.2 hybrid 模式

```
Query
  ↓
Query Builder
  ↓
Dense Search + Sparse Search + Graph Search
  ↓
RRF Fusion
  ↓
Optional Reranker
  ↓
Top-K
```

### 5.3 RRF Fusion

```text
rrf_score(d) = Σ 1 / (k + rank_i(d))
```

默认：`k = 60`。

### 5.4 Graph Search

图谱用于补足“人、群、事件、话题”之间的关系。

```python
@dataclass
class MemoryRelation:
    source_id: str
    target_id: str
    relation_type: str          # mentions | likes | belongs_to | discussed | corrected_by
    weight: float = 1.0
    created_at: int = 0
```

---

## 六、记忆注入

记忆注入必须是内部参考，而不是用户可见事实宣告。

### 6.1 注入器

| Injector | 频率 | 内容 |
|----------|------|------|
| PersonProfileInjector | 每轮 | 当前用户画像、关系、偏好 |
| JargonInjector | 每轮 | 当前群聊相关黑话 |
| HeuristicMemoryInjector | 低频 | 当前话题相关长期记忆 |
| MidTermMemoryInjector | 上下文过长时 | 会话压缩摘要 |
| RelationshipInjector | 每轮或低频 | 熟悉度、称呼偏好 |

### 6.2 注入格式

```text
【长期记忆-内部参考】
1. 用户之前提到正在设计 ISAC 的多 Agent 架构。
   来源: episode/2026-07-22, 置信度: 0.92, 召回原因: 当前话题相似
2. 用户偏好先完善文档图纸，再进入代码施工。
   来源: preference/manual, 置信度: 1.00, 召回原因: 用户偏好

这些内容仅作为内部参考，不要逐字复述；如果不确定，应该用自然语气表达。
```

---

## 七、记忆治理

### 7.1 操作

| 操作 | 说明 |
|------|------|
| search | 查询记忆 |
| update | 修改记忆内容或元数据 |
| delete | 删除记忆 |
| freeze | 冻结，不被自动整合覆盖 |
| protect | 临时保护，防止自动删除 |
| restore | 从回收站恢复 |
| correct | 基于用户反馈修正 |
| export | 导出某作用域记忆 |

### 7.2 权限

记忆权限按作用域控制：

```text
Agent 读取权限 = agent_private ∪ explicitly_shared_scopes ∪ user_global(受用户/会话过滤)
Plugin 读取权限 = Manifest 权限 ∩ Agent 策略 ∩ Channel 策略
Control API 权限 = Token scope ∩ audit policy
```

### 7.3 召回解释

每个 `MemoryHit` 应包含：

```python
@dataclass
class MemoryHit:
    id: str
    content: str
    score: float
    hit_type: str
    source: str
    reason: str = ""          # 为什么被召回
    confidence: float = 0.0
    metadata: dict = field(default_factory=dict)
```

---

## 八、存储 Schema 补充

```sql
CREATE TABLE memory_items (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    scope TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    memory_type TEXT NOT NULL,
    content TEXT NOT NULL,
    source_message_ids TEXT DEFAULT '[]',
    confidence REAL DEFAULT 0.8,
    importance REAL DEFAULT 0.5,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    expires_at INTEGER,
    frozen INTEGER DEFAULT 0,
    protected INTEGER DEFAULT 0,
    metadata TEXT DEFAULT '{}'
);

CREATE INDEX idx_memory_agent_scope ON memory_items(agent_id, scope);
CREATE INDEX idx_memory_subject ON memory_items(subject_id);
CREATE INDEX idx_memory_type ON memory_items(memory_type);
CREATE INDEX idx_memory_time ON memory_items(created_at);

CREATE VIRTUAL TABLE memory_items_fts USING fts5(
    content,
    memory_type,
    content=memory_items,
    content_rowid=rowid
);

CREATE TABLE person_identities (
    person_id TEXT PRIMARY KEY,
    aliases TEXT DEFAULT '[]',
    verified INTEGER DEFAULT 0,
    confidence REAL DEFAULT 0.0,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE platform_identities (
    id TEXT PRIMARY KEY,
    person_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    connection_id TEXT NOT NULL,
    platform_user_id TEXT NOT NULL,
    display_name TEXT DEFAULT '',
    group_aliases TEXT DEFAULT '{}',
    first_seen INTEGER,
    last_seen INTEGER,
    UNIQUE(platform, connection_id, platform_user_id)
);
```

---

## 九、验收标准

| 能力 | 验收 |
|------|------|
| keyword 模式 | 禁用 embedding/rerank 后仍可检索并注入记忆 |
| hybrid 模式 | Dense + Sparse + RRF 可返回稳定 Top-K |
| 身份归一 | 同一平台用户在不同会话映射到同一 person_id |
| 手动绑定 | 控制面可绑定多个 PlatformIdentity 到同一 PersonIdentity |
| 写入流水线 | 消息摘要可生成 MemoryItem 并更新画像 |
| 治理能力 | delete/freeze/protect/correct 有接口与审计 |
| 召回解释 | MemoryHit 包含 reason/confidence/source |
| 作用域隔离 | Agent 默认不能读取其他 Agent 私有记忆 |

---

## 十、文档更新记录

| 日期 | 更新人 | 内容 |
|------|--------|------|
| 2026-07-22 | Architect | 新增记忆系统专项设计，补充身份归一、写入流水线、无 embedding 模式、记忆治理与存储 Schema |
