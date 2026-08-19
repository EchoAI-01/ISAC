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
        """返回工具在配置层的显式策略; 三层均无显式条目时返回 "" (= 无覆盖)。

        合并顺序 (后者覆盖前者): 全局运维配置 → Agent 配置 → Channel 覆盖。

        M3 修复要点:
        - agent_tools_policy 必须传**纯 Agent 配置层** (ToolPermission.agent_policy),
          不得混入 DEFAULT_POLICY —— 否则框架默认条目被当作 Agent 层, 覆盖全局运维
          的 tools_policy (如运维全局 bash: allow 恒被框架默认 deny 压掉)。
        - 三层都未显式配置时返回 "" 而非兜底 allow —— 调用方据此保留框架基线
          (DEFAULT_POLICY), 避免"无配置"被误当成"放行"覆盖框架默认 deny。
        """
        policy = ""
        # 全局运维配置层
        global_tools = self.global_policy.get("tools_policy", {})
        if tool_name in global_tools:
            policy = str(global_tools[tool_name])
        # Agent 配置层覆盖
        if tool_name in agent_tools_policy:
            policy = agent_tools_policy[tool_name]
        # Channel 覆盖
        channel_cfg = self._channel_resource(platform, "tools")
        if isinstance(channel_cfg, dict) and tool_name in channel_cfg:
            channel_val = channel_cfg[tool_name]
            if channel_val == DECISION_DENY:
                return DECISION_DENY
            # U5: ask 档 (人工审批) 与 allow/restricted 一样可作 channel 覆盖值
            if channel_val in (DECISION_ALLOW, "restricted", "ask"):
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

    def mcp_channel_enabled(self, server_name: str, platform: str = "") -> bool:
        """Channel 层 MCP 门控: 该平台的 mcp 配置是否禁用此 server。

        M4: 抽出供两处共用 —— 接线层 (_wire_mcp_clients) 与调用层
        (ToolRegistry.effective_policy 对 mcp:* 工具按 platform 检查)。
        无 platform / 无 Channel 配置时放行 (默认允许)。
        """
        channel_cfg = self._channel_resource(platform, "mcp")
        if isinstance(channel_cfg, dict) and channel_cfg.get(server_name) is False:
            return False
        return True

    def is_mcp_enabled(
        self,
        server_name: str,
        agent_mcp_servers: list[str],
        agent_id: str = "",
        platform: str = "",
    ) -> bool:
        """Agent 的 mcp_servers 白名单 ∩ Channel 允许。

        空 mcp_servers 表示该 Agent 不使用任何 MCP Server。
        M4: Channel 检查经 mcp_channel_enabled (接线层权威门控, 不再是死代码)。
        """
        if server_name not in agent_mcp_servers:
            return False
        return self.mcp_channel_enabled(server_name, platform)

    # ── 内部 ────────────────────────────────────────────────

    def _channel_resource(self, platform: str, resource: str) -> dict[str, Any] | None:
        platform_cfg = self.channel_overrides.get(platform)
        if not platform_cfg:
            return None
        return platform_cfg.get(resource)
