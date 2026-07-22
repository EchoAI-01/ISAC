"""ISACAgentLoop 工具链路测试。"""

from __future__ import annotations

import pytest

from isac.agent.hooks import AgentHooks
from isac.agent.loop import ISACAgentLoop
from isac.agent.prompt_builder import SystemPromptBuilder
from isac.agent.tools.base import Tool, ToolContext
from isac.agent.tools.registry import ToolRegistry
from isac.core.types import AgentContext, LLMResponse, TokenUsage, ToolCall, ToolResult


class ToolCallingProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, system: str, messages: list[dict], tools: list[dict] | None = None, **kwargs) -> LLMResponse:
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                content="",
                tool_calls=[ToolCall(id="tool_1", name="service_echo", arguments={})],
                usage=TokenUsage(total_tokens=1),
            )
        return LLMResponse(content="done", usage=TokenUsage(total_tokens=1))

    def chat_stream(self, system: str, messages: list[dict], tools: list[dict] | None = None, **kwargs):
        raise NotImplementedError

    def get_model_name(self) -> str:
        return "test"

    def get_capabilities(self):
        return None


class ServiceEchoTool(Tool):
    @property
    def name(self) -> str:
        return "service_echo"

    @property
    def description(self) -> str:
        return "回显注入服务"

    async def execute(self, context: ToolContext) -> ToolResult:
        return ToolResult(content=context.services["memory"])


def make_agent_context() -> AgentContext:
    return AgentContext(session=object(), user_profile=None, current_message=object())


@pytest.mark.asyncio
async def test_agent_loop_passes_services_and_appends_tool_result() -> None:
    provider = ToolCallingProvider()
    prompt_builder = SystemPromptBuilder()
    registry = ToolRegistry()
    registry.register(ServiceEchoTool())
    loop = ISACAgentLoop(
        llm=provider,
        prompt_builder=prompt_builder,
        hooks=AgentHooks(),
        tools=registry,
        services={"memory": "memory-service"},
    )
    messages: list[dict] = [{"role": "user", "content": "查记忆"}]

    result = await loop.run(messages, make_agent_context())

    assert result.content == "done"
    assert provider.calls == 2
    assert messages[-1] == {
        "role": "tool",
        "tool_call_id": "tool_1",
        "content": "memory-service",
    }
