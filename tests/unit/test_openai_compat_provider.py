"""OpenAICompatProvider 契约测试 (K2, DEVELOPMENT_PLAN.md)。

用 httpx.MockTransport 模拟 OpenAI 兼容 API 响应, 覆盖:
- 非流式 chat: 2xx + tool_calls + usage
- 流式 chat_stream: SSE 解析 + 多 chunk + [DONE]
- 错误分类: 429 → RateLimitError; 5xx → LLMError(retriable=True); 4xx → LLMError(retriable=False)
- JSON 解析失败 → LLMError(retriable=False)
- aclose 释放连接池
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from isac.core.exceptions import LLMError, RateLimitError
from isac.provider.llm.openai_compat import OpenAICompatProvider


def _make_provider(
    handler: Any,
    *,
    api_key: str = "sk-test",
    base_url: str = "https://api.openai.com/v1",
    model: str = "gpt-4",
    timeout: float = 5.0,
) -> OpenAICompatProvider:
    """构造 provider 并把 httpx.AsyncClient 注入用 MockTransport。"""
    provider = OpenAICompatProvider(
        api_key=api_key, base_url=base_url, model=model, timeout=timeout,
    )
    # 直接替换 _client 为带 MockTransport 的 AsyncClient
    provider._client = httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        transport=httpx.MockTransport(handler),
        timeout=timeout,
    )
    return provider


def _ok_response(*, content: str = "hello", tool_calls: list | None = None, usage: dict | None = None) -> bytes:
    """构造 OpenAI 非流式响应 body。"""
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    body: dict[str, Any] = {
        "id": "chatcmpl-x",
        "object": "chat.completion",
        "model": "gpt-4",
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": usage or {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
    }
    return json.dumps(body).encode("utf-8")


@pytest.mark.asyncio
async def test_chat_non_stream_success() -> None:
    """2xx 响应正确解析 content + usage。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_ok_response(content="hello world"))

    provider = _make_provider(handler)
    resp = await provider.chat(system="be nice", messages=[{"role": "user", "content": "hi"}])
    assert resp.content == "hello world"
    assert resp.usage.total_tokens == 8
    assert resp.model == "gpt-4"
    await provider.aclose()


@pytest.mark.asyncio
async def test_chat_parses_tool_calls() -> None:
    """tool_calls 从 message.tool_calls 解析为 ToolCall 列表。"""

    def handler(request: httpx.Request) -> httpx.Response:
        body = _ok_response(
            content="",
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "bash", "arguments": json.dumps({"command": "ls"})},
                }
            ],
        )
        return httpx.Response(200, content=body)

    provider = _make_provider(handler)
    resp = await provider.chat(
        system="",
        messages=[{"role": "user", "content": "run ls"}],
        tools=[{"type": "function"}],
    )
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].id == "call_1"
    assert resp.tool_calls[0].name == "bash"
    assert resp.tool_calls[0].arguments == {"command": "ls"}
    await provider.aclose()


@pytest.mark.asyncio
async def test_chat_includes_system_prompt() -> None:
    """system 参数被构造为 messages[0] role=system。"""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, content=_ok_response())

    provider = _make_provider(handler)
    await provider.chat(system="you are helpful", messages=[{"role": "user", "content": "hi"}])
    msgs = captured["body"]["messages"]
    assert msgs[0] == {"role": "system", "content": "you are helpful"}
    assert msgs[1] == {"role": "user", "content": "hi"}
    await provider.aclose()


@pytest.mark.asyncio
async def test_chat_429_raises_rate_limit_error() -> None:
    """HTTP 429 → RateLimitError (retriable=True)。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, content=b'{"error":"rate limited"}')

    provider = _make_provider(handler)
    with pytest.raises(RateLimitError):
        await provider.chat(system="", messages=[])
    await provider.aclose()


@pytest.mark.asyncio
async def test_chat_5xx_raises_retriable_llm_error() -> None:
    """HTTP 500 → LLMError(retriable=True)。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=b'{"error":"service unavailable"}')

    provider = _make_provider(handler)
    with pytest.raises(LLMError) as exc_info:
        await provider.chat(system="", messages=[])
    assert exc_info.value.retriable is True
    await provider.aclose()


@pytest.mark.asyncio
async def test_chat_4xx_raises_non_retriable_llm_error() -> None:
    """HTTP 401 → LLMError(retriable=False)。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, content=b'{"error":"invalid api key"}')

    provider = _make_provider(handler)
    with pytest.raises(LLMError) as exc_info:
        await provider.chat(system="", messages=[])
    assert exc_info.value.retriable is False
    await provider.aclose()


@pytest.mark.asyncio
async def test_chat_malformed_json_raises_non_retriable() -> None:
    """2xx 但 body 不是合法 JSON → LLMError(retriable=False)。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json at all")

    provider = _make_provider(handler)
    with pytest.raises(LLMError) as exc_info:
        await provider.chat(system="", messages=[])
    assert exc_info.value.retriable is False
    await provider.aclose()


@pytest.mark.asyncio
async def test_chat_structure_missing_choices_raises() -> None:
    """响应 JSON 缺 choices[0] → LLMError(retriable=False)。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps({"model": "gpt-4"}).encode())

    provider = _make_provider(handler)
    with pytest.raises(LLMError):
        await provider.chat(system="", messages=[])
    await provider.aclose()


@pytest.mark.asyncio
async def test_chat_parses_cache_reasoning_audio_usage_details() -> None:
    """J1: prompt_tokens_details/completion_tokens_details 解析为 TokenUsage 明细字段。"""

    def handler(request: httpx.Request) -> httpx.Response:
        body = _ok_response(
            usage={
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
                "prompt_tokens_details": {"cached_tokens": 80, "audio_tokens": 5},
                "completion_tokens_details": {"reasoning_tokens": 20, "audio_tokens": 3},
            }
        )
        return httpx.Response(200, content=body)

    provider = _make_provider(handler)
    resp = await provider.chat(system="", messages=[{"role": "user", "content": "hi"}])
    assert resp.usage.cache_read_tokens == 80
    assert resp.usage.audio_input_tokens == 5
    assert resp.usage.reasoning_tokens == 20
    assert resp.usage.audio_output_tokens == 3
    assert resp.usage.total_tokens == 150
    await provider.aclose()


@pytest.mark.asyncio
async def test_chat_usage_details_absent_keeps_zero() -> None:
    """未返回 *_tokens_details 时明细字段保持 0, 不猜测。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_ok_response())

    provider = _make_provider(handler)
    resp = await provider.chat(system="", messages=[{"role": "user", "content": "hi"}])
    assert resp.usage.cache_read_tokens == 0
    assert resp.usage.reasoning_tokens == 0
    assert resp.usage.audio_input_tokens == 0
    assert resp.usage.audio_output_tokens == 0
    await provider.aclose()


@pytest.mark.asyncio
async def test_chat_stream_sse_parsing() -> None:
    """chat_stream: SSE data: <json>\\n\\n 多 chunk + [DONE] 正确解析。"""
    chunk1 = b'data: {"choices":[{"delta":{"content":"hel"}}]}\n\n'
    chunk2 = b'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n'
    chunk3 = (
        b'data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
        b'"usage":{"prompt_tokens":3,"completion_tokens":2,"total_tokens":5}}\n\n'
    )
    done = b"data: [DONE]\n\n"
    sse_body = chunk1 + chunk2 + chunk3 + done

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=sse_body, headers={"content-type": "text/event-stream"}
        )

    provider = _make_provider(handler)
    chunks = []
    async for chunk in provider.chat_stream(system="", messages=[]):
        chunks.append(chunk)

    assert len(chunks) == 3
    assert chunks[0].delta_content == "hel"
    assert chunks[1].delta_content == "lo"
    assert chunks[2].finish_reason == "stop"
    assert chunks[2].usage.total_tokens == 5
    await provider.aclose()


@pytest.mark.asyncio
async def test_chat_stream_parses_usage_details() -> None:
    """J1: 流式最终 chunk 的 usage 明细字段也要解析 (与非流式同路径)。"""
    chunk1 = b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
    chunk2 = (
        b'data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
        b'"usage":{"prompt_tokens":100,"completion_tokens":50,"total_tokens":150,'
        b'"prompt_tokens_details":{"cached_tokens":80,"audio_tokens":5},'
        b'"completion_tokens_details":{"reasoning_tokens":20,"audio_tokens":3}}}\n\n'
    )
    done = b"data: [DONE]\n\n"
    sse_body = chunk1 + chunk2 + done

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sse_body, headers={"content-type": "text/event-stream"})

    provider = _make_provider(handler)
    chunks = []
    async for chunk in provider.chat_stream(system="", messages=[]):
        chunks.append(chunk)

    final_usage = chunks[-1].usage
    assert final_usage.cache_read_tokens == 80
    assert final_usage.audio_input_tokens == 5
    assert final_usage.reasoning_tokens == 20
    assert final_usage.audio_output_tokens == 3
    await provider.aclose()


@pytest.mark.asyncio
async def test_chat_stream_accumulates_tool_call_fragments_by_index() -> None:
    """CR3-H4: 工具调用被拆到多个 delta (首块 id+name, 后续 arguments 片段) 时
    必须按 index 累积、流结束后装配为完整 ToolCall, 不产生幽灵空调用。"""
    frag1 = (
        b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1",'
        b'"type":"function","function":{"name":"get_weather","arguments":""}}]}}]}\n\n'
    )
    frag2 = (
        b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
        b'"function":{"arguments":"{\\"city\\": "}}]}}]}\n\n'
    )
    frag3 = (
        b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
        b'"function":{"arguments":"\\"Tokyo\\"}"}}]}}]}\n\n'
    )
    finish = (
        b'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}],'
        b'"usage":{"prompt_tokens":10,"completion_tokens":6,"total_tokens":16}}\n\n'
    )
    sse_body = frag1 + frag2 + frag3 + finish + b"data: [DONE]\n\n"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sse_body, headers={"content-type": "text/event-stream"})

    provider = _make_provider(handler)
    chunks = []
    async for chunk in provider.chat_stream(system="", messages=[]):
        chunks.append(chunk)

    tool_calls = [c.tool_call for c in chunks if c.tool_call]
    assert len(tool_calls) == 1
    assert tool_calls[0].id == "call_1"
    assert tool_calls[0].name == "get_weather"
    assert tool_calls[0].arguments == {"city": "Tokyo"}
    # usage chunk 照常透传 (include_usage)
    assert any(c.usage.total_tokens == 16 for c in chunks)
    await provider.aclose()


@pytest.mark.asyncio
async def test_chat_stream_parallel_tool_calls_by_index() -> None:
    """CR3-H4: 并行工具调用 (index 0/1) 不再被丢弃, 各自独立装配。"""
    sse_body = (
        b'data: {"choices":[{"delta":{"tool_calls":['
        b'{"index":0,"id":"call_a","function":{"name":"tool_a","arguments":"{}"}},'
        b'{"index":1,"id":"call_b","function":{"name":"tool_b","arguments":""}}]}}]}\n\n'
        b'data: {"choices":[{"delta":{"tool_calls":[{"index":1,'
        b'"function":{"arguments":"{\\"x\\": 1}"}}]}}]}\n\n'
        b'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n\n'
        b"data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sse_body, headers={"content-type": "text/event-stream"})

    provider = _make_provider(handler)
    chunks = []
    async for chunk in provider.chat_stream(system="", messages=[]):
        chunks.append(chunk)

    tool_calls = [c.tool_call for c in chunks if c.tool_call]
    assert [(tc.id, tc.name) for tc in tool_calls] == [("call_a", "tool_a"), ("call_b", "tool_b")]
    assert tool_calls[0].arguments == {}
    assert tool_calls[1].arguments == {"x": 1}
    await provider.aclose()


@pytest.mark.asyncio
async def test_chat_stream_payload_requests_usage() -> None:
    """CR3-H4: 流式请求体默认带 stream_options.include_usage (token 预算依赖)。"""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200, content=b"data: [DONE]\n\n", headers={"content-type": "text/event-stream"}
        )

    provider = _make_provider(handler)
    async for _ in provider.chat_stream(system="", messages=[]):
        pass
    assert captured.get("stream_options") == {"include_usage": True}
    # 非流式请求不带 stream_options
    captured.clear()

    def chat_handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, content=_ok_response())

    provider2 = _make_provider(chat_handler)
    await provider2.chat(system="", messages=[])
    assert "stream_options" not in captured
    await provider.aclose()
    await provider2.aclose()


@pytest.mark.asyncio
async def test_chat_stream_429_raises_rate_limit() -> None:
    """流式响应 429 → RateLimitError。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, content=b'{"error":"rate limited"}')

    provider = _make_provider(handler)
    with pytest.raises(RateLimitError):
        async for _ in provider.chat_stream(system="", messages=[]):
            pass
    await provider.aclose()


@pytest.mark.asyncio
async def test_aclose_releases_client() -> None:
    """aclose 后 _client 被置 None, 再次调用 _get_client 会重建。"""
    handler = lambda request: httpx.Response(200, content=_ok_response())  # noqa: E731
    provider = _make_provider(handler)
    await provider.chat(system="", messages=[])
    assert provider._client is not None
    await provider.aclose()
    assert provider._client is None
    # 重新注入 mock client, 验证后续调用仍能工作
    provider._client = httpx.AsyncClient(
        base_url="https://api.openai.com/v1",
        headers={"Authorization": "Bearer sk-test", "Content-Type": "application/json"},
        transport=httpx.MockTransport(handler),
        timeout=5.0,
    )
    resp = await provider.chat(system="", messages=[])
    assert resp.content == "hello"
    await provider.aclose()


@pytest.mark.asyncio
async def test_chat_passes_kwargs_as_extra_params() -> None:
    """kwargs (temperature/top_p/max_tokens 等) 被透传到 payload。"""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, content=_ok_response())

    provider = _make_provider(handler)
    await provider.chat(system="", messages=[], temperature=0.7, max_tokens=100)
    assert captured["body"]["temperature"] == 0.7
    assert captured["body"]["max_tokens"] == 100
    await provider.aclose()


@pytest.mark.asyncio
async def test_chat_timeout_raises_retriable_llm_error() -> None:
    """请求超时 → LLMError(retriable=True)。"""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("simulated timeout")

    provider = _make_provider(handler, timeout=0.5)
    with pytest.raises(LLMError) as exc_info:
        await provider.chat(system="", messages=[])
    assert exc_info.value.retriable is True
    await provider.aclose()


@pytest.mark.asyncio
async def test_chat_network_error_wrapped_as_retriable() -> None:
    """httpx.ConnectError → LLMError(retriable=True)。"""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated connection refused")

    provider = _make_provider(handler)
    with pytest.raises(LLMError) as exc_info:
        await provider.chat(system="", messages=[])
    assert exc_info.value.retriable is True
    await provider.aclose()


@pytest.mark.asyncio
async def test_chat_passes_tools_in_payload() -> None:
    """tools 参数被构造为 payload.tools。"""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, content=_ok_response())

    provider = _make_provider(handler)
    await provider.chat(
        system="", messages=[],
        tools=[{"type": "function", "function": {"name": "bash", "parameters": {}}}],
    )
    assert captured["body"]["tools"] == [{"type": "function", "function": {"name": "bash", "parameters": {}}}]
    await provider.aclose()
