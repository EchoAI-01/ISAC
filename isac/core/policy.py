"""启用矩阵: 有效权限 = Agent 允许 ∩ Channel 允许 ∩ 全局策略。

支持四类资源的启用决策:
- plugin:  AgentConfig.plugins_allow/deny ∩ Channel 矩阵 ∩ 全局
- tool:    AgentConfig.tools_policy ∩ Channel 矩阵 ∩ 全局 DEFAULT_POLICY
- command: AgentConfig.commands_allow ∩ Channel 矩阵
- mcp:     AgentConfig.mcp_servers ∩ Channel 矩阵
"""

from __future__ import annotations

from typing import Any

# 资源类型
RESOURCE_PLUGIN = "plugin"
RESOURCE_TOOL = "tool"
RESOURCE_COMMAND = "command"
RESOURCE_MCP = "mcp"

# allow/deny 决策结果
DECISION_ALLOW = "allow"
DECISION_DENY = "deny"


class EnableMatrix:
    """启用矩阵: 计算 Agent ∩ Channel ∩ 全局 的有效决策。

    Channel 级矩阵通过 channel_overrides 注入, 形如:
        {"qq": {"tools": {"bash": "deny"}, "plugins": {"some_plugin": False}}}
    全局策略来自 global_config 的相应字段。
    """

    def __init__(
        self,
        global_policy: dict[str, Any] | None = None,
        channel_overrides: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.global_policy = global_policy or {}
        self.channel_overrides = channel_overrides or {}

    # ── plugin ──────────────────────────────────────────────

    def is_plugin_enabled(
        self,
        plugin_name: str,
        agent_config_allow: list[str],
        agent_config_deny: list[str],
        agent_id: str = "",
        platform: str = "",
    ) -> bool:
        """Agent 允许 ∩ Channel 允许 ∩ 全局允许。

        Agent 层:
        - allow=["*"] 或未在 deny 中 → 允许
        - 显式在 deny → 拒绝
        - 显式在 allow (非 "*") → 允许
        Channel 层: channel.plugins.get(plugin_name, True); False 表示该平台禁用
        全局层: global_policy.plugins_deny 含该插件 → 拒绝
        """
        # Agent 层
        if plugin_name in agent_config_deny:
            return False
        if "*" in agent_config_allow:
            agent_ok = True
        elif agent_config_allow:  # 显式白名单
            agent_ok = plugin_name in agent_config_allow
        else:  # 未配置 allow 默认放行 (除非在 deny 中)
            agent_ok = True
        if not agent_ok:
            return False
        # Channel 层
        channel_cfg = self._channel_resource(platform, "plugins")
        if isinstance(channel_cfg, dict):
            if channel_cfg.get(plugin_name) is False:
                return False
        # 全局层
        global_deny = self.global_policy.get("plugins_deny", [])
        if plugin_name in global_deny:
            return False
        return True

    # ── tool ────────────────────────────────────────────────

    def tool_policy(
        self,
        tool_name: str,
        agent_tools_policy: dict[str, str],
        agent_id: str = "",
        platform: str = "",
    ) -> str:
        """返回工具的有效策略: allow / restricted / deny。

        合并顺序 (后者覆盖前者): 全局默认 → Agent 配置 → Channel 覆盖。
        """
        # 全局默认
        global_tools = self.global_policy.get("tools_policy", {})
        policy = global_tools.get(tool_name, DECISION_ALLOW)
        # Agent 覆盖
        if tool_name in agent_tools_policy:
            policy = agent_tools_policy[tool_name]
        # Channel 覆盖
        channel_cfg = self._channel_resource(platform, "tools")
        if isinstance(channel_cfg, dict) and tool_name in channel_cfg:
            channel_val = channel_cfg[tool_name]
            if channel_val == DECISION_DENY:
                return DECISION_DENY
            if channel_val in (DECISION_ALLOW, "restricted"):
                policy = channel_val
        return policy

    # ── command ─────────────────────────────────────────────

    def is_command_enabled(
        self,
        command_name: str,
        agent_commands_allow: list[str],
        agent_id: str = "",
        platform: str = "",
    ) -> bool:
        """commands_allow=["*"] 表示全部允许; 否则按显式白名单。

        Channel 层: channel.commands.deny 含该命令 → 拒绝
        """
        # Agent 层
        if "*" in agent_commands_allow:
            agent_ok = True
        else:
            agent_ok = command_name in agent_commands_allow
        if not agent_ok:
            return False
        # Channel 层
        channel_cfg = self._channel_resource(platform, "commands")
        if isinstance(channel_cfg, dict):
            deny_list = channel_cfg.get("deny", [])
            if command_name in deny_list:
                return False
        return True

    # ── mcp ─────────────────────────────────────────────────

    def is_mcp_enabled(
        self,
        server_name: str,
        agent_mcp_servers: list[str],
        agent_id: str = "",
        platform: str = "",
    ) -> bool:
        """Agent 的 mcp_servers 白名单 ∩ Channel 允许。

        空 mcp_servers 表示该 Agent 不使用任何 MCP Server。
        """
        if server_name not in agent_mcp_servers:
            return False
        channel_cfg = self._channel_resource(platform, "mcp")
        if isinstance(channel_cfg, dict):
            if channel_cfg.get(server_name) is False:
                return False
        return True

    # ── 内部 ────────────────────────────────────────────────

    def _channel_resource(self, platform: str, resource: str) -> dict[str, Any] | None:
        platform_cfg = self.channel_overrides.get(platform)
        if not platform_cfg:
            return None
        return platform_cfg.get(resource)
