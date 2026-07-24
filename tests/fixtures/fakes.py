"""测试夹具: Fake Channel + Fake Provider (K5, DEVELOPMENT_PLAN.md)。

FakeChannel: 内存消息队列, 测试通过 receive_inject(msg) 投递消息触发 on_message
回调, send_reply 队列收集 Bot 回复。用于 E2E 测试而不必依赖真实 IM SDK。

FakeLLMProvider: 可配置响应内容的 LLM Provider 替身, 不发 HTTP, 直接返回预设
LLMResponse; 支持多轮对话与 tool_calls 响应, 让 Agent Loop 能完整跑通工具调用。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from isac.channel.base import PlatformAdapter
from isac.channel.model import ISACMessage, MessageSegment
from isac.core.types import LLMChunk, LLMResponse, TokenUsage, ToolCall
from isac.provider.base import LLMProvider, ModelCapabilities


class FakeChannel(PlatformAdapter):
    """内存消息队列 + 回复收集器 (K5 测试夹具)。

    - receive_inject(msg): 测试侧调用, 触发 on_message 回调 (模拟收到消息)
    - replies: Bot send() 进来的所有回复列表
    - platform_name 默认 "fake"
    """

    def __init__(self, platform_name: str = "fake") -> None:
        self._platform = platform_name
        self._running = False
        self.replies: list[ISACMessage] = []
        self._lock = asyncio.Lock()

    @property
    def platform_name(self) -> str:
        return self._platform

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def send(self, message: ISACMessage) -> bool:
        async with self._lock:
            self.replies.append(message)
        return True

    async def receive_inject(
        self,
        content: str,
        *,
        user_id: str = "u1",
        group_id: str | None = None,
        segments: list[MessageSegment] | None = None,
    ) -> ISACMessage:
        """测试侧投递一条消息, 触发 on_message 回调; 返回构造的 ISACMessage。"""
        msg = ISACMessage(
            msg_id=f"fake-{uuid.uuid4().hex[:8]}",
            platform=self._platform,
            timestamp=int(time.time()),
            user_id=user_id,
            user_name=user_id,
            group_id=group_id,
            content=content,
            segments=segments or [MessageSegment(type="text", data={"text": content})] if content else [],
        )
        if self.on_message is not None:
            await self.on_message(msg)
        return msg

    def reset_replies(self) -> list[ISACMessage]:
        """清空并返回已收集的回复。"""
        replies = list(self.replies)
        self.replies.clear()
        return replies


class FakeLLMProvider(LLMProvider):
    """可配置响应的 LLM Provider 替身 (K5 测试夹具)。

    - scripted_replies: 按顺序消费的响应队列; 第 N 次 chat() 返回第 N 个
    - tool_calls 选项: 返回带 tool_calls 的 LLMResponse 触发 Agent Loop 工具调用
    - chat_stream 用 LLMChunk 序列模拟流式
    """

    def __init__(
        self,
        *,
        model: str = "fake-model",
        scripted_replies: list[LLMResponse] | None = None,
        scripted_chunks: list[list[LLMChunk]] | None = None,
    ) -> None:
        self._model = model
        self._replies: list[LLMResponse] = list(scripted_replies or [])
        self._chunks: list[list[LLMChunk]] = list(scripted_chunks or [])
        self.calls: list[dict[str, Any]] = []
        self._default_reply = LLMResponse(
            content="ok", usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )

    def queue_reply(self, reply: LLMResponse) -> None:
        """向 scripted_replies 追加一个响应。"""
        self._replies.append(reply)

    async def chat(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        self.calls.append({"system": system, "messages": list(messages), "tools": tools})
        if self._replies:
            return self._replies.pop(0)
        return self._default_reply

    async def chat_stream(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[LLMChunk]:
        self.calls.append({"system": system, "messages": list(messages), "tools": tools, "stream": True})
        if self._chunks:
            for chunk in self._chunks.pop(0):
                yield chunk
            return
        # 默认单 chunk 流式
        yield LLMChunk(delta_content="ok", finish_reason="stop", usage=TokenUsage(total_tokens=2))

    def get_model_name(self) -> str:
        return self._model

    def get_capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(supports_tools=True, supports_streaming=True)


def make_tool_call_response(tool_name: str, tool_call_id: str = "call_1", arguments: dict | None = None) -> LLMResponse:
    """构造一个带 tool_calls 的 LLMResponse, 用于 Agent Loop 工具调用路径。"""
    return LLMResponse(
        content="",
        tool_calls=[ToolCall(id=tool_call_id, name=tool_name, arguments=arguments or {})],
        usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )


def make_final_reply(content: str) -> LLMResponse:
    """构造最终文本回复 LLMResponse。"""
    return LLMResponse(content=content, usage=TokenUsage(prompt_tokens=2, completion_tokens=5, total_tokens=7))
