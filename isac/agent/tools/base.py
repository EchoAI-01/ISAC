"""Tool 基类与上下文 (DEVELOP.md 3.4 / 7.3)。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from isac.core.types import ToolResult

if TYPE_CHECKING:
    from isac.core.types import AgentContext


@dataclass
class ToolContext:
    """工具执行上下文。

    services 用于注入共享服务 (如 "memory": MemoryRetrievalPipeline,
    "bus": InterAgentBus)，由 runtime 组装时注入，避免工具 import 业务模块。
    """

    args: dict[str, Any]  # LLM 传入的工具参数
    agent_context: AgentContext
    services: dict[str, Any] = field(default_factory=dict)


class Tool(ABC):
    """工具抽象基类。所有内置/插件工具必须继承此类。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """工具唯一名称 (LLM function calling 名)"""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """工具描述 (展示给 LLM)"""
        ...

    @property
    def parameters(self) -> dict:
        """JSON Schema 参数定义"""
        return {"type": "object", "properties": {}}

    @abstractmethod
    async def execute(self, context: ToolContext) -> ToolResult:
        """执行工具。失败应抛出 ToolError 或返回 is_error=True 的结果。"""
        ...


class ToolPermission:
    """工具权限检查 (DEVELOP.md 7.3)。

    有效权限 = 全局策略 ∩ Agent 配置 (AgentConfig.tools_policy)。
    """

    DEFAULT_POLICY: dict[str, str] = {
        "send_emoji": "allow",
        "send_image": "allow",
        "query_memory": "allow",
        "query_person_profile": "allow",
        "ask_agent": "allow",
        "web_search": "allow",
        "read_file": "restricted",  # 限制在项目目录内
        "write_file": "restricted",
        "bash": "deny",  # 默认禁用，需在配置中显式启用
        "task": "restricted",  # 限制递归深度和预算
    }

    def __init__(self, policy: dict[str, str] | None = None):
        self.policy = {**self.DEFAULT_POLICY, **(policy or {})}

    def check(self, tool_name: str) -> str:
        """返回 "allow" | "restricted" | "deny" (未声明默认 allow)。"""
        return self.policy.get(tool_name, "allow")
