"""ToolRegistry: 工具注册与执行 (AST 自动发现 TODO)。

错误处理 (ARCHITECTURE.md 3.5): ToolError → 错误信息给 LLM；未知异常 → 内部错误。
"""

from __future__ import annotations

from isac.agent.tools.base import Tool, ToolContext, ToolPermission
from isac.core.exceptions import ToolError
from isac.core.types import AgentContext, ToolCall, ToolResult
from isac.utils.logger import get_logger

logger = get_logger(__name__)


class ToolRegistry:
    """工具注册表。每个 AgentInstance 持有一个独立实例 (权限策略按 Agent 配置)。"""

    def __init__(self, permission: ToolPermission | None = None):
        self._tools: dict[str, Tool] = {}
        self.permission = permission or ToolPermission()

    def register(self, tool: Tool) -> None:
        """注册工具 (重名覆盖并告警)。"""
        if tool.name in self._tools:
            logger.warning("工具重复注册，已覆盖", tool=tool.name)
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def definitions(self) -> list[dict]:
        """返回 function calling 定义 (过滤 deny 工具)。"""
        return [
            {"name": t.name, "description": t.description, "parameters": t.parameters}
            for t in self._tools.values()
            if self.permission.check(t.name) != "deny"
        ]

    async def execute(
        self,
        tool_call: ToolCall,
        agent_context: AgentContext,
        services: dict | None = None,
    ) -> ToolResult:
        """执行工具调用 (权限检查 + 异常隔离)。"""
        tool = self._tools.get(tool_call.name)
        if tool is None:
            return ToolResult(content=f"未知工具: {tool_call.name}", is_error=True)

        policy = self.permission.check(tool.name)
        if policy == "deny":
            return ToolResult(content=f"工具 {tool.name} 已被配置禁用", is_error=True)
        # TODO(Day 15): "restricted" 策略 (如 read_file/write_file 限制项目目录内)

        context = ToolContext(args=tool_call.arguments, agent_context=agent_context, services=services or {})
        try:
            return await tool.execute(context)
        except ToolError:
            raise
        except NotImplementedError as exc:
            return ToolResult(content=str(exc), is_error=True)
        except Exception as exc:
            raise ToolError(f"{type(exc).__name__}: {exc}") from exc
