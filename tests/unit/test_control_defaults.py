"""G4 控制面安全与审计测试 - 受限默认配置 + 安全地址。"""

from __future__ import annotations

from isac.control.defaults import (
    RESTRICTED_COMMANDS_ALLOW,
    RESTRICTED_TOOLS_POLICY,
    enforce_safe_host,
    is_safe_default_host,
    make_restricted_agent_config,
    resolve_control_host,
)


class TestRestrictedDefaults:
    def test_bash_is_denied_by_default(self) -> None:
        assert RESTRICTED_TOOLS_POLICY["bash"] == "deny"

    def test_task_is_denied_by_default(self) -> None:
        assert RESTRICTED_TOOLS_POLICY["task"] == "deny"

    def test_read_file_write_file_are_restricted(self) -> None:
        assert RESTRICTED_TOOLS_POLICY["read_file"] == "restricted"
        assert RESTRICTED_TOOLS_POLICY["write_file"] == "restricted"

    def test_query_memory_is_allowed(self) -> None:
        assert RESTRICTED_TOOLS_POLICY["query_memory"] == "allow"

    def test_commands_allow_only_safe_set(self) -> None:
        assert set(RESTRICTED_COMMANDS_ALLOW) == {"focus", "mute", "unmute"}

    def test_make_restricted_config_blocks_bash(self) -> None:
        config = make_restricted_agent_config("auto_agent", "Auto Agent")
        assert config.tools_policy["bash"] == "deny"
        assert config.tools_policy["task"] == "deny"
        assert config.tools_policy["read_file"] == "restricted"
        assert "focus" in config.commands_allow
        assert config.plugins_deny == ["*"]
        assert config.mcp_servers == []

    def test_make_restricted_config_applies_extra_overrides(self) -> None:
        config = make_restricted_agent_config(
            "custom_agent",
            extra={"trigger_words": ["帮我", "请"], "memory_namespace": "shared"},
        )
        assert config.trigger_words == ["帮我", "请"]
        assert config.memory_namespace == "shared"

    def test_make_restricted_config_ignores_unknown_fields(self) -> None:
        config = make_restricted_agent_config(
            "agent_x", extra={"nonexistent_field": "value"}
        )
        assert not hasattr(config, "nonexistent_field")


class TestSafeHost:
    def test_127_0_0_1_is_safe(self) -> None:
        assert is_safe_default_host("127.0.0.1") is True

    def test_localhost_is_safe(self) -> None:
        assert is_safe_default_host("localhost") is True

    def test_ipv6_loopback_is_safe(self) -> None:
        assert is_safe_default_host("::1") is True

    def test_0_0_0_0_is_not_safe(self) -> None:
        assert is_safe_default_host("0.0.0.0") is False

    def test_external_ip_is_not_safe(self) -> None:
        assert is_safe_default_host("192.168.1.1") is False

    def test_empty_is_not_safe(self) -> None:
        assert is_safe_default_host("") is False

    def test_enforce_safe_host_keeps_safe(self) -> None:
        assert enforce_safe_host("127.0.0.1") == "127.0.0.1"

    def test_enforce_safe_host_falls_back_to_default(self) -> None:
        assert enforce_safe_host("0.0.0.0") == "127.0.0.1"
        assert enforce_safe_host("8.8.8.8") == "127.0.0.1"
        assert enforce_safe_host("") == "127.0.0.1"


class TestResolveControlHost:
    """容器部署显式逃生门: 默认强制 loopback, allow_external_host=true 才放行。"""

    def test_safe_host_passthrough(self) -> None:
        assert resolve_control_host({"host": "127.0.0.1"}) == "127.0.0.1"
        assert resolve_control_host({"host": "localhost", "allow_external_host": True}) == "localhost"

    def test_unsafe_host_falls_back_by_default(self) -> None:
        assert resolve_control_host({"host": "0.0.0.0"}) == "127.0.0.1"
        assert (
            resolve_control_host({"host": "192.168.1.1", "allow_external_host": False})
            == "127.0.0.1"
        )

    def test_allow_external_host_opts_in(self) -> None:
        assert resolve_control_host({"host": "0.0.0.0", "allow_external_host": True}) == "0.0.0.0"
        assert (
            resolve_control_host({"host": "192.168.1.1", "allow_external_host": True})
            == "192.168.1.1"
        )

    def test_string_truthy_value_does_not_opt_in(self) -> None:
        """fail-closed: 手编配置写字符串 "false"/"true" 时不放行 (只认真布尔)。"""
        assert resolve_control_host({"host": "0.0.0.0", "allow_external_host": "false"}) == "127.0.0.1"
        assert resolve_control_host({"host": "0.0.0.0", "allow_external_host": "true"}) == "127.0.0.1"
        assert resolve_control_host({"host": "0.0.0.0", "allow_external_host": 1}) == "127.0.0.1"

    def test_missing_or_invalid_host_falls_back(self) -> None:
        assert resolve_control_host({}) == "127.0.0.1"
        assert resolve_control_host({"host": ""}) == "127.0.0.1"
        assert resolve_control_host({"host": None}) == "127.0.0.1"

    def test_non_dict_config_falls_back(self) -> None:
        assert resolve_control_host(None) == "127.0.0.1"  # type: ignore[arg-type]
        assert resolve_control_host("0.0.0.0") == "127.0.0.1"  # type: ignore[arg-type]


class TestRestrictedConfigFromPayload:
    """CR3-L1: 自动化创建路径的受限默认配置构造。"""

    def test_capability_fields_in_payload_are_overridden(self) -> None:
        from isac.control.defaults import restricted_config_from_payload

        config = restricted_config_from_payload(
            {
                "agent_id": "auto1",
                "display_name": "Auto",
                "tools_policy": {"bash": "allow"},
                "plugins_allow": ["*"],
                "plugins_deny": [],
                "commands_allow": ["*"],
                "mcp_servers": ["evil-server"],
            }
        )
        assert config.tools_policy["bash"] == "deny"
        assert config.tools_policy["task"] == "deny"
        assert config.plugins_deny == ["*"]
        assert config.plugins_allow == []
        assert set(config.commands_allow) == {"focus", "mute", "unmute"}
        assert config.mcp_servers == []

    def test_non_capability_fields_pass_through(self) -> None:
        from isac.control.defaults import restricted_config_from_payload

        config = restricted_config_from_payload(
            {
                "agent_id": "auto2",
                "display_name": "Auto2",
                "trigger_words": ["hi"],
                "memory_namespace": "shared",
            }
        )
        assert config.trigger_words == ["hi"]
        assert config.memory_namespace == "shared"

    def test_invalid_agent_id_still_raises(self) -> None:
        import pytest

        from isac.control.defaults import restricted_config_from_payload

        with pytest.raises(ValueError):
            restricted_config_from_payload({"agent_id": "../escape"})

    def test_unknown_field_still_raises_type_error(self) -> None:
        import pytest

        from isac.control.defaults import restricted_config_from_payload

        with pytest.raises(TypeError):
            restricted_config_from_payload({"agent_id": "auto3", "no_such_field": 1})
