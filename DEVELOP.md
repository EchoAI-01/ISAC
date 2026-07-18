# ISAC 开发指南

> 面向开发者的编码规范、模块开发流程、测试规范

---

## 目录

- [一、项目结构规范](#一项目结构规范)
- [二、编码规范](#二编码规范)
- [三、模块开发流程](#三模块开发流程)
- [四、核心模块开发规范](#四核心模块开发规范)
- [五、测试规范](#五测试规范)
- [六、Git 规范](#六git-规范)
- [七、调试指南](#七调试指南)

---

## 一、项目结构规范

### 1.1 目录职责

每个目录的职责必须是**单一且明确**的。以下是各目录的职责边界：

| 目录 | 职责 | 禁止做 |
|------|------|--------|
| `channel/` | 平台适配：消息收发、平台协议 | 不处理 Agent 逻辑 |
| `gateway/` | 消息路由：会话管理、事件总线、用户映射 | 不处理 LLM 调用 |
| `gating/` | 门控决策：是否回复、何时回复 | 不处理记忆存储 |
| `agent/` | Agent 循环：LLM 调用、工具执行、Prompt 组装 | 不直接操作记忆存储 |
| `memory/` | 记忆管理：存储、检索、注入策略 | 不直接调用 LLM (除非通过注入策略) |
| `persona/` | 人格配置：风格配置、情绪状态 | 不处理 Agent 逻辑 |
| `plugin/` | 插件兼容：AstrBot 桥接、原生 SDK | 不处理核心业务逻辑 |
| `provider/` | 模型适配：LLM/Embedding/Reranker | 不处理业务逻辑 |
| `utils/` | 公共工具：日志、配置、辅助函数 | 不包含业务逻辑 |

### 1.2 导入规则

**关键原则**: 区分"模块导入依赖"和"运行时实例注入"。

- **模块导入依赖** (`import` 关系): 必须单向、无环
- **运行时实例注入**: 通过 `main.py` 组装时注入实例，不通过 import

#### 模块导入依赖关系 (单向)

```
utils
  ↑
provider (依赖 utils)
  ↑
memory (依赖 utils, provider)
  ↑
persona (依赖 utils)
  ↑
agent (依赖 utils, provider, memory, persona)
  ↑
gating (依赖 utils)
  ↑
gateway (依赖 utils, gating)
  ↑
channel (依赖 utils, gateway)
  ↑
plugin (依赖 utils, agent)
  ↑
main.py (依赖所有，负责组装)
```

**规则**:
- `utils/` 被所有模块依赖，不依赖任何业务模块
- `provider/` 只依赖 `utils/`
- `memory/` 只依赖 `utils/` 和 `provider/` (嵌入模型)
- `agent/` 依赖 `utils/`、`provider/`、`memory/` (通过注入器实例)、`persona/`
- `gating/` 只依赖 `utils/` (不依赖 agent)
- `gateway/` 依赖 `utils/`、`gating/` (不直接调 agent，通过依赖注入)
- `channel/` 依赖 `utils/`、`gateway/`
- `plugin/` 依赖 `utils/`、`agent/` (通过 hooks 注册)
- `main.py` 依赖所有模块，负责组装和依赖注入

**禁止的导入**:
- `channel/` 导入 `agent/`、`memory/`、`gating/`、`plugin/`
- `gating/` 导入 `agent/`、`channel/`、`plugin/`
- `memory/` 导入 `agent/`、`gating/`、`channel/`
- `gateway/` 导入 `agent/`、`channel/` (通过注入调用)
- `provider/` 导入任何业务模块
- `utils/` 导入任何业务模块

#### 运行时依赖注入

```python
# main.py 组装时注入
# Gateway 不 import agent，而是通过注入获得引用

class Gateway:
    def __init__(self, gating: GatingSystem):
        self.gating = gating
        self._agent_handler: Callable | None = None  # 由 main.py 注入

    def set_agent_handler(self, handler: Callable):
        """由 main.py 注入 Agent 处理函数"""
        self._agent_handler = handler

    async def handle_message(self, message: ISACMessage):
        decision = await self.gating.evaluate(...)
        if decision.should_trigger:
            await self._agent_handler(message)  # 调用注入的 handler
```

---

## 二、编码规范

### 2.1 Python 代码规范

基于 [PEP 8](https://peps.python.org/pep-0008/) 并增加以下约定：

**基础设置** (pyproject.toml):
```toml
[tool.ruff]
target-version = "py312"
line-length = 120
select = [
    "E",   # pycodestyle errors
    "W",   # pycodestyle warnings
    "F",   # pyflakes
    "I",   # isort
    "UP",  # pyupgrade
    "ASYNC",  # async-related
    "C90", # mccabe complexity
]
```

**导入顺序** (强制):

```python
# 1. 标准库 (from ... import ... 在前，import ... 在后)
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any
import asyncio
import json

# 2. 第三方库 (from ... import ... 在前，import ... 在后)
from pydantic import BaseModel
from structlog import get_logger
import numpy as np

# 3. 本地模块 (isac.* 绝对导入，同目录用相对导入)
from isac.core.types import Session
from isac.utils.logger import get_logger

from .models import LocalModel
```

**类型注解**:
- 所有公共函数/方法必须有完整的类型注解
- 复杂函数 (> 10 行) 必须有类型注解
- 使用 `from __future__ import annotations` 避免前向引用问题

**异步规范**:
- 所有 I/O 操作必须使用 `async/await`
- 阻塞操作 (文件 I/O、数据库查询) 用 `asyncio.to_thread()` 或异步库
- 不要在 async 函数中调用 `time.sleep()`，使用 `await asyncio.sleep()`

**日志规范**:
```python
from isac.utils.logger import get_logger

logger = get_logger(__name__)

# 带上下文信息的结构化日志
logger.info(
    "消息处理完成",
    session_id=session_id,
    user_id=user_id,
    latency_ms=latency_ms,
)

# 错误日志必须带异常信息
logger.error("LLM 调用失败", error=str(exc), exc_info=True)
```

### 2.2 命名规范

| 类型 | 规则 | 示例 |
|------|------|------|
| 模块/文件 | snake_case | `reply_necessity.py` |
| 类 | PascalCase | `ISACAgentLoop` |
| 函数/方法 | snake_case | `build_injection_message` |
| 常量 | UPPER_SNAKE_CASE | `REPLY_NECESSITY_THRESHOLD` |
| 私有属性/方法 | `_` 前缀 | `_check_frequency` |
| 异步方法 | `async` + snake_case | `async def search_memory` |

### 2.3 注释规范

- **模块级**: 每个 `.py` 文件开头必须有模块 docstring
- **类级**: 公共类必须有 docstring，说明职责和使用方式
- **函数级**: 复杂函数必须有 docstring，说明参数/返回值/副作用
- **行内注释**: 解释"为什么"而不是"是什么"

```python
"""Maisaka 启发式长期记忆自然拉起服务。

根据当前聊天流印象自然拉起长期记忆，注入到 Planner 上下文中。
"""

class HeuristicMemoryInjector:
    """根据当前聊天流印象自然拉起长期记忆。

    每 3 分钟最多触发一次，且需要至少 60 条新消息。
    使用 LLM 生成当前聊天印象，再搜索相关记忆。

    Attributes:
        max_frequency_seconds: 最小触发间隔（秒）
        max_new_messages: 最小新消息数
    """

    async def build_injection_message(self, session_id: str) -> str:
        """构造给 Planner/Replyer 共享的一次性启发式记忆参考。

        Args:
            session_id: 聊天流 ID

        Returns:
            注入文本，空字符串表示无需注入。
        """
```

---

## 三、模块开发流程

### 3.1 新增模块的标准流程

```
需求确认 → 接口设计 → 实现 → 测试 → 集成 → 文档更新
     ↓         ↓        ↓       ↓       ↓        ↓
   理解需求    定义      编写    单测    集成到   更新
   边界       Protocol   代码    集成测  Agent   README
```

### 3.2 新增一个 PromptInjector 的步骤

**注入器归属规则**（选择目录的依据）:

| 注入器数据源 | 放置目录 | 示例 |
|-------------|---------|------|
| 与 Agent 自身行为相关 | `agent/injectors/` | 人格、技能、工具说明 |
| 与记忆数据相关 | `memory/injector/` | 启发式记忆、画像、行话、中期记忆 |
| 与人格配置相关 | `persona/injectors/` | 动态人格配置注入（如有） |

```python
# 1. 根据数据源选择目录
#    例如: isac/agent/injectors/my_injector.py (Agent 自身相关)
#    或: isac/memory/injector/my_memory.py (记忆数据相关)

from isac.agent.injector import PromptInjector
from isac.agent.prompt_builder import InjectionContext


class MyInjector(PromptInjector):
    """我的自定义注入器。"""

    @property
    def key(self) -> str:
        return "my_injector"

    @property
    def priority(self) -> int:
        return 50  # 数字越大，越先注入

    @property
    def max_frequency_seconds(self) -> float:
        return 60.0  # 每分钟最多一次

    @property
    def tokens_estimate(self) -> int:
        return 200

    async def build(self, context: InjectionContext) -> str:
        if not self._should_inject(context):
            return ""
        return "我的注入内容"

# 2. 注册到 PromptBuilder
#    在 isac/agent/prompt_builder.py 的 _register_defaults() 中添加
prompt_builder.register(MyInjector())

# 3. 写测试
#    tests/unit/test_my_injector.py
async def test_my_injector():
    injector = MyInjector()
    context = make_test_context()
    result = await injector.build(context)
    assert "我的注入内容" in result
```

### 3.3 新增一个 Channel Adapter 的步骤

```python
# 1. 在 isac/channel/adapters/ 下创建目录
#    isac/channel/adapters/my_platform/

# 2. 实现 PlatformAdapter
#    isac/channel/adapters/my_platform/adapter.py

from isac.channel.base import PlatformAdapter
from isac.channel.model import ISACMessage


class MyPlatformAdapter(PlatformAdapter):
    """MyPlatform 平台适配器。"""

    @property
    def platform_name(self) -> str:
        return "my_platform"

    async def start(self):
        """启动平台连接"""
        ...

    async def stop(self):
        """停止平台连接"""
        ...

    async def send(self, message: ISACMessage) -> bool:
        """发送消息"""
        ...

    async def on_message(self, message: ISACMessage):
        """接收到消息时调用（由框架注册）"""
        ...

# 3. 在 isac/channel/registry.py 注册
```

### 3.4 新增一个内置工具的步骤

```python
# 1. 在 isac/agent/tools/social/ 或 utility/ 下创建文件
#    isac/agent/tools/social/my_tool.py

from isac.agent.tools.base import Tool, ToolContext, ToolResult

class MyTool(Tool):
    """我的工具。"""

    @property
    def name(self) -> str:
        return "my_tool"

    @property
    def description(self) -> str:
        return "做某件事"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "目标"},
            },
            "required": ["target"],
        }

    async def execute(self, context: ToolContext) -> ToolResult:
        result = await self._do_something(context.args["target"])
        return ToolResult(content=result)
```

---

## 四、核心模块开发规范

### 4.1 PromptInjector 开发规范

**必须遵守的规则**:

1. `build()` 方法必须是**纯函数** — 不产生副作用，不修改 context
2. 返回空字符串 `""` 表示不注入，不是 `None`
3. 所有 I/O 操作 (数据库查询、LLM 调用) 必须异步
4. 每个 Injector 必须实现 `tokens_estimate`，用于预算管理
5. 禁止在 `build()` 中抛异常，异常必须捕获并返回 `""`

```python
class GoodInjector(PromptInjector):
    async def build(self, context: InjectionContext) -> str:
        try:
            data = await self._fetch_data(context)
            if not data:
                return ""
            return self._format(data)
        except Exception as exc:
            logger.warning("Injector 失败，跳过", error=str(exc))
            return ""  # 失败时返回空，不影响其他 Injector
```

### 4.2 Agent Hook 开发规范

**Hook 函数签名**:

```python
from typing import Any

# pre_llm: 可以修改 messages
async def my_pre_llm_hook(messages: list[Message], context: AgentContext) -> list[Message]:
    # 修改或追加消息
    messages.append(new_message)
    return messages  # 必须返回 messages

# pre_tool: 返回 False 阻止工具执行
async def my_pre_tool_hook(tool_call: ToolCall, context: AgentContext) -> bool:
    if not self._check_permission(tool_call):
        return False  # 阻止执行
    return True  # 允许执行

# post_tool: 触发副作用
async def my_post_tool_hook(tool_call: ToolCall, result: ToolResult, context: AgentContext) -> None:
    await self._update_memory(tool_call, result)

# final_response: 记录/学习
async def my_final_hook(response: LLMResponse, context: AgentContext) -> None:
    await self._learn_from_response(response, context)
```

**Hook 注册规范**:
- 每个 Hook 必须有明确的 priority，同优先级按注册顺序执行
- Hook 中禁止直接调用 LLM（避免无限递归）
- Hook 执行失败必须不影响主流程（try-except 包裹）

### 4.3 Memory Injector 开发规范

**检索策略 Injector 必须**:

1. 实现频率控制（`max_frequency_seconds`）
2. 失败时优雅降级（返回空字符串，不阻塞 Agent）
3. 使用 `MemoryRetrievalPipeline` 进行检索，不要直接查 VectorStore
4. 格式化输出时明确标注"内部参考"

```python
class MemoryInjector(PromptInjector):
    """记忆检索注入器基类。"""

    def __init__(self, pipeline: MemoryRetrievalPipeline):
        self.pipeline = pipeline

    async def search_and_format(self, query: str, top_k: int = 3) -> str:
        """通用检索 + 格式化流程"""
        hits = await self.pipeline.search(query, top_k=top_k)
        if not hits:
            return ""
        return self._format_reference(hits)

    @staticmethod
    def _format_reference(hits: list[MemoryHit]) -> str:
        """格式化为内部参考文本"""
        lines = ["【启发式记忆-内部参考】"]
        for i, hit in enumerate(hits, 1):
            lines.append(f"{i}. {hit.content[:150]}")
        lines.append("(仅作为推理参考，不要向用户逐字复述)")
        return "\n".join(lines)
```

---

## 五、测试规范

### 5.1 测试目录结构

```
tests/
├── conftest.py              # 全局 fixtures
├── unit/                    # 单元测试 (测试单个模块)
│   ├── test_prompt_builder.py
│   ├── test_agent_loop.py
│   ├── test_gating.py
│   ├── test_memory_pipeline.py
│   ├── test_injectors.py
│   └── ...
├── integration/             # 集成测试 (测试模块间协作)
│   ├── test_full_flow.py    # 完整消息流测试
│   ├── test_plugin_compat.py # 插件兼容测试
│   └── test_memory_injection.py
└── fixtures/                # 测试数据
    ├── __init__.py
    ├── messages.py          # 各类测试消息
    ├── profiles.py          # 测试用 UserProfile
    ├── responses.py         # Mock LLM 响应
    └── memories.py          # 测试用记忆数据
```

### 5.2 单元测试规范

**每个核心模块必须有对应的单元测试**:

```python
# tests/unit/test_gating.py

import pytest
from isac.gating.system import GatingSystem
from isac.gating.types import GatingContext, GateDecision


class TestGatingSystem:
    """门控系统单元测试。"""

    @pytest.fixture
    def gating(self):
        return GatingSystem(
            reply_necessity=MockReplyNecessity(),
            idle_backoff=MockIdleBackoff(),
        )

    @pytest.mark.asyncio
    async def test_force_trigger_on_at(self, gating):
        """@bot 时必须触发"""
        context = GatingContext(has_at=True, is_private=False)
        decision = await gating.evaluate([], context)
        assert decision == GateDecision.TRIGGER

    @pytest.mark.asyncio
    async def test_wait_when_low_score(self, gating):
        """低评分时等待"""
        context = GatingContext(has_at=False, is_private=True)
        decision = await gating.evaluate([], context)
        assert decision == GateDecision.WAIT
```

**测试覆盖率要求**:
- 核心模块 (`agent/`, `memory/`, `gating/`): ≥ 80%
- 适配器模块 (`channel/`, `provider/`): ≥ 60%
- 插件兼容层 (`plugin/`): ≥ 70%

### 5.3 集成测试规范

**完整消息流测试** (最重要):

```python
# tests/integration/test_full_flow.py

@pytest.mark.asyncio
async def test_full_message_flow(mock_llm, mock_channel, mock_memory):
    """测试从消息接收到回复发送的完整流程"""
    # 1. 模拟消息到达
    message = make_isac_message(content="@ISAC 你好")

    # 2. 经过 Gateway 处理
    await gateway.handle_message(message)

    # 3. 经过 Gating
    decision = await gating.evaluate([message], gating_context)
    assert decision == GateDecision.TRIGGER

    # 4. 组装 System Prompt
    prompt = await prompt_builder.build(injection_context)
    assert "你是 ISAC" in prompt

    # 5. Agent Loop 执行
    result = await agent_loop.run(messages, agent_context)
    assert result.content

    # 6. 记忆更新 (异步)
    await asyncio.sleep(0.1)
    memory_count = await memory.count_episodes(user_id)
    assert memory_count > 0
```

### 5.2 测试 Fixtures 内容

**messages.py** — 各类测试消息:
```python
# 不同类型的测试消息
@dataclass
class TestMessages:
    at_bot: ISACMessage          # @bot 的消息
    private_chat: ISACMessage    # 私聊消息
    group_chat: ISACMessage      # 群聊消息
    short_reaction: ISACMessage  # 短反应 ("哈哈", "好")
    long_text: ISACMessage       # 长文本 (>120字)
    with_image: ISACMessage      # 含图片
    reply_to: ISACMessage        # 回复某条消息
```

**profiles.py** — 测试用 UserProfile:
```python
@dataclass
class TestProfiles:
    new_user: UserProfile        # 新用户 (interaction_count=0)
    acquaintance: UserProfile    # 熟人 (depth=0.3)
    friend: UserProfile          # 朋友 (depth=0.6)
    close_friend: UserProfile    # 密友 (depth=0.9)
```

**responses.py** — Mock LLM 响应:
```python
@dataclass
class MockResponses:
    plain_text: LLMResponse      # 纯文本回复
    with_tool_call: LLMResponse  # 带工具调用
    with_reasoning: LLMResponse  # 带推理内容
    stream_chunks: list[LLMChunk]  # 流式 chunks
```

**memories.py** — 测试用记忆数据:
```python
@dataclass
class TestMemories:
    recent_episode: MemoryHit    # 最近的记忆
    old_episode: MemoryHit       # 旧记忆
    important: MemoryHit         # 高重要性记忆
    from_group: MemoryHit        # 来自群聊的记忆
```

---

## 六、日志规范

### 6.1 日志格式

**开发环境**: 彩色控制台输出，便于阅读
**生产环境**: JSON 格式，便于 ELK/Loki 采集

```python
# 日志字段
{
    "timestamp": "2026-07-18T10:30:00.000Z",
    "level": "info",
    "logger": "isac.agent.loop",
    "event": "LLM 调用",
    "session_id": "sess_001",
    "user_id": "user_001",
    "latency_ms": 1200,
    "tokens": 1500,
}
```

### 6.2 日志级别

| 级别 | 用途 | 示例 |
|------|------|------|
| `DEBUG` | 详细调试信息 | 每个 Injector 的 build() 输入输出 |
| `INFO` | 关键流程节点 | 消息到达、Agent 启动、工具执行 |
| `WARNING` | 可恢复的错误 | 记忆检索失败、Injector 超时 |
| `ERROR` | 严重错误 | LLM 调用失败、数据库错误 |

### 6.3 结构化日志

```python
from isac.utils.logger import get_logger

logger = get_logger(__name__)

# 带上下文的结构化日志
logger.info(
    "消息处理完成",
    session_id=session_id,
    user_id=user_id,
    latency_ms=latency_ms,
)

# 错误日志必须带异常信息
logger.error("LLM 调用失败", error=str(exc), exc_info=True)
```

---

## 七、安全规范

### 7.1 API Key 存储

- **加密算法**: AES-256-GCM
- **密钥来源**: 环境变量 `ISAC_SECRET_KEY` (32 字节，base64 编码)
- **存储位置**: `data/.secrets.enc` (加密文件)
- **禁止**: 明文存储在配置文件或代码中

### 7.2 插件沙箱权限

默认权限（最小权限原则）:
- ❌ 文件系统访问
- ❌ 网络访问
- ❌ 子进程创建
- ❌ 环境变量读取

申请权限（通过 manifest 声明）:
```jsonc
{
    "permissions": [
        "filesystem:read:data/",      // 读取 data/ 目录
        "network:https",               // HTTPS 网络访问
        "env:MY_API_KEY",              // 读取特定环境变量
    ]
}
```

### 7.3 工具权限控制

| 工具 | 默认状态 | 说明 |
|------|---------|------|
| `send_emoji` | ✅ 允许 | 社交工具，低风险 |
| `send_image` | ✅ 允许 | 需要 Image Gen API Key |
| `query_memory` | ✅ 允许 | 只读操作 |
| `web_search` | ✅ 允许 | 只读操作 |
| `read_file` | ⚠️ 受限 | 限制在项目目录内 |
| `write_file` | ⚠️ 受限 | 限制在项目目录内 |
| `bash` | ❌ 默认禁用 | 需要在配置中显式启用 |
| `task` (子Agent) | ⚠️ 受限 | 限制递归深度和预算 |

---

## 八、Git 规范

### 6.1 Commit 规范

使用 [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Type 类型**:
- `feat`: 新功能
- `fix`: Bug 修复
- `docs`: 文档更新
- `refactor`: 重构 (不改变功能)
- `test`: 测试相关
- `chore`: 构建/工具/依赖更新

**示例**:
```
feat(agent): 添加 HeuristicMemoryInjector 支持

- 实现 LLM 聊天印象生成
- 实现记忆检索 + RRF 融合
- 添加频率控制

Closes #123
```

### 6.2 分支策略

```
main (生产分支)
  │
  ├── develop (开发分支)
  │     │
  │     ├── feature/memory-pipeline
  │     ├── feature/astrbot-compat
  │     └── fix/gating-threshold
  │
  └── hotfix/critical-bug
```

---

## 九、调试指南

### 7.1 日志级别

| 级别 | 用途 | 示例 |
|------|------|------|
| `DEBUG` | 详细调试信息 | 每个 Injector 的 build() 输入输出 |
| `INFO` | 关键流程节点 | 消息到达、Agent 启动、工具执行 |
| `WARNING` | 可恢复的错误 | 记忆检索失败、Injector 超时 |
| `ERROR` | 严重错误 | LLM 调用失败、数据库错误 |

### 7.2 调试 Agent Loop

开启 debug 日志后，关键信息包括:

```
# Prompt 组装日志
DEBUG SystemPromptBuilder: 注入了 5 个块，总 tokens ~1200
  - base_identity: ~200t
  - attention_drift: ~250t
  - person_profile: ~400t
  - jargon: ~200t
  - heuristic_memory: ~500t (冷却中，跳过)

# LLM 调用日志
INFO LLMProvider: 调用 model=gpt-4o, tokens=1200
INFO LLMResponse: 返回 content_length=45, tool_calls=1

# 工具执行日志
INFO ToolRegistry: 执行 tool=send_emoji, args={"emoji": "👍"}
INFO ToolResult: 执行成功, content_length=10
```

### 7.3 常见问题排查

| 问题 | 排查方向 |
|------|---------|
| Bot 不回复 | 检查 Gating 日志，看 Score 是否 ≥ 80 |
| Bot 回复太频繁 | 检查频率系数和存在感惩罚 |
| 记忆不注入 | 检查 HeuristicMemoryInjector 冷却时间和消息数 |
| 工具不执行 | 检查 pre_tool hook 是否返回 False |
| Prompt 太长 | 检查各 Injector 的 tokens_estimate 和实际注入量 |
