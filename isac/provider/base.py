"""Provider 抽象基类 (SPECIFICATION.md 2.3 / 2.4)。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from isac.core.types import LLMChunk, LLMResponse

if TYPE_CHECKING:
    from isac.artifacts.models import ArtifactRef, MediaAnalysisResult, MediaInput, TranscriptionResult


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
    """图片生成提供商契约 (旧预留, 返回原始字节; J2 统一契约见 ImageGenerationProvider)"""

    @abstractmethod
    async def generate(self, prompt: str, **kwargs: Any) -> bytes:
        """生成图片，返回图片字节"""
        ...


# ── J2 多模态 Provider 契约 (SPECIFICATION.md 2.4) ──────────────
# 所有多模态 Provider 统一注册到 ModelCatalog, 由 ModelRouter 按 operation / 输入输出
# 模态 / Agent 授权 / 成本 / 延迟 / 健康状态选择。二进制输入先经 MediaNormalizer 校验;
# 生成结果写入 ArtifactStore 并返回 ArtifactRef, 不把二进制塞进历史 / 日志 / 记忆。


class SpeechToTextProvider(ABC):
    """语音转文字 (STT) 提供商契约。"""

    @abstractmethod
    async def transcribe(self, media: MediaInput, **kwargs: Any) -> TranscriptionResult:
        """把音频转写为文本。"""
        ...


class TextToSpeechProvider(ABC):
    """文字转语音 (TTS) 提供商契约。"""

    @abstractmethod
    async def synthesize(self, text: str, **kwargs: Any) -> ArtifactRef:
        """把文本合成为语音, 返回制品引用。"""
        ...


class ImageGenerationProvider(ABC):
    """图片生成提供商契约 (J2; 返回 ArtifactRef 列表)。"""

    @abstractmethod
    async def generate(self, prompt: str, **kwargs: Any) -> list[ArtifactRef]:
        """按提示词生成一张或多张图片。"""
        ...


class VideoUnderstandingProvider(ABC):
    """视频理解提供商契约。"""

    @abstractmethod
    async def understand(self, media: MediaInput, prompt: str, **kwargs: Any) -> MediaAnalysisResult:
        """理解视频内容并按提示作答。"""
        ...


class VideoGenerationProvider(ABC):
    """视频生成提供商契约。"""

    @abstractmethod
    async def generate(self, prompt: str, **kwargs: Any) -> ArtifactRef:
        """按提示词生成视频, 返回制品引用。"""
        ...
