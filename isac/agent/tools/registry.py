"""ToolRegistry: 工具注册与执行 (ARCHITECTURE.md 3.5)。

[已完成] 权限检查 (deny/restricted/allow) + 异常隔离 + restricted 策略 (未注入对应后端时拒绝) +
启用矩阵接入 (EnableMatrix: Agent ∩ Channel ∩ 全局);
AST 自动发现待落地 (当前手动 register)。

错误处理: ToolError → 错误信息给 LLM；未知异常 → 内部错误。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from isac.agent.tools.base import Tool, ToolContext, ToolPermission
from isac.core.exceptions import ToolError
from isac.core.types import AgentContext, ToolCall, ToolResult
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.core.policy import EnableMatrix

logger = get_logger(__name__)


class ToolRegistry:
    """工具注册表。每个 AgentInstance 持有一个独立实例 (权限策略按 Agent 配置)。"""

    def __init__(
        self,
        permission: ToolPermission | None = None,
        enable_matrix: EnableMatrix | None = None,
        agent_id: str = "",
    ):
        self._tools: dict[str, Tool] = {}
        # T6: 工具来源追踪 (tool_name → "builtin" 或插件名), 供热重载按来源 deregister。
        self._source: dict[str, str] = {}
        # T6: on_load 期间设置的默认来源 (激活模块 set_current_source(plugin_name))。
        self._current_source: str | None = None
        self.permission = permission or ToolPermission()
        self.enable_matrix = enable_matrix
        self.agent_id = agent_id

    def register(self, tool: Tool, *, source: str | None = None) -> None:
        """注册工具 (重名覆盖并告警)。

        T6: source 追踪工具来源插件名。source=None 时取 _current_source (on_load
        期间设置) 或 "builtin"。向后兼容: 既有 register(tool) 调用 → source="builtin"。
        """
        effective_source = source or self._current_source or "builtin"
        if tool.name in self._tools:
            logger.warning("工具重复注册，已覆盖", tool=tool.name)
        self._tools[tool.name] = tool
        self._source[tool.name] = effective_source

    def deregister(self, name: str) -> bool:
        """移除工具 (T6 热重载)。返回是否移除成功。"""
        if name not in self._tools:
            return False
        del self._tools[name]
        self._source.pop(name, None)
        return True

    def deregister_by_source(self, source: str) -> list[str]:
        """移除指定来源的全部工具, 返回被移除的工具名列表 (T6 热重载同步)。"""
        removed = [n for n, s in self._source.items() if s == source]
        for n in removed:
            self._tools.pop(n, None)
            self._source.pop(n, None)
        return removed

    def deregister_plugin_sourced(self) -> list[str]:
        """移除全部插件来源工具 (source != "builtin"), 返回被移除的工具名列表。

        供热重载全量同步: 先清空 per-Agent 的全部插件工具, 再从共享表重新合并。
        """
        removed = [n for n, s in self._source.items() if s != "builtin"]
        for n in removed:
            self._tools.pop(n, None)
            self._source.pop(n, None)
        return removed

    def get_by_source(self, source: str) -> list[Tool]:
        """返回指定来源的全部工具 (T6 热重载同步)。"""
        return [self._tools[n] for n, s in self._source.items() if s == source and n in self._tools]

    def set_current_source(self, source: str | None) -> None:
        """设置后续 register() 的默认来源 (on_load 期间设为插件名, 结束后置 None)。"""
        self._current_source = source

    def source_of(self, tool_name: str) -> str | None:
        """返回工具的来源插件名 (或 "builtin"), 不存在返回 None。"""
        return self._source.get(tool_name)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def effective_policy(self, tool_name: str, platform: str = "") -> str:
        """返回工具有效策略: allow / restricted / deny。

        合并顺序: ToolPermission (全局默认+Agent tools_policy) → EnableMatrix (Channel 覆盖)。
        """
        policy = self.permission.check(tool_name)
        if self.enable_matrix is not None:
            agent_policy_dict = self.permission.policy
            platform_policy = self.enable_matrix.tool_policy(
                tool_name, agent_policy_dict, agent_id=self.agent_id, platform=platform
            )
            # Channel 明确 deny 或 restricted 优先
            if platform_policy in ("deny", "restricted"):
                policy = platform_policy
        return policy

    def definitions(self, platform: str = "") -> list[dict]:
        """返回 function calling 定义 (过滤 deny 工具)。"""
        return [
            {"name": t.name, "description": t.description, "parameters": t.parameters}
            for t in self._tools.values()
            if self.effective_policy(t.name, platform) != "deny"
        ]

    async def execute(
        self,
        tool_call: ToolCall,
        agent_context: AgentContext,
        services: dict | None = None,
    ) -> ToolResult:
        """执行工具调用 (权限检查 + 异常隔离)。

        权限策略:
        - deny: 直接拒绝
        - restricted: 必须在 services 中注入对应后端, 否则拒绝 (避免受限工具
          在未配置后端时被 LLM 调用, 暴露 NotImplementedError 给 LLM)
        - allow: 正常执行
        """
        tool = self._tools.get(tool_call.name)
        if tool is None:
            return ToolResult(content=f"未知工具: {tool_call.name}", is_error=True)

        platform = getattr(agent_context.session, "platform", "") if agent_context.session else ""
        policy = self.effective_policy(tool.name, platform)
        if policy == "deny":
            return ToolResult(content=f"工具 {tool.name} 已被配置禁用", is_error=True)
        if policy == "restricted":
            required = self._required_service(tool.name)
            if required:
                # Q0: 支持备选服务键 (tuple) —— 任一后端注入即放行, 如 task 工具
                # 的 subagent_supervisor (生产) / task_runner (旧路径向后兼容)。
                candidates = required if isinstance(required, tuple) else (required,)
                if not services or all(services.get(key) is None for key in candidates):
                    return ToolResult(
                        content=f"工具 {tool.name} 为受限工具, 需注入服务 {' 或 '.join(candidates)} 后方可使用。",
                        is_error=True,
                    )

        context = ToolContext(args=tool_call.arguments, agent_context=agent_context, services=services or {})
        try:
            return await tool.execute(context)
        except ToolError:
            raise
        except NotImplementedError as exc:
            return ToolResult(content=str(exc), is_error=True)
        except Exception as exc:
            raise ToolError(f"{type(exc).__name__}: {exc}") from exc

    @staticmethod
    def _required_service(tool_name: str) -> str | tuple[str, ...] | None:
        """restricted 工具 → 必须注入的 service key (tuple = 任一注入即可)。

        没有列入的 restricted 工具默认只要求 services 非空 (任意后端存在即可)。
        """
        mapping: dict[str, str | tuple[str, ...]] = {
            "read_file": "workspace_root",
            "write_file": "workspace_root",
            "bash": "bash_allowlist",
            "web_search": "web_search",
            # Q0 修正: task 工具 J4 起优先走 subagent_supervisor (生产恒注入),
            # 旧映射只认 task_runner (全仓无生产注入点), 使已接线的 SubAgent
            # 委派在 restricted 门就被挡死; 现两者任一注入即放行。
            "task": ("subagent_supervisor", "task_runner"),
            "send_emoji": "channel_send",
            "send_image": "channel_send",
            "fetch_history": "channel_history",
            "switch_chat": "session_topic",
            "view_forward_message": "channel_forward",
            # M2: 4 个 A2A 工具需 mesh_action_broker 注入后方可调用
            "notify_agent": "mesh_action_broker",
            "handoff_conversation": "mesh_action_broker",
            "list_available_agents": "mesh_action_broker",
            "memory_query_agent": "mesh_action_broker",
        }
        return mapping.get(tool_name)
