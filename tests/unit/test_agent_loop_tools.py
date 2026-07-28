"""ISACAgentLoop 工具链路测试。"""

from __future__ import annotations

import pytest

from isac.agent.hooks import AgentHooks
from isac.agent.loop import ISACAgentLoop
from isac.agent.prompt_builder import SystemPromptBuilder
from isac.agent.tools.base import Tool, ToolContext
from isac.agent.tools.registry import ToolRegistry
from isac.core.types import AgentContext, LLMChunk, LLMResponse, TokenUsage, ToolCall, ToolResult


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


class NoneContentFinalReplyProvider:
    """模拟 LLM API 在最终回复里返回 content=None (异常但合规)。"""

    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, system: str, messages: list[dict], tools: list[dict] | None = None, **kwargs) -> LLMResponse:
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                content=None,
                tool_calls=[ToolCall(id="tool_1", name="service_echo", arguments={})],
                usage=TokenUsage(total_tokens=1),
            )
        # 最终回复 content=None (某些模型在 stop_by_budget 或纯 reasoning 场景会这样)
        return LLMResponse(content=None, usage=TokenUsage(total_tokens=1))

    def chat_stream(self, system: str, messages: list[dict], tools: list[dict] | None = None, **kwargs):
        raise NotImplementedError

    def get_capabilities(self):
        from isac.core.types import ModelCapabilities
        return ModelCapabilities(supports_tools=True, supports_streaming=False)


@pytest.mark.asyncio
async def test_agent_loop_normalizes_none_content_to_empty_string() -> None:
    """R17: 最终回复 content=None 时 AgentResult.content 应归一化为 "".

    原 ``AgentResult(content=response.content)`` 会让 None 传入下游
    f-string/channel.send 抛 TypeError。改为 ``response.content or ""``。
    """
    provider = NoneContentFinalReplyProvider()
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

    # R17: content 应为 "" 而非 None (AgentResult.content 契约为 str)
    assert result.content == ""
    assert result.content is not None
    # 下游 f-string 拼接不应抛 TypeError
    _ = f"reply: {result.content}"


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


# ── H4: 流式路径 (loop 侧 _call_llm_streaming / _merge_chunks) ────────


class StreamingProvider:
    """流式 Fake Provider: 按轮次 yield 预设的 LLMChunk 序列。"""

    def __init__(self, scripts: list[list[LLMChunk]]) -> None:
        self._scripts = scripts
        self.stream_calls = 0

    async def chat(self, system: str, messages: list[dict], tools: list[dict] | None = None, **kwargs) -> LLMResponse:
        return LLMResponse(content="should-not-be-used", usage=TokenUsage())

    async def chat_stream(self, system: str, messages: list[dict], tools: list[dict] | None = None, **kwargs):
        chunks = self._scripts[self.stream_calls]
        self.stream_calls += 1
        for chunk in chunks:
            yield chunk

    def get_model_name(self) -> str:
        return "test"

    def get_capabilities(self):  # noqa: ANN201
        return None


def _streaming_context(collected: list[LLMChunk]) -> AgentContext:
    async def on_chunk(chunk: LLMChunk) -> None:
        collected.append(chunk)

    return AgentContext(
        session=object(),
        user_profile=None,
        current_message=object(),
        streaming=True,
        on_chunk=on_chunk,
    )


@pytest.mark.asyncio
async def test_agent_loop_streaming_merges_content_and_forwards_chunks() -> None:
    """H4: 流式单轮 —— _merge_chunks 合并多个 delta_content, usage 取非末尾的那个
    (不盲取 chunks[-1]); 每个 chunk 都转发给 on_chunk。"""
    provider = StreamingProvider(
        scripts=[
            [
                LLMChunk(delta_content="你"),
                LLMChunk(delta_content="好"),
                LLMChunk(usage=TokenUsage(total_tokens=7)),  # usage 单独一块, 在内容之后
                LLMChunk(delta_content="", finish_reason="stop"),  # 末块无 usage
            ]
        ]
    )
    collected: list[LLMChunk] = []
    loop = ISACAgentLoop(
        llm=provider,
        prompt_builder=SystemPromptBuilder(),
        hooks=AgentHooks(),
        tools=ToolRegistry(),
        services={},
    )
    result = await loop.run([{"role": "user", "content": "hi"}], _streaming_context(collected))

    assert result.content == "你好"
    assert len(collected) == 4  # 每个 chunk 都转发给 on_chunk

    # usage 合并 (取非末尾非空的那个, 不盲取 chunks[-1]) 是 CR3-H4 的核心修复;
    # AgentResult 不透出 usage (它进了 budget.consume), 故直接对 _merge_chunks 断言。
    merged = loop._merge_chunks(  # noqa: SLF001
        [
            LLMChunk(delta_content="你"),
            LLMChunk(delta_content="好"),
            LLMChunk(usage=TokenUsage(total_tokens=7)),
            LLMChunk(delta_content="", finish_reason="stop"),  # 末块 usage 为空
        ]
    )
    assert merged.content == "你好"
    assert merged.usage.total_tokens == 7  # 命中非末尾 chunk 的 usage, 而非末块空 usage


@pytest.mark.asyncio
async def test_agent_loop_streaming_executes_assembled_tool_call() -> None:
    """H4: 流式工具调用 —— Provider 侧按 index 装配好的 tool_call chunk 经
    _merge_chunks 收集后被 loop 正常执行, 第二轮 (仍流式) 产出最终回复。"""
    provider = StreamingProvider(
        scripts=[
            [LLMChunk(tool_call=ToolCall(id="t1", name="service_echo", arguments={}), finish_reason="tool_calls")],
            [LLMChunk(delta_content="done")],
        ]
    )
    registry = ToolRegistry()
    registry.register(ServiceEchoTool())
    collected: list[LLMChunk] = []
    loop = ISACAgentLoop(
        llm=provider,
        prompt_builder=SystemPromptBuilder(),
        hooks=AgentHooks(),
        tools=registry,
        services={"memory": "memory-service"},
    )
    result = await loop.run([{"role": "user", "content": "查记忆"}], _streaming_context(collected))

    assert result.content == "done"
    assert provider.stream_calls == 2  # 工具轮 + 最终轮都走流式


class _FailingStreamProvider:
    """流式 Provider: 推一个 chunk 后中途抛异常 (模拟流式响应中途失败)。"""

    def __init__(self) -> None:
        self.stream_calls = 0

    async def chat(self, system: str, messages: list[dict], tools: list[dict] | None = None, **kwargs) -> LLMResponse:
        return LLMResponse(content="fallback", usage=TokenUsage())

    async def chat_stream(self, system: str, messages: list[dict], tools: list[dict] | None = None, **kwargs):
        self.stream_calls += 1
        yield LLMChunk(delta_content="half-")
        raise RuntimeError("stream failed mid-way")

    def get_model_name(self) -> str:
        return "test"

    def get_capabilities(self):  # noqa: ANN201
        return None


@pytest.mark.asyncio
async def test_streaming_on_error_called_when_chunks_already_pushed() -> None:
    """C3: 流式响应中途失败且已推送 chunk 时调用 context.on_error(exc)。

    fallback 到 chat_with_retry 仅在 chunks=[] 时触发, 已推送过 chunk
    后无法干净重试; on_error 让调用方知道"已推送部分后失败", 可选择向
    用户追加错误标记或回滚已推送 chunks。
    """
    provider = _FailingStreamProvider()
    collected: list[LLMChunk] = []
    errors: list[Exception] = []

    async def on_chunk(chunk: LLMChunk) -> None:
        collected.append(chunk)

    async def on_error(exc: Exception) -> None:
        errors.append(exc)

    ctx = AgentContext(
        session=object(), user_profile=None, current_message=object(),
        streaming=True, on_chunk=on_chunk, on_error=on_error,
    )
    loop = ISACAgentLoop(
        llm=provider,
        prompt_builder=SystemPromptBuilder(),
        hooks=AgentHooks(),
        tools=ToolRegistry(),
    )
    # 流式失败后应 raise (loop.run 让异常冒泡)
    with pytest.raises(RuntimeError, match="stream failed mid-way"):
        await loop.run([{"role": "user", "content": "hi"}], ctx)
    # 已推送过一个 chunk
    assert len(collected) == 1
    assert collected[0].delta_content == "half-"
    # C3: on_error 被调用, 拿到原异常
    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeError)
    assert "stream failed mid-way" in str(errors[0])
