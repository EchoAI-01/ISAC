"""core/events + core/exceptions 单元测试。"""

from __future__ import annotations

from isac.core.events import AgentHookPoint, EventType
from isac.core.exceptions import (
    InterAgentLinkDeniedError,
    ISACError,
    LLMError,
    RateLimitError,
    ToolError,
)


class TestEventEnums:
    def test_event_bus_and_agent_hooks_separated(self):
        """EventBus 事件与 AgentHooks 分离 (SPECIFICATION.md 4.1)。"""
        assert EventType.ON_MESSAGE.value == "on_message"
        assert AgentHookPoint.FINAL_RESPONSE.value == "final_response"
        assert not hasattr(AgentHookPoint, "POST_SEND")

    def test_agent_hook_points_complete(self):
        assert len(AgentHookPoint) == 6


class TestExceptions:
    def test_base_error(self):
        err = ISACError("boom", context={"k": 1})
        assert err.message == "boom"
        assert err.code == "ISAC_ERROR"
        assert err.context == {"k": 1}
        assert str(err) == "boom"

    def test_retriable_flags(self):
        assert LLMError.retriable is True
        assert RateLimitError.retriable is True
        assert ToolError.retriable is False

    def test_inter_agent_denied(self):
        assert InterAgentLinkDeniedError.code == "INTER_AGENT_DENIED"
