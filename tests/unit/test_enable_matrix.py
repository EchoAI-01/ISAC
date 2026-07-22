"""EnableMatrix 启用矩阵单元测试 (E4, ARCHITECTURE.md 3.1 / SPECIFICATION.md 1.6)。"""

from __future__ import annotations

from isac.core.policy import EnableMatrix


class TestPluginMatrix:
    def test_default_allow_all(self):
        matrix = EnableMatrix()
        assert matrix.is_plugin_enabled("foo", ["*"], []) is True

    def test_deny_overrides_allow(self):
        matrix = EnableMatrix()
        assert matrix.is_plugin_enabled("foo", ["*"], ["foo"]) is False

    def test_explicit_allow_whitelist(self):
        matrix = EnableMatrix()
        assert matrix.is_plugin_enabled("foo", ["foo"], []) is True
        assert matrix.is_plugin_enabled("bar", ["foo"], []) is False

    def test_channel_can_disable_plugin(self):
        matrix = EnableMatrix(channel_overrides={"qq": {"plugins": {"foo": False}}})
        assert matrix.is_plugin_enabled("foo", ["*"], [], platform="qq") is False
        assert matrix.is_plugin_enabled("foo", ["*"], [], platform="tg") is True

    def test_global_deny_blocks_everywhere(self):
        matrix = EnableMatrix(global_policy={"plugins_deny": ["evil"]})
        assert matrix.is_plugin_enabled("evil", ["*"], []) is False
        assert matrix.is_plugin_enabled("evil", ["*"], [], platform="qq") is False


class TestToolMatrix:
    def test_default_allow(self):
        matrix = EnableMatrix()
        assert matrix.tool_policy("bash", {}) == "allow"

    def test_agent_policy_overrides_global(self):
        matrix = EnableMatrix(global_policy={"tools_policy": {"bash": "deny"}})
        # Agent 显式 allow 覆盖全局 deny
        assert matrix.tool_policy("bash", {"bash": "allow"}) == "allow"

    def test_channel_deny_overrides_agent(self):
        matrix = EnableMatrix(channel_overrides={"qq": {"tools": {"bash": "deny"}}})
        assert matrix.tool_policy("bash", {"bash": "allow"}, platform="qq") == "deny"

    def test_channel_restricted_overrides_agent(self):
        matrix = EnableMatrix(channel_overrides={"qq": {"tools": {"bash": "restricted"}}})
        assert matrix.tool_policy("bash", {"bash": "allow"}, platform="qq") == "restricted"


class TestCommandMatrix:
    def test_wildcard_allows_all(self):
        matrix = EnableMatrix()
        assert matrix.is_command_enabled("focus", ["*"]) is True

    def test_explicit_whitelist(self):
        matrix = EnableMatrix()
        assert matrix.is_command_enabled("focus", ["focus"]) is True
        assert matrix.is_command_enabled("mute", ["focus"]) is False

    def test_channel_deny_list(self):
        matrix = EnableMatrix(channel_overrides={"qq": {"commands": {"deny": ["focus"]}}})
        assert matrix.is_command_enabled("focus", ["*"], platform="qq") is False
        assert matrix.is_command_enabled("mute", ["*"], platform="qq") is True


class TestMcpMatrix:
    def test_must_be_in_agent_whitelist(self):
        matrix = EnableMatrix()
        assert matrix.is_mcp_enabled("server_a", ["server_a"]) is True
        assert matrix.is_mcp_enabled("server_b", ["server_a"]) is False

    def test_channel_can_disable_mcp(self):
        matrix = EnableMatrix(channel_overrides={"qq": {"mcp": {"server_a": False}}})
        assert matrix.is_mcp_enabled("server_a", ["server_a"], platform="qq") is False
