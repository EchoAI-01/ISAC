"""StubProvider: 占位 LLM Provider，用于 D8 完成前让主链路可启动。

不调用任何外部 API，直接返回固定回复。生产环境应替换为 OpenAICompatProvider。

T1: 默认回复改为引导文案 —— 用户在未配置真实 api_key 时 (含占位符 "sk-your-key")
会收到这条提示, 知道下一步去哪配, 而不是看到一句无意义的 "[Stub] 收到消息" 不知道
是配错了还是程序坏了。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from isac.core.types import LLMChunk, LLMResponse
from isac.provider.base import LLMProvider, ModelCapabilities

# T1: 未配置 LLM 时的引导回复。引用真实配置路径, 让用户知道去哪修。
STUB_REPLY = (
    "[未配置 LLM] 我现在还没接入模型, 无法真正回复。"
    "请在 data/config.jsonc 的 llm 段填入真实 api_key 后重启。"
)


class StubProvider(LLMProvider):
    """占位 LLM Provider。"""

    def __init__(self, reply: str = STUB_REPLY):
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
