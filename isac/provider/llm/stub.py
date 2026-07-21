"""StubProvider: 占位 LLM Provider，用于 D8 完成前让主链路可启动。

不调用任何外部 API，直接返回固定回复。生产环境应替换为 OpenAICompatProvider。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from isac.core.types import LLMChunk, LLMResponse
from isac.provider.base import LLMProvider, ModelCapabilities


class StubProvider(LLMProvider):
    """占位 LLM Provider。"""

    def __init__(self, reply: str = "[Stub] 收到消息，稍后回复。"):
        self.reply = reply

    async def chat(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """返回固定回复。"""
        return LLMResponse(content=self.reply, model=self.get_model_name())

    async def chat_stream(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[LLMChunk]:
        """返回空流式迭代器。"""
        if False:
            yield LLMChunk()

    def get_model_name(self) -> str:
        return "stub"

    def get_capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(supports_tools=False, supports_streaming=False)
