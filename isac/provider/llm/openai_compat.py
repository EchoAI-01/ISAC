"""OpenAI 兼容 Provider。

支持自定义 base_url: OpenAI / DeepSeek / Moonshot / 任意 OpenAI 兼容 API。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from isac.core.types import LLMChunk, LLMResponse
from isac.provider.base import LLMProvider, ModelCapabilities


class OpenAICompatProvider(LLMProvider):
    """OpenAI 兼容 Provider。

    [桩] 待实现:
    - httpx AsyncClient 调用 {base_url}/chat/completions
    - tools 参数 → function calling 格式, tool_calls 响应解析
    - 429 → RateLimitError; 5xx → LLMError(retriable=True) (SPECIFICATION.md 5.1)
    - chat_stream: SSE 解析为 LLMChunk 迭代器
    """

    def __init__(self, api_key: str, base_url: str, model: str, **kwargs: Any):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.extra = kwargs

    async def chat(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        raise NotImplementedError("OpenAICompatProvider.chat 尚未实现")

    async def chat_stream(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[LLMChunk]:
        raise NotImplementedError("OpenAICompatProvider.chat_stream 尚未实现")
        yield  # pragma: no cover (标记为异步生成器)

    def get_model_name(self) -> str:
        return self.model

    def get_capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(supports_tools=True, supports_streaming=True)
