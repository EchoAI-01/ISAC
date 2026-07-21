"""Provider 抽象基类 (SPECIFICATION.md 2.3 / 2.4)。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from isac.core.types import LLMChunk, LLMResponse


@dataclass
class ModelCapabilities:
    """模型能力"""

    supports_tools: bool = True
    supports_streaming: bool = True
    supports_vision: bool = False
    supports_reasoning: bool = False
    max_context_tokens: int = 128000
    extra: dict[str, Any] = field(default_factory=dict)


class LLMProvider(ABC):
    """LLM 提供商抽象基类"""

    @abstractmethod
    async def chat(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """非流式聊天请求"""
        ...

    @abstractmethod
    def chat_stream(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[LLMChunk]:
        """流式聊天请求，返回 chunk 迭代器"""
        ...

    @abstractmethod
    def get_model_name(self) -> str:
        """返回当前使用的模型名称"""
        ...

    def get_capabilities(self) -> ModelCapabilities:
        """返回模型能力"""
        return ModelCapabilities()


class EmbeddingProvider(ABC):
    """嵌入模型提供商契约"""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """批量文本向量化"""
        ...

    @abstractmethod
    async def embed_query(self, query: str) -> list[float]:
        """查询文本向量化"""
        ...

    @abstractmethod
    def dimension(self) -> int:
        """返回向量维度"""
        ...


class RerankerProvider(ABC):
    """重排序模型提供商契约"""

    @abstractmethod
    async def rerank(self, query: str, candidates: list[str]) -> list[float]:
        """对候选文本重排序，返回相关性分数列表"""
        ...


class ImageGenProvider(ABC):
    """图片生成提供商契约 (预留)"""

    @abstractmethod
    async def generate(self, prompt: str, **kwargs: Any) -> bytes:
        """生成图片，返回图片字节"""
        ...
