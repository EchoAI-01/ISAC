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
    # tool 消息前必须有一条声明了对应 tool_calls 的 assistant 消息, 否则下一轮请求里
    # LLM API 会因为 tool_call_id 找不到归属而拒绝 (CODE_REVIEW_REPORT.md #10)。
    assert messages[-2]["role"] == "assistant"
    assert messages[-2]["tool_calls"][0]["id"] == "tool_1"
    assert messages[-2]["tool_calls"][0]["function"]["name"] == "service_echo"


class MultiRoundToolCallingProvider:
    """连续两轮都触发工具调用, 第三轮才产出最终回复。"""

    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, system: str, messages: list[dict], tools: list[dict] | None = None, **kwargs) -> LLMResponse:
        self.calls += 1
        if self.calls <= 2:
            return LLMResponse(
                content="",
                tool_calls=[ToolCall(id=f"tool_{self.calls}", name="service_echo", arguments={})],
                usage=TokenUsage(total_tokens=1),
            )
        return LLMResponse(content="done", usage=TokenUsage(total_tokens=1))

    def chat_stream(self, system: str, messages: list[dict], tools: list[dict] | None = None, **kwargs):
        raise NotImplementedError

    def get_model_name(self) -> str:
        return "test"

    def get_capabilities(self):
        return None


@pytest.mark.asyncio
async def test_agent_loop_appends_assistant_message_for_every_tool_call_round() -> None:
    provider = MultiRoundToolCallingProvider()
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
    assert provider.calls == 3
    # 每一轮工具调用都应补上各自的 assistant/tool 消息对, 而不是只有最后一轮。
    assistant_tool_call_ids = [
        msg["tool_calls"][0]["id"] for msg in messages if msg["role"] == "assistant" and "tool_calls" in msg
    ]
    tool_result_ids = [msg["tool_call_id"] for msg in messages if msg["role"] == "tool"]
    assert assistant_tool_call_ids == ["tool_1", "tool_2"]
    assert tool_result_ids == ["tool_1", "tool_2"]
    # 每个 assistant tool_calls 消息后必须紧跟着对应 tool_call_id 的 tool 结果消息。
    for index, msg in enumerate(messages):
        if msg["role"] == "assistant" and "tool_calls" in msg:
            assert messages[index + 1] == {
                "role": "tool",
                "tool_call_id": msg["tool_calls"][0]["id"],
                "content": "memory-service",
            }


class FailingTool(Tool):
    @property
    def name(self) -> str:
        return "failing_tool"

    @property
    def description(self) -> str:
        return "总是返回错误的工具"

    async def execute(self, context: ToolContext) -> ToolResult:
        return ToolResult(content="出错了", is_error=True)


class SingleToolCallProvider:
    """第一轮调用指定名称的工具, 第二轮产出最终回复。"""

    def __init__(self, tool_name: str) -> None:
        self.calls = 0
        self._tool_name = tool_name

    async def chat(self, system: str, messages: list[dict], tools: list[dict] | None = None, **kwargs) -> LLMResponse:
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                content="",
                tool_calls=[ToolCall(id="tool_1", name=self._tool_name, arguments={})],
                usage=TokenUsage(total_tokens=1),
            )
        return LLMResponse(content="done", usage=TokenUsage(total_tokens=1))

    def chat_stream(self, system: str, messages: list[dict], tools: list[dict] | None = None, **kwargs):
        raise NotImplementedError

    def get_model_name(self) -> str:
        return "test"

    def get_capabilities(self):
        return None


@pytest.mark.asyncio
async def test_agent_loop_records_tool_call_metric_on_success() -> None:
    """成功的工具调用应递增 isac_tool_calls_total, 不递增 isac_tool_errors_total

    (CODE_REVIEW_REPORT.md #5)。
    """
    from isac.observability import get_default_metrics

    metrics = get_default_metrics()
    provider = SingleToolCallProvider("service_echo")
    registry = ToolRegistry()
    registry.register(ServiceEchoTool())
    loop = ISACAgentLoop(
        llm=provider,
        prompt_builder=SystemPromptBuilder(),
        hooks=AgentHooks(),
        tools=registry,
        services={"memory": "memory-service", "metrics": metrics},
    )

    await loop.run([{"role": "user", "content": "查记忆"}], make_agent_context())

    assert metrics.counter("isac_tool_calls_total").value() == 1
    assert metrics.counter("isac_tool_errors_total").value() == 0


@pytest.mark.asyncio
async def test_agent_loop_records_tool_error_metric_on_failure() -> None:
    """返回 is_error=True 的工具调用应同时递增 calls 与 errors 两个指标。"""
    from isac.observability import get_default_metrics

    metrics = get_default_metrics()
    provider = SingleToolCallProvider("failing_tool")
    registry = ToolRegistry()
    registry.register(FailingTool())
    loop = ISACAgentLoop(
        llm=provider,
        prompt_builder=SystemPromptBuilder(),
        hooks=AgentHooks(),
        tools=registry,
        services={"metrics": metrics},
    )

    await loop.run([{"role": "user", "content": "触发失败工具"}], make_agent_context())

    assert metrics.counter("isac_tool_calls_total").value() == 1
    assert metrics.counter("isac_tool_errors_total").value() == 1
